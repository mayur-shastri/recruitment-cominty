"""Svix verification vectors (signature cross-checked via openssl CLI)."""

from __future__ import annotations

from app.integrations.resend.verification import verify_resend_signature

SECRET = "whsec_MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODk="
BODY = b'{"type":"email.received"}'
SIG = "v1,zR9J8fj/9T0CK+3EQkd9edRHhKXBpBsjTH8RAEYrEG8="
NOW = 1_700_000_010.0


def _verify(**overrides) -> bool:
    args: dict = {
        "signing_secret": SECRET,
        "svix_id": "msg_test123",
        "svix_timestamp": "1700000000",
        "svix_signature": SIG,
        "body": BODY,
        "now": NOW,
    }
    args.update(overrides)
    return verify_resend_signature(**args)


def test_valid_vector() -> None:
    assert _verify() is True


def test_multi_signature_list() -> None:
    assert _verify(svix_signature=f"v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= {SIG}") is True


def test_tampered_body_rejected() -> None:
    assert _verify(body=b'{"type":"email.sent"}') is False


def test_stale_timestamp_rejected() -> None:
    assert _verify(now=NOW + 10_000) is False


def test_missing_headers_rejected() -> None:
    assert _verify(svix_id=None) is False
    assert _verify(svix_signature="v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=") is False


def test_malformed_secret_rejected() -> None:
    assert _verify(signing_secret="not-a-secret") is False
