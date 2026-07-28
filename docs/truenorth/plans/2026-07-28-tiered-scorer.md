# Tiered Scorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use truenorth:subagent-driven-development (recommended) or truenorth:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hunter8's regex pre-filter with a free local-model screen so every discovered job gets graded, and reserve Claude for the survivors.

**Architecture:** `intent.md` is compressed once by Claude into a small `rubric.md`. A local Ollama model scores every job 0–100 against that rubric over HTTP; jobs at or above a calibrated threshold become `screened_in` and go to Claude for the real grade. The local tier mirrors the existing `claude_agent.py` interface (`chat_json(system, user) -> dict`) so both tiers are swappable and tested the same way.

**Vision goals served:** End Goal 2 (scoring costs nothing per job) directly; End Goals 1 and 4 by unblocking the 242-job backlog and making a daily run affordable. Executes Planned Detour 1 and absorbs most of Detour 2.

**Tech Stack:** Python 3.9, sqlite3 (stdlib), httpx, click, python-dotenv, pytest. Ollama as a local HTTP service. No new Python dependencies.

## Global Constraints

- **Python 3.9.** No `match` statements, no `X | Y` runtime unions outside `from __future__ import annotations`. The venv is 3.9.6; this is the constraint that ruled out `claude-agent-sdk`.
- **No new Python dependencies.** `httpx` is already in `requirements.txt`.
- **Failures stay visible.** A job that cannot be screened becomes `screen_error` with its reason. Nothing is silently dropped.
- **Ollama unreachable is a hard stop, never a Claude fallback.** Promoting 2,933 jobs to Claude to work around a missing install would burn the subscription quota.
- **Personal artifacts are gitignored:** `rubric.md` and `calibration-report.md` join `intent.md`, `resumes/`, `hunter8.db`.
- **Every module keeps one responsibility.** New CLIs are thin: select jobs by status, call an agent, write a status.
- Tests run with `.venv/bin/python -m pytest`. Project root is already on `sys.path` via `conftest.py`.

---

## File Structure

| File | Responsibility |
|---|---|
| `json_reply.py` *(new)* | Parse a model's text reply into a dict, tolerating markdown fences. Shared by both agents. |
| `local_agent.py` *(new)* | Ollama HTTP client exposing `chat_json`. |
| `rubric.py` *(new)* | Distill `intent.md` → `rubric.md`; cache on hash; preserve the human block. |
| `screen.py` *(new)* | Local tier CLI: `discovered` → `screened_in` / `screened_out` / `screen_error`. |
| `calibrate.py` *(new)* | Score the 85 Claude-graded jobs without mutating them; recommend a threshold. |
| `claude_agent.py` | Loses its private `_parse_object` in favour of `json_reply`. |
| `db.py` | Schema migration, three new columns, ordered/limited queries, `set_screen`. |
| `score.py` | Loses `passes_rules` and the regexes; reads `screened_in`; gains `--limit` and ordering. |

---

### Task 1: Shared JSON reply parser

Both agents need the same fence-stripping, first-`{...}` fallback logic. Extract it before writing the second agent so it is never copy-pasted.

**Files:**
- Create: `json_reply.py`
- Modify: `claude_agent.py` (remove `_parse_object`, import the shared one)
- Test: `tests/test_json_reply.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `json_reply.parse_object(content: str) -> dict`, raising `ValueError` on unparseable input. Callers wrap that in their own error type.

- [ ] **Step 1: Write the failing test**

Create `tests/test_json_reply.py`:

```python
# tests/test_json_reply.py
import pytest

import json_reply


def test_parses_plain_object():
    assert json_reply.parse_object('{"fit_score": 70}') == {"fit_score": 70}


def test_strips_markdown_fence():
    assert json_reply.parse_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extracts_object_from_surrounding_prose():
    assert json_reply.parse_object('Sure: {"a": 1} — done') == {"a": 1}


def test_raises_value_error_on_garbage():
    with pytest.raises(ValueError):
        json_reply.parse_object("no object here")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_json_reply.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'json_reply'`

- [ ] **Step 3: Write minimal implementation**

Create `json_reply.py`:

```python
# json_reply.py
"""Parse a model's text reply into a JSON object.

Models wrap JSON in markdown fences or prose often enough that both agents
need the same tolerance. Kept here so neither has to copy it.
"""
from __future__ import annotations

import json


def parse_object(content: str) -> dict:
    """Return the JSON object in `content`. Raises ValueError if there isn't one."""
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(content[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError(f"no JSON object in reply: {content[:200]!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_json_reply.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Rewire `claude_agent.py` to the shared parser**

In `claude_agent.py`, delete the whole `_parse_object` function and add the import. Change the import block from:

```python
import json
import subprocess
```

to:

```python
import json
import subprocess

import json_reply
```

Then replace the final line of `chat_json` — `return _parse_object(envelope.get("result") or "")` — with:

```python
        try:
            return json_reply.parse_object(envelope.get("result") or "")
        except ValueError as exc:
            raise ClaudeError(str(exc)) from exc
```

- [ ] **Step 6: Run the full suite to verify nothing broke**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. `tests/test_claude_agent.py::test_unparseable_result_raises` still passes because `ClaudeError` is still raised and the message still contains "no JSON object" — update that test's assertion from `"non-json" in str(ei.value).lower()` to `"no json object" in str(ei.value).lower()` if it fails.

- [ ] **Step 7: Commit**

```bash
git add json_reply.py tests/test_json_reply.py claude_agent.py tests/test_claude_agent.py
git commit -m "refactor: extract shared JSON reply parser"
```

---

### Task 2: Database schema and queries

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Job` dataclass gains `fit_score: int | None`, `screen_reason: str | None`, `screened_at: str | None`.
  - `db.jobs_by_status(conn, status, *, order_by=None, limit=None) -> list[Job]` — `order_by` is a literal SQL fragment chosen from a whitelist; `None` keeps today's `ORDER BY id`.
  - `db.set_screen(conn, job_id, *, status, fit_score, screen_reason) -> None`.
  - New statuses used by later tasks: `screened_in`, `screened_out`, `screen_error`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_init_db_migrates_legacy_table(tmp_path):
    """A database created before the screen columns existed gains them."""
    conn = dbmod.connect(tmp_path / "legacy.db")
    conn.executescript(
        """CREATE TABLE jobs (
             id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL,
             company TEXT NOT NULL, title TEXT NOT NULL, location TEXT,
             source TEXT NOT NULL, ats TEXT, posted_at TEXT, raw_text TEXT,
             status TEXT NOT NULL, grade TEXT, reasoning TEXT, archetype TEXT,
             comp_signal TEXT, red_flags TEXT, discovered_at TEXT NOT NULL,
             scored_at TEXT, triaged_at TEXT);"""
    )
    dbmod.init_db(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"fit_score", "screen_reason", "screened_at"} <= cols


def test_init_db_is_idempotent(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.init_db(conn)          # must not raise "duplicate column name"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert "fit_score" in cols


def _screened(conn, url, score):
    job = Job(url=url, company="Acme", title="ML Engineer", location="NYC",
              source="ats:greenhouse", ats="greenhouse", raw_text="d")
    dbmod.insert_job(conn, job)
    stored = [j for j in dbmod.jobs_by_status(conn, "discovered") if j.url == url][0]
    dbmod.set_screen(conn, stored.id, status="screened_in", fit_score=score,
                     screen_reason="r")


def test_jobs_by_status_orders_and_limits(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for url, score in [("https://x/1", 40), ("https://x/2", 90), ("https://x/3", 65)]:
        _screened(conn, url, score)

    top = dbmod.jobs_by_status(conn, "screened_in",
                               order_by="fit_score DESC", limit=2)
    assert [j.fit_score for j in top] == [90, 65]


def test_jobs_by_status_defaults_unchanged(tmp_path):
    """Existing callers keep insertion order and no cap."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for url, score in [("https://x/1", 40), ("https://x/2", 90)]:
        _screened(conn, url, score)
    assert [j.url for j in dbmod.jobs_by_status(conn, "screened_in")] == [
        "https://x/1", "https://x/2"]


def test_jobs_by_status_rejects_unknown_order_by(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    with pytest.raises(ValueError):
        dbmod.jobs_by_status(conn, "screened_in", order_by="1; DROP TABLE jobs")
```

Add `import pytest` and `from db import Job` at the top of `tests/test_db.py` if they are not already there.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: FAIL — `AttributeError: module 'db' has no attribute 'set_screen'`

- [ ] **Step 3: Add the columns to the schema and the dataclass**

In `db.py`, extend `_SCHEMA`'s `CREATE TABLE` with three columns just before the closing paren of the `jobs` table — after `triaged_at TEXT`:

```
  triaged_at    TEXT,
  fit_score     INTEGER,
  screen_reason TEXT,
  screened_at   TEXT
```

Add the matching fields to the end of the `Job` dataclass:

```python
    fit_score: int | None = None
    screen_reason: str | None = None
    screened_at: str | None = None
```

- [ ] **Step 4: Add the guarded migration**

Replace `init_db` in `db.py` with:

```python
_MIGRATIONS = {
    "fit_score": "INTEGER",
    "screen_reason": "TEXT",
    "screened_at": "TEXT",
}


def init_db(conn: sqlite3.Connection) -> None:
    """Create the schema, then add any columns a pre-existing database lacks.

    `CREATE TABLE IF NOT EXISTS` will not add columns to a table that already
    exists, so databases created before the screen tier need an explicit ALTER.
    Idempotent — safe on every startup."""
    conn.executescript(_SCHEMA)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for column, decl in _MIGRATIONS.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {decl}")
    conn.commit()
```

- [ ] **Step 5: Add ordering, limiting, and `set_screen`**

Replace `jobs_by_status` in `db.py` and add `set_screen` beneath it:

```python
# Whitelisted so an order_by string can never carry SQL from a caller.
_ORDER_BY = {"fit_score DESC", "fit_score ASC"}


def jobs_by_status(conn: sqlite3.Connection, status: str, *,
                   order_by: str | None = None,
                   limit: int | None = None) -> list[Job]:
    if order_by is not None and order_by not in _ORDER_BY:
        raise ValueError(f"order_by must be one of {sorted(_ORDER_BY)}, got {order_by!r}")
    sql = f"SELECT * FROM jobs WHERE status=? ORDER BY {order_by or 'id'}"
    params: list = [status]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    return [_row_to_job(r) for r in conn.execute(sql, params).fetchall()]


def set_screen(conn: sqlite3.Connection, job_id: int, *, status: str,
               fit_score: int | None, screen_reason: str | None) -> None:
    conn.execute(
        """UPDATE jobs SET status=?, fit_score=?, screen_reason=?, screened_at=?
           WHERE id=?""",
        (status, fit_score, screen_reason, _now(), job_id),
    )
    conn.commit()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 7: Migrate the live database and confirm**

Run:

```bash
.venv/bin/python -c "import db; c = db.connect('hunter8.db'); db.init_db(c); print(sorted(r[1] for r in c.execute('PRAGMA table_info(jobs)')))"
```

Expected: the printed list includes `fit_score`, `screen_reason`, `screened_at`.

- [ ] **Step 8: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: screen columns, guarded migration, ordered queries"
```

---

### Task 3: Ollama client

**Files:**
- Create: `local_agent.py`
- Test: `tests/test_local_agent.py`

**Interfaces:**
- Consumes: `json_reply.parse_object` (Task 1).
- Produces:
  - `local_agent.LocalAgent(model=..., base_url="http://localhost:11434", timeout=120.0)` with `chat_json(system: str, user: str) -> dict`.
  - `local_agent.LocalError`, `local_agent.LocalUnavailable` (subclass of `LocalError`).
  - `local_agent.DEFAULT_BASE_URL`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_local_agent.py`:

```python
# tests/test_local_agent.py
import httpx
import pytest

import local_agent


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._payload


def _reply(content):
    return _Resp({"message": {"role": "assistant", "content": content}})


def _run(monkeypatch, resp, capture=None):
    def fake_post(url, json=None, timeout=None):
        if capture is not None:
            capture["url"], capture["json"] = url, json
        return resp

    monkeypatch.setattr(local_agent.httpx, "post", fake_post)
    return local_agent.LocalAgent(model="m").chat_json("sys", "user")


def test_chat_json_returns_parsed_object(monkeypatch):
    out = _run(monkeypatch, _reply('{"fit_score": 72, "reason": "good"}'))
    assert out["fit_score"] == 72


def test_chat_json_tolerates_fenced_reply(monkeypatch):
    out = _run(monkeypatch, _reply('```json\n{"fit_score": 10, "reason": "no"}\n```'))
    assert out["fit_score"] == 10


def test_posts_to_ollama_chat_endpoint(monkeypatch):
    capture = {}
    _run(monkeypatch, _reply('{"fit_score": 1, "reason": "r"}'), capture)
    assert capture["url"].endswith("/api/chat")
    assert capture["json"]["model"] == "m"
    assert capture["json"]["stream"] is False
    roles = [m["role"] for m in capture["json"]["messages"]]
    assert roles == ["system", "user"]


def test_connection_refused_is_unavailable(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(local_agent.httpx, "post", fake_post)
    with pytest.raises(local_agent.LocalUnavailable) as ei:
        local_agent.LocalAgent(model="m").chat_json("s", "u")
    assert "ollama" in str(ei.value).lower()


def test_missing_model_is_unavailable(monkeypatch):
    resp = _Resp({"error": "model 'm' not found, try pulling it first"}, status=404)
    with pytest.raises(local_agent.LocalUnavailable):
        _run(monkeypatch, resp)


def test_timeout_is_local_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(local_agent.httpx, "post", fake_post)
    with pytest.raises(local_agent.LocalError):
        local_agent.LocalAgent(model="m").chat_json("s", "u")


def test_unparseable_reply_is_local_error(monkeypatch):
    with pytest.raises(local_agent.LocalError):
        _run(monkeypatch, _reply("I cannot answer that"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_local_agent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'local_agent'`

- [ ] **Step 3: Write the implementation**

Create `local_agent.py`:

```python
# local_agent.py
"""Ollama client for the bulk screening tier.

Mirrors claude_agent.ClaudeAgent's chat_json interface so the two tiers are
swappable. Talks HTTP rather than importing an SDK because the venv is Python
3.9 and httpx is already a dependency.
"""
from __future__ import annotations

import httpx

import json_reply

DEFAULT_BASE_URL = "http://localhost:11434"

# Constrain the reply shape at the model level where Ollama supports it.
_SCHEMA = {
    "type": "object",
    "properties": {
        "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": {"type": "string"},
    },
    "required": ["fit_score", "reason"],
}


class LocalError(RuntimeError):
    """A single local call failed."""


class LocalUnavailable(LocalError):
    """Ollama isn't running, or the model isn't pulled — stop the batch."""


class LocalAgent:
    def __init__(self, *, model: str, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 120.0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat_json(self, system: str, user: str) -> dict:
        """One local turn returning a JSON object. Raises LocalUnavailable when
        the batch should stop, LocalError for a single bad call."""
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "format": _SCHEMA,
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
                timeout=self.timeout,
            )
        except httpx.ConnectError as exc:
            raise LocalUnavailable(
                f"Cannot reach Ollama at {self.base_url}. Start it with "
                "`ollama serve`, or install it with `brew install ollama`."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LocalError(f"ollama timed out after {self.timeout:.0f}s") from exc

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = str(resp.json())
            except Exception:  # noqa: BLE001 — body is best-effort context
                pass
            if "not found" in body.lower():
                raise LocalUnavailable(
                    f"Model {self.model!r} is not pulled. Run "
                    f"`ollama pull {self.model}`."
                ) from exc
            raise LocalError(f"ollama HTTP {resp.status_code}: {body[:200]}") from exc

        content = (resp.json().get("message") or {}).get("content") or ""
        try:
            return json_reply.parse_object(content)
        except ValueError as exc:
            raise LocalError(str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_local_agent.py -v`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add local_agent.py tests/test_local_agent.py
git commit -m "feat: Ollama client for the local screening tier"
```

---

### Task 4: Rubric distillation

**Files:**
- Create: `rubric.py`
- Test: `tests/test_rubric.py`

**Interfaces:**
- Consumes: `claude_agent.ClaudeAgent` (existing).
- Produces:
  - `rubric.load_or_build(intent_path: Path, rubric_path: Path, agent) -> str` — returns the rubric body, regenerating only when `intent.md`'s hash changes.
  - `rubric.HUMAN_BEGIN`, `rubric.HUMAN_END`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rubric.py`:

```python
# tests/test_rubric.py
from pathlib import Path

import rubric


class _FakeAgent:
    """Records how many times Claude was asked to distil."""

    def __init__(self, body="HARD CONSTRAINTS: US only."):
        self.body, self.calls = body, 0

    def chat_json(self, system, user):
        self.calls += 1
        return {"rubric": self.body}


def _paths(tmp_path, intent_text="profile v1"):
    intent = tmp_path / "intent.md"
    intent.write_text(intent_text, encoding="utf-8")
    return intent, tmp_path / "rubric.md"


def test_builds_rubric_on_first_run(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    body = rubric.load_or_build(intent, rub, agent)
    assert "US only" in body
    assert agent.calls == 1
    assert rub.exists()


def test_reuses_cached_rubric_when_intent_unchanged(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    rubric.load_or_build(intent, rub, agent)
    rubric.load_or_build(intent, rub, agent)
    assert agent.calls == 1


def test_regenerates_when_intent_changes(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    rubric.load_or_build(intent, rub, agent)
    intent.write_text("profile v2 — now targeting FDE roles", encoding="utf-8")
    rubric.load_or_build(intent, rub, agent)
    assert agent.calls == 2


def test_human_block_survives_regeneration(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    rubric.load_or_build(intent, rub, agent)

    text = rub.read_text(encoding="utf-8")
    edited = text.replace(
        f"{rubric.HUMAN_BEGIN}\n\n\n{rubric.HUMAN_END}",
        f"{rubric.HUMAN_BEGIN}\n\nNever surface contract roles.\n\n{rubric.HUMAN_END}",
    )
    rub.write_text(edited, encoding="utf-8")

    intent.write_text("profile v2", encoding="utf-8")
    body = rubric.load_or_build(intent, rub, agent)
    assert "Never surface contract roles." in body
    assert "Never surface contract roles." in rub.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_rubric.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rubric'`

- [ ] **Step 3: Write the implementation**

Create `rubric.py`:

```python
# rubric.py
"""Compress intent.md into a screening rubric the local tier can afford.

intent.md is ~36.5k tokens — too slow to send per job and too nuanced for a
mid-size local model. Claude distils it once into ~1-2k tokens of hard
constraints and signals, cached until intent.md changes.

rubric.md is gitignored: it is intent.md in compressed form, so it is personal
data under the same invariant.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

HUMAN_BEGIN = "<!-- BEGIN human -->"
HUMAN_END = "<!-- END human -->"
_HASH_PREFIX = "<!-- intent-sha256: "
_HASH_SUFFIX = " -->"

_SYSTEM = (
    "You compress a candidate's full career profile into a compact screening "
    "rubric for an automated job filter. Reply with a JSON object: "
    '{"rubric": str}. The rubric is markdown, under 400 lines, and contains '
    "only what is needed to judge a job posting: hard disqualifiers, target "
    "role archetypes, positive signals, negative signals, and the compensation "
    "floor. Omit biography, evidence, and narrative — the filter cannot use them."
)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _extract(text: str, begin: str, end: str) -> str:
    start, stop = text.find(begin), text.find(end)
    if start == -1 or stop == -1 or stop < start:
        return ""
    return text[start + len(begin):stop].strip()


def _stored_hash(text: str) -> str:
    line = _extract(text, _HASH_PREFIX, _HASH_SUFFIX)
    return line.strip()


def _render(body: str, human: str, intent_hash: str) -> str:
    return (
        "# Screening Rubric\n\n"
        f"{_HASH_PREFIX}{intent_hash}{_HASH_SUFFIX}\n\n"
        "> Generated from intent.md by rubric.py and overwritten whenever\n"
        "> intent.md changes. Only the block between the `human` markers is\n"
        "> hand-authored; it is carried through untouched.\n\n"
        f"{HUMAN_BEGIN}\n\n{human}\n\n{HUMAN_END}\n\n"
        "---\n\n"
        f"{body.strip()}\n"
    )


def load_or_build(intent_path: Path, rubric_path: Path, agent) -> str:
    """Return the rubric text, regenerating it only when intent.md has changed.

    `agent` is anything exposing chat_json(system, user) -> dict — in practice
    ClaudeAgent, because distillation is a judgement task worth a good model."""
    intent_text = intent_path.read_text(encoding="utf-8")
    intent_hash = _hash(intent_text)

    human = ""
    if rubric_path.exists():
        existing = rubric_path.read_text(encoding="utf-8")
        if _stored_hash(existing) == intent_hash:
            return existing
        human = _extract(existing, HUMAN_BEGIN, HUMAN_END)

    data = agent.chat_json(_SYSTEM, intent_text)
    body = str(data.get("rubric") or "").strip()
    if not body:
        raise SystemExit("Rubric distillation returned nothing. Re-run, or write "
                         f"{rubric_path} by hand.")
    rubric_path.write_text(_render(body, human, intent_hash), encoding="utf-8")
    return rubric_path.read_text(encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_rubric.py -v`
Expected: PASS, 4 passed

- [ ] **Step 5: Commit**

```bash
git add rubric.py tests/test_rubric.py
git commit -m "feat: distil intent.md into a cached screening rubric"
```

---

### Task 5: Screening CLI

**Files:**
- Create: `screen.py`
- Test: `tests/test_screen.py`

**Interfaces:**
- Consumes: `db.jobs_by_status`, `db.set_screen` (Task 2); `local_agent.LocalAgent`, `LocalUnavailable` (Task 3); `rubric.load_or_build` (Task 4).
- Produces: `screen.run_screening(conn, *, rubric_text: str, agent, threshold: int) -> None` and a `click` CLI.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_screen.py`:

```python
# tests/test_screen.py
import pytest

import db as dbmod
import screen
from db import Job
from local_agent import LocalUnavailable


class _FakeAgent:
    def __init__(self, score=None, exc=None):
        self.score, self.exc = score, exc

    def chat_json(self, system, user):
        if self.exc:
            raise self.exc
        return {"fit_score": self.score, "reason": "because"}


def _conn(tmp_path, n=1):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    for i in range(n):
        dbmod.insert_job(conn, Job(url=f"https://x/{i}", company="Acme",
                                   title="ML Engineer", location="NYC",
                                   source="ats:greenhouse", ats="greenhouse",
                                   raw_text="build ml systems"))
    return conn


def test_score_above_threshold_is_screened_in(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=80),
                         threshold=25)
    jobs = dbmod.jobs_by_status(conn, "screened_in")
    assert len(jobs) == 1 and jobs[0].fit_score == 80
    assert jobs[0].screen_reason == "because"


def test_score_below_threshold_is_screened_out_with_reason(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=5),
                         threshold=25)
    jobs = dbmod.jobs_by_status(conn, "screened_out")
    assert len(jobs) == 1
    assert jobs[0].screen_reason == "because"   # rejections stay auditable


def test_score_equal_to_threshold_is_promoted(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(conn, rubric_text="r", agent=_FakeAgent(score=25),
                         threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screened_in")) == 1


def test_per_job_failure_marks_screen_error_and_continues(tmp_path):
    conn = _conn(tmp_path, n=2)
    screen.run_screening(conn, rubric_text="r",
                         agent=_FakeAgent(exc=RuntimeError("bad json")),
                         threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screen_error")) == 2


def test_unavailable_agent_stops_the_batch(tmp_path):
    conn = _conn(tmp_path, n=3)
    with pytest.raises(LocalUnavailable):
        screen.run_screening(conn, rubric_text="r",
                             agent=_FakeAgent(exc=LocalUnavailable("no ollama")),
                             threshold=25)
    assert len(dbmod.jobs_by_status(conn, "screen_error")) == 0
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_screen.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'screen'`

- [ ] **Step 3: Write the implementation**

Create `screen.py`:

```python
# screen.py
"""Local screening tier: grade every discovered job 0-100 against the rubric.

Replaces the deleted regex pre-filter. Cheap enough to run over everything, so
nothing is rejected without a model having read it and left a reason.
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
import rubric as rubricmod
from claude_agent import ClaudeAgent
from db import Job
from local_agent import LocalAgent, LocalUnavailable

load_dotenv()
log = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 25   # deliberately generous until calibrate.py says otherwise

_SYSTEM = (
    "You screen job postings for one candidate against the rubric below. "
    'Reply with a JSON object: {"fit_score": int 0-100, "reason": str}. '
    "fit_score is how well the posting matches the rubric: 0 means it violates "
    "a hard disqualifier, 100 means it hits every target signal. Keep reason to "
    "one sentence. Judge only against the rubric."
)


def _prompt(job: Job, rubric_text: str) -> str:
    return (
        f"# Rubric\n{rubric_text}\n\n"
        f"# Job posting\nCompany: {job.company}\nTitle: {job.title}\n"
        f"Location: {job.location}\n\n{job.raw_text[:6000]}"
    )


def run_screening(conn: sqlite3.Connection, *, rubric_text: str, agent,
                  threshold: int) -> None:
    """Screen every `discovered` job into screened_in / screened_out / screen_error."""
    for job in dbmod.jobs_by_status(conn, "discovered"):
        try:
            data = agent.chat_json(_SYSTEM, _prompt(job, rubric_text))
            score = int(data.get("fit_score", 0))
            reason = str(data.get("reason", ""))
        except LocalUnavailable:
            raise  # fail-fast: every remaining job would fail identically
        except Exception as exc:  # noqa: BLE001 — visible, never a silent default
            log.warning("screening failed for %s: %s", job.title, exc)
            dbmod.set_screen(conn, job.id, status="screen_error", fit_score=None,
                             screen_reason=str(exc)[:200])
            continue
        status = "screened_in" if score >= threshold else "screened_out"
        dbmod.set_screen(conn, job.id, status=status, fit_score=score,
                         screen_reason=reason)


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
@click.option("--rubric", "rubric_path", default="rubric.md", type=Path)
@click.option("--threshold", default=None, type=int,
              envvar="HUNTER8_SCREEN_THRESHOLD")
@click.option("--model", "model", default=None, envvar="HUNTER8_SCREEN_MODEL",
              required=True)
def main(db_path: Path | None, intent_path: Path, rubric_path: Path,
         threshold: int | None, model: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rubric_text = rubricmod.load_or_build(intent_path, rubric_path, ClaudeAgent())
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    run_screening(conn, rubric_text=rubric_text, agent=LocalAgent(model=model),
                  threshold=threshold if threshold is not None else DEFAULT_THRESHOLD)
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("screened_in", "screened_out", "screen_error")}
    click.echo(f"Screening complete: {counts}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_screen.py -v`
Expected: PASS, 5 passed

- [ ] **Step 5: Commit**

```bash
git add screen.py tests/test_screen.py
git commit -m "feat: local screening tier replaces the regex pre-filter"
```

---

### Task 6: Rewire the Claude tier

**Files:**
- Modify: `score.py` (delete `passes_rules` and the four regex blocks; read `screened_in`; add `--limit` and ordering)
- Modify: `tests/test_score.py`
- Test: `tests/test_score.py`

**Interfaces:**
- Consumes: `db.jobs_by_status(order_by=, limit=)` (Task 2); the `screened_in` status (Task 5).
- Produces: `score.run_scoring(conn, *, intent_md, agent, limit=None) -> None`.

- [ ] **Step 1: Update the tests first**

In `tests/test_score.py`, delete the five `passes_rules` tests (`test_passes_rules_accepts_ml_engineer_remote` through `test_passes_rules_rejects_non_us_location`) and the `_job` helper's use by them. Keep `_job`. Then replace the three `run_scoring` tests with these, and add the new limit test:

```python
def _screened(conn, title, score, url=None):
    job = _job(title, url=url)
    dbmod.insert_job(conn, job)
    stored = [j for j in dbmod.jobs_by_status(conn, "discovered")
              if j.url == job.url][0]
    dbmod.set_screen(conn, stored.id, status="screened_in", fit_score=score,
                     screen_reason="r")


def test_run_scoring_grades_screened_in_jobs(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "Machine Learning Engineer", 80)
    _screened(conn, "AI Engineer", 60)

    agent = _FakeAgent(verdict={
        "grade": "B", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "scored")) == 2


def test_run_scoring_marks_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 70)
    agent = _FakeAgent(exc=RuntimeError("agent down"))
    score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 1


def test_run_scoring_fails_fast_when_agent_unavailable(tmp_path):
    """Out of quota or logged out — every remaining job fails the same way."""
    import pytest
    from claude_agent import ClaudeUnavailable
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 70)
    agent = _FakeAgent(exc=ClaudeUnavailable("claude usage limit reached"))
    with pytest.raises(ClaudeUnavailable):
        score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 0


def test_run_scoring_limit_takes_highest_fit_scores_first(tmp_path):
    """A capped run must spend the quota on the most promising jobs."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "Low Fit AI Engineer", 30, url="https://x/low")
    _screened(conn, "High Fit AI Engineer", 95, url="https://x/high")

    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    score.run_scoring(conn, intent_md="intent", agent=agent, limit=1)

    scored = dbmod.jobs_by_status(conn, "scored")
    assert len(scored) == 1 and scored[0].url == "https://x/high"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_score.py -v`
Expected: FAIL — `test_run_scoring_grades_screened_in_jobs` finds 0 scored, because `run_scoring` still reads `discovered`.

- [ ] **Step 3: Delete the regex pre-filter**

In `score.py`, delete: the `import re` line, the four compiled regexes (`_TITLE_INCLUDE`, `_TITLE_EXCLUDE`, `_US_LOCATION`, `_NON_US`), and the entire `passes_rules` function.

- [ ] **Step 4: Rewire `run_scoring`**

Replace `run_scoring` in `score.py` with:

```python
def run_scoring(conn: sqlite3.Connection, *, intent_md: str, agent: ClaudeAgent,
                limit: int | None = None) -> None:
    """Grade screened_in jobs with Claude, best fit first.

    Ordering and `limit` matter: each Claude call carries ~43k tokens of harness
    overhead, so a capped run must spend the quota on the most promising jobs
    rather than on whatever id happens to be lowest."""
    jobs = dbmod.jobs_by_status(conn, "screened_in",
                                order_by="fit_score DESC", limit=limit)
    for job in jobs:
        try:
            v = grade_job(job, intent_md=intent_md, agent=agent)
        except ClaudeUnavailable:
            raise  # fail-fast: not logged in or out of quota — every job would fail
        except Exception as exc:  # noqa: BLE001 — visible, never a silent default
            log.warning("scoring failed for %s: %s", job.title, exc)
            dbmod.set_score(conn, job.id, status="score_error", grade=None,
                            reasoning=str(exc)[:200], archetype=None,
                            comp_signal=None, red_flags=None)
            continue
        dbmod.set_score(conn, job.id, status="scored", grade=v.grade,
                        reasoning=v.reasoning, archetype=v.archetype,
                        comp_signal=v.comp_signal,
                        red_flags=json.dumps(v.red_flags))
```

- [ ] **Step 5: Add the `--limit` option to the CLI**

In `score.py`'s `main`, add the option and thread it through. Add above the existing `--intent` option:

```python
@click.option("--limit", default=None, type=int,
              help="Grade at most N jobs, highest fit_score first.")
```

Change `main`'s signature to `def main(db_path: Path | None, limit: int | None, intent_path: Path) -> None:` and its `run_scoring` call to:

```python
    run_scoring(conn, intent_md=intent_path.read_text(), agent=agent, limit=limit)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_score.py -v`
Expected: PASS, 4 passed

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, all tests green

- [ ] **Step 8: Commit**

```bash
git add score.py tests/test_score.py
git commit -m "feat: Claude tier grades screened_in jobs, best fit first"
```

---

### Task 7: Calibration

**Files:**
- Create: `calibrate.py`
- Test: `tests/test_calibrate.py`

**Interfaces:**
- Consumes: `db.jobs_by_status` (Task 2); `local_agent.LocalAgent` (Task 3); `screen._SYSTEM` and `screen._prompt` (Task 5) so calibration screens exactly the way production does.
- Produces: `calibrate.agreement(rows: list[tuple[str, int]]) -> list[dict]` and `calibrate.collect(conn, *, rubric_text, agent) -> list[tuple[str, int]]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_calibrate.py`:

```python
# tests/test_calibrate.py
import calibrate
import db as dbmod
from db import Job


def test_agreement_reports_recall_per_threshold():
    #      Claude grade, local fit_score
    rows = [("A", 90), ("A", 70), ("B", 60), ("C", 10), ("C", 20)]
    table = {r["threshold"]: r for r in calibrate.agreement(rows)}

    at70 = table[70]
    assert at70["a_recall"] == 1.0        # both A's are >= 70
    assert at70["promoted_fraction"] == 0.4   # 2 of 5

    at80 = table[80]
    assert at80["a_recall"] == 0.5        # the A at 70 would be lost


def test_recommended_threshold_is_highest_with_full_a_recall():
    rows = [("A", 90), ("A", 70), ("C", 10)]
    assert calibrate.recommend(calibrate.agreement(rows)) == 70


def test_collect_does_not_mutate_job_status(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/1", company="Acme",
                               title="ML Engineer", location="NYC",
                               source="ats:greenhouse", ats="greenhouse",
                               raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, job.id, status="scored", grade="A", reasoning="r",
                    archetype="lab", comp_signal="", red_flags="[]")

    class _Agent:
        def chat_json(self, system, user):
            return {"fit_score": 88, "reason": "r"}

    rows = calibrate.collect(conn, rubric_text="r", agent=_Agent())
    assert rows == [("A", 88)]
    assert len(dbmod.jobs_by_status(conn, "scored")) == 1   # untouched
    assert dbmod.jobs_by_status(conn, "scored")[0].fit_score is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_calibrate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'calibrate'`

- [ ] **Step 3: Write the implementation**

Create `calibrate.py`:

```python
# calibrate.py
"""Pick the screening threshold from data instead of guessing.

85 jobs already carry a Claude grade. Running the local screen over them shows
where the A's and B's land, so the promote threshold can be set to the highest
value that still catches every job Claude called an A.
"""
from __future__ import annotations

import logging
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
import rubric as rubricmod
import screen as screenmod
from claude_agent import ClaudeAgent
from local_agent import LocalAgent

load_dotenv()
log = logging.getLogger(__name__)

_THRESHOLDS = list(range(0, 101, 5))


def collect(conn, *, rubric_text: str, agent) -> list:
    """Screen every already-Claude-graded job. Returns (claude_grade, fit_score)
    pairs. Deliberately does not write to the database — calibration must not
    disturb the corpus it is measuring."""
    rows = []
    for job in dbmod.jobs_by_status(conn, "scored"):
        if not job.grade:
            continue
        data = agent.chat_json(screenmod._SYSTEM,
                               screenmod._prompt(job, rubric_text))
        rows.append((job.grade.upper(), int(data.get("fit_score", 0))))
    return rows


def agreement(rows: list) -> list:
    """For each candidate threshold, how much of Claude's judgement survives."""
    a_total = sum(1 for g, _ in rows if g == "A")
    ab_total = sum(1 for g, _ in rows if g in ("A", "B"))
    out = []
    for t in _THRESHOLDS:
        kept = [(g, s) for g, s in rows if s >= t]
        out.append({
            "threshold": t,
            "a_recall": (sum(1 for g, _ in kept if g == "A") / a_total
                         if a_total else 1.0),
            "ab_recall": (sum(1 for g, _ in kept if g in ("A", "B")) / ab_total
                          if ab_total else 1.0),
            "promoted_fraction": len(kept) / len(rows) if rows else 0.0,
        })
    return out


def recommend(table: list) -> int:
    """The highest threshold that still keeps every Claude-A job."""
    full = [r for r in table if r["a_recall"] == 1.0]
    return max(r["threshold"] for r in full) if full else 0


def render(table: list, rows: list) -> str:
    lines = [
        "# Calibration report",
        "",
        f"Sample: {len(rows)} Claude-graded jobs "
        f"({sum(1 for g, _ in rows if g == 'A')} A, "
        f"{sum(1 for g, _ in rows if g == 'B')} B, "
        f"{sum(1 for g, _ in rows if g == 'C')} C)",
        "",
        "| threshold | A recall | A+B recall | promoted |",
        "|---:|---:|---:|---:|",
    ]
    for r in table:
        lines.append(
            f"| {r['threshold']} | {r['a_recall']:.0%} | "
            f"{r['ab_recall']:.0%} | {r['promoted_fraction']:.0%} |")
    rec = recommend(table)
    kept = next(r for r in table if r["threshold"] == rec)
    lines += [
        "",
        f"**Recommended threshold: {rec}** — keeps 100% of Claude-A jobs while "
        f"promoting {kept['promoted_fraction']:.0%} of the corpus.",
        "",
        "Set it with `HUNTER8_SCREEN_THRESHOLD` and write the A-recall figure "
        "into the vision's acceptance criteria.",
    ]
    return "\n".join(lines) + "\n"


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
@click.option("--rubric", "rubric_path", default="rubric.md", type=Path)
@click.option("--out", "out_path", default="calibration-report.md", type=Path)
@click.option("--model", "model", default=None, envvar="HUNTER8_SCREEN_MODEL",
              required=True)
def main(db_path: Path | None, intent_path: Path, rubric_path: Path,
         out_path: Path, model: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    rubric_text = rubricmod.load_or_build(intent_path, rubric_path, ClaudeAgent())
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    rows = collect(conn, rubric_text=rubric_text, agent=LocalAgent(model=model))
    if not rows:
        raise SystemExit("No Claude-graded jobs to calibrate against.")
    table = agreement(rows)
    out_path.write_text(render(table, rows), encoding="utf-8")
    click.echo(f"Wrote {out_path} — recommended threshold {recommend(table)}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calibrate.py -v`
Expected: PASS, 3 passed

- [ ] **Step 5: Commit**

```bash
git add calibrate.py tests/test_calibrate.py
git commit -m "feat: calibrate the screen threshold against Claude-graded jobs"
```

---

### Task 8: Configuration, ignores, and docs

**Files:**
- Modify: `.gitignore`
- Modify: `.env.example`
- Modify: `README.md`

**Interfaces:**
- Consumes: the env vars introduced in Tasks 5 and 7.
- Produces: nothing code-facing.

- [ ] **Step 1: Gitignore the derived personal artifacts**

Add to `.gitignore`, after the `resumes/` line:

```
rubric.md
calibration-report.md
```

- [ ] **Step 2: Add the new env vars**

Add to `.env.example`, after the `HUNTER8_SCORER_MODEL` line:

```
HUNTER8_SCREEN_MODEL=
HUNTER8_SCREEN_THRESHOLD=25
```

- [ ] **Step 3: Update the pipeline section in README.md**

Replace the fenced command block under "## Discovery → Triage → Apply" with:

```bash
python sync_intent.py     # 1. pull your profile/positioning from delapan → intent.md
python discover.py        # 2. poll watchlist ATS boards + Tavily → hunter8.db
python screen.py          # 3. local model grades every job 0-100 against rubric.md
python score.py           # 4. Claude grades the survivors (A/B/C)
python triage.py          # 5. review scored jobs; approve → tracker "To apply" rows
python apply.py           # 6. (existing) submit the approved rows
```

Then add below the existing bullet list:

```markdown
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
```

- [ ] **Step 4: Verify the suite is still green**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add .gitignore .env.example README.md
git commit -m "docs: document the screening tier and its configuration"
```

---

## Rollout (manual, after the code lands)

These are operator steps, not code tasks. Run them in order.

- [ ] **Install Ollama and pull a model.**

```bash
brew install ollama
ollama serve &
ollama pull qwen3:30b-a3b
```

If that tag does not resolve, run `ollama list` after trying a few candidates and use whatever pulls. Target shape: a 14–30B instruct model; a mixture-of-experts model in that range gives large-model quality at small-model speed on Apple Silicon. Record the working tag in `.env` as `HUNTER8_SCREEN_MODEL`.

- [ ] **Generate and correct the rubric.**

```bash
.venv/bin/python calibrate.py --model "$HUNTER8_SCREEN_MODEL"
```

This builds `rubric.md` on the way through. Stop and read it. Where it misrepresents you, edit inside the `BEGIN human` / `END human` markers.

- [ ] **Choose the threshold.** Read `calibration-report.md`, set `HUNTER8_SCREEN_THRESHOLD` in `.env`, and copy the A-recall figure into the acceptance criteria in `docs/truenorth/vision.md`, replacing the deliberately-unset note.

If no threshold reaches 100% A-recall at a useful promotion rate, try a larger model before continuing — the tier boundary is not yet trustworthy.

- [ ] **Reset the regex rejections so they get a fair hearing.**

```bash
.venv/bin/python -c "
import db
c = db.connect('hunter8.db'); db.init_db(c)
n = c.execute(\"UPDATE jobs SET status='discovered' WHERE status='filtered_out'\").rowcount
c.commit(); print('requeued', n)
"
```

Expected: `requeued 2605`

- [ ] **Bulk-screen everything.** `.venv/bin/python screen.py` — roughly 1–2 hours unattended for ~2,847 jobs.

- [ ] **Grade the finalists incrementally.** `.venv/bin/python score.py --limit 50`, repeated across quota windows. Do not run it uncapped on the first pass.

- [ ] **Triage and close the loop.** `.venv/bin/python triage.py` — the first jobs ever to reach the apply queue.

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: rubric → 4, `local_agent` → 3, `screen` → 5, `calibrate` → 7, `score.py` changes → 6, `db.py` changes → 2, shared parser cleanup → 1, error handling → distributed through 3/5/6, testing → in every task, rollout and the quota-cliff risk → the Rollout section, gitignore and docs → 8.

**Placeholders.** None. Every code step carries the code; every command carries its expected output. The one deferred value — the Ollama model tag — is deferred deliberately, with a concrete candidate and a fallback procedure, because an unverified tag in a plan becomes a wrong tag in a shell.

**Type consistency.** `chat_json(system, user) -> dict` is identical across both agents. `fit_score` is `int` everywhere. `set_screen(conn, job_id, *, status, fit_score, screen_reason)` is called with exactly those keywords in Tasks 5 and 6's tests. `jobs_by_status(conn, status, *, order_by, limit)` — `order_by` is whitelisted to `"fit_score DESC"`, the only value Task 6 passes. `run_scoring(conn, *, intent_md, agent, limit=None)` matches its call in Task 6 Step 5.

**One deliberate coupling.** `calibrate.py` imports `screen._SYSTEM` and `screen._prompt` — private names. That is intentional: calibration is only meaningful if it screens *exactly* the way production does, and duplicating the prompt would silently invalidate the threshold the moment either copy drifted.
