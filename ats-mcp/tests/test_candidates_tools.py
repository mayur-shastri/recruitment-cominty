"""Candidate tools: shaping, validation, registration (Harly client faked)."""

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

import tools.candidates as candidates
from services.harly import HarlyError


class FakeHarlyClient:
    def __init__(self) -> None:
        self.calls: list = []

    async def get_candidate(self, candidate_id: str):
        self.calls.append(("get", candidate_id))
        return {"id": candidate_id}

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_client(monkeypatch):
    client = FakeHarlyClient()
    monkeypatch.setattr(candidates, "get_harly_client", lambda: client)
    return client


async def test_get_candidate_passthrough(fake_client) -> None:
    assert await candidates.get_candidate("c1") == {"id": "c1"}
    assert fake_client.calls == [("get", "c1")]


async def test_harly_error_becomes_tool_error(monkeypatch) -> None:
    class Boom(FakeHarlyClient):
        async def get_candidate(self, candidate_id: str):
            raise HarlyError("kaput", code="x")

    monkeypatch.setattr(candidates, "get_harly_client", lambda: Boom())
    with pytest.raises(ToolError, match="kaput"):
        await candidates.get_candidate("c1")


def test_register_tools_registers_named_tools() -> None:
    class StubMcp:
        def __init__(self) -> None:
            self.registered: list = []

        def tool(self, name=None, description=None, **kwargs):
            self.registered.append((name, description))
            return lambda fn: fn

    stub = StubMcp()
    candidates.register_tools(stub)
    assert [name for name, _ in stub.registered] == ["get_candidate"]
    assert all(description for _, description in stub.registered)
