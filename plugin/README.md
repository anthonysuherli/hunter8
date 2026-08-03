# hunter8 plugin

Cursor / Claude Code plugin for the personal hunter8 job-search pipeline.

Run commands from the **hunter8 repo root** (where `analyze.py` and `.venv` live). Each CLI loads `.env` itself — never interpolate env vars into shell commands.

## Install (Cursor)

From the hunter8 repo root:

```bash
ln -sfn "$(pwd)/plugin" ~/.cursor/plugins/local/hunter8
```

Reload Cursor. Commands appear as `/hunter8:morning`, `/hunter8:triage`, etc.

Claude Code continues to use `.claude-plugin/` + the repo marketplace at `../.claude-plugin/marketplace.json`.

## Commands

| Command | Does |
|---|---|
| `/hunter8:morning [days]` | Preflight, discover → screen → score, write `reports/YYYY-MM-DD.md`, offer triage |
| `/hunter8:triage [grade]` | Present graded jobs; approve → tracker via `triage.py --approve` |
| `/hunter8:health` | Queue, threshold drift, screen↔Claude agreement, cost |
| `/hunter8:coverage [stale-days]` | Silent/stale watchlist boards; propose YAML additions (do not auto-edit) |

## Skills

| Skill | When |
|---|---|
| `hunter8-corpus` | Reading or reporting on the corpus — statuses, grades, `analyze.py` rules |

## Agents

| Agent | When |
|---|---|
| `hunter8-analyst` | Narrate `analyze.py` JSON into a short report (keeps raw rows out of the main thread) |

## Prerequisites

- Repo `.venv` with deps installed
- `.env` with `HUNTER8_SCREEN_MODEL`, `TRACKER_PATH`, and (for morning) Ollama running
- `python analyze.py …` works from the repo root
