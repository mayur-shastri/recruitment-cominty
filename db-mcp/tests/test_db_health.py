"""Health tool: direct call + app smoke test.

Full client round trips are proven live (Cominty -> VPS); see docs/vps-deploy.md.
Run from db-mcp/:  pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Both MCP services share flat top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services"}]:
    del sys.modules[_mod]

import server


def test_health_tool_returns_ok() -> None:
    assert server.health() == "ok"


def test_streamable_http_app_exposes_mcp_route() -> None:
    app = server.mcp.streamable_http_app(stateless_http=True)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert "/mcp" in paths
