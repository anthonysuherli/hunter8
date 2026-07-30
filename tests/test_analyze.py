# tests/test_analyze.py
import json
import sqlite3
from datetime import datetime, timezone
from unittest import mock

import pytest
from click.testing import CliRunner

import analyze
import db as dbmod
from db import Job


def _conn(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    return conn


def _scored(conn, *, url, grade, fit_score=80, company="Acme",
            posted_at=None, brief_sha="sha"):
    dbmod.insert_job(conn, Job(url=url, company=company, title="AI Engineer",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", posted_at=posted_at,
                               raw_text="d"))
    job = [j for j in dbmod.jobs_by_status(conn, "discovered") if j.url == url][0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=fit_score,
                     screen_reason="ok")
    dbmod.set_score(conn, job.id, status="scored", grade=grade, reasoning="why",
                    archetype="lab", comp_signal="$200k", red_flags="[]",
                    brief_sha=brief_sha)
    return job.id


def test_shortlist_ranks_by_fit_score_descending(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/lo", grade="B", fit_score=60)
    _scored(conn, url="https://x/hi", grade="A", fit_score=95)
    out = analyze.collect_shortlist(conn)
    assert out["count"] == 2
    assert [j["fit_score"] for j in out["jobs"]] == [95, 60]


def test_shortlist_filters_by_grade(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A")
    _scored(conn, url="https://x/c", grade="C")
    out = analyze.collect_shortlist(conn, grades=["A"])
    assert out["count"] == 1 and out["jobs"][0]["grade"] == "A"


def test_shortlist_marks_rows_graded_since_the_cutoff(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/old", grade="B")
    boundary = conn.execute("SELECT MAX(scored_at) FROM jobs").fetchone()[0]
    _scored(conn, url="https://x/new", grade="A")

    out = analyze.collect_shortlist(conn, new_since=boundary)
    by_url = {j["url"]: j for j in out["jobs"]}
    assert by_url["https://x/new"]["is_new"] is True
    assert by_url["https://x/old"]["is_new"] is False
    assert out["new_count"] == 1


def test_shortlist_reports_an_empty_window_explicitly(tmp_path):
    conn = _conn(tmp_path)
    out = analyze.collect_shortlist(conn, since_days=7)
    assert out["count"] == 0 and out["jobs"] == []


def test_shortlist_includes_grade_movements(tmp_path):
    conn = _conn(tmp_path)
    job_id = _scored(conn, url="https://x/m", grade="C", brief_sha="old")
    dbmod.set_score(conn, job_id, status="scored", grade="A", reasoning="why",
                    archetype="lab", comp_signal="", red_flags="[]",
                    brief_sha="new")
    out = analyze.collect_shortlist(conn)
    assert len(out["movements"]) == 1
    assert out["movements"][0]["to_grade"] == "A"


def test_shortlist_new_since_filters_movements_by_change_time(tmp_path):
    """Task 2's grade_movements(since=...) filter had no test exercising it.
    collect_shortlist is the first real consumer, via new_since — so prove a
    movement before the cutoff is excluded while one after it is kept."""
    conn = _conn(tmp_path)
    job_old = _scored(conn, url="https://x/old-move", grade="C", brief_sha="old1")
    dbmod.set_score(conn, job_old, status="scored", grade="A", reasoning="why",
                    archetype="lab", comp_signal="", red_flags="[]",
                    brief_sha="new1")

    boundary = datetime.now(timezone.utc).isoformat()

    job_new = _scored(conn, url="https://x/new-move", grade="C", brief_sha="old2")
    dbmod.set_score(conn, job_new, status="scored", grade="B", reasoning="why",
                    archetype="lab", comp_signal="", red_flags="[]",
                    brief_sha="new2")

    out = analyze.collect_shortlist(conn, new_since=boundary)
    to_grades = {m["to_grade"] for m in out["movements"]}
    assert "B" in to_grades
    assert "A" not in to_grades


def test_shortlist_cli_emits_valid_json(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A")
    conn.close()
    result = CliRunner().invoke(
        analyze.main,
        ["shortlist", "--db", str(tmp_path / "h.db"), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["count"] == 1


def test_shortlist_degrades_when_grade_history_is_absent(tmp_path):
    """analyze.py must not call init_db (it runs ALTER TABLE), so it has to
    tolerate a database that predates the table."""
    conn = dbmod.connect(tmp_path / "legacy.db")
    conn.executescript("""CREATE TABLE jobs (
        id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, company TEXT NOT NULL,
        title TEXT NOT NULL, location TEXT, source TEXT NOT NULL, ats TEXT,
        posted_at TEXT, raw_text TEXT, status TEXT NOT NULL, grade TEXT,
        reasoning TEXT, archetype TEXT, comp_signal TEXT, red_flags TEXT,
        discovered_at TEXT NOT NULL, scored_at TEXT, triaged_at TEXT,
        fit_score INTEGER, screen_reason TEXT, screened_at TEXT, cost_usd REAL);""")
    conn.commit()
    out = analyze.collect_shortlist(conn)
    assert out["movements"] == []
    assert out["movements_unavailable"] is True


def test_shortlist_does_not_swallow_an_unrelated_database_error(tmp_path):
    """Only a missing grade_history table may degrade quietly. A locked database
    reported as 'no history yet' would send the reader to fix the wrong thing."""
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A")
    with mock.patch.object(dbmod, "grade_movements",
                           side_effect=sqlite3.OperationalError("database is locked")):
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            analyze.collect_shortlist(conn)
