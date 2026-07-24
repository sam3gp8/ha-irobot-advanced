"""Shared entity base."""

from __future__ import annotations

from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import IRobotCoordinator


class IRobotEntity(CoordinatorEntity[IRobotCoordinator]):
    """Base entity bound to one robot."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: IRobotCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.blid}_{key}"

    @property
    def device_info(self) -> DeviceInfo:
        reported = self.coordinator.reported
        connections = set()
        if mac := reported.get("mac"):
            connections.add((CONNECTION_NETWORK_MAC, mac))
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.blid)},
            connections=connections,
            manufacturer="iRobot",
            name=self.coordinator.robot_name,
            model=reported.get("sku"),
            sw_version=(reported.get("softwareVer") or reported.get("sw_ver")),
            configuration_url=f"http://{self.coordinator.host}",
        )

    @property
    def available(self) -> bool:
        return self.coordinator.local.connected
