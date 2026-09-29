"""Serve the dashboard card and register the sidebar panel.

The card JavaScript ships inside the integration rather than as a separate
HACS frontend plugin, so there is nothing extra for the user to install. It is
served from a static path and registered as an extra frontend module, which
also makes it selectable in the Lovelace card picker.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

CARD_FILENAME = "irobot-advanced-card.js"
CARD_URL = f"/{DOMAIN}/{CARD_FILENAME}"
PANEL_URL_PATH = "irobot-advanced"

# The static path and extra-JS URL are bound to the aiohttp app / frontend for
# the lifetime of the running Home Assistant process -- there is no public API
# to undo them. This flag is set once and never cleared, so a reload or a
# remove-and-re-add of the integration does not try to register them a second
# time (which raises "method GET is already registered"). The panel, by
# contrast, can be removed and re-added, so it is not gated by this flag.
_STATIC_REGISTERED = f"{DOMAIN}_frontend_static_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the card and panel once, no matter how many robots exist.

    Frontend registration is best-effort: the card and sidebar panel are a
    convenience, so any failure here is logged and swallowed rather than
    allowed to abort the config entry setup and leave the robot unavailable.
    """
    try:
        await _async_register_frontend(hass)
    except Exception:  # noqa: BLE001 - never let the card break the robot
        _LOGGER.exception(
            "Failed to register the iRobot dashboard card/panel; the robot "
            "entities are unaffected"
        )


async def _async_register_frontend(hass: HomeAssistant) -> None:
    source = Path(__file__).parent / "www" / CARD_FILENAME
    if not source.is_file():
        _LOGGER.warning("Card asset missing at %s; skipping frontend setup", source)
        return

    # Static path + extra-JS URL: register at most once per process. aiohttp
    # keeps the GET route even after the integration is unloaded, so a second
    # attempt after a reload/reinstall would raise a RuntimeError.
    if not hass.data.get(_STATIC_REGISTERED):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(CARD_URL, str(source), cache_headers=False)]
        )
        # Makes <irobot-advanced-card> available to dashboards and the picker.
        frontend.add_extra_js_url(hass, CARD_URL)
        hass.data[_STATIC_REGISTERED] = True

    # The panel can be removed (see async_remove_frontend) and re-added, so
    # (re)register it on every setup. ValueError == already registered.
    with contextlib.suppress(ValueError):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name="irobot-advanced-panel",
            module_url=CARD_URL,
            sidebar_title="iRobot",
            sidebar_icon="mdi:robot-vacuum",
            require_admin=False,
            embed_iframe=False,
        )

    _LOGGER.debug("Frontend card and panel registered at %s", CARD_URL)


def async_remove_frontend(hass: HomeAssistant) -> None:
    """Drop the sidebar panel when the last entry is removed.

    Only the panel is removed here. The static path and extra-JS URL cannot be
    unregistered from the running process, so their guard flag is deliberately
    left in place to keep a later re-add from registering them twice.
    """
    with contextlib.suppress(ValueError):
        # ValueError == panel not currently registered; harmless.
        frontend.async_remove_panel(hass, PANEL_URL_PATH)
