"""Health tool (M2): direct call + app smoke test.

Full client round trips are proven live (Cominty -> VPS); see docs/vps-deploy.md.
Run from ats-mcp/:  pytest tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server


def test_health_tool_returns_ok() -> None:
    assert server.health() == "ok"


def test_streamable_http_app_exposes_mcp_route() -> None:
    app = server.mcp.streamable_http_app(stateless_http=True)
    paths = [getattr(route, "path", "") for route in app.routes]
    assert "/mcp" in paths
