---
description: Review graded jobs and write the ones you approve to the tracker
argument-hint: "[grade, default A]"
allowed-tools: Bash, Read
---

Walk the user through graded jobs and write their approvals to the tracker.

Grade to review: $1 (default `A`).

## Steps

1. Confirm the working directory is the hunter8 repo — `analyze.py` must exist.
   If it does not, say so and stop; do not search the filesystem for it.
2. Run `.venv/bin/python analyze.py shortlist --grade <grade> --json`.
3. If `count` is 0, say so plainly and stop.
4. Present every job as a numbered list. For each, give the id, company, title,
   location, grade, `fit_score`, `comp_signal`, the URL, and the full
   `reasoning`. Then add one line of your own read — whether the reasoning
   actually holds up against the posting, and any `red_flags` worth weighing.
   Do not rank or re-score; the grade is not yours to revise.
5. Ask which to approve. **Wait for an answer.** If the reply is ambiguous
   ("the good ones", "most of them"), ask again with a concrete list — never
   interpret. Approval is the gate; a guessed approval cannot be undone once
   apply runs.
6. Run `.venv/bin/python triage.py --approve <ids> --tracker "$TRACKER_PATH"`
   with only the ids the user named.
7. Report each line the command printed. If any id failed — a locked workbook,
   an already-approved row — say which, and do not retry silently.
8. Tell the user the rows are queued and that `apply.py` is still run by hand.
