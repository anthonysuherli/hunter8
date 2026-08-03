# hunter8 × `/delapan:explore` quickstart

Fill gaps in the delapan KB, then pull that context into hunter8’s grading loop.

## Prerequisites

1. Delapan plugin installed (Cursor / Claude Code).
2. In the **plugin** root `.env` (not hunter8’s): `AI_GATEWAY_API_KEY`, `TAVILY_API_KEY`.
3. In **hunter8** `.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (for `sync_intent.py`).
4. Work from the hunter8 repo on the branch whose KB you want (`main` → KB `main`).

## When to explore

| Situation | Do this |
|---|---|
| Resume says coverage `gap` / `sparse` | `/delapan:explore` (optionally with a topic) |
| You know the gap (“NYC hedge fund AI hiring”) | `/delapan:explore <topic>` |
| No topic — fill whatever the KB most needs | `/delapan:backlog` then `/delapan:explore` with no prompt |
| You’re in chat and can search the web yourself | Prefer `/delapan:ingest` (cheaper); use explore for unattended research |

Explore runs plan → search → crawl → extract → merge (~1–3 min). Empty backlog + no prompt = error, nothing written.

## Daily flow (hunter8)

```text
1. /delapan:resume
      → see coverage; if gap/sparse, explore before trusting answers

2. /delapan:explore <focus>
      examples:
        NYC hedge funds hiring AI / ML / GenAI engineers 2026
        H-1B transfer norms at Citadel Two Sigma Point72 Jane Street
        AI platform roles at BlackRock Goldman JPMorgan Bloomberg

3. python sync_intent.py
      → refreshes intent.md from Profile & Evidence + Positioning & Narrative
      → hand-authored block between BEGIN/END human markers is preserved

4. /hunter8:morning
      → or: python discover.py && python screen.py && python score.py
      → grading uses rubric distilled from intent.md
```

Optional checks: `/delapan:search <question>` after explore; `/hunter8:health` / `/hunter8:coverage` after a discover run. Full Cursor operator loop: [hunter8-quickstart.md](hunter8-quickstart.md).

## Good explore prompts for this project

- Employer / market intel that should change **who** you watch or **how** you pitch.
- Evidence that strengthens Profile & Positioning (metrics, archetypes, objections).
- Sponsorship / location norms that affect hard constraints in `brief.md`.

Skip explore for: editing `watchlist.yaml`, running triage, or applying — those are hunter8 commands (`/hunter8:morning`, `/hunter8:triage`, etc.).

## Failure modes

- **Missing keys** → copy plugin `.env.example` → `.env` and set the named vars.
- **`status: empty`** → read the `reason`; usually thin web results or bad focus.
- **No KB yet** → resume returns onboarding; run explore once to seed, then resume again.
- **`intent.md` out of date after explore** → you forgot `python sync_intent.py`.

## One-liner

`/delapan:resume` → `/delapan:explore <gap>` → `python sync_intent.py` → run the discover/screen/score loop.
