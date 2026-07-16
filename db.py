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
  triaged_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
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


def jobs_by_status(conn: sqlite3.Connection, status: str) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status=? ORDER BY id", (status,)
    ).fetchall()
    return [_row_to_job(r) for r in rows]


def set_score(
    conn: sqlite3.Connection, job_id: int, *, status: str, grade: str | None,
    reasoning: str | None, archetype: str | None, comp_signal: str | None,
    red_flags: str | None,
) -> None:
    conn.execute(
        """UPDATE jobs SET status=?, grade=?, reasoning=?, archetype=?,
           comp_signal=?, red_flags=?, scored_at=? WHERE id=?""",
        (status, grade, reasoning, archetype, comp_signal, red_flags, _now(), job_id),
    )
    conn.commit()


def set_triage(conn: sqlite3.Connection, job_id: int, *, status: str) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, triaged_at=? WHERE id=?", (status, _now(), job_id)
    )
    conn.commit()
