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
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod

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


def collect_patterns(conn: sqlite3.Connection, *, by: str) -> dict:
    """Grade rates per bucket — which companies, archetypes, boards and
    locations actually convert, rather than which produce the most rows."""
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
                        "ab_rate": (a + b) / n if n else 0.0})
    buckets.sort(key=lambda x: (-x["a_rate"], -x["n"], x["key"]))
    return {"by": by, "total": sum(x["n"] for x in buckets), "buckets": buckets}


def _render_patterns(p: dict) -> str:
    if not p["total"]:
        return "No graded jobs to analyse."
    lines = [f"Grade rates by {p['by']} ({p['total']} graded):",
             f"  {'key':<34} {'n':>4} {'A':>3} {'B':>3} {'C':>3} {'A%':>6} {'AB%':>6}"]
    for b in p["buckets"]:
        lines.append(f"  {b['key'][:34]:<34} {b['n']:>4} {b['a']:>3} {b['b']:>3} "
                     f"{b['c']:>3} {b['a_rate']:>5.0%} {b['ab_rate']:>5.0%}")
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
@_json_option
def patterns(db_path: Path | None, by: str, as_json: bool) -> None:
    """Grade rates per bucket."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    _emit(collect_patterns(conn, by=by), as_json, _render_patterns)


if __name__ == "__main__":
    main()
