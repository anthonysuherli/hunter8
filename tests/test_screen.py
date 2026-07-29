# tests/test_screen.py
import pytest

import db as dbmod
import screen
from db import Job
from local_agent import LocalUnavailable


class _FakeAgent:
    def __init__(self, score=None, exc=None):
        self.score, self.exc = score, exc

    def chat_json(self, system, user):
        if self.exc:
            raise self.exc
        return {"fit_score": self.score, "reason": "because"}


def _conn(tmp_path, n=1):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for i in range(n):
        dbmod.insert_job(conn, Job(url=f"https://x/{i}", company="Acme",
                                   title="ML Engineer", location="NYC",
                                   source="ats:greenhouse", ats="greenhouse",
                                   raw_text="build ml systems"))
    return conn


def test_score_above_threshold_is_screened_in(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=80),
                         threshold=25)
    jobs = dbmod.jobs_by_status(conn, "screened_in")
    assert len(jobs) == 1 and jobs[0].fit_score == 80
    assert jobs[0].screen_reason == "because"


def test_score_below_threshold_is_screened_out_with_reason(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=5),
                         threshold=25)
    jobs = dbmod.jobs_by_status(conn, "screened_out")
    assert len(jobs) == 1
    assert jobs[0].screen_reason == "because"   # rejections stay auditable


def test_score_equal_to_threshold_is_promoted(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=25),
                         threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screened_in")) == 1


def test_per_job_failure_marks_screen_error_and_continues(tmp_path):
    conn = _conn(tmp_path, n=2)
    screen.run_screening(conn, rubric_text="r",
                         agent=_FakeAgent(exc=RuntimeError("bad json")),
                         threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screen_error")) == 2


def test_limit_screens_newest_first(tmp_path):
    """A capped run should cover what just came in, not the oldest backlog."""
    conn = _conn(tmp_path, n=0)
    for i, when in enumerate(["2020-01-01T00:00:00", "2026-07-28T00:00:00"]):
        dbmod.insert_job(conn, Job(url=f"https://x/{i}", company="Acme",
                                   title="ML Engineer", location="NYC",
                                   source="ats:greenhouse", ats="greenhouse",
                                   raw_text="build ml systems"))
        conn.execute("UPDATE jobs SET discovered_at=? WHERE url=?",
                     (when, f"https://x/{i}"))
    conn.commit()

    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=80),
                         threshold=25, limit=1)

    assert [j.url for j in dbmod.jobs_by_status(conn, "screened_in")] == ["https://x/1"]
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def _posted(conn, url, posted_at):
    dbmod.insert_job(conn, Job(url=url, company="Acme", title="ML Engineer",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", raw_text="build ml systems"))
    conn.execute("UPDATE jobs SET posted_at=? WHERE url=?", (posted_at, url))
    conn.commit()


def test_since_days_keeps_only_recently_posted(tmp_path):
    conn = _conn(tmp_path, n=0)
    _posted(conn, "https://x/old", "2026-01-01T00:00:00+00:00")
    _posted(conn, "https://x/new", "2026-07-27T00:00:00+00:00")

    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=80),
                         threshold=25, posted_since="2026-07-21T00:00:00+00:00")

    assert [j.url for j in dbmod.jobs_by_status(conn, "screened_in")] == ["https://x/new"]
    assert [j.url for j in dbmod.jobs_by_status(conn, "discovered")] == ["https://x/old"]


def test_since_days_falls_back_to_discovered_at_for_undated_jobs(tmp_path):
    """Web-search hits carry no posted_at. Excluding them outright hid every
    firm with no public ATS — Citadel, Two Sigma, D. E. Shaw, Point72 — from
    every dated run. Fall back to when we found the posting instead."""
    conn = _conn(tmp_path, n=0)
    _posted(conn, "https://x/dated", "2026-07-27T00:00:00+00:00")
    _posted(conn, "https://x/undated", "")

    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=80),
                         threshold=25, posted_since="2026-07-21T00:00:00+00:00")

    assert sorted(j.url for j in dbmod.jobs_by_status(conn, "screened_in")) == [
        "https://x/dated", "https://x/undated"]
    assert dbmod.jobs_by_status(conn, "discovered") == []


def test_since_days_still_excludes_an_undated_job_found_long_ago(tmp_path):
    """The fallback must not become 'undated always passes' — a stale row we
    found months back is not a recent posting."""
    conn = _conn(tmp_path, n=0)
    _posted(conn, "https://x/stale", "")
    conn.execute("UPDATE jobs SET discovered_at='2026-01-05T00:00:00+00:00' "
                 "WHERE url='https://x/stale'")
    conn.commit()

    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=80),
                         threshold=25, posted_since="2026-07-21T00:00:00+00:00")

    assert [j.url for j in dbmod.jobs_by_status(conn, "discovered")] == ["https://x/stale"]


def test_cutoff_none_means_no_date_filter():
    assert screen._cutoff(None) is None
    assert screen._cutoff(7).endswith("+00:00")


def test_unavailable_agent_stops_the_batch(tmp_path):
    conn = _conn(tmp_path, n=3)
    with pytest.raises(LocalUnavailable):
        screen.run_screening(conn, rubric_text="r",
                             agent=_FakeAgent(exc=LocalUnavailable("no ollama")),
                             threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screen_error")) == 0
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 3
