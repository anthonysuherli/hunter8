# Job Discovery & Triage — Design

**Date:** 2026-07-16
**Status:** Approved design, pending spec review
**Sub-project:** 1 of 4 in the HITL-driven automated job search system
**First user:** Anthony Suherli

## Context

`hunter8` today is the *back half* of an automated job search: an Excel tracker of
target roles drives Playwright ATS handlers (Greenhouse/Ashby auto-submit; Lever +
fallback always HITL) that fill and submit applications, build a tailored résumé PDF,
and write status back to the tracker.

The *front half* is missing: something that **finds** roles matching Anthony's intent
and expertise, **scores** their fit, and lets him **approve** which ones enter the apply
queue. This spec designs that front half: **discovery → fit scoring → HITL triage**.

The full system decomposes into four sub-projects:

1. **Discovery + fit scoring + triage** — *this spec*
2. Tailoring engine (KB-driven résumé / cover letter per role) — future
3. (application submission — **exists** in `hunter8` today)
4. (tracking — **exists** in `hunter8` today)

### Grounding: the delapan KB

Intent and expertise are not invented here — they come from the delapan cloud KB
`AI engineer/researcher` (177 findings across 4 KBs):

- **Profile & Evidence (32)** — candidate profile, résumé evidence bank, code-provable
  metrics, objection/counter table.
- **Market & Role Intel (101)** — 47 real job postings, quant/prop-shop comp bands,
  interview loops.
- **Positioning & Narrative (20)** — per-archetype positioning, what each employer type
  values.
- **Interview & Tech Prep (24)**.

The scorer consumes a **snapshot** of the profile/positioning KBs (see `intent.md`), so
discovery runs do not depend on delapan or LLM-gateway availability at run time.

## Decisions (locked in brainstorming)

| Decision | Choice |
|---|---|
| First sub-project | Discovery + fit scoring + triage |
| Sources | ATS public APIs (curated watchlist) + Tavily web search |
| Fit scoring | Hybrid: deterministic pre-filter → LLM grade against KB intent |
| LLM credential | Vercel AI Gateway (`AI_GATEWAY_API_KEY`); user tops up credit |
| HITL surface | CLI triage + Excel writeback (matches hunter8's HITL style) |
| Cadence | Manual CLI runs (designed so cron can schedule later) |
| State store | SQLite (`hunter8.db`); Excel tracker stays the apply queue |
| Watchlist | Seeded from KB, then user-owned YAML |
| KB integration | Snapshot via `sync_intent.py` → `intent.md` |
| Structure | Approach A — extend hunter8 as a flat CLI toolkit |

### Rejected alternatives

- **Separate discovery service (B).** A service boundary buys nothing for a single user
  running manually; it doubles the operational surface.
- **Agent-framework pipeline (C).** The flow is a linear fetch→filter→score→review; a
  framework adds dependency weight and indirection without changing the outcome.
- **Aggregator APIs / LinkedIn scraping** (as sources) — deferred; ATS APIs give
  structured URLs that feed straight into hunter8's router, Tavily covers the long tail,
  and scraping is brittle + against ToS.
- **LLM-only or rules-only scoring** — hybrid keeps token cost down without losing the
  reasoning quality only an LLM gives against a nuanced profile.
- **Live delapan queries per posting** — couples every run to delapan + gateway credit;
  snapshot is decoupled and editable.

## Architecture

```
watchlist.yaml ──┐
                 ├─► discover.py ──► hunter8.db (jobs, seen-URLs, scores)
Tavily queries ──┘        │
                          ▼
intent.md  ────────► score.py  (rules pre-filter → LLM grade A/B/C + reasoning)
                          │
                          ▼
                     triage.py  (CLI: approve / skip / snooze per job)
                          │ approved
                          ▼
              Excel tracker "To apply" row ──► apply.py (existing, unchanged)
```

### Components (each a single-purpose module, flat, matching hunter8 style)

- **`db.py`** — SQLite open/init/migrate; typed row helpers. Owns the schema below.
- **`sync_intent.py`** — pulls Profile & Evidence + Positioning & Narrative findings from
  delapan (service-client path, validated 2026-07-16) into `intent.md`. On-demand;
  `intent.md` is checked in and human-editable between syncs.
- **`discover.py`** — for every watchlist company, polls the matching ATS job-board API;
  plus runs configured Tavily query templates. New postings (URL not already in the
  seen-set) are inserted as `discovered`.
- **`score.py`** — two-stage scoring (rules → LLM); updates each job to `scored`,
  `filtered_out`, or `score_error`.
- **`triage.py`** — interactive CLI over `scored` jobs; approve writes a "To apply" row to
  the Excel tracker via `tracker.py` patterns; records every decision in SQLite.

The existing `apply.py`, `tracker.py`, `resume_builder.py`, `candidate_profile.py`, and
`handlers/` are **unchanged**. Approved rows carry an ATS URL (`greenhouse.io` /
`ashbyhq.com` / `lever.co` / other), so `handlers.route()` selects the correct handler
with no change.

### Commands

```bash
python sync_intent.py          # refresh intent.md from delapan KB
python discover.py             # poll ATS APIs + Tavily → hunter8.db
python score.py                # rules pre-filter + LLM grade against intent.md
python triage.py               # review scored jobs; approve → tracker.xlsx
python apply.py                # existing — submit the approved "To apply" rows
```

(Whether these become subcommands of a single `hunter8` CLI or stay separate scripts is
an implementation detail; separate scripts mirror the current repo and are the default.)

## Data model

SQLite file `hunter8.db` (path via `HUNTER8_DB_PATH`, default alongside the tracker).

```sql
CREATE TABLE jobs (
  id           INTEGER PRIMARY KEY,
  url          TEXT UNIQUE NOT NULL,   -- canonical application URL (dedup key)
  company      TEXT NOT NULL,
  title        TEXT NOT NULL,
  location     TEXT,
  source       TEXT NOT NULL,          -- 'ats:greenhouse' | 'ats:ashby' | 'ats:lever' | 'tavily'
  ats          TEXT,                   -- greenhouse | ashby | lever | null (for router)
  posted_at    TEXT,
  raw_text     TEXT,                   -- job description used by the scorer
  status       TEXT NOT NULL,          -- see state machine
  grade        TEXT,                   -- A | B | C
  reasoning    TEXT,
  archetype    TEXT,                   -- buy-side-ai | ai-finance-startup | lab | app-tier
  comp_signal  TEXT,
  red_flags    TEXT,
  discovered_at TEXT NOT NULL,
  scored_at    TEXT,
  triaged_at   TEXT
);
CREATE INDEX idx_jobs_status ON jobs(status);
```

`url` UNIQUE is the dedup guarantee: re-running `discover.py` never surfaces the same
posting twice.

### Status state machine

```
discovered ──rules──► filtered_out
           └──rules──► (survives) ──LLM──► scored
                                  └──err──► score_error
scored ──triage──► approved | skipped | snoozed
snoozed ──(snooze window elapsed)──► scored   # reappears in triage
```

## Configuration files

### `watchlist.yaml` (seeded from KB, then user-owned)

```yaml
companies:
  - name: Hebbia
    ats: greenhouse        # greenhouse | ashby | lever
    board: hebbia          # ATS board token
    archetype: ai-finance-startup
tavily_queries:
  - '"research engineer" agentic AI hiring {current_month}'
  - 'ML engineer "knowledge graph" fintech job posting'
```

Seeding: companies are extracted from the 47 postings + archetype intel in
**Market & Role Intel**; the file is then Anthony's to edit.

### `intent.md` (generated by `sync_intent.py`, human-editable)

Contains, distilled from the KB:

- Positioning one-liners per archetype.
- The fit table (co-primary: buy-side AI, AI-finance startups).
- Hard constraints from the Profile sheet: salary floor, location (US remote + listed
  metros), work authorization / sponsorship status.
- The objection/counter table, so the LLM knows what **not** to pursue (e.g. HFT C++ core
  roles, pure Research Scientist reqs gated on a PhD + top-venue papers).

## Scoring detail

**Stage 1 — rules (no LLM, cheap):**

- Title matches role patterns (ML/AI engineer, applied/research engineer, agentic, LLM,
  ML platform) — else `filtered_out`.
- Location is US-remote or a listed metro — else `filtered_out`.
- Drops interns, staffing-agency reposts, and titles on the objection list (HFT core C++).

**Stage 2 — LLM (survivors only), via AI Gateway:**

Input: `raw_text` + `intent.md`. Output: strict JSON

```json
{"grade": "A|B|C", "reasoning": "...", "archetype": "...",
 "comp_signal": "...", "red_flags": ["..."]}
```

- **A** = co-primary archetype, meets hard constraints, plays to the unfair advantage.
- **B** = plausible, some friction.
- **C** = weak fit; shown last, easy to skip.

## Error handling

- **Independent source fetches.** One company's dead board or a Tavily timeout logs a
  warning and the run continues; a summary line reports every fetch failure explicitly.
  Errors are never swallowed.
- **Visible scoring failures.** An LLM error sets `status='score_error'` (never a silent
  default to C); these appear in triage flagged so Anthony can re-score or inspect.
- **Excel safety.** Triage refuses to write if the tracker workbook is open/locked and
  tells the user to close it, rather than corrupting or losing the write.
- **Gateway credit.** `score.py` fails fast with a clear message if the AI Gateway returns
  402 (insufficient credit) — the exact failure hit during design.

## Triage UX

`scored` jobs sorted by grade (A→C). Per job, show: company, title, grade, one-line
reasoning, comp signal, location, link. Keys:

- `a` approve → write "To apply" row to tracker (company, role, city, link; priority
  derived from grade: A→A-fit), set `approved`.
- `s` skip → `skipped`.
- `z` snooze 14 days → `snoozed`, reappears later.
- `o` open posting in browser.
- `q` quit (progress persisted).

This mirrors hunter8's existing HITL pause loop (Enter/`s`/`e` keys) for a consistent feel.

## Testing

Mirrors the existing `tests/` layout (`test_handlers.py`, `test_tracker.py`, …):

- **ATS parsers** — fixture JSON payloads for Greenhouse / Ashby / Lever board APIs →
  assert correct `jobs` rows (URL, company, title, location, ats).
- **Rules filter** — unit tests for title/location/objection rules, incl. edge cases.
- **Dedup** — inserting the same URL twice yields one row; `discover.py` re-run is a no-op
  on seen URLs.
- **Scorer** — LLM call stubbed; assert JSON parse, grade mapping, and that a stub error
  sets `score_error`.
- **Triage writeback** — approve against a temp workbook; assert a correct "To apply" row
  and SQLite status transition.

## Dependencies (added to `requirements.txt`)

- `httpx` — ATS API + Tavily HTTP calls.
- `pyyaml` — watchlist parsing.
- `tavily-python` (or direct HTTP) — web-search source.
- LLM access reuses the delapan-style AI Gateway (OpenAI-compatible) client.

No change to Python version (3.11) or the existing pytest config.

## Out of scope (explicit)

- Tailoring engine (sub-project 2) — approved rows use the existing résumé path for now.
- Scheduling daemon — manual runs only; cron-friendly by construction.
- Aggregator APIs, LinkedIn/Indeed scraping.
- Multi-user / auth — single user (Anthony).
