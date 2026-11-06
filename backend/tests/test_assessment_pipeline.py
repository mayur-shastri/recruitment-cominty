"""Assessment pipeline: URL resolution + stage dispatch (all fakes + sqlite)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.harly import HarlyRuntime
from app.integrations.harly.client import HarlyReadError
from app.services import assessment_pipeline as pipeline
from recruitment_db.database import Base
from recruitment_db.models import ApplicationResume


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list = []

    async def start_thread(self, message: str, *, name=None):
        self.calls.append((message, name))
        return "thr_1", "SCORED a1 total=80"

    async def aclose(self) -> None:
        pass


class FakeReads:
    def __init__(self, application: dict, files: list, stages: list, error: Exception | None = None):
        self._application = application
        self._files = files
        self._stages = stages
        self._error = error

    async def get_application(self, application_id: str):
        if self._error:
            raise self._error
        assert application_id == self._application["id"]
        return self._application

    async def list_candidate_files(self, candidate_id: str):
        return self._files

    async def list_job_stages(self, job_id: str):
        return self._stages


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path}/pipe.db",
        connect_args={"check_same_thread": False},
        poolclass=NullPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _runtime(factory, **overrides):
    base = {
        "session_factory": factory,
        "webhook_secrets": ["whsec"],
        "harly_base_url": "https://harly.test",
        "harly_api_key": "key",
        "assessment": FakeCominty(),
        "assessment_agent_id": "agent_1",
        "s3_endpoint": "https://s3.test",
        "s3_bucket": "b",
        "s3_region": "auto",
        "s3_access_key": "k",
        "s3_secret_key": "s",
        "s3_workspace_id": "ws",
        "s3_public_url": "https://pub.test",
    }
    base.update(overrides)
    return HarlyRuntime(**base)


async def _resume_row(factory, application_id: str):
    async with factory() as session:
        return (
            await session.execute(
                select(ApplicationResume).where(ApplicationResume.application_id == application_id)
            )
        ).scalar_one_or_none()


def test_extract_ids() -> None:
    assert pipeline.extract_ids({"applicationId": "a", "candidateId": "c", "jobId": "j"}) == ("a", "c", "j")
    assert pipeline.extract_ids({"id": "a", "application": {"candidateId": "c"}}) == ("a", "c", None)
    assert pipeline.extract_ids({}) == (None, None, None)


async def test_new_application_full_path(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    fake_reads = FakeReads(
        {"id": "a1", "candidateId": "c1", "jobId": "j1"},
        [{"fileName": "resume.pdf", "fileSize": 100, "createdAt": "2026-11-01"}],
        [],
    )
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: fake_reads)
    monkeypatch.setattr(pipeline.resumes, "build_s3_client", lambda *a, **k: object())

    async def fake_find(s3_client, **kwargs):
        assert kwargs["file_name"] == "resume.pdf"
        assert kwargs["prefix"] == "workspaces/ws/resumes/"
        return "workspaces/ws/resumes/x/resume.pdf"

    monkeypatch.setattr(pipeline.resumes, "find_resume_key", fake_find)

    result = await pipeline.process_new_application(runtime, "a1")
    assert result["status"] == "triggered"
    assert result["resume"] == "resolved"
    row = await _resume_row(factory, "a1")
    assert row is not None
    assert row.resume_url == "https://pub.test/workspaces/ws/resumes/x/resume.pdf"
    assert row.file_name == "resume.pdf"
    assert row.file_size == 100
    [(message, name)] = runtime.assessment.calls
    assert message == "Score application a1 for job j1 (candidate c1)."
    assert name == "assess-a1"


async def test_resolution_failure_still_scores(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    fake_reads = FakeReads({"id": "a1", "candidateId": "c1", "jobId": "j1"}, [], [])
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: fake_reads)

    result = await pipeline.process_new_application(runtime, "a1")
    assert result["status"] == "triggered"
    assert result["resume"] == "skipped:no-files"
    assert await _resume_row(factory, "a1") is None
    assert len(runtime.assessment.calls) == 1


async def test_harly_failure_propagates(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    fake_reads = FakeReads({}, [], [], error=HarlyReadError("down"))
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: fake_reads)
    with pytest.raises(HarlyReadError):
        await pipeline.process_new_application(runtime, "a1")
    assert runtime.assessment.calls == []


async def test_stage_change_interview_queued(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    fake_reads = FakeReads(
        {"id": "a1", "candidateId": "c1", "jobId": "j1", "currentStageId": "s9"},
        [],
        [{"id": "s9", "kind": "interview"}],
    )
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: fake_reads)
    result = await pipeline.process_stage_change(runtime, {"applicationId": "a1"})
    assert result["status"] == "scheduler_queued"


async def test_stage_change_other_kind_ignored(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    fake_reads = FakeReads(
        {"id": "a1", "candidateId": "c1", "jobId": "j1", "currentStageId": "s2"},
        [],
        [{"id": "s2", "kind": "screening"}],
    )
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: fake_reads)
    result = await pipeline.process_stage_change(runtime, {"applicationId": "a1"})
    assert result == {"status": "ignored", "kind": "screening"}
    assert await pipeline.process_stage_change(runtime, {}) == {
        "status": "ignored",
        "reason": "no application id",
    }
