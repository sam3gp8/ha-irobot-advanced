"""Cleaning schedule formats.

Two coexist on iRobot robots:

**Legacy** (``cleanSchedule``) — parallel arrays indexed 0=Sunday:

.. code-block:: json

    {"cycle": ["none","start",...], "h": [0,9,...], "m": [0,30,...]}

Proven and accepted by every Wi-Fi robot to date. This module reads and writes
it losslessly.

**v2** (``cleanSchedule2``) — a list of per-entry objects, room-aware. The
field is confirmed present and deserializable in the 7.18.0 app schema (it sits
in the same schema cluster as ``CleanScheduleMultipleMapping``, ``Enabled``,
``StartTime`` and ``Cycle``), but the exact object shape is assembled in the
app's serializer layer and is **not** recoverable statically. The structure
below is the best inference from that field cluster and from how the room-clean
command (``pmap_id`` / ``regions``) is shaped elsewhere in the protocol.

Because the v2 shape is inferred, this module is conservative:

* reads tolerate several plausible key spellings,
* writes default to the legacy format (universally accepted),
* v2 writes are opt-in and clearly marked, so a robot that rejects the inferred
  shape fails safely rather than corrupting the stored schedule.

One real ``cleanSchedule2`` payload — visible in a diagnostics dump once cloud
access is working — turns the inference below into fact. The ``TODO`` markers
show exactly which keys to confirm.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Legacy arrays are indexed 0=Sunday .. 6=Saturday.
WEEKDAY_ORDER = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")


@dataclass(slots=True)
class ScheduleSlot:
    """One day's schedule entry, format-independent."""

    day: str
    enabled: bool
    hour: int = 10
    minute: int = 0
    # v2 only: restrict this run to specific rooms on a specific map.
    pmap_id: str | None = None
    regions: list[str] = field(default_factory=list)

    @property
    def day_index(self) -> int:
        return WEEKDAY_ORDER.index(self.day)


# --------------------------------------------------------------------- legacy


def parse_legacy(raw: dict[str, Any]) -> list[ScheduleSlot]:
    """Read a ``cleanSchedule`` object into slots."""
    cycle = raw.get("cycle") or []
    hours = raw.get("h") or []
    minutes = raw.get("m") or []
    slots: list[ScheduleSlot] = []
    for idx, day in enumerate(WEEKDAY_ORDER):
        if idx >= len(cycle):
            break
        slots.append(
            ScheduleSlot(
                day=day,
                enabled=cycle[idx] not in ("none", "", None),
                hour=hours[idx] if idx < len(hours) else 0,
                minute=minutes[idx] if idx < len(minutes) else 0,
            )
        )
    return slots


def build_legacy(slots: list[ScheduleSlot]) -> dict[str, Any]:
    """Render slots into a ``cleanSchedule`` object.

    Room targeting is dropped here — the legacy format cannot express it.
    """
    cycle = ["none"] * 7
    hours = [0] * 7
    minutes = [0] * 7
    for slot in slots:
        idx = slot.day_index
        cycle[idx] = "start" if slot.enabled else "none"
        hours[idx] = slot.hour
        minutes[idx] = slot.minute
    return {"cycle": cycle, "h": hours, "m": minutes}


# ------------------------------------------------------------------------ v2


def parse_v2(raw: Any) -> list[ScheduleSlot]:
    """Read a ``cleanSchedule2`` value into slots, tolerantly.

    Accepts a list of entry objects. Key spellings are probed because the exact
    names are inferred; whichever the robot actually uses, the first match
    wins.
    """
    if isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = raw.get("entries", [])
    else:
        entries = []
    slots: list[ScheduleSlot] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        day = _first(entry, ("day", "d", "weekday"))
        if isinstance(day, int):
            day = WEEKDAY_ORDER[day % 7]
        elif isinstance(day, str) and day[:3].lower() in WEEKDAY_ORDER:
            day = day[:3].lower()
        else:
            continue

        start = _first(entry, ("start_time", "startTime", "start"))
        hour, minute = _split_start(start, entry)

        slots.append(
            ScheduleSlot(
                day=day,
                enabled=bool(_first(entry, ("enabled", "enable", "active"), default=True)),
                hour=hour,
                minute=minute,
                pmap_id=_first(entry, ("pmap_id", "pmapId", "map_id")),
                regions=_regions(entry),
            )
        )
    return slots


def build_v2(slots: list[ScheduleSlot]) -> list[dict[str, Any]]:
    """Render slots into an inferred ``cleanSchedule2`` list.

    TODO(confirm-with-sample): the key names below (``day``, ``enabled``,
    ``start_time`` as ``{"h","m"}``, ``pmap_id``, ``regions``) are inferred
    from the schema field cluster. Verify against a real ``cleanSchedule2``
    payload from a diagnostics dump and adjust here if they differ.
    """
    out: list[dict[str, Any]] = []
    for slot in slots:
        entry: dict[str, Any] = {
            "day": slot.day,
            "enabled": slot.enabled,
            "start_time": {"h": slot.hour, "m": slot.minute},
            "type": "clean",
        }
        if slot.pmap_id:
            entry["pmap_id"] = slot.pmap_id
        if slot.regions:
            entry["regions"] = [
                {"region_id": str(r), "type": "rid"} for r in slot.regions
            ]
        out.append(entry)
    return out


# ------------------------------------------------------------------- helpers


def has_room_targeting(slots: list[ScheduleSlot]) -> bool:
    """True if any slot targets specific rooms (needs v2)."""
    return any(slot.pmap_id or slot.regions for slot in slots)


def _first(entry: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in entry:
            return entry[key]
    return default


def _split_start(start: Any, entry: dict[str, Any]) -> tuple[int, int]:
    if isinstance(start, dict):
        return int(start.get("h", 0)), int(start.get("m", 0))
    if isinstance(start, int):  # minutes since midnight
        return start // 60, start % 60
    if isinstance(start, str) and ":" in start:  # "HH:MM"
        hh, _, mm = start.partition(":")
        return int(hh), int(mm)
    return int(entry.get("h", entry.get("hour", 0))), int(entry.get("m", entry.get("minute", 0)))


def _regions(entry: dict[str, Any]) -> list[str]:
    raw = _first(entry, ("regions", "rooms", "region_ids"), default=[])
    out: list[str] = []
    for item in raw or []:
        if isinstance(item, dict):
            rid = item.get("region_id") or item.get("id")
            if rid is not None:
                out.append(str(rid))
        else:
            out.append(str(item))
    return out
