---
name: hunter8-corpus
description: Use when reading or reporting on the hunter8 job corpus — running analyze.py, interpreting job statuses, grades or fit scores, or narrating a shortlist. Provides the schema, what each status means, and the rules that govern how this pipeline is allowed to fail.
---

# The hunter8 corpus

A personal job-search pipeline for one user. `hunter8.db` is SQLite, ~104 MB.

## Status lifecycle

`discovered` → `screened_in` | `screened_out` | `screen_error` → `scored` |
`score_error` → `approved` | `skipped` | `snoozed`

- `screened_*` — the local Ollama model's 0–100 `fit_score` against `rubric.md`.
- `scored` — Claude's A/B/C `grade` against `brief.md`, with `reasoning`,
  `archetype`, `comp_signal`, `red_flags`.
- `filtered_out` — dead residue from a deleted regex filter. Nothing reads it.

## The principle that explains the design

**Cost asymmetry.** A false promote costs ~$0.008 of Claude and is caught
downstream. A false reject loses a job silently and permanently. That is why the
screen is deliberately generous, and why noise in the promoted set is preferred
to a tighter filter.

## Rules

- **Never run `analyze.py` expecting it to write.** It is read-only by design.
- **If Ollama is unreachable, stop and report it. Never fall back to Claude** —
  promoting thousands of jobs to the subscription tier is the failure the tiered
  design exists to prevent.
- **Never filter error rows out of a report.** `screen_error` and `score_error`
  carry their reason; surface them.
- **An empty result is stated, never implied.** "No graded jobs in the last 7
  days" — never an empty report that reads as all-clear.
- **Never guess an approval.** Ambiguous input gets a question.
- **Never interpolate `.env` configuration into a shell command.** Each CLI
  loads `.env` itself via `load_dotenv()`, so from a shell `$TRACKER_PATH` and
  friends are always empty — pass nothing and let the CLI read its own config.

## Environment

`HUNTER8_DB_PATH`, `HUNTER8_SCREEN_MODEL` (required by `screen.py`),
`HUNTER8_SCREEN_THRESHOLD` (calibrated: 65), `TRACKER_PATH`, `TAVILY_API_KEY`.

## Commands

Run from the repo root with `.venv/bin/python`:

    analyze.py shortlist --since-days N [--grade A,B] [--new-since ISO] [--json]
    analyze.py patterns --by company|archetype|ats|location|source [--json]
    analyze.py health [--json]
    analyze.py coverage [--stale-days N] [--json]
    triage.py --approve 1,2,3
