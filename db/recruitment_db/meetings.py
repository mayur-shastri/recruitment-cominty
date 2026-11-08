"""Fake video-meeting links for booked interviews (demo only).

Links look like Meet rooms (``https://meet.acmetech.com/abc-defg-hij``) so
candidate emails and the calendar UI can show a joinable link. Nothing
resolves them — no meeting backend exists.
"""

from __future__ import annotations

import secrets
import string

MEET_BASE_URL = "https://meet.acmetech.com"
_ROOM_ALPHA = string.ascii_lowercase


def generate_meeting_url() -> str:
    """Fresh random room URL (3-4-3 letters, Meet-style)."""
    room = "-".join(
        "".join(secrets.choice(_ROOM_ALPHA) for _ in range(n)) for n in (3, 4, 3)
    )
    return f"{MEET_BASE_URL}/{room}"
