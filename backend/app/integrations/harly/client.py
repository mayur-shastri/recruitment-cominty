"""Minimal Harly API reads for the webhook pipeline.

The ATS MCP server owns the full Harly surface (reads and writes) for agents;
the backend keeps only the three GETs the assessment pipeline needs, so it
never blocks on MCP availability. Errors are user-safe (no credentials).
"""

from __future__ import annotations

from typing import Any

import httpx


class HarlyReadError(Exception):
    """User-safe Harly read failure."""


class HarlyReads:
    """Short-lived Harly reader: one instance per pipeline run."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not base_url or not api_key:
            raise HarlyReadError("harly api is not configured")
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            timeout=30.0,
            transport=self._transport,
        )

    async def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        async with self._client() as client:
            try:
                resp = await client.get(path, params=params)
            except httpx.HTTPError as exc:
                raise HarlyReadError(f"harly request failed: {type(exc).__name__}") from exc
        if resp.status_code == 404:
            raise HarlyReadError(f"harly resource not found: {path}")
        if resp.status_code != 200:
            raise HarlyReadError(f"harly request failed (status {resp.status_code})")
        return resp.json()

    async def get_application(self, application_id: str) -> dict[str, Any]:
        env = await self._get(f"/api/v1/applications/{application_id}")
        return env.get("data", {})

    async def get_candidate(self, candidate_id: str) -> dict[str, Any]:
        env = await self._get(f"/api/v1/candidates/{candidate_id}")
        return env.get("data", {})

    async def list_applications(
        self, *, limit: int = 100, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page of applications + the next cursor (None when exhausted)."""
        env = await self._get("/api/v1/applications", {"limit": limit, "cursor": cursor})
        data = env.get("data", [])
        meta = env.get("meta", {}).get("pagination", {})
        next_cursor = meta.get("nextCursor") if meta.get("hasMore") else None
        return data, next_cursor

    async def list_candidate_files(self, candidate_id: str) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            env = await self._get(
                f"/api/v1/candidates/{candidate_id}/files", {"limit": 100, "cursor": cursor}
            )
            files.extend(env.get("data", []))
            meta = env.get("meta", {}).get("pagination", {})
            cursor = meta.get("nextCursor")
            if not meta.get("hasMore") or not cursor:
                break
        return files

    async def list_job_stages(self, job_id: str) -> list[dict[str, Any]]:
        env = await self._get(f"/api/v1/jobs/{job_id}/stages")
        return env.get("data", [])
