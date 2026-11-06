"""Application tools: shaping, validation, registration (Harly client faked)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Both MCP services share flat top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services"}]:
    del sys.modules[_mod]

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import tools.applications as applications
from services.harly import HarlyError


class FakeHarlyClient:
    def __init__(self) -> None:
        self.calls: list = []

    async def list_applications(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"applications": [], "next_cursor": None, "has_more": False}

    async def get_application(self, application_id: str):
        self.calls.append(("get", application_id))
        return {"id": application_id}

    async def move_application(self, application_id: str, to_stage_id: str):
        self.calls.append(("move", application_id, to_stage_id))
        return {"id": application_id, "currentStageId": to_stage_id}

    async def reject_application(self, application_id: str):
        self.calls.append(("reject", application_id))
        return {"id": application_id, "status": "rejected"}

    async def hire_application(self, application_id: str):
        self.calls.append(("hire", application_id))
        return {"id": application_id, "status": "hired"}

    async def create_scorecard(self, candidate_id: str, rating: str, **kwargs):
        self.calls.append(("scorecard", candidate_id, rating, kwargs))
        return {"id": "sc1"}

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeHarlyClient()
    monkeypatch.setattr(applications, "get_harly_client", lambda: client)
    return client


async def test_list_applications_defaults(fake_client) -> None:
    result = await applications.list_applications()
    assert result == {"applications": [], "next_cursor": None, "has_more": False}
    assert fake_client.calls == [
        ("list", {"job_id": None, "status": None, "limit": 20, "cursor": None})
    ]


async def test_list_applications_rejects_bad_limit(fake_client) -> None:
    with pytest.raises(ToolError, match="limit"):
        await applications.list_applications(limit=0)
    with pytest.raises(ToolError, match="limit"):
        await applications.list_applications(limit=101)
    assert fake_client.calls == []


async def test_list_applications_rejects_blank_status(fake_client) -> None:
    with pytest.raises(ToolError, match="must not be blank"):
        await applications.list_applications(status="  ")
    assert fake_client.calls == []


async def test_get_application_passthrough(fake_client) -> None:
    assert await applications.get_application("a1") == {"id": "a1"}
    assert fake_client.calls == [("get", "a1")]


async def test_move_reject_hire_require_confirmation(fake_client) -> None:
    with pytest.raises(ToolError, match="confirmation"):
        await applications.move_application("a1", "s1", "")
    with pytest.raises(ToolError, match="confirmation"):
        await applications.reject_application("a1", "  ")
    with pytest.raises(ToolError, match="confirmation"):
        await applications.hire_application("a1", "")
    assert fake_client.calls == []


async def test_move_rejects_blank_ids(fake_client) -> None:
    with pytest.raises(ToolError, match="must not be blank"):
        await applications.move_application("  ", "s1", "HM said move it")
    with pytest.raises(ToolError, match="must not be blank"):
        await applications.move_application("a1", "  ", "HM said move it")
    assert fake_client.calls == []


async def test_decisions_forward_and_return(fake_client) -> None:
    assert await applications.move_application("a1", "s1", "HM said move to onsite") == {
        "id": "a1",
        "currentStageId": "s1",
    }
    assert await applications.reject_application("a1", "HM said reject") == {
        "id": "a1",
        "status": "rejected",
    }
    assert await applications.hire_application("a1", "HM said hire") == {"id": "a1", "status": "hired"}
    assert fake_client.calls == [
        ("move", "a1", "s1"),
        ("reject", "a1"),
        ("hire", "a1"),
    ]


async def test_scorecard_validates(fake_client) -> None:
    with pytest.raises(ToolError, match="must not be blank"):
        await applications.create_scorecard("  ", "strong")
    with pytest.raises(ToolError, match="rating"):
        await applications.create_scorecard("c1", "bogus")
    with pytest.raises(ToolError, match="criteria"):
        await applications.create_scorecard("c1", "strong", criteria=[{"label": "  ", "score": 1}])
    with pytest.raises(ToolError, match="criteria"):
        await applications.create_scorecard("c1", "strong", criteria=[{"label": "Go"}])
    assert fake_client.calls == []


async def test_scorecard_forwards(fake_client) -> None:
    assert await applications.create_scorecard(
        "c1", "strong", application_id="a1", comment="total 90 v2", criteria=[{"label": "Go", "score": 45}]
    ) == {"id": "sc1"}
    assert fake_client.calls == [
        (
            "scorecard",
            "c1",
            "strong",
            {"application_id": "a1", "comment": "total 90 v2", "criteria": [{"label": "Go", "score": 45}]},
        )
    ]


async def test_harly_error_becomes_tool_error(monkeypatch) -> None:
    class Boom(FakeHarlyClient):
        async def get_application(self, application_id: str):
            raise HarlyError("kaput", code="x")

    monkeypatch.setattr(applications, "get_harly_client", lambda: Boom())
    with pytest.raises(ToolError, match="kaput"):
        await applications.get_application("a1")


def test_register_tools_registers_named_tools() -> None:
    class StubMcp:
        def __init__(self) -> None:
            self.registered: list = []

        def tool(self, name=None, description=None, **kwargs):
            self.registered.append((name, description))
            return lambda fn: fn

    stub = StubMcp()
    applications.register_tools(stub)
    assert [name for name, _ in stub.registered] == [
        "list_applications",
        "get_application",
        "move_application",
        "reject_application",
        "hire_application",
        "create_scorecard",
    ]
    assert all(description for _, description in stub.registered)
