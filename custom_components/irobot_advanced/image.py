"""Obstacle snapshot images.

Creates one image entity for the most recent obstacle the robot photographed,
plus a numbered entity for each of the next few. The URLs are pre-signed S3
links that come back inside the mission-history payload.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity

_LOGGER = logging.getLogger(__name__)

SNAPSHOT_SLOTS = 5


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        IRobotObstacleImage(hass, coordinator, index) for index in range(SNAPSHOT_SLOTS)
    )


class IRobotObstacleImage(IRobotEntity, ImageEntity):
    """One slot in the rolling obstacle-snapshot buffer."""

    _attr_translation_key = "obstacle"

    def __init__(
        self, hass: HomeAssistant, coordinator: IRobotCoordinator, index: int
    ) -> None:
        IRobotEntity.__init__(self, coordinator, f"obstacle_{index}")
        ImageEntity.__init__(self, hass)
        self._index = index
        self._attr_translation_placeholders = {"index": str(index + 1)}
        self._cached_url: str | None = None
        self._cached_bytes: bytes | None = None

    @property
    def _snapshot(self) -> dict | None:
        if self._index < len(self.coordinator.obstacles):
            return self.coordinator.obstacles[self._index]
        return None

    @property
    def available(self) -> bool:
        return self._snapshot is not None

    @property
    def image_last_updated(self) -> datetime | None:
        snapshot = self._snapshot
        if not snapshot or not snapshot.get("timestamp"):
            return None
        ts = snapshot["timestamp"]
        try:
            return datetime.fromtimestamp(float(ts), tz=UTC)
        except (TypeError, ValueError, OSError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        snapshot = self._snapshot or {}
        return {
            "obstacle_type": snapshot.get("obstacle_type"),
            "review_status": snapshot.get("review_status"),
            "mission_id": snapshot.get("mission_id"),
            "position": snapshot.get("position"),
        }

    async def async_image(self) -> bytes | None:
        snapshot = self._snapshot
        if not snapshot or self.coordinator.cloud is None:
            return None

        url = snapshot["image_url"]
        if url == self._cached_url and self._cached_bytes:
            return self._cached_bytes

        try:
            data = await self.coordinator.cloud.async_fetch_image(url)
        except Exception as err:
            _LOGGER.debug("Could not fetch obstacle snapshot: %s", err)
            return self._cached_bytes

        self._cached_url = url
        self._cached_bytes = data
        return data
