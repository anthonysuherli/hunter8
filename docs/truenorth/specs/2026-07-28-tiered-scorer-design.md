# Tiered Scorer — Design

**Date:** 2026-07-28
**Status:** Approved design, pending spec review
**Vision goals served:** End Goal 2 (scoring costs nothing per job) directly;
End Goals 1 and 4 by unblocking the backlog and making a daily run affordable.
Executes Planned Detour 1 and absorbs most of Planned Detour 2.

## Context

Scoring today is one tier: a regex pre-filter, then Claude on whatever survives.
The live database says this is not working.

| status | count |
|---|---:|
| `filtered_out` (regex) | 2,605 |
| `discovered` (never scored) | 242 |
| `scored` | 85 — 8 A, 25 B, 52 C |
| `score_error` | 1 |
| `approved` / `skipped` / `snoozed` | 0 |

Three problems. The regex filter rejects **89%** of everything found and that
kill rate has never been validated — every false negative is a job silently
lost. 242 jobs are stranded from the AI-Gateway 402 era. And the loop has never
closed: 8 A-grade matches sit in the database and no job has ever reached the
apply queue.

Scoring now runs on the Claude Code subscription, which costs no money but
carries ~43k tokens of harness context per invocation. That is affordable for
finalists and wasteful for bulk triage.

## Decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| Regex pre-filter | **Deleted.** The local model replaces it. |
| What the local tier reads | A distilled rubric (~1–2k tokens), not the 36.5k-token `intent.md` |
| Local tier output | `fit_score` 0–100 + one-line reason |
| Promote threshold | Calibrated against the 85 already-Claude-graded jobs, not guessed |
| First run scope | All 2,933 jobs |
| Local runtime | Ollama over HTTP via `httpx` |
| Module layout | Parallel agent modules with a shared interface |

**Why Ollama over MLX:** the venv is Python 3.9 — the constraint that already
ruled out `claude-agent-sdk`. An HTTP call through `httpx` (already a
dependency) needs no new package and no Python-version change. MLX is somewhat
faster on Apple Silicon but must be installed into that 3.9 venv.

**Why a rubric instead of the full profile:** on the target hardware (M5 Pro,
48 GB) a ~3–4k-token prompt runs ~1–3s per job, so a 50-job daily batch takes
about two minutes. Passing all 36.5k tokens costs ~15–30s per job — twenty
minutes daily and an overnight backfill — and a mid-size local model reasons
poorly over that much career nuance anyway.

## Architecture

```
discover.py    →  status=discovered
rubric.py      →  rubric.md              (Claude, once per intent.md change)
screen.py      →  local tier over every discovered job
                    fit_score ≥ threshold → screened_in
                    fit_score <  threshold → screened_out  (reason retained)
                    failure                → screen_error
score.py       →  Claude tier over screened_in only → scored
triage.py      →  unchanged
apply.py       →  unchanged
```

Module layout follows the pattern `claude_agent.py` already established: an
agent object exposing `chat_json(system, user) -> dict`, wrapped by a thin CLI
that selects jobs by status and writes a status back. The two tiers are
therefore swappable and testable by the same mocking approach.

Rejected alternatives: a two-pass function inside `score.py` (concentrates two
models, two prompts, and a threshold in the file that is already the most
tangled), and a `scorers/` package with an abstract base class (an abstraction
over two cases that already share a duck-typed interface).

## Components

### `rubric.py`

Compresses `intent.md` into `rubric.md` with one Claude call. The rubric holds
what a screen needs and drops the evidence bank behind it:

- hard disqualifiers (non-US, internships, C++ HFT core, and similar)
- target archetypes
- positive and negative signals
- comp floor

Caching is keyed on a sha256 of `intent.md` recorded inside `rubric.md`.
Matching hash, reuse the file; changed hash, regenerate.

Regeneration preserves a `<!-- BEGIN human -->` / `<!-- END human -->` block,
reusing the convention `sync_intent.py` already proves. Hand-corrections to the
filter's beliefs survive a resync.

`rubric.md` is **gitignored**. It is `intent.md` in compressed form — personal
data, and the Invariant applies.

### `local_agent.py`

`LocalAgent(model, base_url="http://localhost:11434", timeout)` exposing
`chat_json(system, user) -> dict`. POSTs to `/api/chat` with `stream: false`
and a `format` JSON schema constraining the reply:

```json
{
  "type": "object",
  "properties": {
    "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
    "reason": {"type": "string"}
  },
  "required": ["fit_score", "reason"]
}
```

If the installed Ollama predates JSON-schema support, fall back to
`format: "json"` and rely on the shared parser. Errors mirror the Claude tier:
`LocalError` for a single call, `LocalUnavailable` when the daemon is
unreachable or the model is not pulled.

**Shared-code cleanup:** `_parse_object` — fence stripping plus the
first-`{...}` fallback — currently lives in `claude_agent.py`. It moves to a
small shared module both agents import rather than being copy-pasted.

### `screen.py`

CLI over jobs in a given status (default `discovered`). Builds the prompt from
`rubric.md` plus company, title, location, and `raw_text[:6000]`, then writes
the outcome:

| Outcome | Status | Recorded |
|---|---|---|
| `fit_score >= threshold` | `screened_in` | `fit_score`, `screen_reason`, `screened_at` |
| `fit_score < threshold` | `screened_out` | same — the reason is kept so rejections stay auditable |
| exception | `screen_error` | reason, mirroring `score_error` |

Threshold from `HUNTER8_SCREEN_THRESHOLD`, default **25** — deliberately
generous before calibration, because over-promoting wastes a little compute
while silently dropping the best match is unrecoverable.

Model from `HUNTER8_SCREEN_MODEL`. **The default tag is set during the install
step, not by this spec** — verify what `ollama pull` actually resolves before
writing one in. Target shape is a 14–30B instruct model; a mixture-of-experts
model in that range is preferable on Apple Silicon, giving large-model quality
at small-model speed. Calibration chooses the final model.

### `calibrate.py`

Runs the local screen over the 85 jobs carrying a Claude grade and **does not
mutate status**. For each candidate threshold it reports:

- recall on Claude-A jobs
- recall on Claude-A and Claude-B jobs
- fraction of the corpus promoted (the saving)

Pick the highest threshold holding A-recall at 100%. That number then replaces
the deliberately-unset value in the vision's acceptance criteria. Output goes to
`calibration-report.md`, gitignored — it contains job and profile data.

### `score.py`

Shrinks on one axis and grows on another. `passes_rules()` and its four regex
blocks are deleted, and the module selects `screened_in` instead of
`discovered`. It gains two controls the backfill needs (see Rollout, step 5):

- `--limit N` — cap how many jobs one run grades, so a capped run can stop
  short of exhausting the subscription quota.
- descending `fit_score` order — a capped run spends the quota on the most
  promising jobs rather than on whatever `id` happens to be lowest.

Unchanged: the `Verdict` dataclass, the `ClaudeUnavailable` fail-fast, and
per-job `score_error` handling.

### `db.py`

Adds `fit_score INTEGER`, `screen_reason TEXT`, `screened_at TEXT`. Because
`init_db` only runs `CREATE TABLE IF NOT EXISTS`, existing databases need a
guarded migration: read `PRAGMA table_info(jobs)` and `ALTER TABLE` each missing
column. Idempotent, so it is safe on every startup.

`jobs_by_status` gains optional `order_by` and `limit` arguments to serve
`score.py`'s capped, fit-score-ordered backfill. Existing callers keep today's
behaviour — insertion order, no cap — via defaults.

## Error handling

**Ollama unreachable is a hard stop, never a fallback.** Silently promoting
2,933 jobs to Claude to work around a missing `brew install` would burn a large
share of the subscription quota to paper over a setup problem. `screen.py` exits
with the fix.

**Per-job failures stay soft.** Bad JSON, a timeout, a refusal — the job becomes
`screen_error` with its reason and the run continues. This mirrors `score_error`
and honors the Invariant that failures stay visible.

**A missing rubric triggers one Claude call.** If Claude is unavailable at that
moment, nothing can be screened and the run says so plainly.

## Rollout

1. Install Ollama; pull a candidate model; record the tag that resolves.
2. Generate `rubric.md`; read it and correct it by hand where it misrepresents
   you.
3. Run `calibrate.py` over the 85. Choose the threshold. If A-recall cannot
   reach 100% at any useful threshold, try a larger model before proceeding.
4. Bulk-screen all 2,933 (~1–2 hours unattended).
5. Claude-score the `screened_in` set **incrementally**, highest `fit_score`
   first.
6. Triage; close the loop.

**Risk — step 5 is the quota cliff.** If the threshold promotes 15% of 2,933,
that is ~440 Claude calls at ~43k tokens of harness overhead each: roughly 19M
tokens, which may exhaust the subscription in one sitting. `score.py` therefore
needs a `--limit` and must process in descending `fit_score` order, so a capped
first run grades the most promising jobs and the rest waits for the next window.

**Side benefit.** Step 4 re-scores the 2,605 regex rejections, so the
false-negative rate of the deleted filter falls out of the same run — satisfying
the vision's acceptance criterion on the 89% kill rate without separate work.

## Testing

New: `test_local_agent.py` (mock `httpx`, mirroring how `test_claude_agent.py`
mocks `subprocess`; cover schema-constrained parse, connection-refused →
`LocalUnavailable`, timeout, non-JSON), `test_rubric.py` (hash match reuses,
hash change regenerates, human block survives regeneration),
`test_screen.py` (threshold boundary — a score exactly equal to the threshold
promotes — plus all three status transitions), `test_calibrate.py` (recall math
on a fixture, and confirmation that status is not mutated).

Changed: `test_score.py` loses the five `passes_rules` tests along with the
function, switches its fixtures to `screened_in`, and gains coverage that
`--limit` caps the run and that jobs are graded in descending `fit_score` order.
`test_db.py` gains a test that the migration is idempotent across repeated
`init_db` calls, and that `jobs_by_status` defaults leave existing callers'
behaviour unchanged.

## Out of scope

Feature and UI work toward a "practical, powerful job search engine" — a
separate spec cycle. This spec covers only the scoring tier.
