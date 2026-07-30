---
description: Run the full discovery pipeline, then report and offer triage
argument-hint: "[days, default 7]"
allowed-tools: Bash, Read, Write, Task
---

Run one full morning cycle. Window: $1 days (default 7).

## 1. Preflight — before spending anything

Check, and report all failures together rather than one at a time:

- `analyze.py` exists in the working directory. If not, stop.
- `HUNTER8_SCREEN_MODEL` is set. If not, stop — `screen.py` requires it.
- Ollama answers: `curl -s -m 3 http://localhost:11434/api/tags`. If not, stop
  and print the fix (`ollama serve`, or `brew install ollama`). **Do not offer to
  run the pipeline without the local screen.**
- `intent.md` exists, and `TRACKER_PATH` is set.
- Run `.venv/bin/python analyze.py health --json`. If `threshold.disagrees`,
  `threshold.report_missing`, or `threshold.stale` is true, report it as a
  **warning** and continue — a deliberate override is legitimate.

## 2. Record the boundary

Run:

    .venv/bin/python -c "import db,pathlib;c=db.connect(pathlib.Path('hunter8.db'));print(c.execute('SELECT MAX(scored_at) FROM jobs').fetchone()[0] or '')"

Keep the value as `T0`. Everything graded after it is this run's output. Capture
it **before** the pipeline runs.

## 3. Run the pipeline

    .venv/bin/python discover.py
    .venv/bin/python screen.py --since-days <days>
    .venv/bin/python score.py --limit 25 --since-days <days>

The threshold comes from the configured value reported in step 1; do not pass
`--threshold`.

If `screen.py` stops with an Ollama error, or `score.py` stops with a quota or
login error, report the message verbatim and stop. **Never retry, never fall back
to another model.** For a `score.py` stop, also report how many remain in
`screened_in` so the run can resume with `--limit`.

## 4. Report

Run `.venv/bin/python analyze.py shortlist --since-days <days> --new-since <T0> --json`.

Dispatch the `hunter8-analyst` subagent with that JSON to write
`reports/YYYY-MM-DD.md`. If it returns nothing, present the shortlist table
yourself — never report success with no report.

## 5. Hand over

Show the headline, the new A-grades, and anything `health` flagged. Then offer
`/hunter8:triage`. Do not approve anything yourself.
