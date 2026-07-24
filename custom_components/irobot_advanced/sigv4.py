"""Minimal AWS Signature V4 signer.

The iRobot map/history API sits behind API Gateway and is authenticated with
SigV4 using the temporary STS credentials handed out by ``/v2/login`` -- not
with a bearer token. Rather than pull in botocore (heavy, and Home Assistant
discourages it) this implements just the GET/POST cases we need.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

ALGORITHM = "AWS4-HMAC-SHA256"
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


class SigV4Credentials:
    """Temporary STS credentials with an expiry."""

    __slots__ = ("access_key", "expires_at", "secret_key", "session_token")

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        session_token: str,
        expires_at: datetime | None = None,
    ) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.expires_at = expires_at

    def is_expired(self, skew_seconds: int = 300) -> bool:
        if self.expires_at is None:
            return False
        remaining = (self.expires_at - datetime.now(UTC)).total_seconds()
        return remaining <= skew_seconds


def _sign(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _signing_key(secret: str, datestamp: str, region: str, service: str) -> bytes:
    k_date = _sign(f"AWS4{secret}".encode(), datestamp)
    k_region = _sign(k_date, region)
    k_service = _sign(k_region, service)
    return _sign(k_service, "aws4_request")


def _canonical_query(query: str) -> str:
    """Sort and re-encode the query string as SigV4 requires."""
    if not query:
        return ""
    pairs: list[tuple[str, str]] = []
    for part in query.split("&"):
        if not part:
            continue
        key, _, value = part.partition("=")
        pairs.append((key, value))
    pairs.sort()
    return "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in pairs
    )


def sign_request(
    method: str,
    url: str,
    credentials: SigV4Credentials,
    region: str,
    service: str = "execute-api",
    body: bytes = b"",
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return the headers needed to authenticate ``method url``."""
    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = quote(parsed.path or "/", safe="/-_.~")
    canonical_qs = _canonical_query(parsed.query)

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")

    payload_hash = hashlib.sha256(body).hexdigest() if body else EMPTY_HASH

    headers = {"host": host, "x-amz-date": amz_date}
    if credentials.session_token:
        headers["x-amz-security-token"] = credentials.session_token
    if extra_headers:
        headers.update({k.lower(): v for k, v in extra_headers.items()})

    signed_headers = ";".join(sorted(headers))
    canonical_headers = "".join(
        f"{key}:{headers[key].strip()}\n" for key in sorted(headers)
    )

    canonical_request = "\n".join(
        [
            method.upper(),
            canonical_uri,
            canonical_qs,
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        [
            ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    signature = hmac.new(
        _signing_key(credentials.secret_key, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    authorization = (
        f"{ALGORITHM} Credential={credentials.access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    out = {"Authorization": authorization, "x-amz-date": amz_date}
    if credentials.session_token:
        out["x-amz-security-token"] = credentials.session_token
    if body:
        out["x-amz-content-sha256"] = payload_hash
    return out


def presign_url(
    url: str,
    credentials: SigV4Credentials,
    region: str,
    service: str = "kinesisvideo",
    expires: int = 299,
    extra_query: dict[str, str] | None = None,
) -> str:
    """Return ``url`` with SigV4 auth in the query string (presigned).

    Used for the KVS WebRTC signalling WebSocket, where credentials must ride
    in the URL rather than in headers because the browser/relay opening the
    socket cannot set AWS auth headers. ``extra_query`` carries protocol
    parameters like ``X-Amz-ChannelARN`` and ``X-Amz-ClientId``.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    canonical_uri = quote(parsed.path or "/", safe="/-_.~")

    now = datetime.now(UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    credential_scope = f"{datestamp}/{region}/{service}/aws4_request"

    query: dict[str, str] = {
        "X-Amz-Algorithm": ALGORITHM,
        "X-Amz-Credential": f"{credentials.access_key}/{credential_scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    if credentials.session_token:
        query["X-Amz-Security-Token"] = credentials.session_token
    if extra_query:
        query.update(extra_query)

    canonical_qs = "&".join(
        f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}"
        for k, v in sorted(query.items())
    )

    canonical_request = "\n".join(
        [
            "GET",
            canonical_uri,
            canonical_qs,
            f"host:{host}\n",
            "host",
            EMPTY_HASH,
        ]
    )
    string_to_sign = "\n".join(
        [
            ALGORITHM,
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    signature = hmac.new(
        _signing_key(credentials.secret_key, datestamp, region, service),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return f"{parsed.scheme}://{host}{canonical_uri}?{canonical_qs}&X-Amz-Signature={signature}"
