"""Minimal Resend client: send candidate emails, fetch inbound bodies.

Errors are user-safe (no API keys). No SDK dependency — plain httpx like
the Harly reads.
"""

from __future__ import annotations

from typing import Any

import httpx

RESEND_BASE_URL = "https://api.resend.com"


class ResendError(Exception):
    """User-safe Resend API failure."""


class ResendClient:
    """Short-lived Resend client: one instance per send/receive run."""

    def __init__(
        self,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not api_key:
            raise ResendError("resend api is not configured")
        self._api_key = api_key
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=RESEND_BASE_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
            transport=self._transport,
        )

    async def send_email(
        self, *, from_email: str, to_email: str, subject: str, text: str, reply_to: str
    ) -> str:
        """Send a plain-text email. Returns the Resend email id."""
        async with self._client() as client:
            try:
                resp = await client.post(
                    "/emails",
                    json={
                        "from": from_email,
                        "to": to_email,
                        "subject": subject,
                        "text": text,
                        "reply_to": reply_to,
                    },
                )
            except httpx.HTTPError as exc:
                raise ResendError(f"resend request failed: {type(exc).__name__}") from exc
        if resp.status_code != 200:
            raise ResendError(f"resend send failed (status {resp.status_code})")
        email_id = resp.json().get("id")
        if not email_id:
            raise ResendError("resend send returned no email id")
        return email_id

    async def get_received_email(self, email_id: str) -> dict[str, Any]:
        """Fetch a received email's content (webhooks carry metadata only)."""
        async with self._client() as client:
            try:
                resp = await client.get(f"/emails/receiving/{email_id}")
            except httpx.HTTPError as exc:
                raise ResendError(f"resend request failed: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise ResendError(f"resend email not found: {email_id}")
        if resp.status_code != 200:
            raise ResendError(f"resend fetch failed (status {resp.status_code})")
        return resp.json()
