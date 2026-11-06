"""ScoresStore against a real (SQLite) database. Run from db-mcp/."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Both MCP services share flat top-level names (config/server/tools/services);
# purge any other suite's bindings so this module resolves its own source.
for _mod in [m for m in list(sys.modules) if m.split(".", 1)[0] in {"config", "server", "tools", "services"}]:
    del sys.modules[_mod]

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from recruitment_db.database import Base
from recruitment_db.models import ApplicationScore, ScoringCriteria
from services.scores import ScoresNotFoundError, ScoresStore


@pytest.fixture
async def store(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/scores.db"
    engine = create_async_engine(url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    s = ScoresStore(url)
    try:
        yield s
    finally:
        await s.aclose()


async def _seed_criteria(store: ScoresStore, job_id: str = "j1", version: int = 2) -> None:
    async with store._session() as session:
        session.add(
            ScoringCriteria(
                job_id=job_id,
                version=version,
                criteria=[{"label": "Go", "max_score": 50}],
                active=True,
                created_by="U1",
            )
        )
        await session.commit()


async def test_get_criteria_returns_active(store: ScoresStore) -> None:
    await _seed_criteria(store)
    result = await store.get_criteria("j1")
    assert result == {"job_id": "j1", "version": 2, "criteria": [{"label": "Go", "max_score": 50}]}


async def test_get_criteria_missing_raises(store: ScoresStore) -> None:
    with pytest.raises(ScoresNotFoundError, match="j9"):
        await store.get_criteria("j9")


async def test_save_criteria_versions_and_deactivates(store: ScoresStore) -> None:
    first = await store.save_criteria(
        job_id="j1",
        criteria=[{"label": "Go", "max_score": 60}, {"label": "Comms", "max_score": 40}],
        created_by="U1",
    )
    assert first["version"] == 1
    second = await store.save_criteria(
        job_id="j1",
        criteria=[{"label": "Go", "max_score": 100}],
        created_by="U1",
    )
    assert second["version"] == 2
    assert await store.get_criteria("j1") == {
        "job_id": "j1",
        "version": 2,
        "criteria": [{"label": "Go", "max_score": 100}],
    }


async def test_save_criteria_versions_are_per_job(store: ScoresStore) -> None:
    await store.save_criteria(job_id="j1", criteria=[{"label": "Go", "max_score": 100}])
    other = await store.save_criteria(job_id="j2", criteria=[{"label": "Go", "max_score": 100}])
    assert other["version"] == 1
    assert (await store.get_criteria("j2"))["version"] == 1


async def test_save_and_get_round_trip(store: ScoresStore) -> None:
    saved = await store.save_score(
        application_id="a1",
        job_id="j1",
        candidate_id="c1",
        total_score=82.5,
        breakdown=[{"label": "Go", "score": 40}],
        criteria_version=2,
        rationale="Strong Go background.",
    )
    assert saved["total_score"] == 82.5
    assert saved["rationale"] == "Strong Go background."
    assert await store.get_score("a1") == saved


async def test_save_overwrites_on_rescore(store: ScoresStore) -> None:
    kwargs = {
        "application_id": "a1",
        "job_id": "j1",
        "candidate_id": "c1",
        "breakdown": [{"label": "Go", "score": 40}],
        "criteria_version": 2,
    }
    await store.save_score(total_score=50.0, **kwargs)
    second = await store.save_score(total_score=90.0, rationale="Re-scored.", **kwargs)
    assert second["total_score"] == 90.0
    assert (await store.get_score("a1"))["total_score"] == 90.0


async def test_get_score_missing_raises(store: ScoresStore) -> None:
    with pytest.raises(ScoresNotFoundError, match="a9"):
        await store.get_score("a9")


async def test_list_top_orders_by_score_desc(store: ScoresStore) -> None:
    for app_id, total in (("a1", 50.0), ("a2", 90.0), ("a3", 70.0)):
        await store.save_score(
            application_id=app_id,
            job_id="j1",
            candidate_id="c1",
            total_score=total,
            breakdown=[{"label": "Go", "score": total}],
            criteria_version=2,
        )
    await store.save_score(
        application_id="b1",
        job_id="j2",
        candidate_id="c9",
        total_score=99.0,
        breakdown=[{"label": "Go", "score": 99}],
        criteria_version=1,
    )
    result = await store.list_top("j1", 2)
    assert result["job_id"] == "j1"
    assert [s["application_id"] for s in result["scores"]] == ["a2", "a3"]
    assert result["scores"][0]["total_score"] == 90.0


async def test_list_top_empty_job(store: ScoresStore) -> None:
    assert await store.list_top("j9", 10) == {"job_id": "j9", "scores": []}


async def test_get_resume_round_trip(store: ScoresStore) -> None:
    from recruitment_db.models import ApplicationResume

    async with store._session() as session:
        session.add(
            ApplicationResume(
                application_id="a1",
                resume_url="https://pub.test/r.pdf",
                file_name="r.pdf",
                file_size=100,
            )
        )
        await session.commit()
    result = await store.get_resume("a1")
    assert result["resume_url"] == "https://pub.test/r.pdf"
    with pytest.raises(ScoresNotFoundError, match="a9"):
        await store.get_resume("a9")
