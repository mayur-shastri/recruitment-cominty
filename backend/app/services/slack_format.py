"""Convert agent Markdown to Slack mrkdwn before sending.

Agents write standard Markdown (``**bold**``, ``[text](url)``, ``#`` headings,
tables) but Slack renders its own mrkdwn dialect, so raw Markdown shows up
literally (visible ``**`` pairs, dead ``[text](url)`` links, ragged pipes).
This normalizes the common constructs; tables become aligned monospace blocks
(mrkdwn has no tables) and code spans/blocks pass through untouched.
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
_CELL_CODE_RE = re.compile(r"`([^`\n]+)`")
_DELIM_CHARS = frozenset("|-: \t")


def _is_delim_row(line: str) -> bool:
    stripped = line.strip()
    return "-" in stripped and all(ch in _DELIM_CHARS for ch in stripped)


def _split_row(line: str) -> list[str]:
    cells = line.strip().strip("|").split("|")
    return [cell.strip() for cell in cells]


def _cell_text(cell: str) -> str:
    """Plain text for a table cell: fenced blocks render no mrkdwn inside."""
    out = _BOLD_STAR_RE.sub(r"\1", cell.strip())
    out = _BOLD_UNDER_RE.sub(r"\1", out)
    out = _STRIKE_RE.sub(r"\1", out)
    out = _CELL_CODE_RE.sub(r"\1", out)
    out = _LINK_RE.sub(r"\1 (\2)", out)
    return out.strip()


def _render_table(header: list[str], rows: list[list[str]]) -> str:
    header = [_cell_text(c) for c in header]
    rows = [[_cell_text(c) for c in row] for row in rows]
    ncols = max([len(header)] + [len(r) for r in rows])
    header += [""] * (ncols - len(header))
    rows = [r + [""] * (ncols - len(r)) for r in rows]
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(ncols)]

    def _row(cells: list[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    bar = "|" + "|".join("-" * (w + 2) for w in widths) + "|"
    return "```\n" + "\n".join([_row(header), bar] + [_row(r) for r in rows]) + "\n```"


def _convert_tables(text: str) -> str:
    """Rewrite GFM tables (header + delimiter row) as aligned code blocks."""
    lines = text.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        if (
            "|" in lines[i]
            and i + 1 < len(lines)
            and _is_delim_row(lines[i + 1])
        ):
            header = _split_row(lines[i])
            rows: list[list[str]] = []
            j = i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(_split_row(lines[j]))
                j += 1
            out.append(_render_table(header, rows))
            i = j
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


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
    # Tables next: the rendered fence is stashed so inline rules skip it.
    out = _FENCE_RE.sub(_stash, _convert_tables(out))
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
