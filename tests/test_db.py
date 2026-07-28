# tests/test_db.py
import pytest

import db as dbmod
from db import Job


def _job(url="https://x/1", company="Acme", title="ML Engineer"):
    return dbmod.Job(url=url, company=company, title=title,
                     location="Remote US", source="ats:greenhouse", ats="greenhouse",
                     raw_text="desc")


def test_init_and_insert(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert dbmod.insert_job(conn, _job()) is True


def test_insert_is_deduped_on_url(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert dbmod.insert_job(conn, _job()) is True
    assert dbmod.insert_job(conn, _job()) is False
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def test_set_score_moves_to_scored(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, job.id, status="scored", grade="A",
                    reasoning="great fit", archetype="ai-finance-startup",
                    comp_signal="$180k+", red_flags="")
    scored = dbmod.jobs_by_status(conn, "scored")
    assert len(scored) == 1 and scored[0].grade == "A"


def test_set_triage_records_status(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_triage(conn, job.id, status="approved")
    assert len(dbmod.jobs_by_status(conn, "approved")) == 1


def test_init_db_migrates_legacy_table(tmp_path):
    """A database created before the screen columns existed gains them."""
    conn = dbmod.connect(tmp_path / "legacy.db")
    conn.executescript(
        """CREATE TABLE jobs (
             id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL,
             company TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
             source TEXT NOT NULL, ats TEXT, posted_at TEXT, raw_text TEXT,
             status TEXT NOT NULL, grade TEXT, reasoning TEXT, archetype TEXT,
             comp_signal TEXT, red_flags TEXT, discovered_at TEXT NOT NULL,
             scored_at TEXT, triaged_at TEXT);"""
    )
    dbmod.init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"fit_score", "screen_reason", "screened_at"} <= cols


def test_init_db_is_idempotent(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.init_db(conn)          # must not raise "duplicate column name"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert "fit_score" in cols


def _screened(conn, url, score):
    job = Job(url=url, company="Acme", title="ML Engineer", location="NYC",
              source="ats:greenhouse", ats="greenhouse", raw_text="d")
    dbmod.insert_job(conn, job)
    stored = [j for j in dbmod.jobs_by_status(conn, "discovered") if j.url == url][0]
    dbmod.set_screen(conn, stored.id, status="screened_in", fit_score=score,
                     screen_reason="r")


def test_jobs_by_status_orders_and_limits(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for url, score in [("https://x/1", 40), ("https://x/2", 90), ("https://x/3", 65)]:
        _screened(conn, url, score)

    top = dbmod.jobs_by_status(conn, "screened_in",
                               order_by="fit_score DESC", limit=2)
    assert [j.fit_score for j in top] == [90, 65]


def test_jobs_by_status_defaults_unchanged(tmp_path):
    """Existing callers keep insertion order and no cap."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for url, score in [("https://x/1", 40), ("https://x/2", 90)]:
        _screened(conn, url, score)
    assert [j.url for j in dbmod.jobs_by_status(conn, "screened_in")] == [
        "https://x/1", "https://x/2"]


def test_jobs_by_status_rejects_unknown_order_by(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    with pytest.raises(ValueError):
        dbmod.jobs_by_status(conn, "screened_in", order_by="1; DROP TABLE jobs")
