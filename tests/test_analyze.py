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


def test_patterns_reports_grade_rates_per_bucket(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A", company="Acme")
    _scored(conn, url="https://x/2", grade="C", company="Acme")
    _scored(conn, url="https://x/3", grade="A", company="Beta")
    out = analyze.collect_patterns(conn, by="company")
    buckets = {b["key"]: b for b in out["buckets"]}
    assert buckets["Acme"]["n"] == 2 and buckets["Acme"]["a"] == 1
    assert buckets["Acme"]["a_rate"] == 0.5
    assert buckets["Beta"]["a_rate"] == 1.0
    assert out["total"] == 3


def test_patterns_orders_by_a_rate_then_volume(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A", company="Best")
    _scored(conn, url="https://x/2", grade="C", company="Worst")
    _scored(conn, url="https://x/3", grade="C", company="Worst")
    out = analyze.collect_patterns(conn, by="company")
    assert out["buckets"][0]["key"] == "Best"


def test_patterns_rejects_an_unknown_dimension(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        analyze.collect_patterns(conn, by="favourite_colour")


def test_patterns_handles_an_empty_corpus(tmp_path):
    conn = _conn(tmp_path)
    out = analyze.collect_patterns(conn, by="archetype")
    assert out["total"] == 0 and out["buckets"] == []


def test_patterns_demotes_thin_buckets_below_larger_ones(tmp_path):
    """A single lucky A must not outrank a company with a real track record —
    the rate alone put statistical noise at the top of the report."""
    conn = _conn(tmp_path)
    for i in range(4):
        _scored(conn, url=f"https://x/big{i}", grade="A", company="Bulk")
    _scored(conn, url="https://x/big-miss", grade="C", company="Bulk")
    _scored(conn, url="https://x/thin", grade="A", company="Lucky")

    out = analyze.collect_patterns(conn, by="company", min_n=3)
    buckets = {b["key"]: b for b in out["buckets"]}

    assert buckets["Lucky"]["a_rate"] == 1.0        # still the higher rate
    assert buckets["Bulk"]["a_rate"] == 0.8
    assert out["buckets"][0]["key"] == "Bulk"       # but volume wins the top slot
    assert buckets["Lucky"]["low_sample"] is True
    assert buckets["Bulk"]["low_sample"] is False
    assert out["min_n"] == 3


def test_patterns_respects_min_n_parameter(tmp_path):
    """With min_n=1, a single job is not marked low-sample and can rank by rate."""
    conn = _conn(tmp_path)
    for i in range(4):
        _scored(conn, url=f"https://x/big{i}", grade="A", company="Bulk")
    _scored(conn, url="https://x/big-miss", grade="C", company="Bulk")
    _scored(conn, url="https://x/thin", grade="A", company="Lucky")

    out = analyze.collect_patterns(conn, by="company", min_n=1)
    buckets = {b["key"]: b for b in out["buckets"]}

    assert buckets["Lucky"]["low_sample"] is False
    assert buckets["Bulk"]["low_sample"] is False
    assert out["buckets"][0]["key"] == "Lucky"      # now rate alone determines order
    assert out["min_n"] == 1


def test_patterns_tiebreaks_by_volume_within_same_rate_tier(tmp_path):
    """Two buckets with the same A-rate and different sizes; larger sorts first.
    Both must clear min_n so we're testing the -n term, not the low_sample flag."""
    conn = _conn(tmp_path)
    # Small bucket with perfect rate
    for i in range(3):
        _scored(conn, url=f"https://x/small{i}", grade="A", company="Small")
    # Larger bucket with same rate
    for i in range(6):
        _scored(conn, url=f"https://x/large{i}", grade="A", company="Large")

    out = analyze.collect_patterns(conn, by="company", min_n=3)
    buckets = {b["key"]: b for b in out["buckets"]}

    assert buckets["Small"]["a_rate"] == buckets["Large"]["a_rate"] == 1.0
    assert buckets["Small"]["low_sample"] is False
    assert buckets["Large"]["low_sample"] is False
    assert out["buckets"][0]["key"] == "Large"      # larger volume wins the tiebreak


_STATUSES = ("discovered", "screened_in", "screened_out", "scored",
             "screen_error", "score_error", "approved", "skipped", "snoozed")


def test_health_counts_every_queue_status(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A")
    dbmod.insert_job(conn, Job(url="https://x/2", company="Acme", title="T",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "missing.md",
                                 intent_path=tmp_path / "intent.md")
    assert out["queue"]["scored"] == 1
    assert out["queue"]["discovered"] == 1
    assert set(out["queue"]) >= set(_STATUSES)


def test_health_flags_a_threshold_that_disagrees_with_calibration(tmp_path):
    conn = _conn(tmp_path)
    report = tmp_path / "calibration-report.md"
    report.write_text("**Recommended threshold: 65** — keeps 100% of Claude-A\n",
                      encoding="utf-8")
    intent = tmp_path / "intent.md"
    intent.write_text("x", encoding="utf-8")
    out = analyze.collect_health(conn, threshold_in_effect=25,
                                 calibration_path=report, intent_path=intent)
    assert out["threshold"]["in_effect"] == 25
    assert out["threshold"]["recommended"] == 65
    assert out["threshold"]["disagrees"] is True


def test_health_reports_a_missing_calibration_report(tmp_path):
    conn = _conn(tmp_path)
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "nope.md",
                                 intent_path=tmp_path / "intent.md")
    assert out["threshold"]["recommended"] is None
    assert out["threshold"]["report_missing"] is True


def test_health_flags_calibration_older_than_intent(tmp_path):
    import os
    import time
    conn = _conn(tmp_path)
    report = tmp_path / "calibration-report.md"
    report.write_text("**Recommended threshold: 65**\n", encoding="utf-8")
    intent = tmp_path / "intent.md"
    intent.write_text("x", encoding="utf-8")
    now = time.time()
    os.utime(report, (now - 600, now - 600))
    os.utime(intent, (now, now))
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=report, intent_path=intent)
    assert out["threshold"]["stale"] is True


def test_health_surfaces_error_rows_with_reasons(tmp_path):
    conn = _conn(tmp_path)
    dbmod.insert_job(conn, Job(url="https://x/e", company="Acme", title="T",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screen_error", fit_score=None,
                     screen_reason="ollama exploded")
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "n.md",
                                 intent_path=tmp_path / "i.md")
    assert out["errors"][0]["reason"] == "ollama exploded"


def test_health_reports_agreement_without_calling_a_model(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A", fit_score=90)
    _scored(conn, url="https://x/c", grade="C", fit_score=10)
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "n.md",
                                 intent_path=tmp_path / "i.md")
    assert out["agreement"]["sample"] == 2
    assert out["agreement"]["a_recall_at_threshold"] == 1.0


def test_health_does_not_crash_on_a_threshold_calibrate_never_sampled(tmp_path):
    """calibrate.agreement only produces rows every 5, so a threshold like 67 has
    no row and every *_at_threshold value is None. The renderer used to format
    None with :.0% and die."""
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A", fit_score=90)
    out = analyze.collect_health(conn, threshold_in_effect=67,
                                 calibration_path=tmp_path / "none.md",
                                 intent_path=tmp_path / "none.md")
    assert out["agreement"]["sample"] == 1
    assert out["agreement"]["a_recall_at_threshold"] is None
    assert out["agreement"]["threshold_was_sampled"] is False
    rendered = analyze._render_health(out)          # must not raise
    assert "not one of the sampled points" in rendered


def test_health_reports_agreement_normally_at_a_sampled_threshold(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A", fit_score=90)
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "none.md",
                                 intent_path=tmp_path / "none.md")
    assert out["agreement"]["threshold_was_sampled"] is True
    assert "A-recall" in analyze._render_health(out)


def test_health_shows_the_score_failure_not_the_stale_screen_reason(tmp_path):
    """A job only reaches score_error by passing screening first, so it keeps a
    screen_reason from that pass. Picking the reason by truthiness surfaced the
    old screening rationale instead of what actually went wrong."""
    conn = _conn(tmp_path)
    dbmod.insert_job(conn, Job(url="https://x/e", company="Acme", title="T",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=80,
                     screen_reason="strong match on agentic AI")
    dbmod.set_score(conn, job.id, status="score_error", grade=None,
                    reasoning="claude returned non-JSON", archetype=None,
                    comp_signal=None, red_flags=None)

    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "n.md",
                                 intent_path=tmp_path / "i.md")

    assert len(out["errors"]) == 1
    assert out["errors"][0]["reason"] == "claude returned non-JSON"


def test_health_queue_reports_every_status_including_empty_ones(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A")
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "n.md",
                                 intent_path=tmp_path / "i.md")
    assert out["queue"]["scored"] == 1
    assert out["queue"]["approved"] == 0          # present, not missing
    assert set(out["queue"]) == set(analyze._QUEUE_STATUSES)
