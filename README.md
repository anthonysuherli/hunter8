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
python score.py           # 3. rules pre-filter + LLM grade (A/B/C) against intent.md
python triage.py          # 4. review scored jobs; approve → tracker "To apply" rows
python apply.py           # 5. (existing) submit the approved rows
```

- Edit `watchlist.yaml` to control which companies/boards and web queries are polled.
- Requires `AI_GATEWAY_API_KEY` (scoring) and `TAVILY_API_KEY` (web discovery);
  `sync_intent.py` needs `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY` for the delapan KB.

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
