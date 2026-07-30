# analyze.py
"""Read-only reporting over hunter8.db.

Every query the plugin needs lives here as tested Python with a --json contract,
rather than as SQL in a prompt. Output is bounded by construction: the corpus is
~104 MB over ~13k rows and raw_text alone runs to 6k characters a row.

This module NEVER writes. It skips db's schema-migration step, since that step
applies pending column changes — so a database predating a migration degrades
with a flag here rather than being silently upgraded or crashing.
"""
from __future__ import annotations

import json as jsonlib
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

import calibrate
import db as dbmod
import screen as screenmod

load_dotenv()

_JOB_FIELDS = ("id", "company", "title", "location", "grade", "fit_score",
               "comp_signal", "reasoning", "red_flags", "url", "posted_at",
               "scored_at")


def cutoff(since_days: int | None) -> str | None:
    """ISO timestamp N days back, or None for no date filter. Mirrors
    screen._cutoff so both tiers mean the same thing by a window."""
    if since_days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()


def _emit(payload: dict, as_json: bool, render) -> None:
    click.echo(jsonlib.dumps(payload, indent=2, default=str)
               if as_json else render(payload))


def collect_shortlist(conn: sqlite3.Connection, *, since_days: int | None = None,
                      new_since: str | None = None,
                      grades: list | None = None) -> dict:
    """The ranked graded queue for a window.

    `since_days` bounds the board's posting date; `new_since` marks which of
    those rows this run graded. Different columns, so they compose."""
    jobs = dbmod.jobs_by_status(conn, "scored", order_by="fit_score DESC",
                                posted_since=cutoff(since_days))
    wanted = {g.strip().upper() for g in grades} if grades else None
    out = []
    for j in jobs:
        if wanted and (j.grade or "").upper() not in wanted:
            continue
        row = {f: getattr(j, f) for f in _JOB_FIELDS}
        row["is_new"] = bool(new_since and (j.scored_at or "") > new_since)
        out.append(row)

    movements: list = []
    unavailable = False
    try:
        movements = dbmod.grade_movements(conn, since=new_since)
    except sqlite3.OperationalError as exc:
        # Only a database predating grade_history may degrade quietly. A locked
        # file, or an SQLite too old for the query's window functions, must
        # surface as itself — reporting either as "no history yet" sends the
        # reader to fix the wrong thing.
        if "no such table" not in str(exc).lower():
            raise
        unavailable = True

    return {
        "count": len(out),
        "window_days": since_days,
        "new_since": new_since,
        "grades": sorted(wanted) if wanted else None,
        "new_count": sum(1 for r in out if r["is_new"]),
        "movements": movements,
        "movements_unavailable": unavailable,
        "jobs": out,
    }


def _render_shortlist(p: dict) -> str:
    if not p["count"]:
        window = f"the last {p['window_days']} days" if p["window_days"] else "the corpus"
        return f"No graded jobs in {window}."
    lines = [f"{p['count']} graded job(s), {p['new_count']} new:"]
    for j in p["jobs"]:
        flag = " *new*" if j["is_new"] else ""
        lines.append(f"  [{j['grade']} {j['fit_score']:>3}] {j['company']} — "
                     f"{j['title']} ({j['location']}){flag}")
        lines.append(f"        {j['url']}")
    if p["movements"]:
        lines.append(f"{len(p['movements'])} grade(s) moved:")
        for m in p["movements"]:
            lines.append(f"  {m['company']} — {m['title']}: "
                         f"{m['from_grade']} → {m['to_grade']}")
    elif p["movements_unavailable"]:
        lines.append("(no grade history recorded yet — run the pipeline once "
                     "after upgrading)")
    return "\n".join(lines)


# Whitelisted so a --by value can never carry SQL into the query.
_DIMENSIONS = {"company": "company", "archetype": "archetype", "ats": "ats",
               "location": "location", "source": "source"}


def collect_patterns(conn: sqlite3.Connection, *, by: str, min_n: int = 3) -> dict:
    """Grade rates per bucket — which companies, archetypes, boards and
    locations actually convert, rather than which produce the most rows.

    Buckets with fewer than `min_n` jobs are marked as low-sample and sort
    below higher-volume buckets, since a rate over a handful of jobs is noise."""
    column = _DIMENSIONS.get(by)
    if column is None:
        raise ValueError(f"by must be one of {sorted(_DIMENSIONS)}, got {by!r}")
    rows = conn.execute(
        f"""SELECT IFNULL(NULLIF({column}, ''), '(unset)') AS k,
                   COUNT(*),
                   SUM(grade='A'), SUM(grade='B'), SUM(grade='C')
            FROM jobs WHERE status='scored' GROUP BY k""").fetchall()
    buckets = []
    for key, n, a, b, c in rows:
        a, b, c = int(a or 0), int(b or 0), int(c or 0)
        buckets.append({"key": key, "n": int(n), "a": a, "b": b, "c": c,
                        "a_rate": a / n if n else 0.0,
                        "ab_rate": (a + b) / n if n else 0.0,
                        "low_sample": int(n) < min_n})
    buckets.sort(key=lambda x: (x["low_sample"], -x["a_rate"], -x["n"], x["key"]))
    return {"by": by, "total": sum(x["n"] for x in buckets), "buckets": buckets,
            "min_n": min_n}


def _render_patterns(p: dict) -> str:
    if not p["total"]:
        return "No graded jobs to analyse."
    lines = [f"Grade rates by {p['by']} ({p['total']} graded):",
             f"  {'key':<34} {'n':>4} {'A':>3} {'B':>3} {'C':>3} {'A%':>6} {'AB%':>6}"]
    for b in p["buckets"]:
        marker = " (low n)" if b["low_sample"] else ""
        lines.append(f"  {b['key'][:34]:<34} {b['n']:>4} {b['a']:>3} {b['b']:>3} "
                     f"{b['c']:>3} {b['a_rate']:>5.0%} {b['ab_rate']:>5.0%}{marker}")
    return "\n".join(lines)


_QUEUE_STATUSES = ("discovered", "screened_in", "screened_out", "scored",
                   "approved", "skipped", "snoozed", "screen_error",
                   "score_error", "filtered_out")
_RECOMMENDED_RE = re.compile(r"Recommended threshold:\s*(\d+)")


def _threshold_state(threshold_in_effect: int, calibration_path: Path,
                     intent_path: Path) -> dict:
    """Compare the threshold actually in force against the calibrated one.

    Three separate failure modes, reported separately: they disagree, the report
    was never generated, or the report predates the profile it was measured
    against."""
    state = {"in_effect": threshold_in_effect, "recommended": None,
             "disagrees": False, "report_missing": False, "stale": False}
    if not calibration_path.exists():
        state["report_missing"] = True
        return state
    match = _RECOMMENDED_RE.search(calibration_path.read_text(encoding="utf-8"))
    if match:
        state["recommended"] = int(match.group(1))
        state["disagrees"] = state["recommended"] != threshold_in_effect
    if intent_path.exists():
        state["stale"] = (os.path.getmtime(calibration_path)
                          < os.path.getmtime(intent_path))
    return state


def collect_health(conn: sqlite3.Connection, *, threshold_in_effect: int,
                   calibration_path: Path, intent_path: Path) -> dict:
    """Pipeline and calibration state: what is queued, what is misconfigured,
    what failed and why, and what it has cost."""
    counts = dict(conn.execute(
        "SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall())
    queue = {s: int(counts.get(s, 0)) for s in _QUEUE_STATUSES}

    errors = []
    for r in conn.execute(
            """SELECT id, company, title, status, screen_reason, reasoning
               FROM jobs WHERE status IN ('screen_error','score_error')
               ORDER BY id""").fetchall():
        job_id, company, title, status, screen_reason, reasoning = r
        # Pick the column belonging to the stage that actually failed. A job only
        # reaches score_error by passing screening first, so it carries a stale
        # screen_reason that would otherwise shadow the real failure.
        reason = reasoning if status == "score_error" else screen_reason
        errors.append({"id": job_id, "company": company, "title": title,
                       "status": status, "reason": reason or ""})

    pairs = [(str(g).upper(), int(f)) for g, f in conn.execute(
        """SELECT grade, fit_score FROM jobs
           WHERE status='scored' AND grade IS NOT NULL
             AND fit_score IS NOT NULL""").fetchall()]
    table = calibrate.agreement(pairs) if pairs else []
    at = next((r for r in table if r["threshold"] == threshold_in_effect), None)
    agreement = {
        "sample": len(pairs),
        "a_recall_at_threshold": at["a_recall"] if at else None,
        "ab_recall_at_threshold": at["ab_recall"] if at else None,
        "promoted_fraction_at_threshold": at["promoted_fraction"] if at else None,
        "highest_threshold_with_full_a_recall":
            calibrate.recommend(table) if table else None,
        "threshold_was_sampled": at is not None,
    }

    total, priced = dbmod.total_cost(conn)
    return {
        "queue": queue,
        "errors": errors,
        "threshold": _threshold_state(threshold_in_effect, calibration_path,
                                      intent_path),
        "agreement": agreement,
        "cost": {"lifetime_usd": total, "priced_rows": priced},
    }


def _render_health(p: dict) -> str:
    lines = ["Queue:"]
    for status, n in p["queue"].items():
        if n:
            lines.append(f"  {status:<14} {n:>6}")
    t = p["threshold"]
    lines.append(f"Threshold in effect: {t['in_effect']}")
    if t["report_missing"]:
        lines.append("  ! no calibration-report.md — run calibrate.py")
    if t["disagrees"]:
        lines.append(f"  ! calibration recommends {t['recommended']}")
    if t["stale"]:
        lines.append("  ! calibration predates intent.md — re-run calibrate.py")
    a = p["agreement"]
    if a["sample"] and a["a_recall_at_threshold"] is not None:
        lines.append(f"Agreement over {a['sample']} graded job(s): "
                     f"A-recall {a['a_recall_at_threshold']:.0%} at the current "
                     f"threshold; 100% A-recall holds to "
                     f"{a['highest_threshold_with_full_a_recall']}")
    elif a["sample"]:
        # calibrate samples every 5, so a threshold like 67 has no row. Say so
        # rather than printing a recall figure for a point never evaluated.
        lines.append(f"Agreement over {a['sample']} graded job(s): threshold "
                     f"{p['threshold']['in_effect']} is not one of the sampled "
                     f"points (calibrate evaluates every 5); 100% A-recall holds "
                     f"to {a['highest_threshold_with_full_a_recall']}")
    if p["errors"]:
        lines.append(f"{len(p['errors'])} error row(s):")
        for e in p["errors"][:10]:
            lines.append(f"  [{e['status']}] {e['company']} — {e['reason'][:60]}")
    c = p["cost"]
    lines.append(f"Cost: ${c['lifetime_usd']:.4f} notional across "
                 f"{c['priced_rows']} priced row(s). Billed $0 — subscription auth.")
    return "\n".join(lines)


_db_option = click.option("--db", "db_path", default=None,
                          envvar="HUNTER8_DB_PATH", type=Path)
_json_option = click.option("--json", "as_json", is_flag=True,
                            help="Emit JSON instead of prose.")


@click.group()
def main() -> None:
    """Read-only reporting over hunter8.db."""


@main.command()
@_db_option
@click.option("--since-days", default=None, type=int,
              help="Only jobs the board posted within the last N days.")
@click.option("--new-since", default=None,
              help="ISO timestamp; mark rows graded after it as new.")
@click.option("--grade", default=None,
              help="Comma-separated grades to keep, e.g. A or A,B.")
@_json_option
def shortlist(db_path: Path | None, since_days: int | None,
              new_since: str | None, grade: str | None, as_json: bool) -> None:
    """The ranked graded queue for a window."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    grades = grade.split(",") if grade else None
    _emit(collect_shortlist(conn, since_days=since_days, new_since=new_since,
                            grades=grades), as_json, _render_shortlist)


@main.command()
@_db_option
@click.option("--by", default="archetype",
              type=click.Choice(sorted(_DIMENSIONS)),
              help="Dimension to bucket by.")
@click.option("--min-n", "min_n", default=3, type=int,
              help="Buckets with fewer jobs than this sort last, as low-sample.")
@_json_option
def patterns(db_path: Path | None, by: str, min_n: int, as_json: bool) -> None:
    """Grade rates per bucket."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    _emit(collect_patterns(conn, by=by, min_n=min_n), as_json, _render_patterns)


@main.command()
@_db_option
@click.option("--threshold", default=None, type=int,
              envvar="HUNTER8_SCREEN_THRESHOLD",
              help="Threshold to report as in force. Defaults to the configured one.")
@click.option("--calibration", "calibration_path", default="calibration-report.md",
              type=Path)
@click.option("--intent", "intent_path", default="intent.md", type=Path)
@_json_option
def health(db_path: Path | None, threshold: int | None, calibration_path: Path,
           intent_path: Path, as_json: bool) -> None:
    """Queue counts, threshold drift, screen-vs-Claude agreement, cost."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    _emit(collect_health(
        conn,
        threshold_in_effect=(threshold if threshold is not None
                             else screenmod.DEFAULT_THRESHOLD),
        calibration_path=calibration_path, intent_path=intent_path),
        as_json, _render_health)


if __name__ == "__main__":
    main()
