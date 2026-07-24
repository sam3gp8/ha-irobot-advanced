"""Automated iRobot cloud authentication.

The Gigya API key is *not* baked into the app -- but it doesn't need to be
captured either. The unauthenticated discovery endpoint hands it out, together
with the Gigya data centre, the API Gateway host and the AWS region:

    GET https://disc-prod.iot.irobotapi.com/v1/discover/endpoints?country_code=US

    {
      "deployments": { "v011": { "httpBase": ..., "httpBaseAuth": ...,
                                 "awsRegion": "us-east-1", ... } },
      "gigya": { "api_key": "3_...", "datacenter_domain": "us1.gigya.com" },
      ...
    }

``httpBaseAuth``, ``deployments``, ``datacenter_domain``, ``awsRegion`` and
``api_key`` all appear verbatim in the 7.18.0 native core, so this schema is
current for this app version.

From there the flow is:

    1. POST https://accounts.{datacenter}/accounts.login
       -> UID, UIDSignature, signatureTimestamp, sessionInfo
    2. POST {httpBase}/v2/login  with the Gigya triple
       -> temporary AWS credentials + the robot list (including each robot's
          local MQTT password)
    3. Sign every subsequent API Gateway call with SigV4.

Credentials from step 2 are short-lived, so this module tracks expiry and
re-runs the login transparently. Nothing needs re-capturing by hand.
"""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import aiohttp

from .const import DEFAULT_APP_ID, DISCOVERY_URL, DISCOVERY_URL_CN
from .sigv4 import SigV4Credentials

_LOGGER = logging.getLogger(__name__)

DEFAULT_CREDENTIAL_TTL = timedelta(minutes=55)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


class IRobotAuthError(Exception):
    """Login failed."""


class InvalidCredentials(IRobotAuthError):
    """Wrong email or password."""


class IRobotAuth:
    """Owns the credential lifecycle for one iRobot account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        country_code: str = "US",
        env: str = "prod",
        china: bool = False,
        app_id: str = DEFAULT_APP_ID,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._country = country_code
        self._env = env
        self._china = china
        self._app_id = app_id

        self.http_base: str | None = None
        self.api_host: str | None = None
        self.api_stage: str = ""
        self.region: str = "us-east-1"
        self.gigya_api_key: str | None = None
        self.gigya_datacenter: str | None = None

        self.credentials: SigV4Credentials | None = None
        self.robots: dict[str, Any] = {}
        self.user_info: dict[str, Any] = {}

    # ------------------------------------------------------------- discovery

    async def async_discover(self) -> dict[str, Any]:
        """Unauthenticated bootstrap. This is where the Gigya key comes from."""
        template = DISCOVERY_URL_CN if self._china else DISCOVERY_URL
        url = template.format(env=self._env, cc=self._country)

        async with self._session.get(url, timeout=REQUEST_TIMEOUT) as resp:
            resp.raise_for_status()
            data = await resp.json(content_type=None)

        deployments = data.get("deployments") or {}
        if not deployments:
            raise IRobotAuthError("Discovery returned no deployments")

        # The app picks the deployment named by "current_deployment" when
        # present, otherwise the first one.
        name = data.get("current_deployment") or next(iter(deployments))
        deployment = deployments.get(name) or next(iter(deployments.values()))

        self.http_base = (deployment.get("httpBase") or "").rstrip("/")
        self.region = deployment.get("awsRegion") or self.region

        auth_base = deployment.get("httpBaseAuth") or ""
        if auth_base:
            parsed = urlparse(auth_base)
            self.api_host = parsed.netloc
            # httpBaseAuth usually carries the API Gateway stage in its path
            # (e.g. ".../dev"). Keep it -- hardcoding "/dev" breaks other
            # deployments.
            self.api_stage = parsed.path.rstrip("/")

        gigya = data.get("gigya") or {}
        self.gigya_api_key = gigya.get("api_key")
        self.gigya_datacenter = gigya.get("datacenter_domain")

        if not self.gigya_api_key or not self.gigya_datacenter:
            raise IRobotAuthError(
                "Discovery response did not include Gigya configuration"
            )

        _LOGGER.debug(
            "Discovery: deployment=%s region=%s api_host=%s stage=%s gigya=%s",
            name,
            self.region,
            self.api_host,
            self.api_stage or "(none)",
            self.gigya_datacenter,
        )
        return data

    # ------------------------------------------------------------ gigya step

    async def _async_gigya_login(self) -> dict[str, Any]:
        url = f"https://accounts.{self.gigya_datacenter}/accounts.login"
        form = {
            "apiKey": self.gigya_api_key,
            "targetenv": "mobile",
            "targetEnv": "mobile",
            "loginID": self._username,
            "password": self._password,
            "format": "json",
        }

        async with self._session.post(
            url, data=form, timeout=REQUEST_TIMEOUT
        ) as resp:
            payload = await resp.json(content_type=None)

        error_code = payload.get("errorCode", 0)
        if error_code:
            message = payload.get("errorDetails") or payload.get("errorMessage") or ""
            # 403042 = invalid loginID or password; 403041 = account disabled.
            if error_code in (403042, 403041, 400006):
                raise InvalidCredentials(f"Gigya rejected the login: {message}")
            raise IRobotAuthError(f"Gigya error {error_code}: {message}")

        for field in ("UID", "UIDSignature", "signatureTimestamp"):
            if field not in payload:
                raise IRobotAuthError(f"Gigya response missing {field}")

        return payload

    # ----------------------------------------------------------- irobot step

    async def _async_irobot_login(self, gigya: dict[str, Any]) -> dict[str, Any]:
        body = {
            "app_id": self._app_id,
            "assume_robot_ownership": "0",
            "gigya": {
                "signature": gigya["UIDSignature"],
                "timestamp": gigya["signatureTimestamp"],
                "uid": gigya["UID"],
            },
        }

        async with self._session.post(
            f"{self.http_base}/v2/login", json=body, timeout=REQUEST_TIMEOUT
        ) as resp:
            if resp.status in (401, 403):
                raise IRobotAuthError(
                    f"iRobot rejected the Gigya assertion ({resp.status}). "
                    "The app_id may have rotated."
                )
            resp.raise_for_status()
            return await resp.json(content_type=None)

    # ----------------------------------------------------------------- login

    async def async_login(self) -> None:
        """Run the full flow and populate credentials and the robot list."""
        if self.gigya_api_key is None:
            await self.async_discover()

        gigya = await self._async_gigya_login()
        response = await self._async_irobot_login(gigya)

        creds = response.get("credentials") or {}
        try:
            self.credentials = SigV4Credentials(
                access_key=creds["AccessKeyId"],
                secret_key=creds["SecretKey"],
                session_token=creds["SessionToken"],
                expires_at=_parse_expiry(creds.get("Expiration")),
            )
        except KeyError as err:
            raise IRobotAuthError(f"Login response missing {err}") from err

        self.robots = _normalise_robots(response.get("robots"))
        self.user_info = {
            k: v for k, v in response.items() if k not in ("credentials", "robots")
        }

        _LOGGER.debug(
            "Logged in: %d robot(s), credentials valid until %s",
            len(self.robots),
            self.credentials.expires_at,
        )

    async def async_valid_credentials(self) -> SigV4Credentials:
        """Return live credentials, re-logging in if they have aged out."""
        if self.credentials is None or self.credentials.is_expired():
            await self.async_login()
        assert self.credentials is not None
        return self.credentials

    # --------------------------------------------------------------- helpers

    def api_url(self, path: str) -> str:
        """Build a full API Gateway URL, including the deployment stage."""
        if not self.api_host:
            raise IRobotAuthError("Discovery has not run yet")
        return f"https://{self.api_host}{self.api_stage}{path}"

    @staticmethod
    def nonce() -> str:
        return f"{int(time.time())}_{random.randint(0, 2147483647)}"


def _parse_expiry(value: Any) -> datetime:
    """STS hands back an ISO timestamp; fall back to a conservative TTL."""
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    return datetime.now(timezone.utc) + DEFAULT_CREDENTIAL_TTL


def _normalise_robots(raw: Any) -> dict[str, Any]:
    """``robots`` comes back keyed by BLID; tolerate a list as well."""
    if isinstance(raw, dict):
        return {str(blid): dict(info or {}) for blid, info in raw.items()}
    if isinstance(raw, list):
        out: dict[str, Any] = {}
        for item in raw:
            if not isinstance(item, dict):
                continue
            blid = item.get("blid") or item.get("robotid") or item.get("hostname")
            if blid:
                out[str(blid)] = item
        return out
    return {}
