"""Application tools: shaping, validation, registration (Harly client faked)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    assert [name for name, _ in stub.registered] == ["list_applications", "get_application"]
    assert all(description for _, description in stub.registered)
