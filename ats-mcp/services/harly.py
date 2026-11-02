"""Hand-rolled Harly ATS API client (the OpenAPI spec has no $refs to generate from).

Verified against harly-openapi.json v0.2.4: bearer auth, {data, meta} success
and {error{code, message, details}} error envelopes, cursor pagination via
meta.pagination{nextCursor, hasMore}.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from config import get_mcp_settings

DEFAULT_TIMEOUT_S = 30.0
_MAX_ATTEMPTS = 3
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class HarlyError(Exception):
    """Harly API failure with user-safe details (never includes credentials)."""

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
        transient: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.transient = transient

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.code:
            parts.append(f"(code={self.code})")
        if self.status_code is not None:
            parts.append(f"[http={self.status_code}]")
        return " ".join(parts)


class HarlyClient:
    """Async Harly client. Tools open one client per tool call and close it —
    stateless by construction (no shared sessions)."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
            timeout=timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- jobs: reads (M2.1a; writes land in M2.1b/c) --------------------------

    async def list_jobs(
        self, *, status: str | None = None, limit: int = 20, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        if cursor is not None:
            params["cursor"] = cursor
        env = await self._request("GET", "/api/v1/jobs", params=params)
        meta = env.get("meta", {}).get("pagination", {})
        return {
            "jobs": env.get("data", []),
            "next_cursor": meta.get("nextCursor"),
            "has_more": meta.get("hasMore", False),
        }

    async def get_job(self, job_id: str) -> dict[str, Any]:
        env = await self._request("GET", f"/api/v1/jobs/{job_id}")
        return env.get("data", {})

    async def list_job_stages(self, job_id: str) -> dict[str, Any]:
        env = await self._request("GET", f"/api/v1/jobs/{job_id}/stages")
        return {"stages": env.get("data", [])}

    # -- transport -----------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> dict[str, Any]:
        last_error: HarlyError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = await self._http.request(method, path, params=params, json=json_body)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = HarlyError(f"harly request failed: {exc}", transient=True)
            except httpx.HTTPError as exc:
                raise HarlyError(f"harly request failed: {exc}") from exc
            else:
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = self._error_from_response(response, transient=True)
                elif response.status_code >= 400:
                    raise self._error_from_response(response, transient=False)
                else:
                    return self._decode_success(response)
            await asyncio.sleep(0.5 * (attempt + 1))
        assert last_error is not None
        raise last_error

    @staticmethod
    def _decode_success(response: httpx.Response) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as exc:
            raise HarlyError(
                "harly returned non-JSON response", status_code=response.status_code
            ) from exc
        if isinstance(body, dict) and "error" in body:
            raise HarlyClient._error_from_response(response, transient=False)
        if not isinstance(body, dict):
            raise HarlyError(
                "harly returned unexpected response shape", status_code=response.status_code
            )
        return body

    @staticmethod
    def _error_from_response(response: httpx.Response, *, transient: bool) -> HarlyError:
        try:
            err = response.json().get("error", {})
        except ValueError:
            err = {}
        if isinstance(err, dict):
            code = err.get("code")
            message = err.get("message") or f"harly request failed with HTTP {response.status_code}"
        else:
            code, message = None, f"harly request failed with HTTP {response.status_code}"
        return HarlyError(message, code=code, status_code=response.status_code, transient=transient)


def get_harly_client() -> HarlyClient:
    """Build a client from settings. Tools call this per invocation (stateless)."""
    settings = get_mcp_settings()
    if not settings.harly_api_key:
        raise HarlyError("HARLY_API_KEY is not configured")
    return HarlyClient(base_url=settings.harly_base_url, api_key=settings.harly_api_key)
