"""Vacuum platform."""

from __future__ import annotations

from typing import Any

from homeassistant.components.vacuum import (
    StateVacuumEntity,
    VacuumActivity,
    VacuumEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CYCLE_MAP,
    DOMAIN,
    ERROR_MAP,
    PHASE_MAP,
    SUCTION_LEVELS,
)
from .coordinator import IRobotCoordinator
from .entity import IRobotEntity

ACTIVITY_MAP: dict[str, VacuumActivity] = {
    "charging": VacuumActivity.DOCKED,
    "docked": VacuumActivity.DOCKED,
    "cleaning": VacuumActivity.CLEANING,
    "starting": VacuumActivity.CLEANING,
    "emptying_bin": VacuumActivity.DOCKED,
    "paused": VacuumActivity.PAUSED,
    "stuck": VacuumActivity.ERROR,
    "charging_error": VacuumActivity.ERROR,
    "returning_user": VacuumActivity.RETURNING,
    "returning_mid_mission": VacuumActivity.RETURNING,
    "returning_done": VacuumActivity.RETURNING,
    "docking": VacuumActivity.RETURNING,
    "cancelled": VacuumActivity.IDLE,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: IRobotCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([IRobotVacuum(coordinator)])


class IRobotVacuum(IRobotEntity, StateVacuumEntity):
    """The robot itself."""

    _attr_name = None
    _attr_supported_features = (
        VacuumEntityFeature.START
        | VacuumEntityFeature.STOP
        | VacuumEntityFeature.PAUSE
        | VacuumEntityFeature.RETURN_HOME
        | VacuumEntityFeature.LOCATE
        | VacuumEntityFeature.STATE
        | VacuumEntityFeature.FAN_SPEED
        | VacuumEntityFeature.SEND_COMMAND
    )
    _attr_fan_speed_list = list(SUCTION_LEVELS)

    def __init__(self, coordinator: IRobotCoordinator) -> None:
        super().__init__(coordinator, "vacuum")

    # ----------------------------------------------------------------- state

    @property
    def activity(self) -> VacuumActivity:
        phase = self.coordinator.mission.get("phase")
        friendly = PHASE_MAP.get(phase, "idle")
        if self.coordinator.mission.get("error"):
            return VacuumActivity.ERROR
        return ACTIVITY_MAP.get(friendly, VacuumActivity.IDLE)

    @property
    def fan_speed(self) -> str | None:
        reported = self.coordinator.reported
        # Newer j/s robots have no suctionLevel; they use vacHigh + carpetBoost.
        if "suctionLevel" in reported:
            level = reported.get("suctionLevel")
            for name, value in SUCTION_LEVELS.items():
                if value == level:
                    return name
        if reported.get("vacHigh"):
            return "performance"
        if reported.get("carpetBoost"):
            return "standard"
        return "eco"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        reported = self.coordinator.reported
        mission = self.coordinator.mission
        error_code = mission.get("error", 0)
        attrs: dict[str, Any] = {
            "phase": mission.get("phase"),
            "cycle": CYCLE_MAP.get(mission.get("cycle"), mission.get("cycle")),
            "error_code": error_code,
            "error": ERROR_MAP.get(error_code, f"Unknown ({error_code})"),
            "mission_id": mission.get("mssnM"),
            "square_feet": mission.get("sqft"),
            "elapsed_minutes": mission.get("mssnM"),
            "not_ready": mission.get("notReady"),
            "bin_full": (reported.get("bin") or {}).get("full"),
            "bin_present": (reported.get("bin") or {}).get("present"),
            "software_version": reported.get("softwareVer"),
            "position": self.coordinator.position or None,
            "maps": [
                {"pmap_id": p.get("pmap_id") or p.get("id"), "name": p.get("name")}
                for p in self.coordinator.pmaps
            ],
            "regions": self.coordinator.regions,
            "total_missions": (reported.get("bbrun") or {}).get("nScrubs"),
        }
        if self.coordinator.cloud_error:
            attrs["cloud_error"] = self.coordinator.cloud_error
        return {k: v for k, v in attrs.items() if v is not None}

    # -------------------------------------------------------------- commands

    async def async_start(self) -> None:
        phase = self.coordinator.mission.get("phase")
        command = "resume" if phase in ("stop", "pause") else "start"
        self.coordinator.local.send_command(command)

    async def async_pause(self) -> None:
        self.coordinator.local.send_command("pause")

    async def async_stop(self, **kwargs: Any) -> None:
        self.coordinator.local.send_command("stop")

    async def async_return_to_base(self, **kwargs: Any) -> None:
        self.coordinator.local.send_command("dock")

    async def async_locate(self, **kwargs: Any) -> None:
        self.coordinator.local.send_command("find")

    async def async_set_fan_speed(self, fan_speed: str, **kwargs: Any) -> None:
        reported = self.coordinator.reported
        # Prefer suctionLevel when the robot supports it.
        if "suctionLevel" in reported:
            if (level := SUCTION_LEVELS.get(fan_speed)) is not None:
                self.coordinator.local.set_preference(suctionLevel=level)
            return
        # Otherwise map onto the vacHigh/carpetBoost pair this robot honours:
        #   eco         -> both off
        #   standard    -> carpetBoost auto (vacHigh off)
        #   performance -> vacHigh on
        mapping = {
            "eco": {"vacHigh": False, "carpetBoost": False},
            "standard": {"vacHigh": False, "carpetBoost": True},
            "performance": {"vacHigh": True, "carpetBoost": False},
        }
        if (pref := mapping.get(fan_speed)) is not None:
            self.coordinator.local.set_preference(**pref)

    async def async_send_command(
        self,
        command: str,
        params: dict[str, Any] | list[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Escape hatch. ``set`` writes preferences, anything else is a command."""
        if command == "set" and isinstance(params, dict):
            self.coordinator.local.set_preference(**params)
        elif command == "pose":
            self.coordinator.local.request_position()
        elif command == "timeline":
            self.coordinator.local.request_timeline()
        else:
            extra = params if isinstance(params, dict) else {}
            self.coordinator.local.send_command(command, **extra)
