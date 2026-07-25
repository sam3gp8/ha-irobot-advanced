"""Cleaning schedule formats.

Two coexist on iRobot robots:

**Legacy** (``cleanSchedule``) — parallel arrays indexed 0=Sunday:

.. code-block:: json

    {"cycle": ["none","start",...], "h": [0,9,...], "m": [0,30,...]}

**v2** (``cleanSchedule2``) — a list of entries, each grouping multiple days.
Structure confirmed from a live j-series robot:

.. code-block:: json

    [{"enabled": true,
      "type": 0,
      "start": {"day": [3,4,5,6], "hour": 12, "min": 30},
      "cmdStr": "{'command': 'start', 'params': {...}, 'time': ..., 'initiator': 'schedule'}"}]

Key facts (verified, no longer inferred):

* ``start.day`` is a **list** of weekday integers (0=Sunday), so one entry can
  cover several days that share a time and command.
* Time is ``start.hour`` / ``start.min``.
* ``type`` is 0 for a normal clean.
* ``cmdStr`` is a **stringified command** (note: single-quoted, Python-repr
  style, not strict JSON) carrying the start command and its params. Room
  targeting, when present, lives inside this command, not as sibling keys.
"""

from __future__ import annotations

import ast
import json
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
    # v2 extras carried through the command string.
    params: dict[str, Any] = field(default_factory=dict)
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


def _loads_cmdstr(cmd_str: str) -> dict[str, Any]:
    """Parse the quirky single-quoted ``cmdStr`` into a dict.

    It is Python-repr style (single quotes, ``true``/``false`` lowercased), so
    try strict JSON first, then a safe literal-eval fallback with the booleans
    normalised.
    """
    try:
        return json.loads(cmd_str)
    except (ValueError, TypeError):
        pass
    try:
        return ast.literal_eval(cmd_str)
    except (ValueError, SyntaxError):
        return {}


def _dumps_cmdstr(command: dict[str, Any]) -> str:
    """Render a command dict back to the robot's expected string form.

    The robot emits Python-repr style, but accepts valid JSON on input; use
    JSON for correctness.
    """
    return json.dumps(command)


def parse_v2(raw: Any) -> list[ScheduleSlot]:
    """Expand a ``cleanSchedule2`` value into one slot per day."""
    entries = raw if isinstance(raw, list) else []
    slots: list[ScheduleSlot] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        start = entry.get("start") or {}
        days = start.get("day")
        if isinstance(days, int):
            days = [days]
        if not isinstance(days, list):
            continue
        hour = int(start.get("hour", 0))
        minute = int(start.get("min", start.get("minute", 0)))
        enabled = bool(entry.get("enabled", True))

        command = _loads_cmdstr(entry.get("cmdStr", "")) if entry.get("cmdStr") else {}
        params = command.get("params", {}) if isinstance(command, dict) else {}
        pmap_id = command.get("pmap_id")
        regions = [
            str(r.get("region_id", r)) if isinstance(r, dict) else str(r)
            for r in (command.get("regions") or [])
        ]

        for day_int in days:
            if not isinstance(day_int, int) or not 0 <= day_int <= 6:
                continue
            slots.append(
                ScheduleSlot(
                    day=WEEKDAY_ORDER[day_int],
                    enabled=enabled,
                    hour=hour,
                    minute=minute,
                    params=dict(params),
                    pmap_id=pmap_id,
                    regions=regions,
                )
            )
    return slots


def build_v2(slots: list[ScheduleSlot]) -> list[dict[str, Any]]:
    """Render slots into ``cleanSchedule2``, grouping days that match.

    Entries are grouped by (time, enabled, command) so days sharing a schedule
    collapse into one entry with a ``start.day`` list, mirroring what the robot
    itself stores.
    """
    # Group key -> (representative slot, [day ints])
    groups: dict[tuple, list[int]] = {}
    order: list[tuple] = []
    reps: dict[tuple, ScheduleSlot] = {}
    for slot in slots:
        if not slot.enabled:
            continue
        params_key = tuple(sorted(slot.params.items()))
        regions_key = tuple(slot.regions)
        key = (slot.hour, slot.minute, slot.pmap_id, regions_key, params_key)
        if key not in groups:
            groups[key] = []
            reps[key] = slot
            order.append(key)
        groups[key].append(slot.day_index)

    out: list[dict[str, Any]] = []
    for key in order:
        slot = reps[key]
        command: dict[str, Any] = {
            "command": "start",
            "params": slot.params
            or {
                "carpetBoost": True,
                "noAutoPasses": True,
                "twoPass": True,
                "vacHigh": False,
            },
            "initiator": "schedule",
        }
        if slot.pmap_id:
            command["pmap_id"] = slot.pmap_id
        if slot.regions:
            command["regions"] = [
                {"region_id": str(r), "type": "rid"} for r in slot.regions
            ]
        out.append(
            {
                "enabled": True,
                "type": 0,
                "start": {
                    "day": sorted(set(groups[key])),
                    "hour": slot.hour,
                    "min": slot.minute,
                },
                "cmdStr": _dumps_cmdstr(command),
            }
        )
    return out


# ------------------------------------------------------------------- helpers


def has_room_targeting(slots: list[ScheduleSlot]) -> bool:
    """True if any slot targets specific rooms (needs v2)."""
    return any(slot.pmap_id or slot.regions for slot in slots)
