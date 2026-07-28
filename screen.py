# screen.py
"""Local screening tier: grade every discovered job 0-100 against the rubric.

Replaces the deleted regex pre-filter. Cheap enough to run over everything, so
nothing is rejected without a model having read it and left a reason.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
import rubric as rubricmod
from claude_agent import ClaudeAgent
from db import Job
from local_agent import LocalAgent, LocalUnavailable

load_dotenv()
log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 25   # deliberately generous until calibrate.py says otherwise

_SYSTEM = (
    "You screen job postings for one candidate against the rubric below. "
    'Reply with a JSON object: {"fit_score": int 0-100, "reason": str}. '
    "You are a first-pass filter, not the decision. Everything you score highly "
    "is re-read by a stronger model, so a false promote costs a little compute "
    "while a false reject loses the job permanently. When uncertain, score higher. "
    "Use 70-100 when the posting matches a target archetype; 40-69 when it "
    "plausibly fits, or when the posting is too vague to tell; below 20 only when "
    "the posting explicitly and unambiguously states something the rubric "
    "disqualifies. Never infer a disqualifier from information the posting omits. "
    "Judge only against the rubric. Keep reason to one sentence."
)


def _prompt(job: Job, rubric_text: str) -> str:
    return (
        f"# Rubric\n{rubric_text}\n\n"
        f"# Job posting\nCompany: {job.company}\nTitle: {job.title}\n"
        f"Location: {job.location}\n\n{job.raw_text[:6000]}"
    )


def run_screening(conn: sqlite3.Connection, *, rubric_text: str, agent,
                  threshold: int, limit: int | None = None) -> None:
    """Screen `discovered` jobs into screened_in / screened_out / screen_error.

    Newest first, so a capped run covers what just came in rather than whatever
    has been sitting in the backlog longest."""
    for job in dbmod.jobs_by_status(conn, "discovered",
                                    order_by="discovered_at DESC", limit=limit):
        try:
            data = agent.chat_json(_SYSTEM, _prompt(job, rubric_text))
            score = int(data.get("fit_score", 0))
            reason = str(data.get("reason", ""))
        except LocalUnavailable:
            raise  # fail-fast: every remaining job would fail identically
        except Exception as exc:  # noqa: BLE001 — visible, never a silent default
            log.warning("screening failed for %s: %s", job.title, exc)
            dbmod.set_screen(conn, job.id, status="screen_error", fit_score=None,
                             screen_reason=str(exc)[:200])
            continue
        status = "screened_in" if score >= threshold else "screened_out"
        dbmod.set_screen(conn, job.id, status=status, fit_score=score,
                         screen_reason=reason)


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
@click.option("--rubric", "rubric_path", default="rubric.md", type=Path)
@click.option("--threshold", default=None, type=int,
              envvar="HUNTER8_SCREEN_THRESHOLD")
@click.option("--limit", default=None, type=int,
              help="Screen at most N jobs, newest first.")
@click.option("--model", "model", default=None, envvar="HUNTER8_SCREEN_MODEL",
              required=True)
def main(db_path: Path | None, intent_path: Path, rubric_path: Path,
         threshold: int | None, limit: int | None, model: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rubric_text = rubricmod.load_or_build(intent_path, rubric_path, ClaudeAgent())
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    run_screening(conn, rubric_text=rubric_text, agent=LocalAgent(model=model),
                  threshold=threshold if threshold is not None else DEFAULT_THRESHOLD,
                  limit=limit)
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("screened_in", "screened_out", "screen_error")}
    click.echo(f"Screening complete: {counts}")


if __name__ == "__main__":
    main()
