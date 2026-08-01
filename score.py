# score.py
from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

import claude_agent
import db as dbmod
import rubric
from claude_agent import ClaudeAgent, ClaudeUnavailable
from hunter8_core import GradeAssessment, JobPosting, JsonModel

load_dotenv()
log = logging.getLogger(__name__)


_SYSTEM = (
    "You grade a job posting for a specific candidate. Reply with a JSON object: "
    '{"grade": "A|B|C", "reasoning": str, "archetype": str, "comp_signal": str, '
    '"red_flags": [str]}. Grade A = strong co-primary fit meeting hard constraints; '
    "B = plausible with friction; C = weak. Use ONLY the candidate intent provided."
)


def grade_job(posting: JobPosting, *, intent_md: str,
              agent: JsonModel) -> GradeAssessment:
    user = (
        f"# Candidate intent\n{intent_md}\n\n"
        f"# Job posting\nCompany: {posting.company}\nTitle: {posting.title}\n"
        f"Location: {posting.location}\n\n{posting.description[:6000]}"
    )
    return GradeAssessment.from_payload(agent.chat_json(_SYSTEM, user))


def run_scoring(conn: sqlite3.Connection, *, intent_md: str, agent: ClaudeAgent,
                limit: int | None = None, posted_since: str | None = None,
                brief_sha: str) -> None:
    """Grade screened_in jobs with Claude, best fit first.

    Ordering and `limit` matter: every call re-sends `intent_md`, so a capped run
    must spend the budget on the most promising jobs rather than on whatever id
    happens to be lowest."""
    jobs = dbmod.jobs_by_status(conn, "screened_in", order_by="fit_score DESC",
                                limit=limit, posted_since=posted_since)
    for job in jobs:
        try:
            v = grade_job(job.to_posting(), intent_md=intent_md,
                          agent=agent)
        except ClaudeUnavailable:
            raise  # fail-fast: not logged in or out of quota — every job would fail
        except Exception as exc:  # noqa: BLE001 — visible, never a silent default
            log.warning("scoring failed for %s: %s", job.title, exc)
            # A call that failed to parse still spent tokens — price it anyway,
            # or the run total silently understates what the run cost.
            dbmod.set_score(conn, job.id, status="score_error", grade=None,
                            reasoning=str(exc)[:200], archetype=None,
                            comp_signal=None, red_flags=None,
                            cost_usd=agent.last_cost_usd, brief_sha=brief_sha)
            continue
        dbmod.set_score(conn, job.id, status="scored", grade=v.grade,
                        reasoning=v.reasoning, archetype=v.archetype,
                        comp_signal=v.comp_signal,
                        red_flags=json.dumps(v.red_flags),
                        cost_usd=agent.last_cost_usd, brief_sha=brief_sha)


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--limit", default=None, type=int,
              help="Grade at most N jobs, highest fit_score first.")
@click.option("--since-days", default=None, type=int,
              help="Only jobs the board posted within the last N days.")
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
@click.option("--brief", "brief_path", default="brief.md", type=Path,
              help="Cached grading brief distilled from intent.md.")
@click.option("--full-intent", is_flag=True,
              help="Send the whole of intent.md per job. ~7x the cost; use only "
                   "to compare grades against the brief.")
def main(db_path: Path | None, limit: int | None, since_days: int | None,
         intent_path: Path, brief_path: Path, full_intent: bool) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    agent = ClaudeAgent(
        model=os.getenv("HUNTER8_SCORER_MODEL", claude_agent.DEFAULT_MODEL))
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    since = (None if since_days is None else
             (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat())
    # The brief is one distillation call, cached on intent.md's hash, instead of
    # ~36.5k tokens re-sent on every job.
    intent_md = (intent_path.read_text() if full_intent else
                 rubric.load_or_build(intent_path, brief_path, agent,
                                      profile=rubric.GRADE))
    brief_sha = rubric.provenance_sha(intent_path, brief_path,
                                      full_intent=full_intent)
    run_scoring(conn, intent_md=intent_md, agent=agent, limit=limit,
                posted_since=since, brief_sha=brief_sha)
    # screened_in is the remaining queue — the number a capped run left behind.
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("scored", "screened_in", "score_error")}
    click.echo(f"Scoring complete: {counts}")
    lifetime, priced = dbmod.total_cost(conn)
    per_call = agent.total_cost_usd / agent.calls if agent.calls else 0.0
    click.echo(
        f"Cost: this run ${agent.total_cost_usd:.4f} over {agent.calls} call(s) "
        f"(${per_call:.4f}/call); ${lifetime:.4f} across {priced} priced row(s). "
        f"Billed $0 — subscription auth.")


if __name__ == "__main__":
    main()
