# score.py
from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
from db import Job
from gateway import Gateway

load_dotenv()
log = logging.getLogger(__name__)

_TITLE_INCLUDE = re.compile(
    r"\b("
    r"machine learning|ml|ai|artificial intelligence|applied scientist|"
    r"research engineer|applied research|mle|"
    r"agent|agentic|llm|nlp|deep learning|data scientist"
    r")\b",
    re.I,
)
_TITLE_EXCLUDE = re.compile(
    r"\b(intern|internship|sales|recruiter|marketing|account executive|"
    r"low-latency|hft|c\+\+ core)\b",
    re.I,
)
# US-remote or a US location; reject obviously non-US postings.
_US_LOCATION = re.compile(
    r"\b(remote|united states|usa|us\b|new york|nyc|san francisco|sf\b|"
    r"boston|austin|seattle|chicago|los angeles|philadelphia|washington|"
    r", ?(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|"
    r"MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|"
    r"SD|TN|TX|UT|VT|VA|WA|WV|WI|WY|DC)\b)",
    re.I,
)
_NON_US = re.compile(
    r"\b(london|uk|united kingdom|canada|toronto|india|bangalore|singapore|"
    r"germany|berlin|france|paris|remote - emea|remote \(emea\))\b",
    re.I,
)


@dataclass
class Verdict:
    grade: str
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: list[str]


def passes_rules(job: Job) -> tuple[bool, str]:
    """Cheap deterministic pre-filter. Returns (survives, reason-if-dropped)."""
    title = job.title or ""
    if _TITLE_EXCLUDE.search(title):
        return False, f"title excluded: {title!r}"
    if not _TITLE_INCLUDE.search(title):
        return False, f"title not a target role: {title!r}"
    loc = job.location or ""
    if loc and _NON_US.search(loc) and not _US_LOCATION.search(loc):
        return False, f"location not US: {loc!r}"
    return True, ""


_SYSTEM = (
    "You grade a job posting for a specific candidate. Reply with a JSON object: "
    '{"grade": "A|B|C", "reasoning": str, "archetype": str, "comp_signal": str, '
    '"red_flags": [str]}. Grade A = strong co-primary fit meeting hard constraints; '
    "B = plausible with friction; C = weak. Use ONLY the candidate intent provided."
)


def grade_job(job: Job, *, intent_md: str, gateway: Gateway) -> Verdict:
    user = (
        f"# Candidate intent\n{intent_md}\n\n"
        f"# Job posting\nCompany: {job.company}\nTitle: {job.title}\n"
        f"Location: {job.location}\n\n{job.raw_text[:6000]}"
    )
    data = gateway.chat_json(_SYSTEM, user)
    return Verdict(
        grade=str(data.get("grade", "C")).strip().upper()[:1] or "C",
        reasoning=str(data.get("reasoning", "")),
        archetype=str(data.get("archetype", "")),
        comp_signal=str(data.get("comp_signal", "")),
        red_flags=list(data.get("red_flags", []) or []),
    )


def run_scoring(conn: sqlite3.Connection, *, intent_md: str, gateway: Gateway) -> None:
    """Score every `discovered` job: rules first, then LLM. Updates status to
    filtered_out / scored / score_error."""
    for job in dbmod.jobs_by_status(conn, "discovered"):
        ok, reason = passes_rules(job)
        if not ok:
            dbmod.set_score(conn, job.id, status="filtered_out", grade=None,
                            reasoning=reason, archetype=None, comp_signal=None,
                            red_flags=None)
            continue
        try:
            v = grade_job(job, intent_md=intent_md, gateway=gateway)
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
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
def main(db_path: Path | None, intent_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    key = os.getenv("AI_GATEWAY_API_KEY")
    if not key:
        raise SystemExit("AI_GATEWAY_API_KEY not set.")
    model = os.getenv("HUNTER8_SCORER_MODEL", "anthropic/claude-sonnet-4.5")
    gateway = Gateway(key, model=model)
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    run_scoring(conn, intent_md=intent_path.read_text(), gateway=gateway)
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("scored", "filtered_out", "score_error")}
    click.echo(f"Scoring complete: {counts}")


if __name__ == "__main__":
    main()
