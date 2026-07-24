"""Live view over AWS Kinesis Video Streams WebRTC.

The robot is a KVS **master** on a per-device signalling channel; Home
Assistant connects as a **viewer**. Confirmed in the app by
``AWSKinesisVideoSignalingClient`` / ``AWSKinesisVideoArchivedMediaClient``,
the shadow field ``streamingVideoStatus`` and the operating modes
``ACTIVE_STREAMING`` / ``ACTIVE_NON_STREAMING``.

Viewer flow (all SigV4-signed against the account credentials from
:mod:`.auth`):

1. Ask the robot to bring the camera up (shadow write).
2. ``DescribeSignalingChannel`` -> the channel ARN for this robot.
3. ``GetSignalingChannelEndpoint`` (role VIEWER) -> WSS + HTTPS endpoints.
4. ``GetIceServerConfig`` on the HTTPS endpoint -> STUN/TURN servers.
5. Hand the WSS endpoint (presigned) and ICE servers to go2rtc, which
   performs the SDP/ICE exchange and exposes an H.264 stream Home Assistant
   can show as a camera.

The KVS control-plane calls are the standard public AWS API, so they are
implemented directly here rather than reverse engineered. Everything is gated
on cloud credentials being available; without them no live-view entity is
created.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import aiohttp

from .sigv4 import SigV4Credentials, presign_url, sign_request

if TYPE_CHECKING:
    from .auth import IRobotAuth
    from .local_client import RoombaLocalClient

_LOGGER = logging.getLogger(__name__)

# Robot-side shadow keys that gate streaming.
FIELD_STREAMING_STATUS = "streamingVideoStatus"

KVS_SERVICE = "kinesisvideo"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=20)
VIEWER_CLIENT_ID = "home-assistant-viewer"


@dataclass(slots=True)
class SignalingEndpoints:
    """Result of GetSignalingChannelEndpoint for role=VIEWER."""

    wss: str
    https: str
    channel_arn: str
    region: str


@dataclass(slots=True)
class IceServers:
    """STUN/TURN configuration for the WebRTC connection."""

    servers: list[dict[str, Any]] = field(default_factory=list)


class LiveViewUnavailableError(Exception):
    """The robot or the account cannot provide a stream right now."""


class LiveViewSession:
    """Viewer-side handle for one robot's KVS signalling channel."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        blid: str,
        auth: IRobotAuth | None = None,
        channel_name: str | None = None,
    ) -> None:
        self._session = session
        self._blid = blid
        self._auth = auth
        # The channel is conventionally named after the robot. The robot may
        # also report an explicit ARN in its shadow; that takes precedence.
        self._channel_name = channel_name or blid
        self._channel_arn: str | None = None
        self._endpoints: SignalingEndpoints | None = None

    @property
    def ready(self) -> bool:
        """True once cloud auth is available to sign KVS calls."""
        return self._auth is not None

    # ------------------------------------------------------- robot side

    async def async_request_stream(self, local_client: RoombaLocalClient) -> None:
        """Ask the robot to bring the camera up, via the delta channel."""
        local_client.set_preference(**{FIELD_STREAMING_STATUS: {"enabled": True}})

    async def async_stop_stream(self, local_client: RoombaLocalClient) -> None:
        local_client.set_preference(**{FIELD_STREAMING_STATUS: {"enabled": False}})

    def is_streaming(self, reported: dict[str, Any]) -> bool:
        status = reported.get(FIELD_STREAMING_STATUS)
        if isinstance(status, dict):
            return bool(status.get("enabled") or status.get("active"))
        return str(status).upper() in ("ACTIVE_STREAMING", "ON", "TRUE")

    def channel_arn_from_shadow(self, reported: dict[str, Any]) -> str | None:
        """Some robots publish their signalling channel ARN directly."""
        for key in ("signalingChannelArn", "kvsChannelArn", "channelArn"):
            if value := reported.get(key):
                self._channel_arn = value
                return value
        return None

    # ------------------------------------------------------- control plane

    async def _kvs_post(
        self,
        host: str,
        path: str,
        body: dict[str, Any],
        credentials: SigV4Credentials,
        region: str,
    ) -> dict[str, Any]:
        """One SigV4-signed POST to a KVS control-plane endpoint."""
        url = f"https://{host}{path}"
        raw = json.dumps(body).encode()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        headers.update(
            sign_request(
                "POST",
                url,
                credentials,
                region=region,
                service=KVS_SERVICE,
                body=raw,
                extra_headers={"content-type": "application/json"},
            )
        )
        async with self._session.post(
            url, headers=headers, data=raw, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status >= 400:
                text = await resp.text()
                raise LiveViewUnavailableError(
                    f"KVS {path} failed ({resp.status}): {text[:200]}"
                )
            return await resp.json(content_type=None)

    async def async_describe_channel(self) -> SignalingEndpoints:
        """Resolve the channel ARN and its VIEWER endpoints."""
        if self._auth is None:
            raise LiveViewUnavailableError("Cloud access is not enabled")

        credentials = await self._auth.async_valid_credentials()
        region = self._auth.region
        control_host = f"kinesisvideo.{region}.amazonaws.com"

        # 1. ARN -- from the shadow if we have it, else DescribeSignalingChannel.
        arn = self._channel_arn
        if not arn:
            described = await self._kvs_post(
                control_host,
                "/describeSignalingChannel",
                {"ChannelName": self._channel_name},
                credentials,
                region,
            )
            arn = (described.get("ChannelInfo") or {}).get("ChannelARN")
            if not arn:
                raise LiveViewUnavailableError(
                    f"No signalling channel named {self._channel_name!r}"
                )
            self._channel_arn = arn

        # 2. VIEWER endpoints (WSS for signalling, HTTPS for ICE config).
        endpoint_resp = await self._kvs_post(
            control_host,
            "/getSignalingChannelEndpoint",
            {
                "ChannelARN": arn,
                "SingleMasterChannelEndpointConfiguration": {
                    "Protocols": ["WSS", "HTTPS"],
                    "Role": "VIEWER",
                },
            },
            credentials,
            region,
        )

        by_protocol = {
            item.get("Protocol"): item.get("ResourceEndpoint")
            for item in endpoint_resp.get("ResourceEndpointList", [])
        }
        wss = by_protocol.get("WSS")
        https = by_protocol.get("HTTPS")
        if not wss or not https:
            raise LiveViewUnavailableError("KVS did not return WSS/HTTPS endpoints")

        self._endpoints = SignalingEndpoints(
            wss=wss, https=https, channel_arn=arn, region=region
        )
        return self._endpoints

    async def async_get_ice_servers(self) -> IceServers:
        """Collect STUN + TURN servers for the connection."""
        if self._endpoints is None:
            await self.async_describe_channel()
        assert self._endpoints is not None
        assert self._auth is not None

        credentials = await self._auth.async_valid_credentials()
        region = self._endpoints.region

        # STUN is always the regional KVS endpoint.
        servers: list[dict[str, Any]] = [
            {"urls": f"stun:stun.kinesisvideo.{region}.amazonaws.com:443"}
        ]

        # TURN via GetIceServerConfig on the HTTPS data-plane endpoint.
        host = self._endpoints.https.replace("https://", "").rstrip("/")
        try:
            ice = await self._kvs_post(
                host,
                "/v1/get-ice-server-config",
                {
                    "ChannelARN": self._endpoints.channel_arn,
                    "ClientId": VIEWER_CLIENT_ID,
                },
                credentials,
                region,
            )
        except LiveViewUnavailableError as err:
            # STUN alone is often enough on a LAN; log and continue.
            _LOGGER.debug("GetIceServerConfig failed, STUN only: %s", err)
            return IceServers(servers=servers)

        for entry in ice.get("IceServerList", []):
            uris = entry.get("Uris") or []
            server: dict[str, Any] = {"urls": uris}
            if entry.get("Username"):
                server["username"] = entry["Username"]
            if entry.get("Password"):
                server["credential"] = entry["Password"]
            servers.append(server)

        return IceServers(servers=servers)

    async def async_signed_wss_url(self) -> str:
        """Presigned WSS URL a viewer uses to open the signalling socket."""
        if self._endpoints is None:
            await self.async_describe_channel()
        assert self._endpoints is not None
        assert self._auth is not None

        credentials = await self._auth.async_valid_credentials()
        return presign_url(
            self._endpoints.wss,
            credentials,
            region=self._endpoints.region,
            service=KVS_SERVICE,
            extra_query={
                "X-Amz-ChannelARN": self._endpoints.channel_arn,
                "X-Amz-ClientId": VIEWER_CLIENT_ID,
            },
        )

    # ------------------------------------------------------- go2rtc glue

    async def async_get_go2rtc_config(self) -> dict[str, Any] | None:
        """Return a go2rtc ``webrtc`` source config, or None if unavailable.

        go2rtc (bundled with Home Assistant) performs the SDP/ICE exchange, so
        the integration hands it the presigned WSS URL and ICE servers rather
        than implementing a WebRTC stack itself.
        """
        if not self.ready:
            _LOGGER.debug("Live view not configured for %s", self._blid)
            return None
        try:
            await self.async_describe_channel()
            wss = await self.async_signed_wss_url()
            ice = await self.async_get_ice_servers()
        except LiveViewUnavailableError as err:
            _LOGGER.debug("Live view unavailable for %s: %s", self._blid, err)
            return None

        assert self._endpoints is not None
        return {
            "url": wss,
            "channel_arn": self._endpoints.channel_arn,
            "client_id": VIEWER_CLIENT_ID,
            "region": self._endpoints.region,
            "ice_servers": ice.servers,
        }
