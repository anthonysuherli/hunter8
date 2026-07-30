# hunter8 Plugin — Manual Verification

Task 12 of `docs/truenorth/plans/2026-07-29-hunter8-plugin.md`.

Plugin commands and subagent narration are prompts, not code, so pytest says nothing
about them. This is the substitute, and the plan marks it not optional. The final
whole-branch review put it plainly: do not merge on unit tests for a feature whose
deliverable is prompts.

**Status: partially complete.** The CLI layer is verified. The four slash commands
are installed but require a fresh Claude Code session to load, so the steps that
depend on them are outstanding.

## Step 1 — Install ✅

```bash
claude plugin marketplace add /Users/anthonysuherli/Projects/hunter8
claude plugin install hunter8@hunter8
```

Both manifests validate (`claude plugin validate .` and `claude plugin validate plugin`).
Installed at user scope, enabled. `claude plugin details hunter8` reports:

```
Skills (5)  coverage, health, hunter8-corpus, morning, triage
Agents (1)  hunter8-analyst
Always-on:  ~283 tok added to every session
```

The marketplace sources the plugin from `./plugin` in this working tree, so edits to
the command files take effect without re-copying.

**Caveat found during install:** plugins load at session start. The commands do not
appear in the session that installed them.

## Step 2 — `health` against the live database ✅ (CLI layer)

`python analyze.py health`:

```
Queue:
  discovered       7022
  screened_out     4639
  scored            432
  screen_error        1
  score_error         1
  filtered_out      738
Threshold in effect: 65
  ! calibration recommends 70
  ! calibration predates intent.md — re-run calibrate.py
Agreement over 347 graded job(s): A-recall 100% at the current threshold;
  100% A-recall holds to 65
2 error row(s):
  [screen_error] Jane Street — ollama timed out after 120s
  [score_error] Bessemer Venture Partners — Gateway returned non-JSON: ...
Cost: $57.3814 notional across 308 priced row(s). Billed $0 — subscription auth.
```

Matches the plan's expectation (~432 scored, ~7,022 discovered, 0 approved). Both
drift flags fire correctly, and they disagree in a useful way: the stored calibration
report recommends 70, while a live recompute over 347 graded jobs says 65. The report
was generated when the corpus was 97 jobs — which is exactly what `stale` is for.

**Action arising:** re-run `calibrate.py`.

## Step 3 — Triage the real backlog ⏳ outstanding

Needs a fresh session for `/hunter8:triage`.

The CLI beneath it is proven, on **copies** of the real database and tracker:

```
approving A-grade ids: [496, 1118]
  ok  Schonfeld — Software Engineer - Fundamental Equities
  ok  Hebbia — Forward Deployed Engineer
re-approving the same ids:
  no-op already approved (id 496)
  no-op already approved (id 1118)
unknown id: no job with id 999999
tracker rows 35 -> 37   (+2, not +4)
db approved count: 2
```

Duplicate id within a single call also behaves: `approve_ids(conn, [id, id])` returns
ok then no-op, and the tracker gains one row.

`python analyze.py shortlist --grade A` lists all 25 A-grades. Two of them carry no
`fit_score` (Hebbia, DRW) because they were graded before the screening tier existed;
they render as `[A   —]`.

## Step 4 — Deliberate breaks

### 4a. Local model unavailable ✅ (CLI layer)

Run against a **copy** of the database, with a model name that is not pulled:

```
$ python screen.py --db <copy> --model definitely-not-a-real-model --limit 1
local_agent.LocalUnavailable: Model 'definitely-not-a-real-model' is not pulled.
Run `ollama pull definitely-not-a-real-model`.
```

The run stops, the message names the fix, and **zero rows were mutated** in the copy —
verified by querying for rows screened after the attempt. No fallback to Claude.

This proves the code-level invariant. What is still unproven is the *command-level*
one: that `/hunter8:morning`'s preflight refuses to offer a run without the local
screen. That is prompt behaviour and needs the live command.

### 4b. Ambiguous approval ⏳ outstanding

Answer `/hunter8:triage`'s approval question with "the good ones" and confirm it asks
again with a concrete list rather than choosing. Purely prompt behaviour; no CLI
equivalent.

`triage.md` was strengthened for this during the run: its ambiguity examples now
include a count-or-superlative ("the top three"), because listing order is the
command's own priority ordering and an agent could otherwise map a count onto it.

## Outstanding

1. Restart Claude Code, confirm `/hunter8:morning`, `/hunter8:triage`,
   `/hunter8:health`, `/hunter8:coverage` all resolve.
2. Step 3 — triage the 25 A-grades, approve two, confirm they land in the real tracker
   with working hyperlinks and that nothing else moved.
3. Step 4a at command level — stop Ollama, run `/hunter8:morning`, confirm the preflight
   stops with the fix and does **not** offer to continue without the screen.
4. Step 4b — the ambiguous-approval re-ask.
5. Re-run `calibrate.py` (arising from step 2).

Record what actually happened against each, including any gap between expected and
actual. A gap is a finding, not a failure.
