"""Convert agent Markdown to Slack mrkdwn before sending.

Agents write standard Markdown (``**bold**``, ``[text](url)``, ``#`` headings)
but Slack renders its own mrkdwn dialect, so raw Markdown shows up literally
(visible ``**`` pairs, dead ``[text](url)`` links). This normalizes the common
constructs; code spans/blocks pass through untouched since Slack supports them.
"""

from __future__ import annotations

import re

_PLACEHOLDER = "\ue000CODE%d\ue001"  # Private-use chars: never collide with prose.

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_BOLD_STAR_RE = re.compile(r"\*\*(.+?)\*\*")
_BOLD_UNDER_RE = re.compile(r"__(.+?)__")
_STRIKE_RE = re.compile(r"~~(.+?)~~")
_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s\n]+)\)")
_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+)$")
_BULLET_RE = re.compile(r"(?m)^(\s*)-\s+")


def to_slack_mrkdwn(text: str) -> str:
    """Rewrite Markdown constructs to their Slack mrkdwn equivalents."""
    if not text:
        return text
    saved: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        saved.append(match.group(0))
        return _PLACEHOLDER % (len(saved) - 1)

    # Fenced blocks first so inner backticks/headings survive verbatim.
    out = _FENCE_RE.sub(_stash, text)
    out = _INLINE_CODE_RE.sub(_stash, out)
    out = _BOLD_STAR_RE.sub(r"*\1*", out)
    out = _BOLD_UNDER_RE.sub(r"*\1*", out)
    out = _STRIKE_RE.sub(r"~\1~", out)
    out = _LINK_RE.sub(r"<\2|\1>", out)
    out = _HEADING_RE.sub(r"*\2*", out)
    out = _BULLET_RE.sub(r"\1• ", out)
    for i, chunk in enumerate(saved):
        out = out.replace(_PLACEHOLDER % i, chunk)
    return out
