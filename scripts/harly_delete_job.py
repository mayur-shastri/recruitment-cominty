"""Soft-delete a Harly job (status reverts to closed). TEST CLEANUP ONLY.

Never registered as an MCP tool — the agent must not delete jobs.

Usage (repo root, project venv):  python scripts/harly_delete_job.py <job-id>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ats-mcp"))

from services.harly import get_harly_client


async def main() -> int:
    job_id = parse_args().job_id
    client = get_harly_client()
    try:
        result = await client.delete_job(job_id)
    finally:
        await client.aclose()
    print(f"deleted {result.get('id', job_id)} (status={result.get('status')})")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Soft-delete a Harly job (test cleanup).")
    parser.add_argument("job_id", help="Harly job UUID")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
