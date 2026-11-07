"""Assessment pipeline: URL resolution + stage dispatch (all fakes + sqlite)."""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.harly import HarlyRuntime
from app.integrations.harly.client import HarlyReadError
from app.services import assessment_pipeline as pipeline
from recruitment_db.database import Base
from recruitment_db.models import ApplicationResume, ApplicationScore, ScoringCriteria


class FakeCominty:
    def __init__(self) -> None:
        self.calls: list = []

    async def start_thread(self, message: str, *, name=None):
        self.calls.append((message, name))
        return "thr_1", "SCORED a1 total=80"

    async def aclose(self) -> None:
        pass


class FakeReads:
    def __init__(
        self,
        application: dict,
        files: list,
        stages: list,
        error: Exception | None = None,
        pages: list | None = None,
        candidate: dict | None = None,
        candidate_error: Exception | None = None,
    ):
        self._application = application
        self._files = files
        self._stages = stages
        self._error = error
        self._pages = pages or []
        self._candidate = candidate or {}
        self._candidate_error = candidate_error

    async def get_application(self, application_id: str):
        if self._error:
            raise self._error
        assert application_id == self._application["id"]
        return self._application

    async def list_candidate_files(self, candidate_id: str):
        return self._files

    async def list_job_stages(self, job_id: str):
        return self._stages

    async def get_candidate(self, candidate_id: str):
        if self._candidate_error:
            raise self._candidate_error
        return self._candidate

    async def list_applications(self, *, limit: int = 100, cursor: str | None = None):
        if self._error:
            raise self._error
        idx = 0 if cursor is None else int(cursor)
        page = self._pages[idx] if 0 <= idx < len(self._pages) else []
        nxt = str(idx + 1) if idx + 1 < len(self._pages) else None
        return page, nxt


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
        "scheduler": FakeCominty(),
        "scheduler_agent_id": "sched_1",
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


def _interview_reads(**overrides):
    base = {
        "application": {"id": "a1", "candidateId": "c1", "jobId": "j1", "currentStageId": "s9"},
        "files": [],
        "stages": [{"id": "s9", "kind": "interview", "name": "R1 Interview"}],
        "candidate": {"id": "c1", "email": "cand@test.com"},
    }
    for key in ("application", "files", "stages", "candidate"):
        if key in overrides:
            base[key] = overrides.pop(key)
    return FakeReads(
        base["application"], base["files"], base["stages"], candidate=base["candidate"], **overrides
    )


async def _seed_plan(factory, job_id: str = "j1") -> None:
    from recruitment_db.models import JobInterviewConfig

    async with factory() as session:
        session.add(
            JobInterviewConfig(
                job_id=job_id,
                rounds=[
                    {
                        "name": "R1 Interview",
                        "window": {"start": "2026-11-20", "end": "2026-11-27"},
                        "pool": [{"name": "Asha", "email": "asha@acme.com"}],
                    }
                ],
                updated_by="U1",
            )
        )
        await session.commit()


async def test_stage_change_interview_triggers(factory, monkeypatch) -> None:
    await _seed_plan(factory)
    runtime = _runtime(factory)
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: _interview_reads())
    result = await pipeline.process_stage_change(runtime, {"applicationId": "a1"}, event_id="e9")
    assert result["status"] == "scheduler_triggered"
    assert result["plan"] is True
    assert result["email"] is True
    [(message, name)] = runtime.scheduler.calls
    assert name == "schedule-a1-s9"
    assert "Trigger e9" in message
    assert "R1 Interview (s9)" in message
    assert "cand@test.com" in message
    assert "Asha" in message
    assert runtime.assessment.calls == []


async def test_stage_change_notes_missing_plan_and_email(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    monkeypatch.setattr(
        pipeline,
        "HarlyReads",
        lambda *a, **k: _interview_reads(candidate_error=HarlyReadError("candidate down")),
    )
    result = await pipeline.process_stage_change(runtime, {"applicationId": "a1"}, event_id="e9")
    assert result["status"] == "scheduler_triggered"
    assert result["plan"] is False
    assert result["email"] is False
    [(message, _)] = runtime.scheduler.calls
    assert "none saved" in message
    assert "unknown" in message


async def test_stage_change_trigger_failure_propagates(factory, monkeypatch) -> None:
    runtime = _runtime(factory, scheduler_agent_id="")
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: _interview_reads())
    with pytest.raises(Exception, match="not configured"):
        await pipeline.process_stage_change(runtime, {"applicationId": "a1"}, event_id="e9")


async def test_stage_change_other_kind_ignored(factory, monkeypatch) -> None:
    runtime = _runtime(factory)
    fake_reads = FakeReads(
        {"id": "a1", "candidateId": "c1", "jobId": "j1", "currentStageId": "s2"},
        [],
        [{"id": "s2", "kind": "screening"}],
    )
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: fake_reads)
    result = await pipeline.process_stage_change(runtime, {"applicationId": "a1"}, event_id="e9")
    assert result == {"status": "ignored", "kind": "screening"}
    assert await pipeline.process_stage_change(runtime, {}, event_id="e9") == {
        "status": "ignored",
        "reason": "no application id",
    }
    assert runtime.scheduler.calls == []


async def _seed(factory, *, scores=(), resumes=(), criteria=()) -> None:
    async with factory() as session:
        for app_id, job_id in scores:
            session.add(
                ApplicationScore(
                    application_id=app_id,
                    job_id=job_id,
                    candidate_id="c",
                    total_score=80.0,
                    breakdown=[],
                    criteria_version=1,
                )
            )
        for app_id in resumes:
            session.add(
                ApplicationResume(
                    application_id=app_id,
                    resume_url="https://pub.test/r.pdf",
                    file_name="r.pdf",
                    file_size=10,
                )
            )
        for job_id, version, active in criteria:
            session.add(
                ScoringCriteria(job_id=job_id, version=version, criteria=[], active=active)
            )
        await session.commit()


def _patch_sweep(monkeypatch, pages, process=None):
    monkeypatch.setattr(pipeline, "HarlyReads", lambda *a, **k: FakeReads({}, [], [], pages=pages))
    calls: list = []

    async def fake_process(runtime, app_id: str):
        calls.append(app_id)
        if process is not None:
            return await process(runtime, app_id)
        return {"status": "triggered"}

    monkeypatch.setattr(pipeline, "process_new_application", fake_process)
    return calls


async def test_sweep_triggers_only_unscored(factory, monkeypatch) -> None:
    await _seed(
        factory,
        scores=[("a1", "j1")],
        resumes=["a2"],
        criteria=[("j1", 1, True)],
    )
    pages = [
        [
            {"id": "a1", "jobId": "j1"},
            {"id": "a2", "jobId": "j1"},
            {"id": "a3", "jobId": "j1"},
            {"id": "a4", "jobId": "j2"},
            {"id": None, "jobId": "j1"},
            {"id": "a5"},
        ]
    ]
    calls = _patch_sweep(monkeypatch, pages)
    result = await pipeline.sweep_unscored_applications(_runtime(factory))
    assert result["status"] == "ok"
    assert result["checked"] == 4
    assert result["triggered"] == 1
    assert result["skipped_scored"] == 1
    assert result["skipped_inflight"] == 1
    assert result["skipped_no_criteria"] == 1
    assert result["failed"] == 0
    assert calls == ["a3"]


async def test_sweep_paginates_and_respects_max_pages(factory, monkeypatch) -> None:
    await _seed(factory, criteria=[("j1", 1, True)])
    pages = [[{"id": "a1", "jobId": "j1"}], [{"id": "a2", "jobId": "j1"}]]
    calls = _patch_sweep(monkeypatch, pages)
    result = await pipeline.sweep_unscored_applications(_runtime(factory))
    assert result["triggered"] == 2
    assert calls == ["a1", "a2"]

    pages3 = [[{"id": "a1", "jobId": "j1"}], [{"id": "a2", "jobId": "j1"}], [{"id": "a3", "jobId": "j1"}]]
    calls3 = _patch_sweep(monkeypatch, pages3)
    result = await pipeline.sweep_unscored_applications(_runtime(factory), max_pages=2)
    assert result["triggered"] == 2
    assert calls3 == ["a1", "a2"]


async def test_sweep_isolates_process_failures(factory, monkeypatch) -> None:
    await _seed(factory, criteria=[("j1", 1, True)])
    pages = [[{"id": "a1", "jobId": "j1"}, {"id": "a2", "jobId": "j1"}]]

    async def flaky(runtime, app_id: str):
        if app_id == "a1":
            raise RuntimeError("agent down")
        return {"status": "triggered"}

    calls = _patch_sweep(monkeypatch, pages, process=flaky)
    result = await pipeline.sweep_unscored_applications(_runtime(factory))
    assert result["triggered"] == 1
    assert result["failed"] == 1
    assert calls == ["a1", "a2"]


async def test_sweep_skips_when_unconfigured(factory) -> None:
    result = await pipeline.sweep_unscored_applications(_runtime(factory, assessment_agent_id=""))
    assert result["status"] == "skipped"

    result = await pipeline.sweep_unscored_applications(
        _runtime(factory, harly_base_url="", harly_api_key="")
    )
    assert result == {
        "status": "skipped",
        "reason": "harly not configured",
        "checked": 0,
        "triggered": 0,
        "skipped_scored": 0,
        "skipped_inflight": 0,
        "skipped_no_criteria": 0,
        "failed": 0,
    }


async def test_sweep_harly_list_failure(factory, monkeypatch) -> None:
    monkeypatch.setattr(
        pipeline, "HarlyReads", lambda *a, **k: FakeReads({}, [], [], error=HarlyReadError("down"))
    )
    result = await pipeline.sweep_unscored_applications(_runtime(factory))
    assert result["status"] == "error"
    assert result["reason"] == "harly list failed"


async def test_poll_loop_runs_until_cancelled(factory, monkeypatch) -> None:
    calls: list = []

    async def fake_sweep(runtime):
        calls.append(1)
        return {"status": "ok"}

    monkeypatch.setattr(pipeline, "sweep_unscored_applications", fake_sweep)
    task = asyncio.create_task(pipeline.run_poll_loop(_runtime(factory), interval_s=3600))
    for _ in range(200):
        if calls:
            break
        await asyncio.sleep(0.01)
    assert calls == [1]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_poll_loop_survives_sweep_errors(factory, monkeypatch) -> None:
    calls: list = []

    async def flaky(runtime):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"status": "ok"}

    monkeypatch.setattr(pipeline, "sweep_unscored_applications", flaky)
    task = asyncio.create_task(pipeline.run_poll_loop(_runtime(factory), interval_s=0.01))
    try:
        for _ in range(200):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.01)
        assert len(calls) >= 2
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
