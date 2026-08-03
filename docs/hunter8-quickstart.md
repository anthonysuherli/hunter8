# hunter8 Cursor quickstart

Suggested daily loop once the plugin is installed (`~/.cursor/plugins/local/hunter8`).

Always open the **hunter8 repo root** in Cursor before running commands.

## One-time setup

```bash
# from repo root
ln -sfn "$(pwd)/plugin" ~/.cursor/plugins/local/hunter8
# reload Cursor

cp .env.example .env   # if needed
# set at least: HUNTER8_SCREEN_MODEL, TRACKER_PATH, TAVILY_API_KEY
# optional: HUNTER8_SCREEN_THRESHOLD=65 (calibrated)

ollama serve           # local screen — never skip this for morning
```

Profile refresh (when delapan findings changed): see [explore-quickstart.md](explore-quickstart.md), then `python sync_intent.py`.

## Suggested morning

```text
1. /hunter8:health
      → catch threshold drift, stuck queues, Ollama/config issues first

2. /hunter8:morning 7
      → preflight → discover → screen → score (limit 25)
      → writes reports/YYYY-MM-DD.md via hunter8-analyst
      → offers triage; does not approve anything

3. /hunter8:triage A
      → read each A with full reasoning
      → reply with explicit ids only (e.g. 12, 15, 18)
      → rows land in the tracker “To apply”

4. python apply.py --dry-run     # then apply.py when ready
```

Weekly (or when boards look dead): `/hunter8:coverage 30` — review proposed `watchlist.yaml` adds; paste yourself, don’t auto-edit.

## What to say in chat (if you skip slash commands)

| You want | Say / do |
|---|---|
| Full daily cycle | `/hunter8:morning` |
| Approve A-grades | `/hunter8:triage` |
| “Is the pipeline healthy?” | `/hunter8:health` |
| “Why am I seeing nothing?” | `/hunter8:coverage` |
| Corpus rules while debugging | skill `hunter8-corpus` (auto) |

## Rules that matter

- **Human approves every submission.** Triage waits for explicit ids — never “the good ones.”
- **Ollama down → stop.** Do not fall back to Claude for screening.
- **Don’t pass `.env` vars on the CLI.** Scripts load `.env` themselves.
- **`analyze.py` is read-only.** It never writes approvals.

## Failure shortcuts

| Symptom | Fix |
|---|---|
| morning stops on screen model | set `HUNTER8_SCREEN_MODEL` in `.env` |
| Ollama unreachable | `ollama serve` / `brew install ollama` |
| score quota / login error | stop; resume later with `score.py --limit N` |
| empty triage | nothing graded in window — check health, widen days, or run morning |
| plugin commands missing | re-symlink + reload Cursor |

## One-liner

`/hunter8:health` → `/hunter8:morning` → `/hunter8:triage` → `apply.py`
