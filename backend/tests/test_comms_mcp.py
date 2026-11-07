"""Comms MCP: send tool (Slack faked) plus backend mount handshake."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from mcp.server.mcpserver.exceptions import ToolError

from app.main import create_app
from app.mcp import tools as comms_tools
from app.mcp.server import create_comms_mcp
from app.services.interviewer_comms import CommsError


class FakeSlack:
    def __init__(self) -> None:
        self.calls: list = []

    async def users_lookupByEmail(self, email: str):
        return {"ok": True, "user": {"id": "U1"}}

    async def conversations_open(self, users: str):
        return {"ok": True, "channel": {"id": "D1"}}

    async def chat_postMessage(self, channel: str, text: str):
        self.calls.append((channel, text))
        return {"ok": True, "ts": "1"}


@pytest.fixture
def fake_slack(monkeypatch):
    slack = FakeSlack()
    monkeypatch.setattr(comms_tools, "get_slack_client", lambda: slack)
    return slack


async def test_send_validates(fake_slack) -> None:
    with pytest.raises(ToolError, match="must not be blank"):
        await comms_tools.send_slack_message("  ", "hi")
    with pytest.raises(ToolError, match="must not be blank"):
        await comms_tools.send_slack_message("a@b.c", "  ")
    assert fake_slack.calls == []


async def test_send_forwards(fake_slack) -> None:
    result = await comms_tools.send_slack_message("asha@acme.tech", "Tue 10am?")
    assert result == {"slack_user_id": "U1", "channel": "D1"}
    assert fake_slack.calls == [("D1", "Tue 10am?")]


async def test_comms_error_becomes_tool_error(monkeypatch) -> None:
    class Failing(FakeSlack):
        async def users_lookupByEmail(self, email: str):
            raise CommsError("no Slack user for ghost@acme.tech")

    monkeypatch.setattr(comms_tools, "get_slack_client", lambda: Failing())
    with pytest.raises(ToolError, match="no Slack user"):
        await comms_tools.send_slack_message("ghost@acme.tech", "hi")


async def test_send_email_validates(monkeypatch) -> None:
    async def boom(*args, **kwargs):
        raise AssertionError("service must not run")

    monkeypatch.setattr(comms_tools.candidate_comms, "send_candidate_email", boom)
    with pytest.raises(ToolError, match="must not be blank"):
        await comms_tools.send_email("  ", "s", "t", "a1", "s9")
    with pytest.raises(ToolError, match="must not be blank"):
        await comms_tools.send_email("a@b.c", "  ", "t", "a1", "s9")


async def test_send_email_forwards(monkeypatch) -> None:
    from types import SimpleNamespace

    calls: list = []

    async def fake_send(resend, factory, **kwargs):
        calls.append(kwargs)
        return {"email_id": "email_1", "reply_to": "sched-tok@in.test.dev"}

    monkeypatch.setattr(comms_tools.candidate_comms, "send_candidate_email", fake_send)
    monkeypatch.setattr(
        comms_tools,
        "get_settings",
        lambda: SimpleNamespace(
            resend_api_key="re_test",
            resend_from_email="Acme <sched@test.dev>",
            resend_receiving_domain="in.test.dev",
            database_url="sqlite+aiosqlite:///:memory:",
        ),
    )
    result = await comms_tools.send_email("cand@test.com", "R1 options", "Tue?", "a1", "s9")
    assert result["email_id"] == "email_1"
    assert calls[0]["to_email"] == "cand@test.com"
    assert calls[0]["application_id"] == "a1"


async def test_send_email_refuses_unconfigured(monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(
        comms_tools, "get_settings", lambda: SimpleNamespace(resend_api_key="", database_url="")
    )
    with pytest.raises(ToolError, match="not configured"):
        await comms_tools.send_email("a@b.c", "s", "t", "a1", "s9")


def test_register_exposes_comms_tools() -> None:
    names = [t.name for t in create_comms_mcp()._tool_manager._tools.values()]
    assert names == ["health", "send_slack_message", "send_email"]


def _rpc(client, method: str, params: dict, rpc_id: int = 1) -> dict:
    import json

    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params})
    assert resp.status_code == 200
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no SSE data frame in {resp.text!r}")


def test_backend_mount_serves_mcp_and_bridge(monkeypatch) -> None:
    from types import SimpleNamespace

    import app.main as main_module

    fake = SimpleNamespace(
        app_env="test",
        log_level="INFO",
        backend_host="127.0.0.1",
        database_url="postgresql://u:p@localhost/db",
        slack_bot_token="xoxb-test",
        slack_signing_secret="secret",
        cominty_api_key="key",
        cominty_user_id="user_abcdefghijklmnopqrst",
        cominty_recruiter_agent_id="rec",
        cominty_timeout_s=1.0,
        cominty_assessment_agent_id="",
        cominty_db_mcp_connection_id="app_database",
        cominty_scheduler_agent_id="",
        cominty_calendar_connection_id="",
        cominty_comms_connection_id="",
        assessment_poll_enabled=False,
        assessment_poll_interval_s=300.0,
        harly_base_url="",
        harly_api_key="",
        harly_webhook_secret_application_created="",
        harly_webhook_secret_stage_changed="",
        harly_s3_endpoint="",
        harly_s3_bucket="",
        harly_s3_region="auto",
        harly_s3_access_key_id="",
        harly_s3_secret_access_key="",
        harly_s3_workspace_id="",
        harly_s3_public_url="",
        resend_api_key="",
        resend_from_email="",
        resend_receiving_domain="",
        resend_webhook_secret="",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: fake)
    app = create_app()
    with TestClient(app, base_url="http://localhost:8000") as client:
        assert client.get("/health").status_code in (200, 503)
        recruiter_conns = app.state.runtime.cominty._thread_capabilities.mcp.connections
        assert recruiter_conns == ["harly_ats", "app_database"]
        init = _rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0.0"},
            },
        )
        assert init["result"]["serverInfo"]["name"] == "acmetech-comms"
        tools = _rpc(client, "tools/list", {}, rpc_id=2)
        assert [t["name"] for t in tools["result"]["tools"]] == [
            "health",
            "send_slack_message",
            "send_email",
        ]
