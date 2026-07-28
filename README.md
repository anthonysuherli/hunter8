# hunter8

Playwright CLI that auto-submits job applications from an Excel tracker.
Fills forms automatically and pauses for human review only when open-ended text fields are detected.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
# edit .env — set TRACKER_PATH to your ML-AI-Roles-Tracker.xlsx path
```

## Discovery → Triage → Apply

The full loop, upstream of the existing apply step:

```bash
python sync_intent.py     # 1. pull your profile/positioning from delapan → intent.md
python discover.py        # 2. poll watchlist ATS boards + Tavily → hunter8.db
python screen.py          # 3. local model grades every job 0-100 against rubric.md
python score.py           # 4. Claude grades the survivors (A/B/C)
python triage.py          # 5. review scored jobs; approve → tracker "To apply" rows
python apply.py           # 6. (existing) submit the approved rows
```

- Edit `watchlist.yaml` to control which companies/boards and web queries are polled.
- Screening runs on a local Ollama model, so grading every discovered job costs
  nothing. Install with `brew install ollama`, then `ollama pull <model>` and set
  `HUNTER8_SCREEN_MODEL`. `screen.py` stops with instructions if Ollama is not
  reachable — it never falls back to Claude, because promoting thousands of jobs
  to the subscription tier would exhaust the quota.
- `rubric.md` is distilled from `intent.md` by Claude on first run and reused
  until `intent.md` changes. Read it — it is what the screen believes about you —
  and hand-edit inside the `BEGIN human` / `END human` markers, which survive
  regeneration.
- Run `python calibrate.py` once to choose `HUNTER8_SCREEN_THRESHOLD` from the
  jobs Claude has already graded, rather than guessing it.
- `score.py --limit N` grades the N highest-scoring jobs. Use it for the first
  bulk run: each Claude call carries ~43k tokens of harness overhead, so grading
  hundreds of jobs in one sitting can exhaust the subscription quota.
- Requires `TAVILY_API_KEY` (web discovery); `sync_intent.py` needs `SUPABASE_URL` +
  `SUPABASE_SERVICE_ROLE_KEY` for the delapan KB.

## Usage

```bash
# dry run — navigate and fill but do not submit
python apply.py --dry-run

# apply to all A-fit "To apply" rows
python apply.py

# single row (by Excel row number)
python apply.py --row 4

# one ATS type only
python apply.py --ats greenhouse

# headless mode
python apply.py --headless
```

## Supported ATS

| ATS | Auto-submit | HITL trigger |
|-----|-------------|-------------|
| Greenhouse | Yes | open-ended textarea detected |
| Ashby | Yes | open-ended textarea detected |
| Lever | Always HITL | always has free-text field |
| Everything else | Always HITL | fallback — you submit manually |

## Profile sheet

The tracker Excel needs a "Profile" sheet with `key` / `value` columns.
Fields: full_name, email, phone, linkedin, github, location_city, work_authorized,
requires_sponsorship, sponsorship_type, gc_timeline, years_experience, highest_degree,
degree_field, university, grad_year, salary_min, willing_to_relocate.

## HITL pause

When an open-ended textarea is detected, the bot freezes with the browser open:
```
🟡 HITL required: Anthropic — Research Engineer, Knowledge Team
   Reason: 1 open-ended textarea(s) detected
   Fill the field(s) in the browser, then:
     Enter  → mark Applied
     's'    → skip
     'e'    → mark Error
   →
```
