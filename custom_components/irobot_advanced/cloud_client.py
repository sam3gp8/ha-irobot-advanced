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
        """Collect obstacle captures from the omap spatial data.

        Obstacle images are part of the Mapping Metadata (omap) API, not the
        mission summary or timeline -- the mission records carry no image URLs
        (confirmed against a live j-series robot). Each omap version's spatial
        data holds the detected objects with their pre-signed image URLs.
        """
        snapshots: list[dict[str, Any]] = []
        try:
            omaps = await self.async_get_omaps(blid)
        except (aiohttp.ClientError, CloudAuthError):
            return snapshots

        for omap in omaps:
            omap_id = omap.get("omap_id") or omap.get("id")
            version = (
                omap.get("active_omapv_id")
                or omap.get("omapv_id")
                or omap.get("version")
            )
            if not omap_id or not version:
                continue
            try:
                spatial = await self.async_get_omap_spatial(blid, omap_id, version)
            except (aiohttp.ClientError, CloudAuthError):
                continue
            snapshots.extend(self._extract_obstacles(spatial, omap_id))

        snapshots.sort(key=lambda s: s.get("timestamp") or 0, reverse=True)
        return snapshots

    @staticmethod
    def _extract_obstacles(spatial: dict[str, Any], omap_id: str) -> list[dict[str, Any]]:
        """Pull obstacle objects with image URLs out of omap spatial data."""
        out: list[dict[str, Any]] = []
        # Objects live under several plausible containers depending on firmware.
        containers = (
            spatial.get("observed_objects")
            or spatial.get("objects")
            or spatial.get("obstacles")
            or spatial.get("detections")
            or (spatial.get("spatialData") or {}).get("objects")
            or []
        )
        for item in containers:
            if not isinstance(item, dict):
                continue
            url = (
                item.get("image_url")
                or item.get("imageUrl")
                or item.get("url")
                or item.get("presignedUrl")
            )
            if not url:
                continue
            pos = item.get("position") or item
            out.append(
                {
                    "omap_id": omap_id,
                    "timestamp": item.get("timestamp") or item.get("detection_time"),
                    "obstacle_type": (
                        item.get("classification")
                        or item.get("object_type")
                        or item.get("type")
                    ),
                    "review_status": item.get("review_status")
                    or item.get("reviewStatus"),
                    "position": {
                        "x": pos.get("x"),
                        "y": pos.get("y"),
                        "theta": pos.get("theta"),
                    },
                    "image_url": url,
                }
            )
        return out

    async def async_fetch_image(self, url: str) -> bytes:
        return await self._get_bytes(url)

    async def async_request_image_removal(self, image_ids: list[str]) -> None:
        await self._request(
            "POST", PATH_IMAGE_REMOVAL, json_body={"imageIds": image_ids}
        )
