# hunter8 Claude Code Plugin — Design

**Date:** 2026-07-29
**Status:** Approved design, pending spec review
**Vision goals served:** End Goal 1 (close the loop) directly — the approval gate
moves to where the reasoning is, and the step that has never once completed
becomes the default path. End Goal 4 (worth running daily) by collapsing a
five-command sequence into one, with a preflight that catches the misconfiguration
class that has been silently degrading runs.

## Context

The pipeline works. The loop still does not close.

| status | count |
|---|---:|
| `discovered` (never screened) | 7,022 |
| `screened_out` | 4,639 |
| `filtered_out` (dead regex-era residue) | 738 |
| `scored` | 432 — **25 A, 160 B, 247 C** |
| `screened_in` (queue remaining) | 0 |
| `score_error` / `screen_error` | 1 / 1 |
| `approved` / `skipped` / `snoozed` | **0 / 0 / 0** |

`triage.py` has never recorded a single decision. 432 graded jobs, 25 of them
A-grade, and the status column proves no human has ever adjudicated one through
the tool built for it. Meanwhile the `jobs-to-apply-*.md` reports — which diff
against the previous run, carry corpus statistics, explain *why* adding a Hong
Kong track surfaced the hedge funds, and in one case correct a claim the prior
day's report made — are produced by **no script in this repo**. They are
hand-rolled each morning and gitignored, so nothing accumulates.

That is the gap: the valuable analysis is ad-hoc and disposable, and the step
that would act on it is unused.

Two configuration defects found in the same audit, both symptoms of there being
no preflight anywhere:

- **The screen runs at threshold 25, not the calibrated 65.** `calibrate.py`
  measured 65 as the highest threshold holding 100% A-recall, and the vision
  records it — but `HUNTER8_SCREEN_THRESHOLD` is absent from `.env` and both
  `screen.py`'s default and `.env.example` still say 25. Every screening run
  since calibration used the uncalibrated value.
- **`HUNTER8_SCREEN_MODEL` is absent from `.env`** while `screen.py --model` is
  `required=True`, so the bare `python screen.py` the README prints exits
  immediately.

Cost context for anything that adds Claude calls: lifetime notional spend is
**$57.38 across 308 priced rows**, almost entirely from the pre-`brief.md` era at
$0.659/call. Post-`brief.md` grading runs ~$0.008/job. Billed $0 — subscription
auth.

## Scope and decomposition

The request — "a plugin to use and do analysis with this project" — resolved in
brainstorming to five things: plugin scaffolding, four analyses, a daily
operator, a chat-based approval gate, and agent-driven `apply.py`. That is more
than one spec should carry, and the riskiest piece is unrelated to the analyses.

**The split is at `tracker.py`, a seam the codebase already has.** Everything
upstream of a tracker row reads SQLite and writes a spreadsheet cell. Everything
downstream drives a browser and sends things that cannot be recalled.

- **This spec (Spec 1)** — plugin, four analyses, daily operator, approval gate.
  Ends with approved rows in the tracker. Touches no Playwright.
- **Spec 2, separate cycle** — agent-driven apply: restructure `apply.py` so its
  blocking `input()` HITL defers instead of stalling a chat turn, surface ATS
  routing per row, run real submissions behind an explicit per-run confirm.

Accepted consequence: after Spec 1 ships, `apply.py` is still run by hand. The
loop closes in two steps rather than one.

## Decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| Primary job | Both — the report drives triage. A report you cannot act on is what already exists; a pipeline run without the report is what a shell script does |
| Approval gate | **Confirm in chat, plugin writes rows.** Present each A-grade with its reasoning, user names the approvals, `triage.py --approve <ids>` writes them |
| How Claude reaches the corpus | A tested query CLI (`analyze.py`) with a thin plugin on top |
| Analyses in scope | All four: shortlist + cross-run diff, corpus patterns, pipeline/calibration health, coverage gaps |
| "Last run" definition | Derived from a `MAX(scored_at)` snapshot taken before the run. **No `runs` table** |
| New persistent state | Exactly one table: `grade_history` |
| Apply step | Out of scope (Spec 2) |

**Why a query CLI over raw `sqlite3` in a skill document.** Every other piece of
logic in this repo is tested Python — 122 tests in 0.75s. SQL embedded in a skill
document would be the only untested logic in the pipeline, and it would drift
silently. Output is also bounded by construction rather than by an agent
remembering `LIMIT`: the corpus is ~104 MB over 12,833 rows, and `raw_text` alone
runs to 6,000 characters per row.

**Why not an MCP server.** It would duplicate `db.py`, add a process to run and
debug, tax every unrelated session with its tool schemas, and the venv is Python
3.9. Deferred until wanting these tools from outside this repo actually happens.

**Where the judgment lives.** The queries are deterministic and belong in tested
code. The narration — "OKX is the story, and unlike Databricks' 33 it is not a
volume artifact" — is judgment, and that is the half worth spending Claude on.
The split follows that line exactly.

## Architecture

```
Layer 1 — analyze.py            read-only, tested, --json on every subcommand
            shortlist / patterns / health / coverage

Layer 2 — existing code, two changes
            triage.py --approve <ids>       non-interactive gate
            db.grade_history                append-only grade log

Layer 3 — plugin/  (in-repo, versioned with the code it drives)
            commands/  morning · triage · health · coverage
            skills/hunter8-corpus/          shared context
            agents/hunter8-analyst.md       narrates --json output
```

The plugin is thin on purpose: commands that know which subcommand to call and
how to read it. No SQL in the plugin, no business logic, nothing to keep in sync
with `db.py`.

## Components

### `analyze.py` (new)

One Click CLI, four read-only subcommands, `--json` on all of them. It never
writes to `hunter8.db`.

| Subcommand | Answers | Key flags |
|---|---|---|
| `shortlist` | The ranked graded queue for a window | `--since-days`, `--grade A,B`, `--new-since <iso>` |
| `patterns` | A/B/C rate per bucket — where you actually score | `--by company\|archetype\|ats\|location\|source` |
| `health` | Queue counts, threshold state, screen↔Claude agreement, cost, error rows | — |
| `coverage` | Per watchlist entry: rows found, newest posting, zero/stale flags | `--stale-days` |

Reuse rather than reimplementation: `coverage` reads `watchlist.yaml` through
`watchlist.load_watchlist()` so an unsupported ATS still raises in one place, and
`health` computes screen↔Claude agreement by passing the `(grade, fit_score)`
pairs already stored on `scored` rows into `calibrate.agreement()`. That function
takes rows and returns recall — **it makes no model calls.** `calibrate.collect()`
is the part that drives the local model, and `health` does not use it.

`health` reports the threshold **in effect** (from `HUNTER8_SCREEN_THRESHOLD`,
falling back to `screen.DEFAULT_THRESHOLD`) alongside the recommendation parsed
from `calibration-report.md`, and flags three conditions: values disagree, report
absent, or report older than `intent.md` (calibration is stale). It never re-runs
calibration itself — that is `calibrate.py`'s job and it costs a full pass of the
local model over the scored corpus.

**`analyze.py` must not call `init_db()`**, because that runs `ALTER TABLE` and
would break the read-only rule. On a database predating the migration the
grade-movement section reports "no history recorded yet" rather than crashing on
a missing `grade_history`.

### `db.py` — `grade_history`

```sql
CREATE TABLE grade_history (
  id        INTEGER PRIMARY KEY,
  job_id    INTEGER NOT NULL,
  grade     TEXT,
  fit_score INTEGER,
  brief_sha TEXT,
  scored_at TEXT NOT NULL
);
```

Appended by `set_score`. This is the only new state in the spec, and it exists
for one reason: `set_score` overwrites `jobs.grade`, so a grade that moved from C
to A is currently unrecoverable — you can read the current value and nothing
else.

**How `brief_sha` reaches the row.** `set_score` gains a `brief_sha: str | None`
keyword parameter, and `score.py` supplies it — `db.py` stays ignorant of what a
brief is. The value is the sha256 `rubric.py` already stamps into `brief.md`, read
back from the cached file rather than recomputed. Under `--full-intent` there is
no brief, so `score.py` records `intent.md`'s own sha instead, because that is
what actually graded the job. Never silently `NULL`: a graded row with no
provenance would make the grade-movement analysis quietly wrong rather than
visibly incomplete.

**`brief_sha` is the load-bearing column.** `rubric.py` already computes
`intent.md`'s sha256 and stamps it into the generated brief. Recording *which
brief produced each grade* turns "what did my `intent.md` edit do to the corpus?"
from narration into a `GROUP BY`, and it stays correct when two edits land the
same day. The 28 July report had to *reason* that "you added a Hong Kong track at
20:49, so every grade after that point applies it" — inferred from wall-clock
timestamps and asserted as prose.

Follows the established migration pattern: one `_MIGRATIONS` entry, applied by
the idempotent `init_db`. Append-only, so it cannot corrupt `jobs`.

### `triage.py` — `--approve <ids>`

A non-interactive path into the same `apply_decision` the prompt loop already
calls, so tracker-writing behaviour keeps exactly one implementation. Reports
per-id outcomes; see Error handling for the failure cases.

### `plugin/` — the plugin

Layout follows the standard: manifest at `plugin/.claude-plugin/plugin.json`
(`name: hunter8`, plus `description` and `version`), components at plugin root,
kebab-case throughout, skills as `skills/<name>/SKILL.md`.

| Component | Purpose |
|---|---|
| `commands/morning.md` | Preflight → pipeline → shortlist → narrate → offer triage |
| `commands/triage.md` | Present graded jobs with reasoning, collect approvals, write rows |
| `commands/health.md` | Pipeline and calibration state, drift called out |
| `commands/coverage.md` | Gaps, plus proposed `watchlist.yaml` additions |
| `skills/hunter8-corpus/SKILL.md` | Shared context: schema, what each `status` means, the cost-asymmetry principle, report conventions, env requirements |
| `agents/hunter8-analyst.md` | Narrates `--json` output into the report |

The subagent is deliberate: a shortlist run returns 160+ rows each carrying
`reasoning`, and that bulk belongs in a subagent's context rather than the main
thread's. It returns the finished report.

**Working-directory assumption.** Commands invoke `python analyze.py` relative to
the current directory rather than `${CLAUDE_PLUGIN_ROOT}/../analyze.py`. This is
a one-user, one-repo tool by Non-Goal, so assuming the repo root is cwd is
acceptable — but preflight verifies `analyze.py` is present and fails with a
clear message rather than a traceback when it is not.

## Data flow

`/hunter8:morning`, in order:

1. **Preflight, before spending anything** — `analyze.py` present in cwd; Ollama
   reachable and model pulled; threshold state; `intent.md` present;
   `TRACKER_PATH` set.
2. Capture `SELECT MAX(scored_at) FROM jobs` as **`T₀`**.
3. `discover.py` → `screen.py --since-days N` → `score.py --limit N --since-days N`
   — the threshold comes from the configured value, which step 1 has already
   reported, so no `--threshold` override is passed
4. `analyze.py shortlist --since-days N --new-since T₀ --json`. The two window
   flags compose on **different columns**: `--since-days` bounds the board's
   posting date (`posted_at`, falling back to `discovered_at`), while `--new-since`
   marks which of those rows were graded by this run (`scored_at`)
5. `hunter8-analyst` narrates → writes `reports/YYYY-MM-DD.md`
6. Main thread surfaces the A-grades and the diff, then offers triage

Capturing `T₀` *before* the pipeline runs is what defines "last run" without any
run-tracking state. Everything with `scored_at > T₀` is this run's output by
construction, and it stays correct if a run is interrupted halfway.

The diff needs three different things, and only one needs new state:

| Question | Source | New state |
|---|---|---|
| What is new since last run? | `scored_at > T₀` | none |
| What did this run cost? | `db.total_cost(since=T₀)` — already exists | none |
| Which grades moved, and why? | `grade_history` + `brief_sha` | one table |

`/hunter8:triage`: `analyze.py shortlist --grade A --json` → present grade,
`fit_score`, `comp_signal`, `reasoning`, `red_flags`, URL → user names the ids →
`triage.py --approve <ids>` → report the Excel rows written.

**The write-path invariant, stated once so it is checkable.** `analyze.py` never
writes. `triage.py` is the only writer to the tracker. `db.set_screen` /
`set_score` / `set_triage` remain the only writers to SQLite. **The plugin never
opens the database** — it shells out. This is what stops four analyses becoming
four places where schema knowledge drifts.

`reports/` is added to `.gitignore`, the same class as the `jobs-to-apply-*.md`
files it supersedes — job and profile data, so the personal-artifact Invariant
applies.

## Error handling

**The plugin surfaces the pipeline's existing failures; it never works around
them.** The existing code fails fast well. The new risk is an agent's instinct to
retry or find another path.

| Failure | Existing behaviour | Plugin must |
|---|---|---|
| Ollama down / model unpulled | `LocalUnavailable`, batch stops | Relay verbatim — the message already names `ollama serve` / `ollama pull`. **Never retry, never fall back to Claude** |
| Claude quota / not logged in / bad model name | `ClaudeUnavailable`, batch stops | Report graded-so-far and remaining `screened_in` so the run resumes with `--limit`. Never loop |
| One job fails to grade | `score_error` row with reason, call still priced | `health` surfaces count and reasons. Never filter error rows out of view |
| Empty result | — | State "nothing in window" explicitly. An empty report must never read as all-clear |

The Ollama prohibition is the one that matters most and is therefore written down
rather than left to judgment: promoting thousands of jobs to the subscription
tier to paper over a missing `brew install` is precisely the invariant violation
the tiered design exists to prevent.

**Preflight distinguishes warnings from stops.** Ollama unreachable is a hard
stop. Threshold disagreeing with the calibrated value is a *warning* that reports
and continues — a deliberate override is legitimate.

**The tracker is an .xlsx the user may have open.** `openpyxl` cannot reliably
write a workbook Excel is holding. `triage.py --approve` reports per-id which
rows landed and which did not — never a silent partial write. Unknown id,
already-approved id, and job-not-in-`scored` are each reported individually, and
re-approving is an idempotent no-op with a message.

**Ambiguous approval input gets a question, never an interpretation.** "Approve
the good ones" is not actionable. Approval is the product; a guessed approval is
the one error that cannot be undone once apply runs.

**If the analyst subagent returns nothing**, fall back to presenting the raw
shortlist table. Never report success with no report.

## Testing

Assert against the `--json` contract, never the prose. Fixtures follow the
existing `tests/test_db.py` pattern — a temp SQLite seeded through
`db.insert_job` / `set_screen` / `set_score`.

**New — `test_analyze.py`**, per subcommand:

- `shortlist` — window filtering, `--new-since`, grade filter, ordering, empty result
- `patterns` — bucket counts, each `--by` dimension, division on an empty bucket
- `health` — queue counts, error rows surfaced, all three threshold-drift conditions, cost
- `coverage` — zero-result firms, stale firms, watchlist entries with no rows

**Changed — `test_db.py`** gains: the `grade_history` migration applies to a
pre-existing database, `set_score` appends a row, `brief_sha` is recorded, and
re-scoring **appends rather than overwrites**.

**Changed — `test_triage.py`** gains: `--approve` with valid ids, unknown id,
already-approved, and empty; plus that it routes through the same
`apply_decision` as the interactive loop, so the two paths cannot diverge.

**What has no test coverage, stated plainly.** The plugin's commands and the
subagent's narration. Prompt behaviour is not unit-testable, so the plan carries
an explicit manual verification step — run `/hunter8:morning` against the live
database and record the output — rather than implying coverage that does not
exist.

The 122 existing tests must stay green. `set_score` is a hot path, so
`test_score.py` and `test_db.py` are the regression surface.

## Rollout

1. Add `HUNTER8_SCREEN_MODEL=qwen3:30b-a3b` and `HUNTER8_SCREEN_THRESHOLD=65` to
   `.env`; change `screen.py`'s default and `.env.example` from 25 to 65 so the
   calibrated value is the default rather than a flag to remember.
2. `grade_history` migration + `set_score` append, with tests. Ship before
   `analyze.py` so history starts accumulating immediately.
3. `analyze.py` subcommand by subcommand, `shortlist` first — it is what the
   report and triage both need.
4. `triage.py --approve`, with tests.
5. Plugin scaffolding, then commands in the order `triage` → `morning` →
   `health` → `coverage`. `triage` first: it is the step that has never run, and
   it is useful on the existing 25 A-grades before any new discovery happens.
6. Manual verification run; record the output in the plan.

**Step 5 ordering is the point of the whole spec.** The backlog of 25 untriaged
A-grades can be cleared as soon as `/hunter8:triage` exists, independently of the
morning command and the other three analyses.

## Out of scope

- **Agent-driven apply** — Spec 2. Includes restructuring `apply.py`'s blocking
  HITL, per-row ATS routing surfaced ahead of a run, and the per-run submit
  confirm.
- **Auditing the 738 `filtered_out` rows.** Dead residue from the deleted regex
  filter; nothing reads them. The vision still lists it as a planned detour.
- **Wrapping `analyze.py` in an MCP server.** Revisit only if these tools are
  wanted from sessions outside this repo.
- **Resume tailoring per job.** A Non-Goal, and unchanged by this spec.
