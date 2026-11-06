"""Score tools: shaping, validation, registration, profiles (store faked)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Both MCP services share flat top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services"}]:
    del sys.modules[_mod]

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import tools.scores as scores
from services.scores import ScoresNotFoundError


class FakeScoresStore:
    def __init__(self) -> None:
        self.calls: list = []

    async def get_criteria(self, job_id: str):
        self.calls.append(("criteria", job_id))
        return {"job_id": job_id, "version": 2, "criteria": [{"label": "Go", "max_score": 50}]}

    async def save_criteria(self, *, job_id, criteria, created_by=None):
        self.calls.append(("save_criteria", job_id, criteria, created_by))
        return {"job_id": job_id, "version": 3, "criteria": criteria}

    async def save_score(
        self,
        *,
        application_id,
        job_id,
        candidate_id,
        total_score,
        breakdown,
        criteria_version,
        rationale=None,
    ):
        self.calls.append(
            (
                "save",
                {
                    "application_id": application_id,
                    "job_id": job_id,
                    "candidate_id": candidate_id,
                    "total_score": total_score,
                    "breakdown": breakdown,
                    "criteria_version": criteria_version,
                    "rationale": rationale,
                },
            )
        )
        return {"application_id": application_id, "job_id": job_id, "total_score": total_score}

    async def get_score(self, application_id: str):
        self.calls.append(("get", application_id))
        return {"application_id": application_id, "total_score": 82.5}

    async def get_resume(self, application_id: str):
        self.calls.append(("resume", application_id))
        return {"application_id": application_id, "resume_url": "https://pub.test/r.pdf"}

    async def list_top(self, job_id: str, limit: int):
        self.calls.append(("top", job_id, limit))
        return {"job_id": job_id, "scores": [{"application_id": "a1", "total_score": 90.0}]}

    async def aclose(self) -> None:
        pass


@pytest.fixture
def fake_store(monkeypatch):
    store = FakeScoresStore()
    monkeypatch.setattr(scores, "get_scores_store", lambda: store)
    return store


async def test_get_criteria_passthrough(fake_store) -> None:
    result = await scores.get_scoring_criteria("j1")
    assert result["version"] == 2
    assert fake_store.calls == [("criteria", "j1")]


async def test_get_score_passthrough(fake_store) -> None:
    assert await scores.get_application_score("a1") == {"application_id": "a1", "total_score": 82.5}
    assert fake_store.calls == [("get", "a1")]


async def test_list_top_defaults_to_10(fake_store) -> None:
    result = await scores.list_top_applications("j1")
    assert result["job_id"] == "j1"
    assert fake_store.calls == [("top", "j1", 10)]


async def test_list_top_rejects_bad_limit(fake_store) -> None:
    with pytest.raises(ToolError, match="limit"):
        await scores.list_top_applications("j1", limit=0)
    with pytest.raises(ToolError, match="limit"):
        await scores.list_top_applications("j1", limit=101)
    assert fake_store.calls == []


async def test_save_validates_ids(fake_store) -> None:
    good = {
        "application_id": "a1",
        "job_id": "j1",
        "candidate_id": "c1",
        "total_score": 82.5,
        "breakdown": [{"label": "Go", "score": 40}],
        "criteria_version": 2,
    }
    for field in ("application_id", "job_id", "candidate_id"):
        bad = {**good, field: "  "}
        with pytest.raises(ToolError, match="must not be blank"):
            await scores.save_application_score(**bad)
    assert fake_store.calls == []


async def test_save_validates_total_and_version(fake_store) -> None:
    good = {
        "application_id": "a1",
        "job_id": "j1",
        "candidate_id": "c1",
        "total_score": 82.5,
        "breakdown": [{"label": "Go", "score": 40}],
        "criteria_version": 2,
    }
    with pytest.raises(ToolError, match="total_score"):
        await scores.save_application_score(**{**good, "total_score": -1})
    with pytest.raises(ToolError, match="total_score"):
        await scores.save_application_score(**{**good, "total_score": 101})
    with pytest.raises(ToolError, match="total_score"):
        await scores.save_application_score(**{**good, "total_score": "high"})
    with pytest.raises(ToolError, match="criteria_version"):
        await scores.save_application_score(**{**good, "criteria_version": 0})
    assert fake_store.calls == []


async def test_save_validates_breakdown(fake_store) -> None:
    good = {
        "application_id": "a1",
        "job_id": "j1",
        "candidate_id": "c1",
        "total_score": 82.5,
        "breakdown": [{"label": "Go", "score": 40}],
        "criteria_version": 2,
    }
    with pytest.raises(ToolError, match="breakdown"):
        await scores.save_application_score(**{**good, "breakdown": []})
    with pytest.raises(ToolError, match="breakdown"):
        await scores.save_application_score(**{**good, "breakdown": [{"label": "  ", "score": 1}]})
    with pytest.raises(ToolError, match="breakdown"):
        await scores.save_application_score(**{**good, "breakdown": [{"label": "Go"}]})
    with pytest.raises(ToolError, match="breakdown"):
        await scores.save_application_score(
            **{**good, "breakdown": [{"label": "Go", "score": "lots"}]}
        )
    assert fake_store.calls == []


async def test_save_forwards_and_returns(fake_store) -> None:
    result = await scores.save_application_score(
        application_id="a1",
        job_id="j1",
        candidate_id="c1",
        total_score=82.5,
        breakdown=[{"label": "Go", "score": 40}],
        criteria_version=2,
        rationale="Strong Go background.",
    )
    assert result["total_score"] == 82.5
    [call] = fake_store.calls
    assert call[0] == "save"
    assert call[1]["rationale"] == "Strong Go background."
    assert call[1]["criteria_version"] == 2


async def test_save_criteria_requires_confirmation(fake_store) -> None:
    good = {
        "job_id": "j1",
        "criteria": [{"label": "Go", "max_score": 100}],
        "confirmation": "HM: score Go out of 100",
    }
    with pytest.raises(ToolError, match="confirmation"):
        await scores.save_scoring_criteria(**{**good, "confirmation": "  "})
    assert fake_store.calls == []


async def test_save_criteria_validates_shape(fake_store) -> None:
    good = {
        "job_id": "j1",
        "criteria": [{"label": "Go", "max_score": 60}, {"label": "Comms", "max_score": 40}],
        "confirmation": "HM: Go 60, comms 40",
    }
    with pytest.raises(ToolError, match="must not be blank"):
        await scores.save_scoring_criteria(**{**good, "job_id": "  "})
    with pytest.raises(ToolError, match="non-empty list"):
        await scores.save_scoring_criteria(**{**good, "criteria": []})
    with pytest.raises(ToolError, match="non-blank label"):
        await scores.save_scoring_criteria(
            **{**good, "criteria": [{"label": "  ", "max_score": 100}]}
        )
    with pytest.raises(ToolError, match="unique"):
        await scores.save_scoring_criteria(
            **{
                **good,
                "criteria": [
                    {"label": "Go", "max_score": 50},
                    {"label": "Go", "max_score": 50},
                ],
            }
        )
    with pytest.raises(ToolError, match="max_score"):
        await scores.save_scoring_criteria(
            **{**good, "criteria": [{"label": "Go", "max_score": 0}]}
        )
    with pytest.raises(ToolError, match="sum to 100"):
        await scores.save_scoring_criteria(
            **{**good, "criteria": [{"label": "Go", "max_score": 60}]}
        )
    assert fake_store.calls == []


async def test_save_criteria_forwards_and_returns(fake_store) -> None:
    criteria = [{"label": "Go", "max_score": 60}, {"label": "Comms", "max_score": 40}]
    result = await scores.save_scoring_criteria(
        job_id="j1",
        criteria=criteria,
        confirmation="HM: Go 60, comms 40",
        created_by="U1",
    )
    assert result["version"] == 3
    assert fake_store.calls == [("save_criteria", "j1", criteria, "U1")]


async def test_get_resume_passthrough(fake_store) -> None:
    assert await scores.get_application_resume("a1") == {
        "application_id": "a1",
        "resume_url": "https://pub.test/r.pdf",
    }
    assert fake_store.calls == [("resume", "a1")]


async def test_not_found_becomes_tool_error(monkeypatch) -> None:
    class Missing(FakeScoresStore):
        async def get_score(self, application_id: str):
            raise ScoresNotFoundError("no score for a9")

    monkeypatch.setattr(scores, "get_scores_store", lambda: Missing())
    with pytest.raises(ToolError, match="no score for a9"):
        await scores.get_application_score("a9")


def _registered(profile: str) -> list:
    class StubMcp:
        def __init__(self) -> None:
            self.registered: list = []

        def tool(self, name=None, description=None, **kwargs):
            self.registered.append((name, description))
            return lambda fn: fn

    stub = StubMcp()
    scores.register_tools(stub, profile)
    return stub.registered


def test_register_all_exposes_everything() -> None:
    registered = _registered("all")
    assert [name for name, _ in registered] == [
        "get_scoring_criteria",
        "save_scoring_criteria",
        "save_application_score",
        "get_application_score",
        "list_top_applications",
        "get_application_resume",
    ]
    assert all(description for _, description in registered)


def test_register_profiles_split_read_write() -> None:
    assert [name for name, _ in _registered("write")] == [
        "get_scoring_criteria",
        "save_application_score",
        "get_application_score",
        "get_application_resume",
    ]
    assert [name for name, _ in _registered("read")] == [
        "get_scoring_criteria",
        "save_scoring_criteria",
        "get_application_score",
        "list_top_applications",
        "get_application_resume",
    ]


def test_register_rejects_unknown_profile() -> None:
    class StubMcp:
        def tool(self, *args, **kwargs):
            raise AssertionError("must not register")

    with pytest.raises(ValueError, match="profile"):
        scores.register_tools(StubMcp(), "bogus")
