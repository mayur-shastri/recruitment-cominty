"""Slack mrkdwn: agent Markdown must render, not show literally (fakes)."""

from __future__ import annotations

from app.services.interviewer_comms import post_interviewer_dm
from app.services.slack_format import to_slack_mrkdwn


def test_bold_double_star_becomes_single() -> None:
    assert to_slack_mrkdwn("Job **posted** today") == "Job *posted* today"


def test_bold_underscores_become_single_star() -> None:
    assert to_slack_mrkdwn("__Offer__ extended") == "*Offer* extended"


def test_strike_and_link() -> None:
    assert to_slack_mrkdwn("~~old~~ [board](https://x/y)") == "~old~ <https://x/y|board>"


def test_heading_and_bullets() -> None:
    assert to_slack_mrkdwn("## Plan\n- one\n  - two") == "*Plan*\n• one\n  • two"


def test_code_spans_and_blocks_untouched() -> None:
    assert to_slack_mrkdwn("run `**x**` now") == "run `**x**` now"
    assert to_slack_mrkdwn("```\n**x**\n# h\n```") == "```\n**x**\n# h\n```"


def test_empty_and_plain_passthrough() -> None:
    assert to_slack_mrkdwn("") == ""
    assert to_slack_mrkdwn("plain *already* fine") == "plain *already* fine"


def test_table_becomes_aligned_code_block() -> None:
    md = "| Criterion | Weight |\n|---|---|\n| Relevant experience | 30 |\n| Technical skills | 35 |"
    assert to_slack_mrkdwn(md) == (
        "```\n"
        "| Criterion           | Weight |\n"
        "|---------------------|--------|\n"
        "| Relevant experience | 30     |\n"
        "| Technical skills    | 35     |\n"
        "```"
    )


def test_table_without_outer_pipes_and_alignment() -> None:
    md = "Criterion | Weight\n:---|---:\nA | 1"
    assert to_slack_mrkdwn(md) == (
        "```\n| Criterion | Weight |\n|-----------|--------|\n| A         | 1      |\n```"
    )


def test_table_cells_become_plain_text() -> None:
    md = "| A |\n|---|\n| **bold** [t](https://x) `c` |"
    assert to_slack_mrkdwn(md) == (
        "```\n| A                    |\n|----------------------|\n| bold t (https://x) c |\n```"
    )


def test_table_surrounding_text_preserved() -> None:
    md = "Here you go:\n| A |\n|---|\n| b |\nDone **now**."
    assert to_slack_mrkdwn(md) == "Here you go:\n```\n| A |\n|---|\n| b |\n```\nDone *now*."


def test_pipe_text_without_delimiter_untouched() -> None:
    assert to_slack_mrkdwn("a | b\nc | d") == "a | b\nc | d"


def test_table_inside_code_block_untouched() -> None:
    md = "```\n| A |\n|---|\n| b |\n```"
    assert to_slack_mrkdwn(md) == md


class FakeSlack:
    def __init__(self) -> None:
        self.posts: list = []

    async def users_lookupByEmail(self, email: str):
        return {"ok": True, "user": {"id": "U1"}}

    async def conversations_open(self, users: str):
        return {"ok": True, "channel": {"id": "D1"}}

    async def chat_postMessage(self, channel: str, text: str):
        self.posts.append((channel, text))
        return {"ok": True}


async def test_proactive_dm_converts_markdown() -> None:
    slack = FakeSlack()
    await post_interviewer_dm(slack, "iv@acme.tech", "Hi **Asha**, see [cal](https://x)")
    assert slack.posts == [("D1", "Hi *Asha*, see <https://x|cal>")]
