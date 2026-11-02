"""ComintyService: start/send wiring and error mapping (SDK client faked)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from cominty_sdk.exceptions import AuthError, ServerError

from cominty_sdk import AgentCapabilities, McpCapability

from app.services.cominty import ComintyService, ComintyServiceError


class FakeRun:
    def __init__(self, thread_id: str | None = None, reply: str = "hello") -> None:
        self._thread_id = thread_id
        self._reply = reply

    @property
    def thread(self):
        return SimpleNamespace(id=self._thread_id)

    async def text(self) -> str:
        return self._reply


class FakeChat:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.failure: Exception | None = None

    async def start(self, *, agent_id: str, message: str, name=None, thread_capabilities=None):
        self.calls.append(("start", agent_id, message, name, thread_capabilities))
        if self.failure is not None:
            raise self.failure
        return FakeRun(thread_id="thr_1", reply="started!")

    async def send(self, thread_id, *, message: str, agent_id: str):
        self.calls.append(("send", thread_id, message, agent_id))
        if self.failure is not None:
            raise self.failure
        return FakeRun(reply="continued!")


class FakeClient:
    def __init__(self) -> None:
        self.chat = FakeChat()

    async def close(self) -> None:
        pass


async def test_start_returns_thread_and_reply() -> None:
    client = FakeClient()
    service = ComintyService(client, agent_id="agt_1")  # type: ignore[arg-type]
    thread_id, reply = await service.start_thread("hi", name="slack:U1")
    assert (thread_id, reply) == ("thr_1", "started!")
    assert client.chat.calls == [("start", "agt_1", "hi", "slack:U1", None)]


async def test_start_passes_thread_capabilities() -> None:
    client = FakeClient()
    capabilities = AgentCapabilities(mcp=McpCapability(activation="always", connections=["ats"]))
    service = ComintyService(client, agent_id="agt_1", thread_capabilities=capabilities)  # type: ignore[arg-type]
    await service.start_thread("hi")
    assert client.chat.calls == [("start", "agt_1", "hi", None, capabilities)]


async def test_send_returns_reply() -> None:
    client = FakeClient()
    service = ComintyService(client, agent_id="agt_1")  # type: ignore[arg-type]
    assert await service.send_message("thr_1", "again") == "continued!"
    assert client.chat.calls == [("send", "thr_1", "again", "agt_1")]


async def test_auth_error_is_not_transient() -> None:
    client = FakeClient()
    client.chat.failure = AuthError("bad key", status_code=401)
    service = ComintyService(client, agent_id="agt_1")  # type: ignore[arg-type]
    with pytest.raises(ComintyServiceError) as exc_info:
        await service.send_message("thr_1", "hi")
    assert exc_info.value.transient is False


async def test_server_error_is_transient() -> None:
    client = FakeClient()
    client.chat.failure = ServerError("boom", status_code=500)
    service = ComintyService(client, agent_id="agt_1")  # type: ignore[arg-type]
    with pytest.raises(ComintyServiceError) as exc_info:
        await service.send_message("thr_1", "hi")
    assert exc_info.value.transient is True
