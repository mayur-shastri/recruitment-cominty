"""Health tool plus combined-app smoke test (UI routes + mounted /mcp)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# All flat-layout suites share top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services", "ui", "seed"}]:
    del sys.modules[_mod]

from fastapi.testclient import TestClient

import server
import ui
from services.booking import BookingError


def test_health_tool_returns_ok() -> None:
    assert server.health() == "ok"


def _rpc(client, method: str, params: dict, rpc_id: int = 1) -> dict:
    resp = client.post("/mcp", json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params})
    assert resp.status_code == 200
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            import json

            return json.loads(line[len("data: ") :])
    raise AssertionError(f"no SSE data frame in {resp.text!r}")


def test_combined_app_exposes_mcp_and_ui(monkeypatch) -> None:
    def _missing():
        raise BookingError("DATABASE_URL is not configured")

    monkeypatch.setattr(ui, "get_booking_store", _missing)
    # Localhost base URL: the MCP factory enables DNS-rebinding protection
    # for loopback hosts, and TestClient's default "testserver" is rejected.
    with TestClient(server.create_app(), base_url="http://localhost:8004") as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/interviewers").status_code == 500
        init = _rpc(
            client,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "probe", "version": "0.0"},
            },
        )
        assert init["result"]["serverInfo"]["name"] == "acmetech-calendar"
        tools = _rpc(client, "tools/list", {}, rpc_id=2)
        assert [t["name"] for t in tools["result"]["tools"]] == [
            "health",
            "list_interviewers",
            "get_availability",
            "book_interview",
            "list_interviews",
        ]
        called = _rpc(
            client, "tools/call", {"name": "health", "arguments": {}}, rpc_id=3
        )
        assert called["result"]["content"][0]["text"] == "ok"


def test_mcp_tool_surface() -> None:
    names = [t.name for t in server.mcp._tool_manager._tools.values()]
    assert names == [
        "health",
        "list_interviewers",
        "get_availability",
        "book_interview",
        "list_interviews",
    ]
