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
    "fit_score is how well the posting matches the rubric: 0 means it violates "
    "a hard disqualifier, 100 means it hits every target signal. Keep reason to "
    "one sentence. Judge only against the rubric."
)


def _prompt(job: Job, rubric_text: str) -> str:
    return (
        f"# Rubric\n{rubric_text}\n\n"
        f"# Job posting\nCompany: {job.company}\nTitle: {job.title}\n"
        f"Location: {job.location}\n\n{job.raw_text[:6000]}"
    )


def run_screening(conn: sqlite3.Connection, *, rubric_text: str, agent,
                  threshold: int) -> None:
    """Screen every `discovered` job into screened_in / screened_out / screen_error."""
    for job in dbmod.jobs_by_status(conn, "discovered"):
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
@click.option("--model", "model", default=None, envvar="HUNTER8_SCREEN_MODEL",
              required=True)
def main(db_path: Path | None, intent_path: Path, rubric_path: Path,
         threshold: int | None, model: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rubric_text = rubricmod.load_or_build(intent_path, rubric_path, ClaudeAgent())
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    run_screening(conn, rubric_text=rubric_text, agent=LocalAgent(model=model),
                  threshold=threshold if threshold is not None else DEFAULT_THRESHOLD)
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("screened_in", "screened_out", "screen_error")}
    click.echo(f"Screening complete: {counts}")


if __name__ == "__main__":
    main()
