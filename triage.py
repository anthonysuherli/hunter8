# triage.py
from __future__ import annotations

import logging
import sqlite3
import webbrowser
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
from db import Job
from tracker import append_application

load_dotenv()
log = logging.getLogger(__name__)

_GRADE_PRIORITY = {
    "A": "A — strong fit",
    "B": "B — good fit",
    "C": "C — possible fit",
}


def priority_from_grade(grade: str | None) -> str:
    return _GRADE_PRIORITY.get((grade or "C").upper(), "C — possible fit")


def apply_decision(conn: sqlite3.Connection, job: Job, choice: str,
                   tracker_path: Path) -> None:
    """Apply one triage decision. 'a' approve → tracker row + approved; 's' skip;
    'z' snooze; anything else is a no-op (job stays scored)."""
    if choice == "a":
        append_application(
            tracker_path, company=job.company, role=job.title, city=job.location,
            url=job.url, priority=priority_from_grade(job.grade),
            why_fits=job.reasoning or "",
        )
        dbmod.set_triage(conn, job.id, status="approved")
    elif choice == "s":
        dbmod.set_triage(conn, job.id, status="skipped")
    elif choice == "z":
        dbmod.set_triage(conn, job.id, status="snoozed")


def _print_job(job: Job) -> None:
    print(f"\n{'='*70}")
    print(f"  [{job.grade}] {job.company} — {job.title}")
    print(f"  {job.location}   {job.comp_signal or ''}")
    print(f"  {job.url}")
    print(f"  {(job.reasoning or '')[:400]}")
    print("  a → approve · s → skip · z → snooze · o → open · q → quit")


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--tracker", "tracker_path", default=None, envvar="TRACKER_PATH",
              required=True, type=click.Path(exists=True, path_type=Path))
def main(db_path: Path | None, tracker_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    jobs = sorted(dbmod.jobs_by_status(conn, "scored"),
                  key=lambda j: (j.grade or "Z"))
    if not jobs:
        click.echo("No scored jobs to triage.")
        return
    for job in jobs:
        _print_job(job)
        choice = input("  → ").strip().lower()
        if choice == "q":
            break
        if choice == "o":
            webbrowser.open(job.url)
            choice = input("  → ").strip().lower()
            if choice == "q":
                break
        apply_decision(conn, job, choice, tracker_path)
    click.echo("Triage session ended.")


if __name__ == "__main__":
    main()
