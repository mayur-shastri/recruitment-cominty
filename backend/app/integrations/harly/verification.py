"""Harly webhook signature verification (HMAC-SHA256, `t=<unix>,v1=<hex>` scheme).

Per https://docs.harly.dev/developers/webhooks.md: every delivery carries an
`x-harly-signature-256` header; the MAC covers `{t}.{rawBody}` keyed by the
endpoint secret, with a 5-minute replay window.
"""

from __future__ import annotations

import hashlib
import hmac
import time

DEFAULT_TOLERANCE_S = 5 * 60


def verify_harly_signature(
    *,
    secret: str,
    body: bytes,
    signature: str | None,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: float | None = None,
) -> bool:
    """Verify an inbound Harly webhook delivery. `now` exists for deterministic tests."""
    if not secret or not signature:
        return False
    parts: dict[str, str] = {}
    for chunk in signature.split(","):
        key, sep, value = chunk.partition("=")
        if sep:
            parts[key.strip()] = value.strip()
    try:
        request_ts = int(parts["t"])
    except (KeyError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - request_ts) > tolerance_s:
        return False
    v1 = parts.get("v1")
    if not v1:
        return False
    expected = hmac.new(secret.encode(), f"{request_ts}.".encode() + body, hashlib.sha256).hexdigest()
    if len(expected) != len(v1):
        return False
    return hmac.compare_digest(expected, v1)
