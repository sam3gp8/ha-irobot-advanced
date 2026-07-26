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
        # anyone having to paste their map data into an issue. Goes one level
        # deeper into the structures we're still nailing down (region objects,
        # mission timeline) so their field names are visible without the data.
        "shapes": {
            "pmap_keys": sorted({k for p in coordinator.pmaps for k in p}),
            "mission_keys": sorted(
                {k for m in coordinator.missions[:5] for k in m}
            ),
            "umf_top_level_keys": sorted(
                {k for umf in coordinator.pmap_details.values() for k in umf}
            ),
            "region_object_keys": _first_child_keys(
                coordinator.pmap_details.values(), "regions"
            ),
            "zone_object_keys": _first_child_keys(
                coordinator.pmap_details.values(), "zones"
            ),
            "mission_timeline_keys": _first_timeline_keys(coordinator.missions),
            "omap_keys": _omap_shape(coordinator),
            # Service names the robot advertises. Keys only -- the values can
            # carry deployment/account identifiers and stay redacted.
            "svc_endpoint_names": _svc_endpoint_names(coordinator),
        },
    }


def _svc_endpoint_names(coordinator: IRobotCoordinator) -> Any:
    """Which services the robot advertises, without exposing their URLs."""
    svc = coordinator.reported.get("svcEndpoints")
    if isinstance(svc, dict):
        return sorted(svc.keys())
    if isinstance(svc, str):
        return {"type": "string", "length": len(svc)}
    return None


def _omap_shape(coordinator: IRobotCoordinator) -> dict[str, Any]:
    """Capture omap + spatial-data shape so obstacle fields can be confirmed."""
    cloud = coordinator.cloud
    if cloud is None:
        return {"available": False}
    # Best-effort synchronous snapshot from whatever the coordinator cached.
    debug = getattr(cloud, "last_omap_debug", None)
    sample = getattr(coordinator, "_last_omap_spatial", None)
    if not isinstance(sample, dict):
        return {
            "available": False,
            "note": "no omap spatial fetched",
            "omap_list": debug,
        }
    return {
        "omap_list": debug,
        "available": True,
        "spatial_top_level_keys": sorted(sample.keys()),
        "object_container_keys": sorted(
            k for k in sample
            if isinstance(sample.get(k), list)
        ),
    }


def _first_child_keys(details: Any, list_key: str) -> list[str]:
    """Keys of the first object inside ``detail[list_key]`` across maps."""
    for detail in details:
        items = detail.get(list_key) or []
        for item in items:
            if isinstance(item, dict):
                return sorted(item.keys())
    return []


def _first_timeline_keys(missions: Any) -> list[str]:
    """Keys of the first mission-timeline entry, where obstacles may live."""
    for mission in missions[:10]:
        timeline = mission.get("timeline")
        if isinstance(timeline, list) and timeline and isinstance(timeline[0], dict):
            return sorted(timeline[0].keys())
        if isinstance(timeline, dict):
            return sorted(timeline.keys())
    return []
