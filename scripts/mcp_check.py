"""Check a remote ATS MCP server: initialize, list tools, call health.

Usage (repo root, project venv):
    python scripts/mcp_check.py https://<your-duckdns-domain>/mcp
"""

from __future__ import annotations

import argparse
import asyncio

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> int:
    url = parse_args().url
    async with streamable_http_client(url) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [tool.name for tool in tools.tools])
            result = await session.call_tool("health", {})
            for block in result.content:
                print("health:", getattr(block, "text", block))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a remote ATS MCP server.")
    parser.add_argument("url", help="MCP endpoint URL (e.g. https://host/mcp)")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
