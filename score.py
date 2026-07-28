# score.py
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path

import click
from dotenv import load_dotenv

import claude_agent
import db as dbmod
from claude_agent import ClaudeAgent, ClaudeUnavailable
from db import Job

load_dotenv()
log = logging.getLogger(__name__)


@dataclass
class Verdict:
    grade: str
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: list[str]


_SYSTEM = (
    "You grade a job posting for a specific candidate. Reply with a JSON object: "
    '{"grade": "A|B|C", "reasoning": str, "archetype": str, "comp_signal": str, '
    '"red_flags": [str]}. Grade A = strong co-primary fit meeting hard constraints; '
    "B = plausible with friction; C = weak. Use ONLY the candidate intent provided."
)


def grade_job(job: Job, *, intent_md: str, agent: ClaudeAgent) -> Verdict:
    user = (
        f"# Candidate intent\n{intent_md}\n\n"
        f"# Job posting\nCompany: {job.company}\nTitle: {job.title}\n"
        f"Location: {job.location}\n\n{job.raw_text[:6000]}"
    )
    data = agent.chat_json(_SYSTEM, user)
    return Verdict(
        grade=str(data.get("grade", "C")).strip().upper()[:1] or "C",
        reasoning=str(data.get("reasoning", "")),
        archetype=str(data.get("archetype", "")),
        comp_signal=str(data.get("comp_signal", "")),
        red_flags=list(data.get("red_flags", []) or []),
    )


def run_scoring(conn: sqlite3.Connection, *, intent_md: str, agent: ClaudeAgent,
                limit: int | None = None, posted_since: str | None = None) -> None:
    """Grade screened_in jobs with Claude, best fit first.

    Ordering and `limit` matter: each Claude call carries ~43k tokens of harness
    overhead, so a capped run must spend the quota on the most promising jobs
    rather than on whatever id happens to be lowest."""
    jobs = dbmod.jobs_by_status(conn, "screened_in", order_by="fit_score DESC",
                                limit=limit, posted_since=posted_since)
    for job in jobs:
        try:
            v = grade_job(job, intent_md=intent_md, agent=agent)
        except ClaudeUnavailable:
            raise  # fail-fast: not logged in or out of quota — every job would fail
        except Exception as exc:  # noqa: BLE001 — visible, never a silent default
            log.warning("scoring failed for %s: %s", job.title, exc)
            dbmod.set_score(conn, job.id, status="score_error", grade=None,
                            reasoning=str(exc)[:200], archetype=None,
                            comp_signal=None, red_flags=None)
            continue
        dbmod.set_score(conn, job.id, status="scored", grade=v.grade,
                        reasoning=v.reasoning, archetype=v.archetype,
                        comp_signal=v.comp_signal,
                        red_flags=json.dumps(v.red_flags))


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--limit", default=None, type=int,
              help="Grade at most N jobs, highest fit_score first.")
@click.option("--since-days", default=None, type=int,
              help="Only jobs the board posted within the last N days.")
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
def main(db_path: Path | None, limit: int | None, since_days: int | None,
         intent_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    agent = ClaudeAgent(
        model=os.getenv("HUNTER8_SCORER_MODEL", claude_agent.DEFAULT_MODEL))
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    since = (None if since_days is None else
             (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat())
    run_scoring(conn, intent_md=intent_path.read_text(), agent=agent, limit=limit,
                posted_since=since)
    # screened_in is the remaining queue — the number a capped run left behind.
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("scored", "screened_in", "score_error")}
    click.echo(f"Scoring complete: {counts}")


if __name__ == "__main__":
    main()
