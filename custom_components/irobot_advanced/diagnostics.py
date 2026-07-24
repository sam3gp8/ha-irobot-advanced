"""Diagnostics dump for bug reports."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_BLID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_USERNAME,
    CONF_ROBOT_PASSWORD,
    DOMAIN,
)
from .coordinator import IRobotCoordinator

REDACT_CONFIG = {
    CONF_ROBOT_PASSWORD,
    CONF_CLOUD_USERNAME,
    CONF_CLOUD_PASSWORD,
    CONF_BLID,
    "host",
    "hostname",
}

REDACT_STATE = {
    "blid",
    "mac",
    "netinfo",
    "wlcfg",
    "ssid",
    "bssid",
    "hostname",
    "password",
    "cloudEnv",
    "svcEndpoints",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]

    return {
        "entry": async_redact_data(dict(entry.data), REDACT_CONFIG),
        "options": async_redact_data(dict(entry.options), REDACT_CONFIG),
        "local": {
            "connected": coordinator.local.connected,
            "state": async_redact_data(coordinator.reported, REDACT_STATE),
            "position": coordinator.position,
        },
        "cloud": {
            "enabled": coordinator.cloud is not None,
            "error": coordinator.cloud_error,
            "region": coordinator.auth.region if coordinator.auth else None,
            "api_stage": coordinator.auth.api_stage if coordinator.auth else None,
            "pmap_count": len(coordinator.pmaps),
            "region_count": len(coordinator.regions),
            "mission_count": len(coordinator.missions),
            "obstacle_count": len(coordinator.obstacles),
        },
        # Shapes only -- useful for fixing the heuristic parsers without
        # anyone having to paste their map data into an issue.
        "shapes": {
            "pmap_keys": sorted({k for p in coordinator.pmaps for k in p}),
            "mission_keys": sorted(
                {k for m in coordinator.missions[:5] for k in m}
            ),
            "umf_top_level_keys": sorted(
                {k for umf in coordinator.pmap_details.values() for k in umf}
            ),
        },
    }
