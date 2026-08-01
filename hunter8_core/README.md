# hunter8-core

Provider-neutral contracts shared by local hunter8 and the hosted companion.

## Owns

- Immutable public job-posting data
- Draft and confirmed profile evidence contracts
- Company thesis, verified watchlist, match assessment, and ranked-match values
- Résumé, question-planning, company-recommendation, source, evidence-ranking,
  shortlist-ranking, and JSON-model protocols
- Validated local screening and grade assessment values

## Does not own

- SQLite status or grade history
- YAML watchlists or Tavily discovery
- `intent.md`, `rubric.md`, `brief.md`, résumés, or personal KB ids
- Ollama, Claude CLI, AI Gateway, or any provider SDK
- Supabase, auth, queues, HTTP APIs, Excel, or Playwright

`hunter8_core` is stdlib-only. Infrastructure implements its protocols at the
application edge.

## Python version

The dataclasses here use `@dataclass(frozen=True)` without `slots=True`, because
the project venv is Python 3.9 and `slots` requires 3.10+. Immutability is
unaffected. Add `slots=True` if the interpreter is ever raised.
