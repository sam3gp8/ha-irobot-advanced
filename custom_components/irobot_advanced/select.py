"""Select platform: pick a mapped room to clean next."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IRobotRoomSelect(coordinator)])


class IRobotRoomSelect(IRobotEntity, SelectEntity):
    """Selecting a room starts a targeted clean immediately."""

    _attr_translation_key = "room"

    def __init__(self, coordinator: IRobotCoordinator) -> None:
        super().__init__(coordinator, "room")
        self._current: str | None = None

    @property
    def options(self) -> list[str]:
        names = [r["name"] for r in self.coordinator.regions if r.get("name")]
        return names or ["No maps available"]

    @property
    def current_option(self) -> str | None:
        return self._current

    async def async_select_option(self, option: str) -> None:
        match = next(
            (r for r in self.coordinator.regions if r.get("name") == option), None
        )
        if not match:
            return
        self._current = option
        self.coordinator.local.clean_regions(
            match["pmap_id"], [{"region_id": match["region_id"], "type": "rid"}]
        )
        self.async_write_ha_state()
