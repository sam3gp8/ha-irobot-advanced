"""Live view over AWS Kinesis Video Streams WebRTC.

This is the one feature that cannot work without cloud auth. The robot acts as
a KVS **master** on a signalling channel; the app connects as a **viewer**.
Confirmed in the APK by ``AWSKinesisVideoSignalingClient``,
``AWSKinesisVideoArchivedMediaClient``, the shadow field
``streamingVideoStatus`` and the operating modes ``ACTIVE_STREAMING`` /
``ACTIVE_NON_STREAMING``.

Flow:

1. Ask the robot to start streaming (shadow write, see ``async_request_stream``).
2. ``kinesisvideo:DescribeSignalingChannel`` -> channel ARN for this robot.
3. ``kinesisvideo:GetSignalingChannelEndpoint`` with role VIEWER -> WSS + HTTPS
   endpoints.
4. ``kinesisvideosignaling:GetIceServerConfig`` -> TURN credentials.
5. Open the WSS socket (SigV4-signed query string), send an SDP offer as a
   base64 ``SDP_OFFER`` message, collect ``SDP_ANSWER`` + ``ICE_CANDIDATE``.
6. Feed the resulting H.264 track to go2rtc, which Home Assistant already
   ships, and expose it as a normal camera.

Steps 2-4 need AWS credentials scoped to the iRobot account, which come from
the same login the rest of ``cloud_client`` needs. Until you have captured
that, ``async_get_stream_source`` returns ``None`` and the integration simply
does not create a live-view camera.

The pieces below are deliberately thin: they define the shape of the exchange
so the remaining work is wiring credentials, not re-deriving the protocol.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

# Robot-side shadow keys that gate streaming.
FIELD_STREAMING_STATUS = "streamingVideoStatus"
OPERATING_MODE_STREAM = "OperatingModeVideoStream"


@dataclass(slots=True)
class SignalingEndpoints:
    """Result of GetSignalingChannelEndpoint for role=VIEWER."""

    wss: str
    https: str
    channel_arn: str
    region: str


class LiveViewUnavailable(Exception):
    """Raised when the robot or the account cannot provide a stream."""


class LiveViewSession:
    """Viewer-side handle for one robot's KVS signalling channel."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        blid: str,
        credentials: dict[str, Any] | None = None,
        region: str = "us-east-1",
    ) -> None:
        self._session = session
        self._blid = blid
        self._credentials = credentials
        self._region = region
        self._endpoints: SignalingEndpoints | None = None

    @property
    def ready(self) -> bool:
        """True once AWS credentials have been supplied."""
        return bool(self._credentials)

    async def async_request_stream(self, local_client) -> None:  # noqa: ANN001
        """Ask the robot to bring the camera up.

        Written through the same delta channel as any other preference. The
        robot answers by flipping ``streamingVideoStatus`` in its shadow, and
        the app waits for that before opening the signalling socket.
        """
        local_client.set_preference(**{FIELD_STREAMING_STATUS: {"enabled": True}})

    async def async_stop_stream(self, local_client) -> None:  # noqa: ANN001
        local_client.set_preference(**{FIELD_STREAMING_STATUS: {"enabled": False}})

    def is_streaming(self, reported: dict[str, Any]) -> bool:
        status = reported.get(FIELD_STREAMING_STATUS)
        if isinstance(status, dict):
            return bool(status.get("enabled") or status.get("active"))
        return str(status).upper() in ("ACTIVE_STREAMING", "ON", "TRUE")

    async def async_describe_channel(self) -> SignalingEndpoints:
        """Resolve the signalling channel for this robot.

        Requires SigV4-signed calls to the ``kinesisvideo`` control plane with
        the account credentials from the iRobot login.
        """
        if not self._credentials:
            raise LiveViewUnavailable(
                "No AWS credentials. Capture an iRobot login with mitmproxy first "
                "-- see PROTOCOL.md section 2."
            )
        raise NotImplementedError(
            "Wire DescribeSignalingChannel / GetSignalingChannelEndpoint here once "
            "credentials are available."
        )

    async def async_get_stream_source(self) -> str | None:
        """Return a go2rtc-compatible source URL, or None if unavailable.

        The intended shape once credentials exist::

            webrtc:<wss-url>#format=kinesis#client_id=<viewer-id>

        go2rtc consumes that directly, so Home Assistant needs no extra
        WebRTC stack of its own.
        """
        if not self.ready:
            _LOGGER.debug("Live view not configured for %s", self._blid)
            return None
        try:
            endpoints = await self.async_describe_channel()
        except (LiveViewUnavailable, NotImplementedError) as err:
            _LOGGER.debug("Live view unavailable for %s: %s", self._blid, err)
            return None
        return f"webrtc:{endpoints.wss}#format=kinesis"
