"""Thin wrapper over the Cominty managed-agent chat API (cominty-sdk v1.x)."""

from __future__ import annotations

from cominty_sdk import AgentCapabilities, AsyncCominty
from cominty_sdk.exceptions import (
    APIConnectionError,
    ComintyError,
    RateLimitError,
    ServerError,
    StreamInterrupted,
)

ATS_CONNECTION_ID = "harly_ats"
"""Cominty MCP integration identifier. Must exactly match the identifier
registered in the Cominty workspace — a mismatch silently attaches zero tools."""


class ComintyServiceError(Exception):
    """User-safe Cominty failure. `transient` hints whether a retry may help."""

    def __init__(self, message: str, *, transient: bool) -> None:
        super().__init__(message)
        self.transient = transient


_TRANSIENT_ERRORS = (RateLimitError, ServerError, APIConnectionError, StreamInterrupted)


class ComintyService:
    """Start threads and send follow-ups on the Recruiter Agent."""

    def __init__(
        self, client: AsyncCominty, *, agent_id: str, thread_capabilities: AgentCapabilities | None = None
    ) -> None:
        self._client = client
        self._agent_id = agent_id
        self._thread_capabilities = thread_capabilities

    async def aclose(self) -> None:
        await self._client.close()

    async def start_thread(self, message: str, *, name: str | None = None) -> tuple[str, str]:
        """Start a thread with a first message. Returns (thread_id, reply_text)."""
        try:
            run = await self._client.chat.start(
                agent_id=self._agent_id,
                message=message,
                name=name,
                thread_capabilities=self._thread_capabilities,
            )
            return str(run.thread.id), await run.text()
        except ComintyError as exc:
            raise self._wrap(exc) from exc

    async def send_message(self, thread_id: str, message: str) -> str:
        """Send a follow-up in an existing thread. Returns the reply text."""
        try:
            run = await self._client.chat.send(thread_id, message=message, agent_id=self._agent_id)
            return await run.text()
        except ComintyError as exc:
            raise self._wrap(exc) from exc

    @staticmethod
    def _wrap(exc: ComintyError) -> ComintyServiceError:
        return ComintyServiceError(f"cominty request failed: {exc}", transient=isinstance(exc, _TRANSIENT_ERRORS))
