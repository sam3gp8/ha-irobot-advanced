"""iRobot cloud REST client.

Authenticated with SigV4 against API Gateway using the temporary credentials
from :mod:`.auth`, which refreshes them transparently. Nothing here expires
from the user's point of view.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
from yarl import URL

from .auth import IRobotAuth, IRobotAuthError
from .const import (
    PATH_EVAC_HISTORY,
    PATH_IMAGE_REMOVAL,
    PATH_MAP_RENDERED,
    PATH_MISSION_HISTORY,
    PATH_OMAP_SPATIAL,
    PATH_OMAPS,
    PATH_PMAP_SETTINGS,
    PATH_PMAP_UMF,
    PATH_PMAP_VERSIONS,
    PATH_PMAPS,
)
from .sigv4 import sign_request

_LOGGER = logging.getLogger(__name__)


class CloudAuthError(IRobotAuthError):
    """Raised when the cloud rejects a signed request."""


class IRobotCloudClient:
    """Thin async wrapper over the authenticated iRobot HTTP API."""

    def __init__(self, session: aiohttp.ClientSession, auth: IRobotAuth) -> None:
        self._session = session
        self._auth = auth

    @property
    def auth(self) -> IRobotAuth:
        return self._auth

    # ------------------------------------------------------------- transport

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
        raw: bool = False,
    ) -> Any:
        credentials = await self._auth.async_valid_credentials()

        url = URL(self._auth.api_url(path))
        if params:
            url = url.with_query({k: v for k, v in params.items() if v is not None})

        body = b""
        headers: dict[str, str] = {"Accept": "application/json"}
        extra: dict[str, str] | None = None
        if json_body is not None:
            body = json.dumps(json_body, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
            extra = {"content-type": "application/json"}

        headers.update(
            sign_request(
                method,
                str(url),
                credentials,
                region=self._auth.region,
                body=body,
                extra_headers=extra,
            )
        )

        async with self._session.request(
            method,
            url,
            headers=headers,
            data=body or None,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as resp:
            if resp.status in (401, 403):
                # Credentials may have been revoked early -- drop them so the
                # next call re-logs in.
                self._auth.credentials = None
                raise CloudAuthError(f"Cloud rejected the request ({resp.status})")
            resp.raise_for_status()
            return await resp.read() if raw else await resp.json(content_type=None)

    async def _get(self, path: str, **params: Any) -> Any:
        return await self._request("GET", path, params=params or None)

    async def _get_bytes(self, url: str) -> bytes:
        """Fetch a pre-signed S3 asset. These carry their own signature."""
        async with self._session.get(
            url, timeout=aiohttp.ClientTimeout(total=60)
        ) as resp:
            resp.raise_for_status()
            return await resp.read()

    # ------------------------------------------------------------- robots

    async def async_get_robots(self) -> dict[str, Any]:
        """Robot list from the login response, including local passwords."""
        await self._auth.async_valid_credentials()
        return self._auth.robots

    # ------------------------------------------------------------- maps

    async def async_get_pmaps(self, blid: str) -> list[dict[str, Any]]:
        data = await self._get(PATH_PMAPS.format(blid=blid), activeDetails=2)
        return data if isinstance(data, list) else data.get("pmaps", [])

    async def async_get_pmap_versions(
        self, blid: str, pmap_id: str
    ) -> list[dict[str, Any]]:
        data = await self._get(PATH_PMAP_VERSIONS.format(blid=blid, pmap_id=pmap_id))
        return data if isinstance(data, list) else data.get("versions", [])

    async def async_get_pmap_umf(
        self, blid: str, pmap_id: str, version: str
    ) -> dict[str, Any]:
        return await self._get(
            PATH_PMAP_UMF.format(blid=blid, pmap_id=pmap_id, version=version)
        )

    async def async_set_pmap_settings(
        self, blid: str, pmap_id: str, settings: dict[str, Any]
    ) -> None:
        await self._request(
            "PUT",
            PATH_PMAP_SETTINGS.format(blid=blid, pmap_id=pmap_id),
            json_body=settings,
        )

    async def async_get_rendered_map(self, map_id: str) -> bytes:
        return await self._request(
            "GET", PATH_MAP_RENDERED.format(map_id=map_id), raw=True
        )

    # ------------------------------------------------------------- omaps

    async def async_get_omaps(self, blid: str) -> list[dict[str, Any]]:
        data = await self._get(PATH_OMAPS, robotId=blid)
        return data if isinstance(data, list) else data.get("omaps", [])

    async def async_get_omap_spatial(
        self, blid: str, omap_id: str, version: str
    ) -> dict[str, Any]:
        return await self._get(
            PATH_OMAP_SPATIAL.format(omap_id=omap_id, version=version), robotId=blid
        )

    # ------------------------------------------------------------- history

    async def async_get_mission_history(self, blid: str) -> list[dict[str, Any]]:
        data = await self._get(PATH_MISSION_HISTORY.format(blid=blid))
        return data if isinstance(data, list) else data.get("history", [])

    async def async_get_evac_history(self) -> list[dict[str, Any]]:
        data = await self._get(PATH_EVAC_HISTORY)
        return data if isinstance(data, list) else data.get("history", [])

    # ------------------------------------------------------------- obstacles

    async def async_get_obstacle_snapshots(self, blid: str) -> list[dict[str, Any]]:
        """Flatten obstacle records out of the mission history."""
        history = await self.async_get_mission_history(blid)
        snapshots: list[dict[str, Any]] = []
        for mission in history:
            for key in ("obstacles", "hazards", "imageUploads", "detections"):
                for item in mission.get(key) or []:
                    if not isinstance(item, dict):
                        continue
                    url = (
                        item.get("imageUrl")
                        or item.get("url")
                        or item.get("presignedUrl")
                    )
                    if not url:
                        continue
                    snapshots.append(
                        {
                            "mission_id": mission.get("id") or mission.get("missionId"),
                            "timestamp": item.get("timestamp")
                            or mission.get("startTime"),
                            "obstacle_type": item.get("type") or item.get("objectType"),
                            "review_status": item.get("reviewStatus"),
                            "position": {
                                "x": item.get("x"),
                                "y": item.get("y"),
                                "theta": item.get("theta"),
                            },
                            "image_url": url,
                        }
                    )
        snapshots.sort(key=lambda s: s.get("timestamp") or 0, reverse=True)
        return snapshots

    async def async_fetch_image(self, url: str) -> bytes:
        return await self._get_bytes(url)

    async def async_request_image_removal(self, image_ids: list[str]) -> None:
        await self._request(
            "POST", PATH_IMAGE_REMOVAL, json_body={"imageIds": image_ids}
        )
