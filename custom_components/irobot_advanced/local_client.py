"""Local LAN transport for iRobot devices.

Three pieces, all reverse engineered from the 7.18.0 app's native core
(see PROTOCOL.md sections 3 and 4):

* UDP discovery  -- broadcast ``irobotmcs`` to :5678
* password exchange -- ``f0 05 ef cc 3b 29 00`` over TLS to :8883
* MQTT session   -- client id == username == BLID, TLS 1.0 + SECLEVEL=1
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import socket
import ssl
import time
from collections.abc import Callable
from typing import Any

import paho.mqtt.client as mqtt

from .const import (
    DEFAULT_PORT,
    DISCOVERY_MAGIC,
    DISCOVERY_PORT,
    PASSWORD_HEADER_LEN,
    PASSWORD_REQUEST,
    TOPIC_CMD,
    TOPIC_DELTA,
    TOPIC_RRTP_REPORT,
    TOPIC_RRTP_REQUEST,
    TOPIC_TIMELINE_REPORT,
    TOPIC_TIMELINE_REQUEST,
)

_LOGGER = logging.getLogger(__name__)

DISCOVERY_TIMEOUT = 5.0
PASSWORD_TIMEOUT = 5.0


def _legacy_ssl_context() -> ssl.SSLContext:
    """Roomba firmware speaks old TLS with weak ciphers.

    Modern OpenSSL refuses by default, hence SECLEVEL=1 and the explicit
    TLSv1 floor. Certificate verification is off because the robot presents a
    self-signed cert -- the MQTT password is the actual authentication.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with contextlib.suppress(AttributeError, ValueError):  # old python
        ctx.minimum_version = ssl.TLSVersion.TLSv1
    try:
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
    except ssl.SSLError:  # pragma: no cover - distro without SECLEVEL
        ctx.set_ciphers("DEFAULT")
    return ctx


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, results: dict[str, dict[str, Any]]) -> None:
        self._results = results

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if data.strip() == DISCOVERY_MAGIC:
            return  # our own broadcast bouncing back
        try:
            payload = json.loads(data.decode("utf-8", "ignore"))
        except ValueError:
            return
        hostname = payload.get("hostname", "")
        # hostname is "Roomba-<blid>" or "iRobot-<blid>"
        blid = hostname.split("-", 1)[1] if "-" in hostname else payload.get("robotid")
        if not blid:
            return
        payload["blid"] = blid
        payload.setdefault("ip", addr[0])
        self._results[blid] = payload


async def async_discover(timeout: float = DISCOVERY_TIMEOUT) -> list[dict[str, Any]]:
    """Broadcast the discovery magic and collect every robot that answers."""
    loop = asyncio.get_running_loop()
    results: dict[str, dict[str, Any]] = {}

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", 0))
    sock.setblocking(False)

    transport, _ = await loop.create_datagram_endpoint(
        lambda: _DiscoveryProtocol(results), sock=sock
    )
    try:
        for _ in range(3):
            transport.sendto(DISCOVERY_MAGIC, ("255.255.255.255", DISCOVERY_PORT))
            await asyncio.sleep(timeout / 3)
    finally:
        transport.close()

    return list(results.values())


def _blocking_get_password(host: str, port: int) -> str:
    ctx = _legacy_ssl_context()
    with (
        socket.create_connection((host, port), timeout=PASSWORD_TIMEOUT) as raw,
        ctx.wrap_socket(raw, server_hostname=host) as tls,
    ):
        tls.settimeout(PASSWORD_TIMEOUT)
        tls.send(PASSWORD_REQUEST)
        buf = b""
        deadline = time.monotonic() + PASSWORD_TIMEOUT
        while time.monotonic() < deadline:
            try:
                chunk = tls.recv(1024)
            except TimeoutError:
                break
            if not chunk:
                break
            buf += chunk
            # Short reply == robot is not in "add user" mode.
            if len(buf) > PASSWORD_HEADER_LEN + 6:
                break

    if len(buf) <= PASSWORD_HEADER_LEN:
        raise PasswordNotReadyError(
            "Robot did not return a password. Hold HOME until it chimes, then retry."
        )
    return buf[PASSWORD_HEADER_LEN:].decode("utf-8", "ignore").strip("\x00").strip()


class PasswordNotReadyError(Exception):
    """Raised when the robot is not in password-exchange mode."""


async def async_get_password(host: str, port: int = DEFAULT_PORT) -> str:
    """Run the password exchange. Robot must be docked with HOME held."""
    return await asyncio.get_running_loop().run_in_executor(
        None, _blocking_get_password, host, port
    )


class RoombaLocalClient:
    """Persistent local MQTT session against a single robot."""

    def __init__(
        self,
        host: str,
        blid: str,
        password: str,
        port: int = DEFAULT_PORT,
        on_state: Callable[[dict[str, Any]], None] | None = None,
        on_position: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.blid = blid
        self._password = password
        self._on_state = on_state
        self._on_position = on_position

        self.state: dict[str, Any] = {}
        self.connected = False

        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = mqtt.Client(
            client_id=blid,
            clean_session=True,
            protocol=mqtt.MQTTv311,
        )
        self._client.username_pw_set(blid, password)
        self._client.tls_set_context(_legacy_ssl_context())
        self._client.tls_insecure_set(True)
        self._client.on_connect = self._handle_connect
        self._client.on_disconnect = self._handle_disconnect
        self._client.on_message = self._handle_message

    # ---------------------------------------------------------------- lifecycle

    async def async_connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        await self._loop.run_in_executor(
            None, lambda: self._client.connect(self.host, self.port, keepalive=60)
        )
        self._client.loop_start()

    async def async_disconnect(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()
        self.connected = False

    # ---------------------------------------------------------------- callbacks

    def _handle_connect(self, client, userdata, flags, rc) -> None:
        if rc != 0:
            _LOGGER.error("%s: local MQTT refused (rc=%s)", self.blid, rc)
            return
        self.connected = True
        client.subscribe("#", qos=0)
        _LOGGER.debug("%s: local MQTT connected", self.blid)

    def _handle_disconnect(self, client, userdata, rc) -> None:
        self.connected = False
        if rc != 0:
            _LOGGER.warning("%s: unexpected local disconnect (rc=%s)", self.blid, rc)

    def _handle_message(self, client, userdata, msg) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8", "ignore"))
        except ValueError:
            return

        if msg.topic.endswith("/mission/rrtp/report/update"):
            self._dispatch(self._on_position, payload)
            return

        # Everything else arrives as {"state": {"reported": {...}}}
        reported = payload.get("state", {}).get("reported")
        if not isinstance(reported, dict):
            return
        _deep_merge(self.state, reported)
        self._dispatch(self._on_state, dict(self.state))

    def _dispatch(self, cb: Callable | None, payload: Any) -> None:
        if cb is None or self._loop is None:
            return
        self._loop.call_soon_threadsafe(cb, payload)

    # ---------------------------------------------------------------- publishing

    def _publish(self, topic: str, payload: Any) -> None:
        body = payload if isinstance(payload, str) else json.dumps(payload)
        _LOGGER.debug("%s -> %s: %s", self.blid, topic, body)
        self._client.publish(topic, body, qos=0)

    def send_command(self, command: str, **extra: Any) -> None:
        """Fire a top-level command. Payload shape lifted verbatim from the app."""
        payload: dict[str, Any] = {
            "command": command,
            "time": int(time.time()),
            "initiator": "localApp",
        }
        payload.update(extra)
        self._publish(TOPIC_CMD, payload)

    def set_preference(self, **fields: Any) -> None:
        """Write robot settings: {"do":"set","args":[{...}]}."""
        self._publish(TOPIC_DELTA, {"state": fields})

    def clean_regions(
        self,
        pmap_id: str,
        regions: list[dict[str, str]],
        user_pmapv_id: str | None = None,
    ) -> None:
        """Start a room-targeted clean.

        ``regions`` is a list of ``{"region_id": "3", "type": "rid"}``.
        """
        args: dict[str, Any] = {
            "ordered": 1,
            "pmap_id": pmap_id,
            "regions": regions,
        }
        if user_pmapv_id:
            args["user_pmapv_id"] = user_pmapv_id
        self.send_command("start", **args)

    def request_position(self) -> None:
        """Ask for a one-shot pose, and subscribe to the live rrtp stream."""
        self._publish(TOPIC_CMD, {"do": "get", "args": ["pose"], "id": 2})
        self._publish(
            TOPIC_RRTP_REQUEST.format(blid=self.blid),
            {"time": int(time.time()), "initiator": "localApp"},
        )

    def request_timeline(self) -> None:
        self._publish(
            TOPIC_TIMELINE_REQUEST.format(blid=self.blid),
            {"time": int(time.time()), "initiator": "localApp"},
        )

    @property
    def rrtp_report_topic(self) -> str:
        return TOPIC_RRTP_REPORT.format(blid=self.blid)

    @property
    def timeline_report_topic(self) -> str:
        return TOPIC_TIMELINE_REPORT.format(blid=self.blid)


def _deep_merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Shadow deltas are partial -- merge rather than replace."""
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
