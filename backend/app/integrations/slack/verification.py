"""Slack request-signature verification (HMAC-SHA256, `v0` scheme)."""

from __future__ import annotations

import hashlib
import hmac
import time

_SIGNATURE_VERSION = "v0"
DEFAULT_TOLERANCE_S = 5 * 60


def verify_slack_signature(
    *,
    signing_secret: str,
    timestamp: str,
    body: bytes,
    signature: str,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: float | None = None,
) -> bool:
    """Verify an inbound Slack request. `now` exists for deterministic tests."""
    try:
        request_ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - request_ts) > tolerance_s:
        return False
    if not signature.startswith(f"{_SIGNATURE_VERSION}="):
        return False
    expected = _SIGNATURE_VERSION + "=" + hmac.new(
        signing_secret.encode(), f"{_SIGNATURE_VERSION}:{timestamp}:".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)
