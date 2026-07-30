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


def approve_ids(conn: sqlite3.Connection, ids: list, tracker_path: Path) -> list:
    """Approve jobs by id without the prompt loop, reporting each outcome.

    Routes through apply_decision, so the interactive and non-interactive paths
    cannot diverge in what they write. Per-id results rather than one boolean:
    the tracker is an .xlsx the user may have open, so a partial write is a real
    outcome that must be visible rather than inferred.

    Looks up each id with a targeted single-row query rather than re-scanning
    the whole `scored` list (432 rows at ~6k characters of raw_text each — a
    full scan per id materialises tens of megabytes approving 25 jobs). The
    fresh per-id read is still load-bearing, not just an artifact of the old
    scan: if the same id appears twice in one call, the first iteration flips
    it to `approved`, and the second iteration's query must see that write so
    it routes to the "already approved" branch instead of appending a
    duplicate tracker row."""
    results = []
    for job_id in ids:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            results.append({"id": job_id, "ok": False,
                            "detail": f"no job with id {job_id}"})
            continue
        if row["status"] != "scored":
            if row["status"] == "approved":
                detail = f"already approved (id {job_id})"
            else:
                detail = f"id {job_id} is {row['status']}, not scored"
            results.append({"id": job_id, "ok": False, "detail": detail})
            continue
        job = dbmod._row_to_job(row)
        try:
            apply_decision(conn, job, "a", tracker_path)
        except Exception as exc:  # noqa: BLE001 — surfaced per id, never silent
            results.append({"id": job_id, "ok": False,
                            "detail": f"approve failed: {exc}"})
            continue
        results.append({"id": job_id, "ok": True,
                        "detail": f"{job.company} — {job.title}"})
    return results


def _print_job(job: Job) -> None:
    print(f"\n{'='*70}")
    print(f"  [{job.grade}] {job.company} — {job.title}")
    print(f"  {job.location}   {job.comp_signal or ''}")
    print(f"  {job.url}")
    print(f"  {(job.reasoning or '')[:400]}")
    print("  a → approve · s → skip · z → snooze · o → open · q → quit")


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--approve", "approve", default=None,
              help="Comma-separated job ids to approve without the prompt loop.")
@click.option("--tracker", "tracker_path", default=None, envvar="TRACKER_PATH",
              required=True, type=click.Path(exists=True, path_type=Path))
def main(db_path: Path | None, approve: str | None, tracker_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    if approve is not None:
        try:
            ids = [int(x) for x in approve.split(",") if x.strip()]
        except ValueError:
            raise SystemExit(f"--approve takes comma-separated integers, got "
                             f"{approve!r}")
        if not ids:
            click.echo("no ids given, nothing approved")
            return
        for r in approve_ids(conn, ids, tracker_path):
            mark = "✓" if r["ok"] else "✗"
            click.echo(f"  {mark} {r['detail']}")
        return
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
