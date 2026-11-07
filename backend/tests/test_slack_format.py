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
