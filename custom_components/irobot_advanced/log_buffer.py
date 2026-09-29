"""In-memory capture of this integration's recent log records.

Home Assistant's *Download Diagnostics* gives a point-in-time snapshot of the
robot's state, but not the trail of log messages that led up to a problem --
the very thing that is most useful in a bug report. This module installs a
small, bounded ring-buffer handler on the integration's package logger so that
recent messages (and errors in particular) travel with the diagnostics dump
instead of having the user hunt through Home Assistant's system log.

The handler only receives whatever records the logger already emits, so it does
not raise the integration's log level or add noise to the main HA log; it just
keeps the last few hundred lines in memory.
"""

from __future__ import annotations

import logging
from collections import deque
from datetime import UTC, datetime
from typing import Any

from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

# Root logger for everything under ``custom_components.irobot_advanced.*``.
_PACKAGE_LOGGER = __name__.rsplit(".", 1)[0]

# How many recent records / errors to retain. Bounded so the buffer can never
# grow without limit on a long-running instance.
_MAX_RECORDS = 300
_MAX_ERRORS = 50

DATA_LOG_HANDLER = f"{DOMAIN}_log_handler"

_EXC_FORMATTER = logging.Formatter()


class _RingBufferHandler(logging.Handler):
    """Keep the most recent log records in memory for diagnostics."""

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        # deque.append is atomic under the GIL, so records emitted from the
        # paho-mqtt threads can be captured without extra locking.
        self.records: deque[dict[str, Any]] = deque(maxlen=_MAX_RECORDS)
        self.errors: deque[dict[str, Any]] = deque(maxlen=_MAX_ERRORS)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry: dict[str, Any] = {
                "time": datetime.fromtimestamp(
                    record.created, tz=UTC
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                entry["exception"] = _EXC_FORMATTER.formatException(record.exc_info)
        except Exception:  # logging must never raise
            return
        self.records.append(entry)
        if record.levelno >= logging.ERROR:
            self.errors.append(entry)


@callback
def async_setup_log_capture(hass: HomeAssistant) -> None:
    """Attach the ring-buffer handler to the integration logger, once."""
    if hass.data.get(DATA_LOG_HANDLER):
        return
    handler = _RingBufferHandler()
    logging.getLogger(_PACKAGE_LOGGER).addHandler(handler)
    hass.data[DATA_LOG_HANDLER] = handler


@callback
def async_teardown_log_capture(hass: HomeAssistant) -> None:
    """Detach the ring-buffer handler when the last entry is removed."""
    handler: _RingBufferHandler | None = hass.data.pop(DATA_LOG_HANDLER, None)
    if handler is None:
        return
    logging.getLogger(_PACKAGE_LOGGER).removeHandler(handler)


@callback
def async_get_log_snapshot(hass: HomeAssistant) -> dict[str, Any]:
    """Return a copy of the captured logs and errors for diagnostics.

    The returned dicts are shallow copies so callers (e.g. redaction) can mutate
    them freely without corrupting the live buffer.
    """
    handler: _RingBufferHandler | None = hass.data.get(DATA_LOG_HANDLER)
    if handler is None:
        return {"available": False, "captured": 0, "errors": [], "recent": []}
    errors = [dict(e) for e in handler.errors]
    recent = [dict(r) for r in handler.records]
    return {
        "available": True,
        "captured": len(recent),
        "error_count": len(errors),
        "errors": errors,
        "recent": recent,
    }
