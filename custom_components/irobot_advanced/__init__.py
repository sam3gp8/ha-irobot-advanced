"""The iRobot Advanced integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv, entity_registry as er

from .const import (
    CONF_APP_ID,
    CONF_ENABLE_CLOUD,
    DEFAULT_APP_ID,
    DOMAIN,
    SERVICE_CLEAN_ROOMS,
    SERVICE_EMPTY_BIN,
    SERVICE_LOCATE,
    SERVICE_REFRESH_MAPS,
    SERVICE_SET_SCHEDULE,
    WEEKDAYS,
)
from .coordinator import IRobotCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.VACUUM,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
    Platform.SWITCH,
    Platform.CAMERA,
    Platform.IMAGE,
]

CLEAN_ROOMS_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required("regions"): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional("pmap_id"): cv.string,
        vol.Optional("two_pass", default=False): cv.boolean,
    }
)

SET_SCHEDULE_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required("schedule"): vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required("day"): vol.In(WEEKDAYS),
                        vol.Required("enabled"): cv.boolean,
                        vol.Optional("hour", default=10): vol.All(int, vol.Range(0, 23)),
                        vol.Optional("minute", default=0): vol.All(int, vol.Range(0, 59)),
                    }
                )
            ],
        ),
    }
)

SIMPLE_SCHEMA = vol.Schema({vol.Required("entity_id"): cv.entity_ids})


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old config entries forward.

    v1 -> v2: cloud access used a manually captured bearer token. That
    mechanism is gone -- the integration now signs in with the account email
    and password and refreshes on its own. The token is dropped and cloud
    features are switched off; local control is unaffected, and the user can
    re-enable the cloud from the options flow at any time.
    """
    if entry.version > 2:
        # Downgraded from a newer release -- refuse rather than corrupt data.
        return False

    if entry.version == 1:
        data = dict(entry.data)
        had_token = bool(data.pop("cloud_token", None))
        data.pop("cloud_base", None)
        data[CONF_ENABLE_CLOUD] = False
        data.setdefault(CONF_APP_ID, DEFAULT_APP_ID)

        hass.config_entries.async_update_entry(entry, data=data, version=2)

        if had_token:
            _LOGGER.warning(
                "%s: the stored cloud token was discarded. Cloud features now "
                "use your iRobot account sign-in -- re-enable them from the "
                "integration options to restore maps and snapshots",
                entry.title,
            )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one robot."""
    coordinator = IRobotCoordinator(hass, entry)

    try:
        await coordinator.async_start()
    except OSError as err:
        raise ConfigEntryNotReady(f"Cannot reach robot at {coordinator.host}") from err

    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _async_register_services(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: IRobotCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_CLEAN_ROOMS):
        return

    def _coordinators_for(call: ServiceCall) -> list[IRobotCoordinator]:
        registry = er.async_get(hass)
        found: list[IRobotCoordinator] = []
        for entity_id in call.data["entity_id"]:
            entry = registry.async_get(entity_id)
            if entry and entry.config_entry_id in hass.data.get(DOMAIN, {}):
                found.append(hass.data[DOMAIN][entry.config_entry_id])
        return found

    async def _clean_rooms(call: ServiceCall) -> None:
        for coordinator in _coordinators_for(call):
            pmap_id = call.data.get("pmap_id")
            if not pmap_id:
                known = coordinator.regions
                pmap_id = known[0]["pmap_id"] if known else None
            if not pmap_id:
                _LOGGER.error("No pmap_id known -- enable cloud access or pass one")
                continue
            regions = [
                {"region_id": str(rid), "type": "rid"} for rid in call.data["regions"]
            ]
            coordinator.local.clean_regions(pmap_id, regions)

    async def _set_schedule(call: ServiceCall) -> None:
        for coordinator in _coordinators_for(call):
            cycle = ["none"] * 7
            hours = [0] * 7
            minutes = [0] * 7
            for slot in call.data["schedule"]:
                idx = WEEKDAYS.index(slot["day"])
                cycle[idx] = "start" if slot["enabled"] else "none"
                hours[idx] = slot.get("hour", 10)
                minutes[idx] = slot.get("minute", 0)
            coordinator.local.set_preference(
                cleanSchedule={"cycle": cycle, "h": hours, "m": minutes}
            )

    async def _empty_bin(call: ServiceCall) -> None:
        for coordinator in _coordinators_for(call):
            coordinator.local.send_command("evac")

    async def _locate(call: ServiceCall) -> None:
        for coordinator in _coordinators_for(call):
            coordinator.local.send_command("find")

    async def _refresh_maps(call: ServiceCall) -> None:
        for coordinator in _coordinators_for(call):
            await coordinator.async_refresh_maps()

    hass.services.async_register(DOMAIN, SERVICE_CLEAN_ROOMS, _clean_rooms, CLEAN_ROOMS_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_SET_SCHEDULE, _set_schedule, SET_SCHEDULE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_EMPTY_BIN, _empty_bin, SIMPLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_LOCATE, _locate, SIMPLE_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_REFRESH_MAPS, _refresh_maps, SIMPLE_SCHEMA)
