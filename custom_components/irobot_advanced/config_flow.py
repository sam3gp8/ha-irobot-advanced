"""Config flow.

Two ways in:

* **Cloud account** (recommended) -- email and password. The integration
  discovers the Gigya API key itself, logs in, and pulls every robot's local
  MQTT password straight out of the login response. No HOME-button dance, and
  credentials refresh on their own afterwards.
* **Local only** -- LAN discovery plus the manual password exchange, for people
  who would rather not hand their account password to Home Assistant.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    SOURCE_INTEGRATION_DISCOVERY,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
try:  # HA 2025.1+
    from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # pragma: no cover - older cores
    from homeassistant.components.dhcp import DhcpServiceInfo
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .auth import IRobotAuth, IRobotAuthError, InvalidCredentials
from .const import (
    CONF_APP_ID,
    CONF_BLID,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_USERNAME,
    CONF_CONTINUOUS,
    CONF_COUNTRY,
    CONF_ENABLE_CLOUD,
    CONF_ROBOT_PASSWORD,
    DEFAULT_APP_ID,
    DOMAIN,
)
from .local_client import PasswordNotReady, async_discover, async_get_password

_LOGGER = logging.getLogger(__name__)


class IRobotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle setup for one robot."""

    VERSION = 2

    def __init__(self) -> None:
        self._discovered: list[dict[str, Any]] = []
        self._selected: dict[str, Any] = {}
        self._cloud: dict[str, Any] = {}
        self._cloud_robots: dict[str, Any] = {}

    # ------------------------------------------------------------------ entry

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=["cloud", "local"]
        )

    # ------------------------------------------------------------------ cloud

    async def async_step_cloud(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            auth = IRobotAuth(
                session=async_get_clientsession(self.hass),
                username=user_input[CONF_USERNAME],
                password=user_input[CONF_PASSWORD],
                country_code=user_input.get(CONF_COUNTRY, "US"),
                app_id=user_input.get(CONF_APP_ID) or DEFAULT_APP_ID,
            )
            try:
                await auth.async_login()
            except InvalidCredentials:
                errors["base"] = "invalid_auth"
            except IRobotAuthError as err:
                _LOGGER.debug("Cloud login failed: %s", err)
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during cloud login")
                errors["base"] = "unknown"
            else:
                if not auth.robots:
                    errors["base"] = "no_robots"
                else:
                    self._cloud = {
                        CONF_CLOUD_USERNAME: user_input[CONF_USERNAME],
                        CONF_CLOUD_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_COUNTRY: user_input.get(CONF_COUNTRY, "US"),
                        CONF_APP_ID: user_input.get(CONF_APP_ID) or DEFAULT_APP_ID,
                    }
                    self._cloud_robots = auth.robots
                    self._discovered = await async_discover()
                    return await self.async_step_pick_robot()

        return self.async_show_form(
            step_id="cloud",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_COUNTRY, default="US"): str,
                }
            ),
            errors=errors,
        )

    async def async_step_pick_robot(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Choose which of the account's robots to add."""
        if user_input is not None:
            blid = user_input[CONF_BLID]
            info = self._cloud_robots[blid]
            host = self._ip_for(blid) or user_input.get(CONF_HOST)
            if not host:
                return await self.async_step_manual_host()

            password = info.get("password") or info.get("robot_password")
            if not password:
                # Rare, but fall back to the local exchange rather than fail.
                self._selected = {"ip": host, "blid": blid}
                return await self.async_step_password()

            await self.async_set_unique_id(blid)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})
            self._queue_other_robots(blid)
            return self.async_create_entry(
                title=info.get("name") or f"Roomba {blid[-6:]}",
                data={
                    CONF_HOST: host,
                    "host": host,
                    CONF_BLID: blid,
                    CONF_ROBOT_PASSWORD: password,
                    CONF_CONTINUOUS: True,
                    CONF_ENABLE_CLOUD: True,
                    **self._cloud,
                },
            )

        choices = {
            blid: f"{info.get('name') or blid} "
            f"({self._ip_for(blid) or 'not seen on this network'})"
            for blid, info in self._cloud_robots.items()
        }
        return self.async_show_form(
            step_id="pick_robot",
            data_schema=vol.Schema({vol.Required(CONF_BLID): vol.In(choices)}),
        )

    async def async_step_manual_host(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The robot is in the account but did not answer LAN discovery."""
        if user_input is not None:
            return await self.async_step_pick_robot(
                {CONF_BLID: user_input[CONF_BLID], CONF_HOST: user_input[CONF_HOST]}
            )

        return self.async_show_form(
            step_id="manual_host",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_BLID): vol.In(list(self._cloud_robots)),
                    vol.Required(CONF_HOST): str,
                }
            ),
        )

    def _ip_for(self, blid: str) -> str | None:
        for robot in self._discovered:
            if robot.get("blid") == blid:
                return robot.get("ip")
        return None

    # ------------------------------------------------------------------ local

    async def async_step_local(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_HOST] == "__manual__":
                return await self.async_step_manual()
            self._selected = next(
                r for r in self._discovered if r["ip"] == user_input[CONF_HOST]
            )
            return await self.async_step_password()

        self._discovered = await async_discover()
        if not self._discovered:
            return await self.async_step_manual()

        choices = {
            robot["ip"]: f"{robot.get('robotname', 'Roomba')} ({robot['ip']})"
            for robot in self._discovered
        }
        choices["__manual__"] = "Enter an IP address manually"

        return self.async_show_form(
            step_id="local",
            data_schema=vol.Schema({vol.Required(CONF_HOST): vol.In(choices)}),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._selected = {"ip": user_input[CONF_HOST]}
            return await self.async_step_password()

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
        )

    async def async_step_password(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual password exchange -- only used on the local-only path."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = self._selected["ip"]
            try:
                password = await async_get_password(host)
            except PasswordNotReady:
                errors["base"] = "not_in_pairing_mode"
            except OSError as err:
                _LOGGER.debug("Password exchange failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                blid = self._selected.get("blid") or _blid_from_hostname(
                    self._selected.get("hostname", "")
                )
                if not blid:
                    errors["base"] = "no_blid"
                else:
                    await self.async_set_unique_id(blid)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                    return self.async_create_entry(
                        title=self._selected.get("robotname") or f"Roomba {blid[-6:]}",
                        data={
                            CONF_HOST: host,
                            "host": host,
                            CONF_BLID: blid,
                            CONF_ROBOT_PASSWORD: password,
                            CONF_CONTINUOUS: True,
                            CONF_ENABLE_CLOUD: False,
                            **self._cloud,
                        },
                    )

        return self.async_show_form(
            step_id="password",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"host": self._selected.get("ip", "")},
        )

    # ------------------------------------------------------------ discovery

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """A robot appeared on the network with a recognisable hostname."""
        return await self._async_handle_discovery(
            host=discovery_info.ip,
            hostname=discovery_info.hostname or "",
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """Robots advertise plain _mqtt._tcp; the name carries the BLID."""
        return await self._async_handle_discovery(
            host=discovery_info.host,
            hostname=discovery_info.hostname or discovery_info.name or "",
        )

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> ConfigFlowResult:
        """Queued by the cloud step for the account's other robots."""
        blid = discovery_info["blid"]
        await self.async_set_unique_id(blid)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info["host"]}
        )
        self._selected = {
            "ip": discovery_info["host"],
            "blid": blid,
            "robotname": discovery_info.get("name"),
        }
        self.context["title_placeholders"] = {
            "name": discovery_info.get("name") or f"Roomba {blid[-6:]}"
        }
        return await self.async_step_discovery_confirm()

    async def _async_handle_discovery(
        self, host: str, hostname: str
    ) -> ConfigFlowResult:
        blid = _blid_from_hostname(hostname)
        if not blid:
            return self.async_abort(reason="no_blid")

        await self.async_set_unique_id(blid)
        # Also keeps the stored IP current when the robot's lease changes.
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self._selected = {"ip": host, "blid": blid, "hostname": hostname}
        self.context["title_placeholders"] = {"name": f"Roomba {blid[-6:]}"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Offer to finish setup for a robot we already located."""
        blid = self._selected.get("blid", "")

        # If another entry already has cloud credentials, reuse them and skip
        # every prompt -- this is the whole point of the discovery path.
        if creds := self._existing_cloud_credentials():
            return await self.async_step_reuse_account(creds)

        return self.async_show_menu(
            step_id="discovery_confirm",
            menu_options=["cloud", "password"],
            description_placeholders={
                "name": self._selected.get("robotname") or f"Roomba {blid[-6:]}",
                "host": self._selected.get("ip", ""),
            },
        )

    async def async_step_reuse_account(
        self, creds: dict[str, Any], user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Finish setup using credentials already stored by another entry."""
        auth = IRobotAuth(
            session=async_get_clientsession(self.hass),
            username=creds[CONF_CLOUD_USERNAME],
            password=creds[CONF_CLOUD_PASSWORD],
            country_code=creds.get(CONF_COUNTRY, "US"),
            app_id=creds.get(CONF_APP_ID) or DEFAULT_APP_ID,
        )
        try:
            await auth.async_login()
        except IRobotAuthError:
            # Fall back to asking, rather than dead-ending.
            return self.async_show_menu(
                step_id="discovery_confirm", menu_options=["cloud", "password"]
            )

        blid = self._selected["blid"]
        info = auth.robots.get(blid, {})
        password = info.get("password") or info.get("robot_password")
        if not password:
            return await self.async_step_password()

        return self.async_create_entry(
            title=info.get("name") or f"Roomba {blid[-6:]}",
            data={
                CONF_HOST: self._selected["ip"],
                "host": self._selected["ip"],
                CONF_BLID: blid,
                CONF_ROBOT_PASSWORD: password,
                CONF_CONTINUOUS: True,
                CONF_ENABLE_CLOUD: True,
                CONF_CLOUD_USERNAME: creds[CONF_CLOUD_USERNAME],
                CONF_CLOUD_PASSWORD: creds[CONF_CLOUD_PASSWORD],
                CONF_COUNTRY: creds.get(CONF_COUNTRY, "US"),
                CONF_APP_ID: creds.get(CONF_APP_ID) or DEFAULT_APP_ID,
            },
        )

    def _existing_cloud_credentials(self) -> dict[str, Any] | None:
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            data = {**entry.data, **entry.options}
            if data.get(CONF_ENABLE_CLOUD) and data.get(CONF_CLOUD_USERNAME):
                return data
        return None

    def _queue_other_robots(self, added_blid: str) -> None:
        """Surface the account's remaining robots as discovered devices."""
        configured = {
            entry.unique_id for entry in self.hass.config_entries.async_entries(DOMAIN)
        }
        configured.add(added_blid)

        for blid, info in self._cloud_robots.items():
            if blid in configured:
                continue
            host = self._ip_for(blid)
            if not host:
                continue  # can't reach it; user can add manually later
            self.hass.async_create_task(
                self.hass.config_entries.flow.async_init(
                    DOMAIN,
                    context={"source": SOURCE_INTEGRATION_DISCOVERY},
                    data={"blid": blid, "host": host, "name": info.get("name")},
                )
            )

    # ------------------------------------------------------------ reconfigure

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change a robot's IP address without removing the entry."""
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data={
                    **entry.data,
                    CONF_HOST: user_input[CONF_HOST],
                    "host": user_input[CONF_HOST],
                },
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_HOST, default=entry.data.get(CONF_HOST, "")
                    ): str
                }
            ),
        )

    # --------------------------------------------------------------- reauth

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        assert entry is not None

        if user_input is not None:
            auth = IRobotAuth(
                session=async_get_clientsession(self.hass),
                username=entry.data[CONF_CLOUD_USERNAME],
                password=user_input[CONF_PASSWORD],
                country_code=entry.data.get(CONF_COUNTRY, "US"),
                app_id=entry.data.get(CONF_APP_ID) or DEFAULT_APP_ID,
            )
            try:
                await auth.async_login()
            except InvalidCredentials:
                errors["base"] = "invalid_auth"
            except IRobotAuthError:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={**entry.data, CONF_CLOUD_PASSWORD: user_input[CONF_PASSWORD]},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={
                "username": entry.data.get(CONF_CLOUD_USERNAME, "")
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:  # noqa: ANN001
        return IRobotOptionsFlow()


class IRobotOptionsFlow(OptionsFlow):
    """Add or change cloud credentials after the fact.

    Note: no __init__. Home Assistant supplies `self.config_entry` itself, and
    assigning to it raises on modern cores because it is a read-only property.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            if user_input.get(CONF_ENABLE_CLOUD) and user_input.get(CONF_USERNAME):
                auth = IRobotAuth(
                    session=async_get_clientsession(self.hass),
                    username=user_input[CONF_USERNAME],
                    password=user_input[CONF_PASSWORD],
                    country_code=user_input.get(CONF_COUNTRY, "US"),
                    app_id=user_input.get(CONF_APP_ID) or DEFAULT_APP_ID,
                )
                try:
                    await auth.async_login()
                except InvalidCredentials:
                    errors["base"] = "invalid_auth"
                except IRobotAuthError:
                    errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_ENABLE_CLOUD: user_input.get(CONF_ENABLE_CLOUD, False),
                        CONF_CLOUD_USERNAME: user_input.get(CONF_USERNAME) or "",
                        CONF_CLOUD_PASSWORD: user_input.get(CONF_PASSWORD) or "",
                        CONF_COUNTRY: user_input.get(CONF_COUNTRY, "US"),
                        CONF_APP_ID: user_input.get(CONF_APP_ID) or DEFAULT_APP_ID,
                    },
                )

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_ENABLE_CLOUD,
                        default=current.get(CONF_ENABLE_CLOUD, False),
                    ): bool,
                    vol.Optional(
                        CONF_USERNAME, default=current.get(CONF_CLOUD_USERNAME, "")
                    ): str,
                    vol.Optional(
                        CONF_PASSWORD, default=current.get(CONF_CLOUD_PASSWORD, "")
                    ): str,
                    vol.Optional(
                        CONF_COUNTRY, default=current.get(CONF_COUNTRY, "US")
                    ): str,
                    vol.Optional(
                        CONF_APP_ID, default=current.get(CONF_APP_ID, DEFAULT_APP_ID)
                    ): str,
                }
            ),
            errors=errors,
        )


def _blid_from_hostname(hostname: str) -> str | None:
    """Pull the BLID out of "Roomba-<blid>" / "irobot-<blid>._mqtt._tcp.local."."""
    if not hostname:
        return None
    name = hostname.split(".", 1)[0]
    if "-" not in name:
        return None
    blid = name.split("-", 1)[1].strip()
    return blid or None
