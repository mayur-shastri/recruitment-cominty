"""Job tools: shaping, validation, registration (Harly client faked)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import tools.jobs as jobs
from services.harly import HarlyError


class FakeHarlyClient:
    def __init__(self) -> None:
        self.calls: list = []

    async def list_jobs(self, **kwargs):
        self.calls.append(("list", kwargs))
        return {"jobs": [], "next_cursor": None, "has_more": False}

    async def get_job(self, job_id: str):
        self.calls.append(("get", job_id))
        return {"id": job_id}

    async def list_job_stages(self, job_id: str):
        self.calls.append(("stages", job_id))
        return {"stages": []}

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeHarlyClient()
    monkeypatch.setattr(jobs, "get_harly_client", lambda: client)
    return client


async def test_list_jobs_defaults(fake_client) -> None:
    result = await jobs.list_jobs()
    assert result == {"jobs": [], "next_cursor": None, "has_more": False}
    assert fake_client.calls == [("list", {"status": None, "limit": 20, "cursor": None})]


async def test_list_jobs_rejects_bad_status(fake_client) -> None:
    with pytest.raises(ToolError, match="unknown status"):
        await jobs.list_jobs(status="bogus")
    assert fake_client.calls == []


async def test_list_jobs_rejects_bad_limit(fake_client) -> None:
    with pytest.raises(ToolError, match="limit"):
        await jobs.list_jobs(limit=0)
    with pytest.raises(ToolError, match="limit"):
        await jobs.list_jobs(limit=101)
    assert fake_client.calls == []


async def test_get_job_passthrough(fake_client) -> None:
    assert await jobs.get_job("j1") == {"id": "j1"}
    assert fake_client.calls == [("get", "j1")]


async def test_list_job_stages_passthrough(fake_client) -> None:
    assert await jobs.list_job_stages("j1") == {"stages": []}
    assert fake_client.calls == [("stages", "j1")]


async def test_harly_error_becomes_tool_error(monkeypatch) -> None:
    class Boom(FakeHarlyClient):
        async def get_job(self, job_id: str):
            raise HarlyError("kaput", code="x")

    monkeypatch.setattr(jobs, "get_harly_client", lambda: Boom())
    with pytest.raises(ToolError, match="kaput"):
        await jobs.get_job("j1")


def test_register_tools_registers_three_named_tools() -> None:
    class StubMcp:
        def __init__(self) -> None:
            self.registered: list = []

        def tool(self, name=None, description=None, **kwargs):
            self.registered.append((name, description))
            return lambda fn: fn

    stub = StubMcp()
    jobs.register_tools(stub)
    assert [name for name, _ in stub.registered] == ["list_jobs", "get_job", "list_job_stages"]
    assert all(description for _, description in stub.registered)
