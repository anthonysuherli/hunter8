# rubric.py
"""Compress intent.md into the two briefs the pipeline can afford to send.

intent.md is ~36.5k tokens. Sending it per job is what made grading cost
$0.659/call — measured 2026-07-28, of which ~97% was re-sending this one
unchanged document. Both tiers get a distillation instead, cached until
intent.md changes:

  SCREEN  ~1-2k tokens — hard constraints and signals only, for the local model.
  GRADE   ~3-5k tokens — adds the evidence inventory Claude cites when it
          justifies a grade, without the biography and narrative.

Both outputs are gitignored: they are intent.md in compressed form, so they are
personal data under the same invariant.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

HUMAN_BEGIN = "<!-- BEGIN human -->"
HUMAN_END = "<!-- END human -->"
_HASH_PREFIX = "<!-- intent-sha256: "
_HASH_SUFFIX = " -->"

_SYSTEM = (
    "You compress a candidate's full career profile into a compact screening "
    "rubric for an automated job filter. Reply with a JSON object: "
    '{"rubric": str}. The rubric is markdown, under 400 lines, and contains '
    "only what is needed to judge a job posting: hard disqualifiers, target "
    "role archetypes, positive signals, negative signals, and the compensation "
    "floor. Omit biography, evidence, and narrative — the filter cannot use them."
)

_GRADE_SYSTEM = (
    "You compress a candidate's full career profile into a grading brief for a "
    "strong model that must grade one job posting A/B/C and justify it with "
    'specific evidence. Reply with a JSON object: {"brief": str}. Markdown, '
    "under 500 lines, containing: (1) every hard constraint, (2) preferred role "
    "shapes in priority order, (3) an evidence inventory — the shipped systems, "
    "with the metrics and scale that make each one citable, (4) known gaps and "
    "weakest requirements, (5) the compensation floor and location preferences. "
    "Drop biography, career narrative, and anything the grader cannot cite.\n\n"
    "COPY EVERY HARD CONSTRAINT VERBATIM. Work authorization in particular: "
    "reproduce the visa status, what sponsorship the candidate needs, and how to "
    "treat a posting that is silent on it, word for word. A grade that misses a "
    "disqualifier is worse than no grade, and constraints are the one thing that "
    "cannot survive paraphrase."
)


@dataclass(frozen=True)
class Profile:
    """One distillation target: which key the reply carries, what to title the
    file, the system prompt, and terms whose absence means the distillation
    dropped a hard constraint."""
    key: str
    title: str
    system: str
    required: tuple[str, ...] = ()


def _required_terms() -> tuple[str, ...]:
    """Terms the grading brief must still contain after distillation.

    Losing a hard constraint once invalidated every grade in the corpus, so its
    survival is asserted rather than hoped for. The specific terms live in .env
    because they describe the candidate — this repo is public, and a default of
    "work authorization" checks the section survived without publishing which
    status it is."""
    raw = os.getenv("HUNTER8_BRIEF_REQUIRED", "work authorization")
    return tuple(t.strip() for t in raw.split(",") if t.strip())


SCREEN = Profile("rubric", "Screening Rubric", _SYSTEM)
GRADE = Profile("brief", "Grading Brief", _GRADE_SYSTEM, required=_required_terms())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str, begin: str, end: str) -> str:
    start, stop = text.find(begin), text.find(end)
    if start == -1 or stop == -1 or stop < start:
        return ""
    return text[start + len(begin):stop].strip()


def _stored_hash(text: str) -> str:
    line = _extract(text, _HASH_PREFIX, _HASH_SUFFIX)
    return line.strip()


def _render(body: str, human: str, intent_hash: str, title: str) -> str:
    return (
        f"# {title}\n\n"
        f"{_HASH_PREFIX}{intent_hash}{_HASH_SUFFIX}\n\n"
        "> Generated from intent.md by rubric.py and overwritten whenever\n"
        "> intent.md changes. Only the block between the `human` markers is\n"
        "> hand-authored; it is carried through untouched.\n\n"
        f"{HUMAN_BEGIN}\n\n{human}\n{HUMAN_END}\n\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def load_or_build(intent_path: Path, rubric_path: Path, agent,
                  profile: Profile = SCREEN) -> str:
    """Return the distilled text, regenerating only when intent.md has changed.

    `agent` is anything exposing chat_json(system, user) -> dict — in practice
    ClaudeAgent, because distillation is a judgement task worth a good model."""
    intent_text = intent_path.read_text(encoding="utf-8")
    intent_hash = _hash(intent_text)

    human = ""
    if rubric_path.exists():
        existing = rubric_path.read_text(encoding="utf-8")
        if _stored_hash(existing) == intent_hash:
            return existing
        human = _extract(existing, HUMAN_BEGIN, HUMAN_END)

    data = agent.chat_json(profile.system, intent_text)
    body = str(data.get(profile.key) or "").strip()
    if not body:
        raise SystemExit(f"{profile.title} distillation returned nothing. Re-run, "
                         f"or write {rubric_path} by hand.")
    missing = [t for t in profile.required if t.lower() not in body.lower()]
    if missing:
        # Silently grading against a brief that lost a hard constraint is the
        # failure mode that already invalidated one whole corpus. Refuse instead.
        raise SystemExit(
            f"{profile.title} distillation dropped required term(s): "
            f"{', '.join(missing)}. Nothing written — re-run, or write "
            f"{rubric_path} by hand.")
    rubric_path.write_text(_render(body, human, intent_hash, profile.title),
                           encoding="utf-8")
    return rubric_path.read_text(encoding="utf-8")


def provenance_sha(intent_path: Path, brief_path: Path, *,
                   full_intent: bool) -> str:
    """The sha256 of whichever document actually graded a job.

    Under `--full-intent` that is `intent.md` itself; otherwise it is the hash
    already stamped into the cached brief by `_render`, read back rather than
    recomputed so the recorded value is exactly what the grader read.

    Refuses rather than returning None: a graded row with no provenance would
    make the grade-movement analysis quietly wrong instead of visibly
    incomplete."""
    if full_intent:
        return _hash(intent_path.read_text(encoding="utf-8"))
    if not brief_path.exists():
        raise SystemExit(f"{brief_path} does not exist — cannot record which "
                         f"brief graded these jobs. Run score.py once to build it.")
    sha = _stored_hash(brief_path.read_text(encoding="utf-8"))
    if not sha:
        raise SystemExit(
            f"{brief_path} carries no {_HASH_PREFIX.strip()} stamp. Delete it and "
            f"let rubric.py regenerate it, or the grade history cannot say which "
            f"brief produced a grade.")
    return sha
