"""Slack signature verification: valid, forged, and replayed requests."""

from __future__ import annotations

import hashlib
import hmac

from app.integrations.slack.verification import verify_slack_signature

SECRET = "test-signing-secret"
BODY = b'{"type":"event_callback","event_id":"ev1"}'
NOW = 1_700_000_000.0


def _sign(secret: str, timestamp: str, body: bytes) -> str:
    return "v0=" + hmac.new(secret.encode(), f"v0:{timestamp}:".encode() + body, hashlib.sha256).hexdigest()


def test_valid_signature() -> None:
    ts = str(int(NOW))
    assert verify_slack_signature(signing_secret=SECRET, timestamp=ts, body=BODY, signature=_sign(SECRET, ts, BODY), now=NOW)


def test_wrong_secret_rejected() -> None:
    ts = str(int(NOW))
    assert not verify_slack_signature(
        signing_secret=SECRET, timestamp=ts, body=BODY, signature=_sign("other-secret", ts, BODY), now=NOW
    )


def test_tampered_body_rejected() -> None:
    ts = str(int(NOW))
    assert not verify_slack_signature(
        signing_secret=SECRET, timestamp=ts, body=BODY + b"!", signature=_sign(SECRET, ts, BODY), now=NOW
    )


def test_expired_timestamp_rejected() -> None:
    ts = str(int(NOW) - 301)
    assert not verify_slack_signature(
        signing_secret=SECRET, timestamp=ts, body=BODY, signature=_sign(SECRET, ts, BODY), now=NOW
    )


def test_malformed_timestamp_rejected() -> None:
    assert not verify_slack_signature(signing_secret=SECRET, timestamp="not-a-ts", body=BODY, signature="v0=abc", now=NOW)


def test_malformed_signature_rejected() -> None:
    ts = str(int(NOW))
    assert not verify_slack_signature(signing_secret=SECRET, timestamp=ts, body=BODY, signature="abc123", now=NOW)
