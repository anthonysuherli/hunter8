# tests/test_db.py
import pytest

import db as dbmod
from db import Job


def _legacy_schema_sql():
    """Pre-migration schema without fit_score, screen_reason, screened_at."""
    return """CREATE TABLE jobs (
             id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL,
             company TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
             source TEXT NOT NULL, ats TEXT, posted_at TEXT, raw_text TEXT,
             status TEXT NOT NULL, grade TEXT, reasoning TEXT, archetype TEXT,
             comp_signal TEXT, red_flags TEXT, discovered_at TEXT NOT NULL,
             scored_at TEXT, triaged_at TEXT);"""


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
    conn.executescript(_legacy_schema_sql())
    dbmod.init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"fit_score", "screen_reason", "screened_at"} <= cols


def test_init_db_is_idempotent(tmp_path):
    """init_db must safely handle legacy databases called twice without error."""
    conn = dbmod.connect(tmp_path / "legacy.db")
    conn.executescript(_legacy_schema_sql())
    # First call adds the migration columns via ALTER TABLE
    dbmod.init_db(conn)
    # Second call must not raise "duplicate column name"
    dbmod.init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"fit_score", "screen_reason", "screened_at"} <= cols


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


def test_set_score_persists_cost_and_total_cost_sums_it(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for i, cost in enumerate([0.01, 0.02, None]):
        dbmod.insert_job(conn, dbmod.Job(url=f"https://x/{i}", company="Acme",
                                        title="T", location="NYC",
                                        source="ats:greenhouse", ats="greenhouse"))
        jid = [j for j in dbmod.jobs_by_status(conn, "discovered")
               if j.url == f"https://x/{i}"][0].id
        dbmod.set_score(conn, jid, status="scored", grade="A", reasoning="r",
                        archetype="a", comp_signal="", red_flags="[]", cost_usd=cost)
    total, priced = dbmod.total_cost(conn)
    assert round(total, 4) == 0.03 and priced == 2
    assert dbmod.jobs_by_status(conn, "scored")[0].cost_usd == 0.01


def _job_row(url, posted_at, discovered_at=None):
    return url, posted_at, discovered_at


def test_posted_since_falls_back_to_discovered_at(tmp_path):
    """The clause that required a non-empty posted_at hid all 261 web-search
    rows — the only route to firms with no public ATS — from every dated run."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for url, posted in [("https://x/dated", "2026-07-27T00:00:00+00:00"),
                        ("https://x/null", None),
                        ("https://x/empty", "")]:
        dbmod.insert_job(conn, dbmod.Job(url=url, company="Acme", title="T",
                                         location="NYC", source="tavily", ats=None))
        conn.execute("UPDATE jobs SET posted_at=? WHERE url=?", (posted, url))
    conn.execute("UPDATE jobs SET discovered_at='2026-07-26T00:00:00+00:00'")
    conn.commit()

    got = dbmod.jobs_by_status(conn, "discovered",
                               posted_since="2026-07-21T00:00:00+00:00")
    assert sorted(j.url for j in got) == [
        "https://x/dated", "https://x/empty", "https://x/null"]


def test_posted_since_uses_posted_at_when_present_even_if_recently_discovered(tmp_path):
    """A job published in January but scraped today is still a January posting."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, dbmod.Job(url="https://x/old", company="Acme", title="T",
                                     location="NYC", source="ats:greenhouse",
                                     ats="greenhouse"))
    conn.execute("UPDATE jobs SET posted_at='2026-01-02T00:00:00+00:00', "
                 "discovered_at='2026-07-28T00:00:00+00:00'")
    conn.commit()

    assert dbmod.jobs_by_status(conn, "discovered",
                                posted_since="2026-07-21T00:00:00+00:00") == []
