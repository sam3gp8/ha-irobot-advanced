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

_REGISTERED = f"{DOMAIN}_frontend_registered"


async def async_register_frontend(hass: HomeAssistant) -> None:
    """Register the card and panel once, no matter how many robots exist."""
    if hass.data.get(_REGISTERED):
        return

    source = Path(__file__).parent / "www" / CARD_FILENAME
    if not source.is_file():
        _LOGGER.warning("Card asset missing at %s; skipping frontend setup", source)
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(source), cache_headers=False)]
    )

    # Makes <irobot-advanced-card> available to dashboards and the card picker.
    frontend.add_extra_js_url(hass, CARD_URL)

    with contextlib.suppress(ValueError):
        # ValueError == already registered by a previous setup; harmless.
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

    hass.data[_REGISTERED] = True
    _LOGGER.debug("Frontend card and panel registered at %s", CARD_URL)


def async_remove_frontend(hass: HomeAssistant) -> None:
    """Drop the sidebar panel when the last entry is removed."""
    if not hass.data.pop(_REGISTERED, None):
        return
    frontend.async_remove_panel(hass, PANEL_URL_PATH)
