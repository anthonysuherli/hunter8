from dataclasses import FrozenInstanceError, replace

import pytest

import db as dbmod
from hunter8_core import JobPosting, SourceConfig


def _posting(url: str = "https://x/1") -> JobPosting:
    return JobPosting(
        url=url,
        company="Acme",
        title="AI Engineer",
        location="New York, NY",
        source="ats:greenhouse",
        ats="greenhouse",
        posted_at="2026-08-01T00:00:00+00:00",
        description="Build agent systems.",
    )


def test_job_posting_is_immutable():
    posting = _posting()
    with pytest.raises(FrozenInstanceError):
        posting.title = "Changed"


def test_source_config_requires_explicit_values():
    with pytest.raises(ValueError, match="ats, board, and company"):
        SourceConfig(ats="", board="acme", company="Acme")


def test_insert_posting_round_trips_through_local_job(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)

    assert dbmod.insert_posting(conn, _posting()) is True
    stored = dbmod.jobs_by_status(conn, "discovered")[0]

    assert stored.raw_text == "Build agent systems."
    assert stored.to_posting() == replace(
        _posting(), fetched_at=stored.discovered_at
    )


def test_insert_job_remains_a_compatibility_wrapper(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    job = dbmod.Job(
        url="https://x/legacy",
        company="Acme",
        title="ML Engineer",
        location="Remote US",
        source="ats:lever",
        ats="lever",
        raw_text="Legacy caller.",
    )

    assert dbmod.insert_job(conn, job) is True
    assert dbmod.insert_job(conn, job) is False
