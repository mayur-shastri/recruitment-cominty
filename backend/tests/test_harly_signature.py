"""Harly webhook signature verification vectors."""

from __future__ import annotations

import hashlib
import hmac

from app.integrations.harly.verification import verify_harly_signature

SECRET = "whsec_test"
BODY = b'{"id":"evt_1","type":"application.created","data":{}}'
NOW = 1_800_000_000.0


def _sign(secret: str, ts: int, body: bytes) -> str:
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def test_valid_signature() -> None:
    assert verify_harly_signature(secret=SECRET, body=BODY, signature=_sign(SECRET, int(NOW), BODY), now=NOW)


def test_wrong_secret_rejected() -> None:
    sig = _sign("whsec_other", int(NOW), BODY)
    assert not verify_harly_signature(secret=SECRET, body=BODY, signature=sig, now=NOW)


def test_tampered_body_rejected() -> None:
    sig = _sign(SECRET, int(NOW), BODY)
    assert not verify_harly_signature(secret=SECRET, body=BODY + b" ", signature=sig, now=NOW)


def test_stale_timestamp_rejected() -> None:
    sig = _sign(SECRET, int(NOW) - 301, BODY)
    assert not verify_harly_signature(secret=SECRET, body=BODY, signature=sig, now=NOW)


def test_malformed_and_missing_rejected() -> None:
    assert not verify_harly_signature(secret=SECRET, body=BODY, signature=None, now=NOW)
    assert not verify_harly_signature(secret=SECRET, body=BODY, signature="bogus", now=NOW)
    assert not verify_harly_signature(secret=SECRET, body=BODY, signature="t=abc,v1=00", now=NOW)
    assert not verify_harly_signature(secret="", body=BODY, signature=_sign(SECRET, int(NOW), BODY), now=NOW)
