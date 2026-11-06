"""Job tools: shaping, validation, registration (Harly client faked)."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Both MCP services share flat top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services"}]:
    del sys.modules[_mod]

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

    async def create_job(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"id": "j9", "slug": "demo", "status": "draft"}

    async def update_job(self, job_id, **kwargs):
        self.calls.append(("update", job_id, kwargs))
        return {"id": job_id}

    async def publish_job(self, job_id):
        self.calls.append(("publish", job_id))
        return {"id": job_id, "status": "open"}

    async def close_job(self, job_id):
        self.calls.append(("close", job_id))
        return {"id": job_id, "status": "closed"}

    async def create_job_stage(self, job_id, **kwargs):
        self.calls.append(("create_stage", job_id, kwargs))
        return {"id": "s9", "jobId": job_id, **kwargs}

    async def update_job_stage(self, job_id, stage_id, **kwargs):
        self.calls.append(("update_stage", job_id, stage_id, kwargs))
        return {"id": stage_id}

    async def delete_job_stage(self, job_id, stage_id):
        self.calls.append(("delete_stage", job_id, stage_id))
        return {"id": stage_id}

    async def archive_job_stage(self, job_id, stage_id, **kwargs):
        self.calls.append(("archive_stage", job_id, stage_id, kwargs))
        return {"id": stage_id}

    async def reorder_job_stages(self, job_id, stage_ids):
        self.calls.append(("reorder_stages", job_id, stage_ids))
        return {"jobId": job_id}

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
    assert [name for name, _ in stub.registered] == [
        "list_jobs",
        "get_job",
        "list_job_stages",
        "create_job",
        "update_job",
        "publish_job",
        "close_job",
        "create_job_stage",
        "update_job_stage",
        "delete_job_stage",
        "archive_job_stage",
        "reorder_job_stages",
    ]
    assert all(description for _, description in stub.registered)


def test_write_tools_have_no_status_param() -> None:
    for func in (jobs.create_job, jobs.update_job):
        assert "status" not in inspect.signature(func).parameters


async def test_create_job_passthrough(fake_client) -> None:
    result = await jobs.create_job(
        title="T", description="D", employment_type="full_time", workplace_type="remote"
    )
    assert result["status"] == "draft"
    [(name, kwargs)] = fake_client.calls
    assert name == "create"
    assert kwargs["title"] == "T"
    assert "status" not in kwargs


async def test_create_job_rejects_bad_enum_and_blank(fake_client) -> None:
    with pytest.raises(ToolError, match="employment_type"):
        await jobs.create_job(
            title="T", description="D", employment_type="bogus", workplace_type="remote"
        )
    with pytest.raises(ToolError, match="must not be blank"):
        await jobs.create_job(
            title="  ", description="D", employment_type="full_time", workplace_type="remote"
        )
    assert fake_client.calls == []


async def test_update_requires_confirmation_and_fields(fake_client) -> None:
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.update_job("j1", "  ", title="T")
    with pytest.raises(ToolError, match="at least one field"):
        await jobs.update_job("j1", "HM said edit it")
    assert fake_client.calls == []


async def test_update_forwards_provided_only(fake_client) -> None:
    await jobs.update_job("j1", "HM said edit it", title="T")
    assert fake_client.calls == [("update", "j1", {"title": "T"})]


async def test_publish_close_require_confirmation(fake_client) -> None:
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.publish_job("j1", "")
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.close_job("j1", "  ")
    assert await jobs.publish_job("j1", "HM said publish") == {"id": "j1", "status": "open"}
    assert await jobs.close_job("j1", "HM said close") == {"id": "j1", "status": "closed"}


async def test_stage_writes_require_confirmation(fake_client) -> None:
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.create_job_stage("j1", "Onsite", "")
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.update_job_stage("j1", "s1", "  ", name="Final")
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.delete_job_stage("j1", "s1", "")
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.archive_job_stage("j1", "s1", "  ")
    with pytest.raises(ToolError, match="confirmation"):
        await jobs.reorder_job_stages("j1", ["s1"], "")
    assert fake_client.calls == []


async def test_create_stage_validates_name_kind_position(fake_client) -> None:
    with pytest.raises(ToolError, match="must not be blank"):
        await jobs.create_job_stage("j1", "  ", "HM said add it")
    with pytest.raises(ToolError, match="at most 120"):
        await jobs.create_job_stage("j1", "x" * 121, "HM said add it")
    with pytest.raises(ToolError, match="kind"):
        await jobs.create_job_stage("j1", "Onsite", "HM said add it", kind="bogus")
    with pytest.raises(ToolError, match="position"):
        await jobs.create_job_stage("j1", "Onsite", "HM said add it", position=-1)
    assert fake_client.calls == []


async def test_update_stage_needs_field_and_valid_kind(fake_client) -> None:
    with pytest.raises(ToolError, match="at least one field"):
        await jobs.update_job_stage("j1", "s1", "HM said edit it")
    with pytest.raises(ToolError, match="kind"):
        await jobs.update_job_stage("j1", "s1", "HM said edit it", kind="bogus")
    assert fake_client.calls == []


async def test_reorder_validates_ids(fake_client) -> None:
    with pytest.raises(ToolError, match="at least one stage"):
        await jobs.reorder_job_stages("j1", [], "HM said reorder")
    with pytest.raises(ToolError, match="at most 100"):
        await jobs.reorder_job_stages("j1", ["s"] * 101, "HM said reorder")
    assert fake_client.calls == []


async def test_stage_writes_forward(fake_client) -> None:
    await jobs.create_job_stage("j1", "Onsite", "HM said add it", kind="interview", position=3)
    await jobs.update_job_stage("j1", "s1", "HM said edit it", name="Final")
    await jobs.delete_job_stage("j1", "s1", "HM said delete it")
    await jobs.archive_job_stage("j1", "s1", "HM said archive it", merge_into_stage_id="s2")
    await jobs.reorder_job_stages("j1", ["s2", "s1"], "HM said reorder")
    assert fake_client.calls == [
        ("create_stage", "j1", {"name": "Onsite", "kind": "interview", "position": 3}),
        ("update_stage", "j1", "s1", {"name": "Final"}),
        ("delete_stage", "j1", "s1"),
        ("archive_stage", "j1", "s1", {"merge_into_stage_id": "s2"}),
        ("reorder_stages", "j1", ["s2", "s1"]),
    ]
