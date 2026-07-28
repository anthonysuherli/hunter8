# rubric.py
"""Compress intent.md into a screening rubric the local tier can afford.

intent.md is ~36.5k tokens — too slow to send per job and too nuanced for a
mid-size local model. Claude distils it once into ~1-2k tokens of hard
constraints and signals, cached until intent.md changes.

rubric.md is gitignored: it is intent.md in compressed form, so it is personal
data under the same invariant.
"""
from __future__ import annotations

import hashlib
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


def _render(body: str, human: str, intent_hash: str) -> str:
    return (
        "# Screening Rubric\n\n"
        f"{_HASH_PREFIX}{intent_hash}{_HASH_SUFFIX}\n\n"
        "> Generated from intent.md by rubric.py and overwritten whenever\n"
        "> intent.md changes. Only the block between the `human` markers is\n"
        "> hand-authored; it is carried through untouched.\n\n"
        f"{HUMAN_BEGIN}\n\n{human}\n{HUMAN_END}\n\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def load_or_build(intent_path: Path, rubric_path: Path, agent) -> str:
    """Return the rubric text, regenerating it only when intent.md has changed.

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

    data = agent.chat_json(_SYSTEM, intent_text)
    body = str(data.get("rubric") or "").strip()
    if not body:
        raise SystemExit("Rubric distillation returned nothing. Re-run, or write "
                         f"{rubric_path} by hand.")
    rubric_path.write_text(_render(body, human, intent_hash), encoding="utf-8")
    return rubric_path.read_text(encoding="utf-8")
