# calibrate.py
"""Pick the screening threshold from data instead of guessing.

85 jobs already carry a Claude grade. Running the local screen over them shows
where the A's and B's land, so the promote threshold can be set to the highest
value that still catches every job Claude called an A.
"""
from __future__ import annotations

import logging
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
import rubric as rubricmod
import screen as screenmod
from claude_agent import ClaudeAgent
from local_agent import LocalAgent

load_dotenv()
log = logging.getLogger(__name__)

_THRESHOLDS = list(range(0, 101, 5))


def collect(conn, *, rubric_text: str, agent) -> list:
    """Screen every already-Claude-graded job. Returns (claude_grade, fit_score)
    pairs. Deliberately does not write to the database — calibration must not
    disturb the corpus it is measuring."""
    rows = []
    for job in dbmod.jobs_by_status(conn, "scored"):
        if not job.grade:
            continue
        data = agent.chat_json(screenmod._SYSTEM,
                               screenmod._prompt(job.to_posting(), rubric_text))
        rows.append((job.grade.upper(), int(data.get("fit_score", 0))))
    return rows


def agreement(rows: list) -> list:
    """For each candidate threshold, how much of Claude's judgement survives."""
    a_total = sum(1 for g, _ in rows if g == "A")
    ab_total = sum(1 for g, _ in rows if g in ("A", "B"))
    out = []
    for t in _THRESHOLDS:
        kept = [(g, s) for g, s in rows if s >= t]
        out.append({
            "threshold": t,
            "a_recall": (sum(1 for g, _ in kept if g == "A") / a_total
                         if a_total else 1.0),
            "ab_recall": (sum(1 for g, _ in kept if g in ("A", "B")) / ab_total
                          if ab_total else 1.0),
            "promoted_fraction": len(kept) / len(rows) if rows else 0.0,
        })
    return out


def recommend(table: list) -> int:
    """The highest threshold that still keeps every Claude-A job."""
    full = [r for r in table if r["a_recall"] == 1.0]
    return max(r["threshold"] for r in full) if full else 0


def render(table: list, rows: list) -> str:
    lines = [
        "# Calibration report",
        "",
        f"Sample: {len(rows)} Claude-graded jobs "
        f"({sum(1 for g, _ in rows if g == 'A')} A, "
        f"{sum(1 for g, _ in rows if g == 'B')} B, "
        f"{sum(1 for g, _ in rows if g == 'C')} C)",
        "",
        "| threshold | A recall | A+B recall | promoted |",
        "|---:|---:|---:|---:|",
    ]
    for r in table:
        lines.append(
            f"| {r['threshold']} | {r['a_recall']:.0%} | "
            f"{r['ab_recall']:.0%} | {r['promoted_fraction']:.0%} |")
    rec = recommend(table)
    kept = next(r for r in table if r["threshold"] == rec)
    lines += [
        "",
        f"**Recommended threshold: {rec}** — keeps 100% of Claude-A jobs while "
        f"promoting {kept['promoted_fraction']:.0%} of the corpus.",
        "",
        "Set it with `HUNTER8_SCREEN_THRESHOLD` and write the A-recall figure "
        "into the vision's acceptance criteria.",
    ]
    return "\n".join(lines) + "\n"


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
@click.option("--rubric", "rubric_path", default="rubric.md", type=Path)
@click.option("--out", "out_path", default="calibration-report.md", type=Path)
@click.option("--model", "model", default=None, envvar="HUNTER8_SCREEN_MODEL",
              required=True)
def main(db_path: Path | None, intent_path: Path, rubric_path: Path,
         out_path: Path, model: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rubric_text = rubricmod.load_or_build(intent_path, rubric_path, ClaudeAgent())
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    rows = collect(conn, rubric_text=rubric_text, agent=LocalAgent(model=model))
    if not rows:
        raise SystemExit("No Claude-graded jobs to calibrate against.")
    table = agreement(rows)
    out_path.write_text(render(table, rows), encoding="utf-8")
    click.echo(f"Wrote {out_path} — recommended threshold {recommend(table)}.")


if __name__ == "__main__":
    main()
