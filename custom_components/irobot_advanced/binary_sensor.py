"""Binary sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity


@dataclass(frozen=True, kw_only=True)
class IRobotBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[IRobotCoordinator], bool | None]


BINARY_SENSORS: tuple[IRobotBinaryDescription, ...] = (
    IRobotBinaryDescription(
        key="bin_full",
        translation_key="bin_full",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: (c.reported.get("bin") or {}).get("full"),
    ),
    IRobotBinaryDescription(
        key="bin_present",
        translation_key="bin_present",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (c.reported.get("bin") or {}).get("present"),
    ),
    IRobotBinaryDescription(
        key="docked",
        translation_key="docked",
        value_fn=lambda c: c.mission.get("phase") in ("charge", "dockend"),
    ),
    IRobotBinaryDescription(
        key="error",
        translation_key="error",
        device_class=BinarySensorDeviceClass.PROBLEM,
        value_fn=lambda c: bool(c.mission.get("error")),
    ),
    IRobotBinaryDescription(
        key="child_lock",
        translation_key="child_lock",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.reported.get("childLock"),
    ),
    IRobotBinaryDescription(
        key="cloud_connected",
        translation_key="cloud_connected",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.cloud is not None and c.cloud_error is None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(IRobotBinarySensor(coordinator, d) for d in BINARY_SENSORS)


class IRobotBinarySensor(IRobotEntity, BinarySensorEntity):
    entity_description: IRobotBinaryDescription

    def __init__(
        self, coordinator: IRobotCoordinator, description: IRobotBinaryDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)
