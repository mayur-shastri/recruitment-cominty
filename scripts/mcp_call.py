"""Call any ATS MCP tool on a remote server (live checks for entity milestones).

Usage (repo root, project venv):
    python scripts/mcp_call.py https://<domain>/mcp list_jobs '{"status": "open"}'
    python scripts/mcp_call.py https://<domain>/mcp health
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> int:
    args = parse_args()
    try:
        tool_args = json.loads(args.args_json)
    except json.JSONDecodeError as exc:
        print(f"invalid JSON args: {exc}", file=sys.stderr)
        return 2
    async with streamable_http_client(args.url) as streams:
        read_stream, write_stream = streams[0], streams[1]
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("tools:", [tool.name for tool in tools.tools])
            result = await session.call_tool(args.tool, tool_args)
            for block in result.content:
                print("result:", getattr(block, "text", block))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Call an ATS MCP tool on a remote server.")
    parser.add_argument("url", help="MCP endpoint URL (e.g. https://host/mcp)")
    parser.add_argument("tool", help="Tool name (e.g. list_jobs)")
    parser.add_argument("args_json", nargs="?", default="{}", help="Tool args as JSON")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
