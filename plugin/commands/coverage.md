---
description: Find watchlist boards producing nothing, and propose additions
argument-hint: "[stale-days, default 30]"
allowed-tools: Bash, Read
---

Stale-days: $1 (default 30).

Run `.venv/bin/python analyze.py coverage --stale-days <stale-days> --json`.

Report:

1. **Silent boards** — configured and returning zero rows. For each, say whether
   the likely cause is a wrong slug, a board that has moved, or a firm that
   genuinely is not hiring. Do not guess a replacement slug and present it as
   fact — a Workday tenant slug cannot be inferred, only verified.
2. **Stale boards** — producing rows once, nothing recent.
3. **Firms with no entry at all** — read `watchlist.yaml` and name target firms
   absent from it entirely.

Then propose concrete `watchlist.yaml` additions as a YAML block for the user to
paste. Do not edit `watchlist.yaml` yourself. For any Workday or Eightfold
suggestion, say explicitly that the slug is unverified and must be probed before
it is trusted.
