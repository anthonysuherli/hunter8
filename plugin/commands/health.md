---
description: Report pipeline and calibration state, with drift called out
allowed-tools: Bash, Read
---

Run `.venv/bin/python analyze.py health --json` and
`.venv/bin/python analyze.py patterns --by archetype --json`, then report:

1. **Queue** — what is where, and what is stuck. A large `discovered` count
   means screening is behind; a large `screened_in` count means grading is.
2. **Misconfiguration** — every true flag under `threshold`, with the fix.
   `disagrees` means runs are screening at a value nobody chose.
3. **Agreement** — A-recall at the current threshold over the graded sample, and
   the highest threshold still holding 100%. If A-recall is below 1.0, say
   plainly that the screen is currently discarding jobs Claude would have called
   A.
4. **Errors** — every `screen_error` / `score_error` row with its reason,
   grouped if they share a cause.
5. **Cost** — notional lifetime spend and priced rows. Note that billing is $0
   under subscription auth.
6. **Where you convert** — the top and bottom archetypes by A-rate, flagging any
   whose sample is too small to read.

Recommend at most two concrete actions. Do not run them.
