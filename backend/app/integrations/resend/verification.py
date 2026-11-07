"""Resend webhook verification (Svix HMAC-SHA256 scheme, manual stdlib port).

Signed content is `{svix-id}.{svix-timestamp}.{raw body}`; the key is the
base64 portion of the `whsec_...` signing secret. See
https://docs.svix.com/receiving/verifying-payloads/how-manual
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

DEFAULT_TOLERANCE_S = 5 * 60


def verify_resend_signature(
    *,
    signing_secret: str,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    body: bytes,
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now: float | None = None,
) -> bool:
    """Verify an inbound Resend webhook. `now` exists for deterministic tests."""
    if not svix_id or not svix_timestamp or not svix_signature:
        return False
    try:
        request_ts = int(svix_timestamp)
    except (TypeError, ValueError):
        return False
    current = time.time() if now is None else now
    if abs(current - request_ts) > tolerance_s:
        return False
    try:
        key = base64.b64decode(signing_secret.split("_", 1)[1])
    except (IndexError, ValueError, base64.binascii.Error):
        return False
    expected = hmac.new(
        key, f"{svix_id}.{svix_timestamp}.".encode() + body, hashlib.sha256
    ).digest()
    for entry in svix_signature.split():
        scheme, _, value = entry.partition(",")
        if scheme != "v1":
            continue
        try:
            candidate = base64.b64decode(value)
        except (ValueError, base64.binascii.Error):
            continue
        if hmac.compare_digest(expected, candidate):
            return True
    return False
