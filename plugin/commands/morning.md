---
description: Run the full discovery pipeline, then report and offer triage
argument-hint: "[days, default 7]"
allowed-tools: Bash, Read, Write, Task
---

Run one full morning cycle. Window: $1 days (default 7).

## 1. Preflight — before spending anything

Check, and report all failures together rather than one at a time:

- `analyze.py` exists in the working directory. If not, stop.
- `HUNTER8_SCREEN_MODEL` is configured — `grep -q '^HUNTER8_SCREEN_MODEL=.' .env`.
  If not, stop — `screen.py` requires it. (`.env` values are not shell
  environment variables: each CLI loads `.env` itself via `load_dotenv()`, so
  `$HUNTER8_SCREEN_MODEL` reads empty from the shell even when `.env` is fine —
  check the file, never the shell variable.)
- Ollama answers: `curl -s -m 3 http://localhost:11434/api/tags`. If not, stop
  and print the fix (`ollama serve`, or `brew install ollama`). **Do not offer to
  run the pipeline without the local screen.**
- `intent.md` exists, and `TRACKER_PATH` is configured —
  `grep -q '^TRACKER_PATH=.' .env`.
- Run `.venv/bin/python analyze.py health --json`. If `threshold.disagrees`,
  `threshold.report_missing`, or `threshold.stale` is true, report it as a
  **warning** and continue — a deliberate override is legitimate.

## 2. Record the boundary

Run:

    .venv/bin/python -c "from dotenv import load_dotenv;load_dotenv();import os,db,pathlib;c=db.connect(pathlib.Path(os.environ.get('HUNTER8_DB_PATH', db.DEFAULT_DB)));print(c.execute('SELECT MAX(scored_at) FROM jobs').fetchone()[0] or '')"

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

Dispatch the `hunter8-analyst` subagent with the window (`<days>` days), the
`T0` value from step 2, and the output path `reports/YYYY-MM-DD.md`. Tell it to
run `.venv/bin/python analyze.py shortlist --since-days <days> --new-since <T0>
--json` itself. **Do not run that command in the main thread and do not pass its
JSON to the subagent** — the whole reason the subagent exists is to keep 160+
rows of `reasoning` out of the main conversation, and running the command here
first defeats that before the subagent ever sees it.

If the subagent returns nothing, run the shortlist command yourself now and
present the table — never report success with no report.

## 5. Hand over

Show the headline, the new A-grades, and anything `health` flagged. Then offer
`/hunter8:triage`. Do not approve anything yourself.
