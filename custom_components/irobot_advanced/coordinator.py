"""Update coordinator: local push + cloud poll."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .auth import InvalidCredentialsError, IRobotAuth
from .cloud_client import CloudAuthError, IRobotCloudClient
from .const import (
    CONF_APP_ID,
    CONF_BLID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_USERNAME,
    CONF_COUNTRY,
    CONF_ENABLE_CLOUD,
    CONF_ROBOT_PASSWORD,
    DEFAULT_APP_ID,
    DOMAIN,
)
from .live_view import LiveViewSession
from .local_client import RoombaLocalClient

_LOGGER = logging.getLogger(__name__)

CLOUD_INTERVAL = timedelta(minutes=15)


class IRobotCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Owns the local MQTT session and periodically refreshes cloud data."""

    @staticmethod
    def _shared_auth(hass: HomeAssistant, options: dict) -> IRobotAuth:
        """One login per account, not one per robot.

        Three robots on the same account share a single set of STS
        credentials and a single refresh cycle.
        """
        registry: dict[str, IRobotAuth] = hass.data.setdefault(f"{DOMAIN}_auth", {})
        key = options[CONF_CLOUD_USERNAME].strip().lower()
        auth = registry.get(key)
        if auth is None or auth._password != options[CONF_CLOUD_PASSWORD]:
            auth = IRobotAuth(
                session=async_get_clientsession(hass),
                username=options[CONF_CLOUD_USERNAME],
                password=options[CONF_CLOUD_PASSWORD],
                country_code=options.get(CONF_COUNTRY, "US"),
                app_id=options.get(CONF_APP_ID) or DEFAULT_APP_ID,
            )
            registry[key] = auth
        return auth

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{entry.data[CONF_BLID]}",
            update_interval=CLOUD_INTERVAL,
        )
        self.entry = entry
        self.blid: str = entry.data[CONF_BLID]
        self.host: str = entry.data["host"]

        self.local = RoombaLocalClient(
            host=self.host,
            blid=self.blid,
            password=entry.data[CONF_ROBOT_PASSWORD],
            on_state=self._handle_local_state,
            on_position=self._handle_position,
        )

        self.auth: IRobotAuth | None = None
        self.cloud: IRobotCloudClient | None = None
        self.live_view: LiveViewSession | None = None
        options = {**entry.data, **entry.options}
        if options.get(CONF_ENABLE_CLOUD) and options.get(CONF_CLOUD_USERNAME):
            self.auth = self._shared_auth(hass, options)
            session = async_get_clientsession(hass)
            self.cloud = IRobotCloudClient(session, self.auth)
            self.live_view = LiveViewSession(session, self.blid, self.auth)

        self.position: dict[str, Any] = {}
        self.pmaps: list[dict[str, Any]] = []
        self.pmap_details: dict[str, dict[str, Any]] = {}
        self.missions: list[dict[str, Any]] = []
        self.obstacles: list[dict[str, Any]] = []
        self.cloud_error: str | None = None
        self._last_omap_spatial: dict[str, Any] | None = None

    # ------------------------------------------------------------------ setup

    async def async_start(self) -> None:
        await self.local.async_connect()

    async def async_stop(self) -> None:
        await self.local.async_disconnect()

    # ------------------------------------------------------------- local push

    def _handle_local_state(self, state: dict[str, Any]) -> None:
        self.async_set_updated_data(state)

    def _handle_position(self, payload: dict[str, Any]) -> None:
        pose = payload.get("pose") or payload
        self.position = {
            "x": pose.get("point", {}).get("x", pose.get("x")),
            "y": pose.get("point", {}).get("y", pose.get("y")),
            "theta": pose.get("theta"),
        }
        self.async_update_listeners()

    # ------------------------------------------------------------ cloud poll

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh cloud-only data. Local state arrives out-of-band via push."""
        if self.cloud is not None:
            try:
                await self._async_refresh_cloud()
                self.cloud_error = None
            except InvalidCredentialsError as err:
                # Password changed on the account -- ask the user to re-enter it
                # rather than silently degrading.
                raise ConfigEntryAuthFailed(str(err)) from err
            except CloudAuthError as err:
                self.cloud_error = str(err)
                _LOGGER.warning("Cloud auth failed for %s: %s", self.blid, err)
            except (aiohttp.ClientError, TimeoutError) as err:
                self.cloud_error = str(err)
                _LOGGER.debug("Cloud refresh failed for %s: %s", self.blid, err)

        return self.local.state or self.data or {}

    async def _async_refresh_cloud(self) -> None:
        assert self.cloud is not None
        self.pmaps = await self.cloud.async_get_pmaps(self.blid)

        for pmap in self.pmaps:
            pmap_id = pmap.get("pmap_id") or pmap.get("id")
            if not pmap_id:
                continue
            # Real pmap shape carries the active version inline; the details may
            # already include regions. Fall back to the versioned UMF endpoint
            # only if we still have no detail.
            detail = pmap.get("active_pmapv_details")
            version = (
                pmap.get("active_pmapv_id")
                or pmap.get("robot_pmapv_id")
                or pmap.get("user_pmapv_id")
            )
            if not detail and version:
                try:
                    detail = await self.cloud.async_get_pmap_umf(
                        self.blid, pmap_id, version
                    )
                except Exception as err:
                    _LOGGER.debug("pmap detail fetch failed for %s: %s", pmap_id, err)
                    detail = None
            if detail:
                self.pmap_details[pmap_id] = detail

        self.missions = await self.cloud.async_get_mission_history(self.blid)
        self.obstacles = await self.cloud.async_get_obstacle_snapshots(self.blid)
        # Keep the last omap spatial sample for diagnostics field-name capture.
        self._last_omap_spatial = getattr(
            self.cloud, "last_omap_spatial", None
        )

    async def async_refresh_maps(self) -> None:
        if self.cloud is None:
            raise RuntimeError("Cloud access is not enabled for this robot")
        await self._async_refresh_cloud()
        self.async_update_listeners()

    # ---------------------------------------------------------------- helpers

    @property
    def reported(self) -> dict[str, Any]:
        return self.data or {}

    @property
    def mission(self) -> dict[str, Any]:
        return self.reported.get("cleanMissionStatus", {}) or {}

    @property
    def robot_name(self) -> str:
        """The robot's own name.

        Deliberately NOT called `name` -- DataUpdateCoordinator assigns
        `self.name` in its constructor, so a read-only `name` property here
        breaks setup with "property has no setter".
        """
        return self.reported.get("name") or f"Roomba {self.blid[-6:]}"

    @property
    def sku(self) -> str | None:
        return self.reported.get("sku")

    @property
    def regions(self) -> list[dict[str, Any]]:
        """Flatten every named region across all known maps."""
        out: list[dict[str, Any]] = []
        for pmap_id, detail in self.pmap_details.items():
            regions = (
                detail.get("regions")
                or detail.get("rooms")
                or (detail.get("active_pmapv_details") or {}).get("regions")
                or []
            )
            for region in regions:
                if not isinstance(region, dict):
                    continue
                out.append(
                    {
                        "pmap_id": pmap_id,
                        "region_id": str(
                            region.get("region_id", region.get("id", ""))
                        ),
                        "name": region.get("name")
                        or region.get("region_name"),
                        "type": region.get("region_type", region.get("type")),
                    }
                )
        return out
