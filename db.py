# db.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = "hunter8.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY,
  url           TEXT UNIQUE NOT NULL,
  company       TEXT NOT NULL,
  title         TEXT NOT NULL,
  location      TEXT,
  source        TEXT NOT NULL,
  ats           TEXT,
  posted_at     TEXT,
  raw_text      TEXT,
  status        TEXT NOT NULL,
  grade         TEXT,
  reasoning     TEXT,
  archetype     TEXT,
  comp_signal   TEXT,
  red_flags     TEXT,
  discovered_at TEXT NOT NULL,
  scored_at     TEXT,
  triaged_at    TEXT,
  fit_score     INTEGER,
  screen_reason TEXT,
  screened_at   TEXT,
  cost_usd      REAL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS grade_history (
  id        INTEGER PRIMARY KEY,
  job_id    INTEGER NOT NULL,
  grade     TEXT,
  fit_score INTEGER,
  brief_sha TEXT,
  scored_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grade_history_job ON grade_history(job_id);
"""


@dataclass
class Job:
    url: str
    company: str
    title: str
    location: str
    source: str
    ats: str | None = None
    posted_at: str | None = None
    raw_text: str = ""
    id: int | None = None
    status: str = "discovered"
    grade: str | None = None
    reasoning: str | None = None
    archetype: str | None = None
    comp_signal: str | None = None
    red_flags: str | None = None
    discovered_at: str | None = None
    scored_at: str | None = None
    triaged_at: str | None = None
    fit_score: int | None = None
    screen_reason: str | None = None
    screened_at: str | None = None
    cost_usd: float | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


_MIGRATIONS = {
    "fit_score": "INTEGER",
    "screen_reason": "TEXT",
    "screened_at": "TEXT",
    "cost_usd": "REAL",
}


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema, then add any columns a pre-existing database lacks.

    `CREATE TABLE IF NOT EXISTS` will not add columns to a table that already
    exists, so databases created before the screen tier need an explicit ALTER.
    Idempotent — safe on every startup."""
    conn.executescript(_SCHEMA)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for column, decl in _MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {decl}")
    conn.commit()


def insert_job(conn: sqlite3.Connection, job: Job) -> bool:
    """Insert a discovered job. Returns True if inserted, False if the URL was
    already present (dedup)."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO jobs
           (url, company, title, location, source, ats, posted_at, raw_text,
            status, discovered_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (job.url, job.company, job.title, job.location, job.source, job.ats,
         job.posted_at, job.raw_text, "discovered", _now()),
    )
    conn.commit()
    return cur.rowcount == 1


def _row_to_job(row: sqlite3.Row) -> Job:
    names = {f.name for f in fields(Job)}
    return Job(**{k: row[k] for k in row.keys() if k in names})


# Whitelisted so an order_by string can never carry SQL from a caller.
_ORDER_BY = {"fit_score DESC", "fit_score ASC", "discovered_at DESC"}


def jobs_by_status(conn: sqlite3.Connection, status: str, *,
                   order_by: str | None = None,
                   limit: int | None = None,
                   posted_since: str | None = None) -> list[Job]:
    """Jobs in one status.

    `posted_since` is an ISO timestamp filtering on the board's posting date,
    falling back to discovered_at when the source supplies none.

    That fallback is not cosmetic. Excluding undated rows outright hid every
    web-search hit from every dated run — and since the firms with no public ATS
    (Citadel, Two Sigma, D. E. Shaw, Point72, Goldman) are reachable *only* by
    web search, it hid that entire tier. Measured 2026-07-28: an undated run
    surfaced three A-grades the dated runs never saw, including a $300-400K
    Point72 seat. When we found a posting is a worse recency signal than when it
    was published, but it beats dropping the row."""
    if order_by is not None and order_by not in _ORDER_BY:
        raise ValueError(f"order_by must be one of {sorted(_ORDER_BY)}, got {order_by!r}")
    sql = "SELECT * FROM jobs WHERE status=?"
    params: list = [status]
    if posted_since is not None:
        sql += " AND COALESCE(NULLIF(posted_at, ''), discovered_at) >= ?"
        params.append(posted_since)
    sql += f" ORDER BY {order_by or 'id'}"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_row_to_job(r) for r in conn.execute(sql, params).fetchall()]


def set_screen(conn: sqlite3.Connection, job_id: int, *, status: str,
               fit_score: int | None, screen_reason: str | None) -> None:
    conn.execute(
        """UPDATE jobs SET status=?, fit_score=?, screen_reason=?, screened_at=?
           WHERE id=?""",
        (status, fit_score, screen_reason, _now(), job_id),
    )
    conn.commit()


def set_score(
    conn: sqlite3.Connection, job_id: int, *, status: str, grade: str | None,
    reasoning: str | None, archetype: str | None, comp_signal: str | None,
    red_flags: str | None, cost_usd: float | None = None,
    brief_sha: str | None = None,
) -> None:
    """Write a grade and append an immutable history row.

    `jobs.grade` is overwritten in place, so without the history append a grade
    that moved is unrecoverable. `brief_sha` identifies the distilled document
    that produced this grade, which is what makes "what did my intent.md edit do
    to the corpus?" a query rather than an inference from wall-clock timestamps."""
    now = _now()
    conn.execute(
        """UPDATE jobs SET status=?, grade=?, reasoning=?, archetype=?,
           comp_signal=?, red_flags=?, cost_usd=?, scored_at=? WHERE id=?""",
        (status, grade, reasoning, archetype, comp_signal, red_flags, cost_usd,
         now, job_id),
    )
    fit_score = conn.execute(
        "SELECT fit_score FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    conn.execute(
        """INSERT INTO grade_history (job_id, grade, fit_score, brief_sha, scored_at)
           VALUES (?,?,?,?,?)""",
        (job_id, grade, fit_score, brief_sha, now),
    )
    conn.commit()


def grade_movements(conn: sqlite3.Connection, *,
                    since: str | None = None) -> list[dict]:
    """Jobs whose grade changed between their first and most recent history row.

    Only movement is reported — a job graded B twice is not news. `since` filters
    on the *later* of the two gradings, so a run's report covers what this run
    changed."""
    sql = """
      WITH firsts AS (
        SELECT job_id, grade, brief_sha, scored_at,
               ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY id ASC) AS rn
        FROM grade_history),
      lasts AS (
        SELECT job_id, grade, brief_sha, scored_at,
               ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY id DESC) AS rn
        FROM grade_history)
      SELECT j.id, j.company, j.title,
             f.grade, l.grade, f.brief_sha, l.brief_sha, l.scored_at
      FROM firsts f
      JOIN lasts  l ON l.job_id = f.job_id AND l.rn = 1
      JOIN jobs   j ON j.id     = f.job_id
      WHERE f.rn = 1 AND IFNULL(f.grade,'') != IFNULL(l.grade,'')
    """
    params: list = []
    if since is not None:
        sql += " AND l.scored_at >= ?"
        params.append(since)
    sql += " ORDER BY l.scored_at DESC"
    keys = ("job_id", "company", "title", "from_grade", "to_grade",
            "from_brief_sha", "to_brief_sha", "changed_at")
    return [dict(zip(keys, tuple(r))) for r in conn.execute(sql, params).fetchall()]


def total_cost(conn: sqlite3.Connection, *, since: str | None = None) -> tuple[float, int]:
    """(sum of cost_usd, number of priced rows). `since` filters on scored_at."""
    sql = "SELECT COALESCE(SUM(cost_usd), 0), COUNT(cost_usd) FROM jobs WHERE cost_usd IS NOT NULL"
    params: list = []
    if since is not None:
        sql += " AND scored_at >= ?"
        params.append(since)
    total, n = conn.execute(sql, params).fetchone()
    return float(total), int(n)


def set_triage(conn: sqlite3.Connection, job_id: int, *, status: str) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, triaged_at=? WHERE id=?", (status, _now(), job_id)
    )
    conn.commit()
