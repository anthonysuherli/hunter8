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


def test_unavailable_agent_stops_the_batch(tmp_path):
    conn = _conn(tmp_path, n=3)
    with pytest.raises(LocalUnavailable):
        screen.run_screening(conn, rubric_text="r",
                             agent=_FakeAgent(exc=LocalUnavailable("no ollama")),
                             threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screen_error")) == 0
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 3
