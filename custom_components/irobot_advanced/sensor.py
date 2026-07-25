"""Sensor platform."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfArea, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CYCLE_MAP, DOMAIN, ERROR_MAP, PHASE_MAP
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity
from .schedule import parse_legacy, parse_v2


@dataclass(frozen=True, kw_only=True)
class IRobotSensorDescription(SensorEntityDescription):
    value_fn: Callable[[IRobotCoordinator], Any]
    attrs_fn: Callable[[IRobotCoordinator], dict[str, Any]] | None = None


def _run_stats(coordinator: IRobotCoordinator, key: str) -> Any:
    return (coordinator.reported.get("bbrun") or {}).get(key)


def _last_mission_start(coordinator: IRobotCoordinator) -> datetime | None:
    ts = coordinator.mission.get("mssnStrtTm")
    if not ts:
        return None
    return datetime.fromtimestamp(ts, tz=UTC)


SENSORS: tuple[IRobotSensorDescription, ...] = (
    IRobotSensorDescription(
        key="battery",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda c: c.reported.get("batPct"),
    ),
    IRobotSensorDescription(
        key="phase",
        translation_key="phase",
        value_fn=lambda c: PHASE_MAP.get(c.mission.get("phase"), c.mission.get("phase")),
    ),
    IRobotSensorDescription(
        key="cycle",
        translation_key="cycle",
        value_fn=lambda c: CYCLE_MAP.get(c.mission.get("cycle"), c.mission.get("cycle")),
    ),
    IRobotSensorDescription(
        key="error",
        translation_key="error",
        value_fn=lambda c: ERROR_MAP.get(
            c.mission.get("error", 0), f"Unknown ({c.mission.get('error')})"
        ),
        attrs_fn=lambda c: {"error_code": c.mission.get("error", 0)},
    ),
    IRobotSensorDescription(
        key="area_cleaned",
        translation_key="area_cleaned",
        device_class=SensorDeviceClass.AREA,
        native_unit_of_measurement=UnitOfArea.SQUARE_FEET,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.mission.get("sqft"),
    ),
    IRobotSensorDescription(
        key="mission_minutes",
        translation_key="mission_minutes",
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: c.mission.get("mssnM"),
    ),
    IRobotSensorDescription(
        key="last_mission_start",
        translation_key="last_mission_start",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_last_mission_start,
    ),
    IRobotSensorDescription(
        key="total_missions",
        translation_key="total_missions",
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _run_stats(c, "nScrubs"),
        attrs_fn=lambda c: {"recent_missions": _recent_missions(c)},
    ),
    IRobotSensorDescription(
        key="total_runtime",
        translation_key="total_runtime",
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _run_stats(c, "hr"),
    ),
    IRobotSensorDescription(
        key="wifi_signal",
        translation_key="wifi_signal",
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement="dBm",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (c.reported.get("signal") or {}).get("rssi"),
        attrs_fn=lambda c: {"snr": (c.reported.get("signal") or {}).get("snr")},
    ),
    IRobotSensorDescription(
        key="obstacle_count",
        translation_key="obstacle_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: len(c.obstacles),
        attrs_fn=lambda c: {
            "recent": [
                {
                    "type": o.get("obstacle_type"),
                    "timestamp": o.get("timestamp"),
                    "position": o.get("position"),
                }
                for o in c.obstacles[:10]
            ]
        },
    ),
    IRobotSensorDescription(
        key="map_count",
        translation_key="map_count",
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: len(c.pmaps),
        attrs_fn=lambda c: {"regions": c.regions},
    ),
    IRobotSensorDescription(
        key="schedule",
        translation_key="schedule",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: _schedule_summary(c),
        attrs_fn=lambda c: {
            "raw": c.reported.get("cleanSchedule2") or c.reported.get("cleanSchedule"),
            "on_hold": c.reported.get("scheduleOnHold"),
        },
    ),
)


def _recent_missions(coordinator: IRobotCoordinator) -> list[dict[str, Any]]:
    """Trimmed mission records for the dashboard card.

    Entity attributes are size-capped, so this keeps the ten most recent runs
    and only the fields the card renders.
    """
    return [
        {
            "id": mission.get("id") or mission.get("missionId"),
            "start": mission.get("startTime") or mission.get("start_time"),
            "duration": mission.get("duration") or mission.get("runtime"),
            "area": mission.get("sqft") or mission.get("area"),
            "status": mission.get("status") or mission.get("endStatus"),
            "error": mission.get("error"),
        }
        for mission in coordinator.missions[:10]
    ]


def _schedule_summary(coordinator: IRobotCoordinator) -> str:
    """Summarise whichever schedule format the robot reports."""
    reported = coordinator.reported
    if "cleanSchedule2" in reported:
        slots = parse_v2(reported["cleanSchedule2"])
        enabled = sum(1 for slot in slots if slot.enabled)
        rooms = sum(1 for slot in slots if slot.regions)
        if not slots:
            return "unknown"
        suffix = f", {rooms} room-specific" if rooms else ""
        return f"{enabled} day(s) scheduled{suffix}"

    sched = reported.get("cleanSchedule") or {}
    if not sched.get("cycle"):
        return "unknown"
    enabled = sum(1 for slot in parse_legacy(sched) if slot.enabled)
    return f"{enabled} day(s) scheduled"


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(IRobotSensor(coordinator, desc) for desc in SENSORS)


class IRobotSensor(IRobotEntity, SensorEntity):
    entity_description: IRobotSensorDescription

    def __init__(
        self, coordinator: IRobotCoordinator, description: IRobotSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator)
