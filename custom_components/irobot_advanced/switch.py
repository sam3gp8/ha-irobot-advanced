"""Switch platform for robot preferences."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity


@dataclass(frozen=True, kw_only=True)
class IRobotSwitchDescription(SwitchEntityDescription):
    value_fn: Callable[[IRobotCoordinator], bool | None]
    set_fn: Callable[[IRobotCoordinator, bool], None]


SWITCHES: tuple[IRobotSwitchDescription, ...] = (
    IRobotSwitchDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.reported.get("childLock"),
        set_fn=lambda c, v: c.local.set_preference(childLock=v),
    ),
    IRobotSwitchDescription(
        key="edge_clean",
        translation_key="edge_clean",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.reported.get("openOnly") is False,
        set_fn=lambda c, v: c.local.set_preference(openOnly=not v),
    ),
    IRobotSwitchDescription(
        key="two_pass",
        translation_key="two_pass",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.reported.get("twoPass"),
        set_fn=lambda c, v: c.local.set_preference(twoPass=v),
    ),
    IRobotSwitchDescription(
        key="schedule_hold",
        translation_key="schedule_hold",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: (c.reported.get("scheduleOnHold") or {}).get("enabled"),
        set_fn=lambda c, v: c.local.set_preference(scheduleOnHold={"enabled": v}),
    ),
    IRobotSwitchDescription(
        key="carpet_boost",
        translation_key="carpet_boost",
        entity_category=EntityCategory.CONFIG,
        value_fn=lambda c: c.reported.get("carpetBoost"),
        set_fn=lambda c, v: c.local.set_preference(carpetBoost=v, vacHigh=False),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(IRobotSwitch(coordinator, d) for d in SWITCHES)


class IRobotSwitch(IRobotEntity, SwitchEntity):
    entity_description: IRobotSwitchDescription

    def __init__(
        self, coordinator: IRobotCoordinator, description: IRobotSwitchDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.entity_description.set_fn(self.coordinator, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.entity_description.set_fn(self.coordinator, False)
