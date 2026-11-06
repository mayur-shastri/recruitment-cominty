"""Resume services: file picking and the S3 join."""

from __future__ import annotations

from app.services import resumes


def test_pick_prefers_resume_match() -> None:
    files = [
        {"fileName": "cover.pdf", "createdAt": "2026-11-02"},
        {"fileName": "Mayur_Resume.pdf", "createdAt": "2026-11-01"},
    ]
    assert resumes.pick_resume_file(files)["fileName"] == "Mayur_Resume.pdf"
    assert resumes.pick_resume_file([]) is None


def test_pick_falls_back_to_latest() -> None:
    files = [
        {"fileName": "a.pdf", "createdAt": "2026-11-01"},
        {"fileName": "b.pdf", "createdAt": "2026-11-02"},
    ]
    assert resumes.pick_resume_file(files)["fileName"] == "b.pdf"


class _StubPaginator:
    def __init__(self, pages: list) -> None:
        self._pages = pages
        self.seen: list = []

    def paginate(self, **kwargs):
        self.seen.append(kwargs)
        yield from self._pages


class _StubS3:
    def __init__(self, pages: list) -> None:
        self.paginator = _StubPaginator(pages)

    def get_paginator(self, name: str):
        assert name == "list_objects_v2"
        return self.paginator


def _obj(key: str, size: int, modified: str = "2026-11-01"):
    return {"Key": key, "Size": size, "LastModified": modified}


async def test_find_joins_on_name_and_size() -> None:
    s3 = _StubS3(
        [
            {
                "Contents": [
                    _obj("p/x/resume.pdf", 100),
                    _obj("p/y/resume.pdf", 200),
                    _obj("p/z/other.pdf", 100),
                ]
            }
        ]
    )
    key = await resumes.find_resume_key(s3, bucket="b", prefix="p/", file_name="resume.pdf", file_size=200)
    assert key == "p/y/resume.pdf"
    assert s3.paginator.seen[0]["Bucket"] == "b"


async def test_find_returns_none_without_match() -> None:
    s3 = _StubS3([{"Contents": [_obj("p/x/resume.pdf", 100)]}])
    assert (
        await resumes.find_resume_key(s3, bucket="b", prefix="p/", file_name="resume.pdf", file_size=999)
        is None
    )


async def test_find_latest_wins_ties() -> None:
    s3 = _StubS3(
        [{"Contents": [_obj("p/old/r.pdf", 50, "2026-11-01"), _obj("p/new/r.pdf", 50, "2026-11-03")]}]
    )
    assert (
        await resumes.find_resume_key(s3, bucket="b", prefix="p/", file_name="r.pdf", file_size=50)
        == "p/new/r.pdf"
    )
