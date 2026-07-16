# Job Discovery & Triage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the front half of the automated job search to hunter8 — discover roles from ATS APIs + Tavily, score fit against Anthony's delapan-KB intent, and HITL-triage approved roles into the existing Excel apply queue.

**Architecture:** Flat CLI toolkit extending hunter8. New root modules (`db.py`, `sources.py`, `watchlist.py`, `gateway.py`, `discover.py`, `score.py`, `triage.py`, `sync_intent.py`) write to a SQLite store (`hunter8.db`) and, on approval, append "To apply" rows to the existing tracker Excel — which `apply.py` already consumes unchanged.

**Tech Stack:** Python 3.11, sqlite3 (stdlib), httpx, pyyaml, openai (OpenAI-compatible client for the Vercel AI Gateway), openpyxl, click, pytest.

**Spec:** `docs/superpowers/specs/2026-07-16-job-discovery-triage-design.md`

---

## File structure

**Create:**
- `db.py` — SQLite schema, `Job` dataclass, connect/init/insert(dedup)/read/update helpers.
- `sources.py` — pure ATS response parsers + thin httpx fetchers for Greenhouse/Ashby/Lever + Tavily.
- `watchlist.py` — load/validate `watchlist.yaml` into typed configs.
- `watchlist.yaml` — seeded company watchlist + Tavily query templates (user-owned after seed).
- `gateway.py` — OpenAI-compatible chat-JSON client for the Vercel AI Gateway; explicit 402 handling.
- `discover.py` — CLI: watchlist + Tavily → `hunter8.db` (status `discovered`).
- `score.py` — rules pre-filter + LLM grader; CLI over `discovered` jobs.
- `sync_intent.py` — CLI: pull Profile & Positioning findings from delapan (Supabase REST) → `intent.md`.
- `intent.md` — generated scorer input (checked in, human-editable).
- Tests: `tests/test_db.py`, `tests/test_sources.py`, `tests/test_watchlist.py`, `tests/test_gateway.py`, `tests/test_score.py`, `tests/test_triage.py`, `tests/test_sync_intent.py`.
- Fixtures: `tests/fixtures/greenhouse.json`, `tests/fixtures/ashby.json`, `tests/fixtures/lever.json`.

**Modify:**
- `tracker.py` — add `append_application(...)`.
- `triage.py` — created (CLI), depends on `db.py` + `tracker.append_application`.
- `requirements.txt` — add `httpx`, `pyyaml`.
- `README.md` — document the discovery → triage → apply flow.

**Unchanged:** `apply.py`, `handlers/*`, `resume_builder.py`, `candidate_profile.py`, `conftest.py`.

---

## Shared contracts (defined once, referenced by later tasks)

`Job` dataclass (in `db.py`):

```python
@dataclass
class Job:
    url: str
    company: str
    title: str
    location: str
    source: str                     # 'ats:greenhouse'|'ats:ashby'|'ats:lever'|'tavily'
    ats: str | None = None          # 'greenhouse'|'ashby'|'lever'|None
    posted_at: str | None = None
    raw_text: str = ""
    id: int | None = None
    status: str = "discovered"
    grade: str | None = None
    reasoning: str | None = None
    archetype: str | None = None
    comp_signal: str | None = None
    red_flags: str | None = None
    discovered_at: str | None = None
    scored_at: str | None = None
    triaged_at: str | None = None
```

`Verdict` dataclass (in `score.py`):

```python
@dataclass
class Verdict:
    grade: str                      # 'A'|'B'|'C'
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: list[str]
```

Status values: `discovered`, `filtered_out`, `scored`, `score_error`, `approved`, `skipped`, `snoozed`.

---

## Task 1: SQLite store (`db.py`)

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_db.py
import db as dbmod


def _job(url="https://x/1", company="Acme", title="ML Engineer"):
    return dbmod.Job(url=url, company=company, title=title,
                     location="Remote US", source="ats:greenhouse", ats="greenhouse",
                     raw_text="desc")


def test_init_and_insert(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert dbmod.insert_job(conn, _job()) is True


def test_insert_is_deduped_on_url(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert dbmod.insert_job(conn, _job()) is True
    assert dbmod.insert_job(conn, _job()) is False
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def test_set_score_moves_to_scored(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, job.id, status="scored", grade="A",
                    reasoning="great fit", archetype="ai-finance-startup",
                    comp_signal="$180k+", red_flags="")
    scored = dbmod.jobs_by_status(conn, "scored")
    assert len(scored) == 1 and scored[0].grade == "A"


def test_set_triage_records_status(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_triage(conn, job.id, status="approved")
    assert len(dbmod.jobs_by_status(conn, "approved")) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'db'`.

- [ ] **Step 3: Write `db.py`**

```python
# db.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = "hunter8.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id            INTEGER PRIMARY KEY,
  url           TEXT UNIQUE NOT NULL,
  company       TEXT NOT NULL,
  title         TEXT NOT NULL,
  location      TEXT,
  source        TEXT NOT NULL,
  ats           TEXT,
  posted_at     TEXT,
  raw_text      TEXT,
  status        TEXT NOT NULL,
  grade         TEXT,
  reasoning     TEXT,
  archetype     TEXT,
  comp_signal   TEXT,
  red_flags     TEXT,
  discovered_at TEXT NOT NULL,
  scored_at     TEXT,
  triaged_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


@dataclass
class Job:
    url: str
    company: str
    title: str
    location: str
    source: str
    ats: str | None = None
    posted_at: str | None = None
    raw_text: str = ""
    id: int | None = None
    status: str = "discovered"
    grade: str | None = None
    reasoning: str | None = None
    archetype: str | None = None
    comp_signal: str | None = None
    red_flags: str | None = None
    discovered_at: str | None = None
    scored_at: str | None = None
    triaged_at: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: str | Path = DEFAULT_DB) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def insert_job(conn: sqlite3.Connection, job: Job) -> bool:
    """Insert a discovered job. Returns True if inserted, False if the URL was
    already present (dedup)."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO jobs
           (url, company, title, location, source, ats, posted_at, raw_text,
            status, discovered_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (job.url, job.company, job.title, job.location, job.source, job.ats,
         job.posted_at, job.raw_text, "discovered", _now()),
    )
    conn.commit()
    return cur.rowcount == 1


def _row_to_job(row: sqlite3.Row) -> Job:
    names = {f.name for f in fields(Job)}
    return Job(**{k: row[k] for k in row.keys() if k in names})


def jobs_by_status(conn: sqlite3.Connection, status: str) -> list[Job]:
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status=? ORDER BY id", (status,)
    ).fetchall()
    return [_row_to_job(r) for r in rows]


def set_score(
    conn: sqlite3.Connection, job_id: int, *, status: str, grade: str | None,
    reasoning: str | None, archetype: str | None, comp_signal: str | None,
    red_flags: str | None,
) -> None:
    conn.execute(
        """UPDATE jobs SET status=?, grade=?, reasoning=?, archetype=?,
           comp_signal=?, red_flags=?, scored_at=? WHERE id=?""",
        (status, grade, reasoning, archetype, comp_signal, red_flags, _now(), job_id),
    )
    conn.commit()


def set_triage(conn: sqlite3.Connection, job_id: int, *, status: str) -> None:
    conn.execute(
        "UPDATE jobs SET status=?, triaged_at=? WHERE id=?", (status, _now(), job_id)
    )
    conn.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: SQLite store for discovered jobs with URL dedup"
```

---

## Task 2: ATS response parsers (`sources.py` — pure functions)

**Files:**
- Create: `sources.py`, `tests/fixtures/greenhouse.json`, `tests/fixtures/ashby.json`, `tests/fixtures/lever.json`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Write the fixtures**

`tests/fixtures/greenhouse.json`:

```json
{"jobs": [
  {"id": 4017331008,
   "title": "Research Engineer, Agents",
   "location": {"name": "San Francisco, CA"},
   "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/4017331008",
   "updated_at": "2026-07-10T12:00:00Z",
   "content": "Build agentic systems. Python, LLMs, RAG."}
]}
```

`tests/fixtures/ashby.json`:

```json
{"jobs": [
  {"id": "abc-123",
   "title": "ML Engineer, Applied",
   "location": "Remote (US)",
   "jobUrl": "https://jobs.ashbyhq.com/acme/abc-123",
   "publishedAt": "2026-07-11T00:00:00Z",
   "descriptionPlain": "LLM orchestration, knowledge graphs, fintech."}
]}
```

`tests/fixtures/lever.json`:

```json
[
  {"id": "def-456",
   "text": "Staff ML Engineer",
   "categories": {"location": "New York, NY", "team": "AI"},
   "hostedUrl": "https://jobs.lever.co/acme/def-456",
   "createdAt": 1752000000000,
   "descriptionPlain": "Production ML, agents, distributed systems."}
]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_sources.py
import json
from pathlib import Path

import sources

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_parse_greenhouse():
    jobs = sources.parse_greenhouse(_load("greenhouse.json"), company="Acme")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Acme"
    assert j.title == "Research Engineer, Agents"
    assert j.location == "San Francisco, CA"
    assert j.url == "https://job-boards.greenhouse.io/acme/jobs/4017331008"
    assert j.source == "ats:greenhouse" and j.ats == "greenhouse"
    assert "agentic" in j.raw_text.lower()


def test_parse_ashby():
    jobs = sources.parse_ashby(_load("ashby.json"), company="Acme")
    j = jobs[0]
    assert j.title == "ML Engineer, Applied"
    assert j.url == "https://jobs.ashbyhq.com/acme/abc-123"
    assert j.ats == "ashby"


def test_parse_lever():
    jobs = sources.parse_lever(_load("lever.json"), company="Acme")
    j = jobs[0]
    assert j.title == "Staff ML Engineer"
    assert j.location == "New York, NY"
    assert j.url == "https://jobs.lever.co/acme/def-456"
    assert j.ats == "lever"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sources'`.

- [ ] **Step 4: Write the parsers in `sources.py`**

```python
# sources.py
from __future__ import annotations

from typing import Any

from db import Job


def parse_greenhouse(payload: dict[str, Any], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Job(
            url=j["absolute_url"], company=company, title=j.get("title", ""),
            location=loc, source="ats:greenhouse", ats="greenhouse",
            posted_at=j.get("updated_at"), raw_text=j.get("content", "") or "",
        ))
    return out


def parse_ashby(payload: dict[str, Any], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload.get("jobs", []):
        loc = j.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name", "")
        out.append(Job(
            url=j["jobUrl"], company=company, title=j.get("title", ""),
            location=loc or "", source="ats:ashby", ats="ashby",
            posted_at=j.get("publishedAt"),
            raw_text=j.get("descriptionPlain", "") or "",
        ))
    return out


def parse_lever(payload: list[dict[str, Any]], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload:
        cats = j.get("categories") or {}
        out.append(Job(
            url=j["hostedUrl"], company=company, title=j.get("text", ""),
            location=cats.get("location", ""), source="ats:lever", ats="lever",
            posted_at=str(j.get("createdAt", "")) or None,
            raw_text=j.get("descriptionPlain", "") or "",
        ))
    return out
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add sources.py tests/test_sources.py tests/fixtures/
git commit -m "feat: pure ATS response parsers (greenhouse/ashby/lever)"
```

---

## Task 3: ATS + Tavily fetchers (`sources.py` — HTTP)

**Files:**
- Modify: `sources.py`
- Test: `tests/test_sources.py`

- [ ] **Step 1: Add failing tests (append to `tests/test_sources.py`)**

```python
def test_fetch_greenhouse_builds_url_and_parses(monkeypatch):
    payload = _load("greenhouse.json")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return payload

    called = {}

    def fake_get(url, timeout):
        called["url"] = url
        return FakeResp()

    monkeypatch.setattr(sources.httpx, "get", fake_get)
    jobs = sources.fetch_ats("greenhouse", board="acme", company="Acme")
    assert "boards-api.greenhouse.io/v1/boards/acme/jobs" in called["url"]
    assert jobs[0].company == "Acme"


def test_fetch_ats_bad_ats_raises():
    import pytest
    with pytest.raises(ValueError):
        sources.fetch_ats("workday", board="x", company="X")
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_sources.py -k fetch -v`
Expected: FAIL — `AttributeError: module 'sources' has no attribute 'httpx'` / `fetch_ats` undefined.

- [ ] **Step 3: Add fetchers to `sources.py`**

Add at top imports and functions:

```python
import httpx

_ATS_URL = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true",
    "lever": "https://api.lever.co/v0/postings/{board}?mode=json",
}

_PARSERS = {
    "greenhouse": parse_greenhouse,
    "ashby": parse_ashby,
    "lever": parse_lever,
}


def fetch_ats(ats: str, *, board: str, company: str, timeout: float = 20.0) -> list[Job]:
    """Fetch + parse one company's board. Raises ValueError for unknown ATS;
    lets httpx errors propagate to the caller (discover.py handles per-company)."""
    if ats not in _ATS_URL:
        raise ValueError(f"unsupported ATS: {ats}")
    url = _ATS_URL[ats].format(board=board)
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    return _PARSERS[ats](resp.json(), company=company)


def fetch_tavily(query: str, api_key: str, *, max_results: int = 5,
                 timeout: float = 30.0) -> list[Job]:
    """Tavily search → Job rows (source='tavily', ats=None). URL is the result
    link; raw_text is the result content."""
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": max_results,
              "search_depth": "basic"},
        timeout=timeout,
    )
    resp.raise_for_status()
    out: list[Job] = []
    for r in resp.json().get("results", []):
        out.append(Job(
            url=r["url"], company="(tavily)", title=r.get("title", "")[:200],
            location="", source="tavily", ats=None,
            raw_text=r.get("content", "") or "",
        ))
    return out
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_sources.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add sources.py tests/test_sources.py
git commit -m "feat: ATS + Tavily HTTP fetchers"
```

---

## Task 4: Watchlist config (`watchlist.py` + seed `watchlist.yaml`)

**Files:**
- Create: `watchlist.py`, `watchlist.yaml`
- Modify: `requirements.txt` (add `pyyaml`, `httpx`)
- Test: `tests/test_watchlist.py`

- [ ] **Step 1: Add deps and install**

Append to `requirements.txt`:

```
httpx==0.27.0
pyyaml==6.0.1
```

Run: `.venv/bin/pip install httpx==0.27.0 pyyaml==6.0.1`
Expected: both install successfully.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_watchlist.py
import watchlist


def test_load_parses_companies_and_queries(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text(
        "companies:\n"
        "  - name: Hebbia\n"
        "    ats: greenhouse\n"
        "    board: hebbia\n"
        "    archetype: ai-finance-startup\n"
        "tavily_queries:\n"
        "  - 'research engineer agentic AI'\n"
    )
    wl = watchlist.load_watchlist(p)
    assert wl.companies[0].name == "Hebbia"
    assert wl.companies[0].ats == "greenhouse"
    assert wl.tavily_queries == ["research engineer agentic AI"]


def test_load_rejects_bad_ats(tmp_path):
    import pytest
    p = tmp_path / "w.yaml"
    p.write_text(
        "companies:\n  - name: X\n    ats: workday\n    board: x\n    archetype: lab\n"
    )
    with pytest.raises(ValueError):
        watchlist.load_watchlist(p)
```

- [ ] **Step 3: Run to verify fail**

Run: `.venv/bin/pytest tests/test_watchlist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'watchlist'`.

- [ ] **Step 4: Write `watchlist.py`**

```python
# watchlist.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_VALID_ATS = {"greenhouse", "ashby", "lever"}


@dataclass
class Company:
    name: str
    ats: str
    board: str
    archetype: str


@dataclass
class Watchlist:
    companies: list[Company] = field(default_factory=list)
    tavily_queries: list[str] = field(default_factory=list)


def load_watchlist(path: str | Path) -> Watchlist:
    data = yaml.safe_load(Path(path).read_text()) or {}
    companies: list[Company] = []
    for c in data.get("companies", []):
        ats = c.get("ats")
        if ats not in _VALID_ATS:
            raise ValueError(f"{c.get('name')}: unsupported ats {ats!r}")
        companies.append(Company(
            name=c["name"], ats=ats, board=c["board"],
            archetype=c.get("archetype", ""),
        ))
    return Watchlist(companies=companies, tavily_queries=data.get("tavily_queries", []))
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/pytest tests/test_watchlist.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Seed `watchlist.yaml`**

Write the seed file (companies drawn from Market & Role Intel KB postings + archetypes; boards are ATS tokens the implementer confirms against each company's live board URL, correcting any that 404 during the first `discover.py` run):

```yaml
# hunter8 discovery watchlist — seeded from delapan KB "Market & Role Intel".
# Edit freely. `ats` ∈ greenhouse|ashby|lever; `board` is the ATS board token.
companies:
  - name: Hebbia
    ats: ashby
    board: hebbia
    archetype: ai-finance-startup
  - name: Rogo
    ats: ashby
    board: rogo
    archetype: ai-finance-startup
  - name: Anthropic
    ats: greenhouse
    board: anthropic
    archetype: lab
tavily_queries:
  - '"research engineer" agentic AI hiring 2026'
  - 'ML engineer "knowledge graph" fintech job posting 2026'
  - '"applied AI" engineer LLM RAG remote US job'
```

- [ ] **Step 7: Commit**

```bash
git add watchlist.py watchlist.yaml requirements.txt tests/test_watchlist.py
git commit -m "feat: watchlist config loader + KB-seeded watchlist.yaml"
```

---

## Task 5: Discovery CLI (`discover.py`)

**Files:**
- Create: `discover.py`
- Test: `tests/test_discover.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discover.py
import db as dbmod
import discover
import sources
from db import Job


def test_run_discovery_inserts_and_dedupes(tmp_path, monkeypatch):
    wl_path = tmp_path / "w.yaml"
    wl_path.write_text(
        "companies:\n  - name: Acme\n    ats: greenhouse\n    board: acme\n"
        "    archetype: lab\n"
    )
    db_path = tmp_path / "h.db"

    def fake_fetch_ats(ats, *, board, company, timeout=20.0):
        return [Job(url="https://x/1", company=company, title="ML Engineer",
                    location="Remote US", source="ats:greenhouse", ats="greenhouse",
                    raw_text="d")]

    monkeypatch.setattr(discover.sources, "fetch_ats", fake_fetch_ats)

    n1 = discover.run_discovery(wl_path, db_path, tavily_key=None)
    n2 = discover.run_discovery(wl_path, db_path, tavily_key=None)
    assert n1 == 1
    assert n2 == 0  # deduped on second run

    conn = dbmod.connect(db_path)
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def test_run_discovery_continues_past_failing_company(tmp_path, monkeypatch):
    wl_path = tmp_path / "w.yaml"
    wl_path.write_text(
        "companies:\n"
        "  - name: Bad\n    ats: greenhouse\n    board: bad\n    archetype: lab\n"
        "  - name: Good\n    ats: greenhouse\n    board: good\n    archetype: lab\n"
    )

    def fake_fetch_ats(ats, *, board, company, timeout=20.0):
        if company == "Bad":
            raise RuntimeError("boom")
        return [Job(url="https://x/2", company=company, title="T", location="",
                    source="ats:greenhouse", ats="greenhouse", raw_text="d")]

    monkeypatch.setattr(discover.sources, "fetch_ats", fake_fetch_ats)
    n = discover.run_discovery(wl_path, tmp_path / "h.db", tavily_key=None)
    assert n == 1  # Good succeeded despite Bad failing
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_discover.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'discover'`.

- [ ] **Step 3: Write `discover.py`**

```python
# discover.py
from __future__ import annotations

import logging
import os
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
import sources
from watchlist import load_watchlist

load_dotenv()
log = logging.getLogger(__name__)


def run_discovery(watchlist_path: str | Path, db_path: str | Path,
                  tavily_key: str | None) -> int:
    """Fetch every watchlist company + Tavily query, insert new jobs. Returns the
    count of newly inserted (deduped) jobs. Per-source failures are logged and
    skipped, never fatal."""
    wl = load_watchlist(watchlist_path)
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)

    inserted = 0
    failures: list[str] = []

    for c in wl.companies:
        try:
            jobs = sources.fetch_ats(c.ats, board=c.board, company=c.name)
        except Exception as exc:  # noqa: BLE001 — one bad board must not abort the run
            failures.append(f"{c.name} ({c.ats}/{c.board}): {exc}")
            log.warning("fetch failed for %s: %s", c.name, exc)
            continue
        for job in jobs:
            if dbmod.insert_job(conn, job):
                inserted += 1

    if tavily_key:
        for q in wl.tavily_queries:
            try:
                jobs = sources.fetch_tavily(q, tavily_key)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"tavily {q!r}: {exc}")
                log.warning("tavily failed for %r: %s", q, exc)
                continue
            for job in jobs:
                if dbmod.insert_job(conn, job):
                    inserted += 1

    if failures:
        log.warning("%d source failure(s):\n  %s", len(failures), "\n  ".join(failures))
    return inserted


@click.command()
@click.option("--watchlist", "watchlist_path", default="watchlist.yaml",
              type=click.Path(exists=True, path_type=Path))
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
def main(watchlist_path: Path, db_path: Path | None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path = db_path or Path(dbmod.DEFAULT_DB)
    tavily_key = os.getenv("TAVILY_API_KEY")
    n = run_discovery(watchlist_path, db_path, tavily_key)
    click.echo(f"Discovery complete: {n} new job(s) queued in {db_path}.")
    if not tavily_key:
        click.echo("(TAVILY_API_KEY not set — skipped web queries.)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_discover.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add discover.py tests/test_discover.py
git commit -m "feat: discovery CLI — watchlist + Tavily into SQLite, fault-tolerant"
```

---

## Task 6: AI Gateway client (`gateway.py`)

**Files:**
- Create: `gateway.py`
- Modify: `requirements.txt` (add `openai`)
- Test: `tests/test_gateway.py`

- [ ] **Step 1: Add dep and install**

Append to `requirements.txt`:

```
openai==1.40.0
```

Run: `.venv/bin/pip install openai==1.40.0`
Expected: installs successfully.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_gateway.py
import json

import pytest

import gateway


class _FakeMessage:
    def __init__(self, content): self.content = content


class _FakeChoice:
    def __init__(self, content): self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content): self.choices = [_FakeChoice(content)]


def test_chat_json_parses_object(monkeypatch):
    def fake_create(**kwargs):
        return _FakeCompletion(json.dumps({"grade": "A"}))

    client = gateway.Gateway(api_key="k", model="m")
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    out = client.chat_json("sys", "user")
    assert out["grade"] == "A"


def test_chat_json_raises_clear_message_on_402(monkeypatch):
    import openai

    def fake_create(**kwargs):
        raise openai.APIStatusError(
            "insufficient_funds", response=_Resp(402), body=None)

    class _Resp:
        def __init__(self, code): self.status_code = code
        request = None

    client = gateway.Gateway(api_key="k", model="m")
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    with pytest.raises(gateway.GatewayError) as ei:
        client.chat_json("sys", "user")
    assert "credit" in str(ei.value).lower()
```

- [ ] **Step 3: Run to verify fail**

Run: `.venv/bin/pytest tests/test_gateway.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gateway'`.

- [ ] **Step 4: Write `gateway.py`**

```python
# gateway.py
from __future__ import annotations

import json

import openai
from openai import OpenAI

DEFAULT_BASE_URL = "https://ai-gateway.vercel.sh/v1"
DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"


class GatewayError(RuntimeError):
    """Raised for gateway failures with an actionable message."""


class Gateway:
    def __init__(self, api_key: str, *, model: str = DEFAULT_MODEL,
                 base_url: str = DEFAULT_BASE_URL) -> None:
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def chat_json(self, system: str, user: str) -> dict:
        """One chat turn expected to return a JSON object. Raises GatewayError with
        a clear message on 402 (out of credit) or unparseable output."""
        try:
            comp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
        except openai.APIStatusError as exc:
            if getattr(exc.response, "status_code", None) == 402:
                raise GatewayError(
                    "AI Gateway has no credit (402). Top up at "
                    "vercel.com → AI → top-up, or set a different key."
                ) from exc
            raise GatewayError(f"AI Gateway error: {exc}") from exc

        content = comp.choices[0].message.content or ""
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise GatewayError(f"Gateway returned non-JSON: {content[:200]!r}") from exc
```

- [ ] **Step 5: Run to verify pass**

Run: `.venv/bin/pytest tests/test_gateway.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add gateway.py requirements.txt tests/test_gateway.py
git commit -m "feat: AI Gateway JSON chat client with explicit 402 handling"
```

---

## Task 7: Rules pre-filter (`score.py` — part 1)

**Files:**
- Create: `score.py`
- Test: `tests/test_score.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_score.py
import score
from db import Job


def _job(title, location="Remote, US"):
    return Job(url="https://x/1", company="Acme", title=title, location=location,
               source="ats:greenhouse", ats="greenhouse", raw_text="desc")


def test_passes_rules_accepts_ml_engineer_remote():
    ok, reason = score.passes_rules(_job("Machine Learning Engineer"))
    assert ok is True


def test_passes_rules_rejects_offtopic_title():
    ok, reason = score.passes_rules(_job("Sales Development Representative"))
    assert ok is False and "title" in reason.lower()


def test_passes_rules_rejects_internship():
    ok, reason = score.passes_rules(_job("ML Engineering Intern"))
    assert ok is False


def test_passes_rules_rejects_hft_core_cpp():
    ok, reason = score.passes_rules(_job("C++ Low-Latency Trading Engineer"))
    assert ok is False


def test_passes_rules_rejects_non_us_location():
    ok, reason = score.passes_rules(_job("ML Engineer", location="London, UK"))
    assert ok is False and "location" in reason.lower()
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_score.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'score'`.

- [ ] **Step 3: Write the rules half of `score.py`**

```python
# score.py
from __future__ import annotations

import re
from dataclasses import dataclass

from db import Job

_TITLE_INCLUDE = re.compile(
    r"\b("
    r"machine learning|ml|ai|artificial intelligence|applied scientist|"
    r"research engineer|applied research|mle|"
    r"agent|agentic|llm|nlp|deep learning|data scientist"
    r")\b",
    re.I,
)
_TITLE_EXCLUDE = re.compile(
    r"\b(intern|internship|sales|recruiter|marketing|account executive|"
    r"low-latency|hft|c\+\+ core)\b",
    re.I,
)
# US-remote or a US location; reject obviously non-US postings.
_US_LOCATION = re.compile(
    r"\b(remote|united states|usa|us\b|new york|nyc|san francisco|sf\b|"
    r"boston|austin|seattle|chicago|los angeles|philadelphia|washington|"
    r", ?[A-Z]{2}\b)",
    re.I,
)
_NON_US = re.compile(
    r"\b(london|uk|united kingdom|canada|toronto|india|bangalore|singapore|"
    r"germany|berlin|france|paris|remote - emea|remote \(emea\))\b",
    re.I,
)


@dataclass
class Verdict:
    grade: str
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: list[str]


def passes_rules(job: Job) -> tuple[bool, str]:
    """Cheap deterministic pre-filter. Returns (survives, reason-if-dropped)."""
    title = job.title or ""
    if _TITLE_EXCLUDE.search(title):
        return False, f"title excluded: {title!r}"
    if not _TITLE_INCLUDE.search(title):
        return False, f"title not a target role: {title!r}"
    loc = job.location or ""
    if loc and _NON_US.search(loc) and not _US_LOCATION.search(loc):
        return False, f"location not US: {loc!r}"
    return True, ""
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_score.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add score.py tests/test_score.py
git commit -m "feat: deterministic rules pre-filter for job fit"
```

---

## Task 8: LLM grader + scoring CLI (`score.py` — part 2)

**Files:**
- Modify: `score.py`
- Test: `tests/test_score.py`

- [ ] **Step 1: Add failing tests (append to `tests/test_score.py`)**

```python
import db as dbmod


class _FakeGateway:
    def __init__(self, verdict=None, exc=None):
        self._verdict, self._exc = verdict, exc

    def chat_json(self, system, user):
        if self._exc:
            raise self._exc
        return self._verdict


def test_grade_job_parses_verdict():
    gw = _FakeGateway(verdict={
        "grade": "A", "reasoning": "agentic + finance", "archetype": "ai-finance-startup",
        "comp_signal": "$180k", "red_flags": []})
    v = score.grade_job(_job("ML Engineer"), intent_md="intent", gateway=gw)
    assert v.grade == "A" and v.archetype == "ai-finance-startup"


def test_run_scoring_filters_scores_and_flags_errors(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job("Machine Learning Engineer"))   # survives → scored
    dbmod.insert_job(conn, _job("Sales Rep", location="Remote US"))  # filtered_out
    from db import Job as J
    dbmod.insert_job(conn, J(url="https://x/err", company="Acme", title="AI Engineer",
                             location="Remote US", source="ats:greenhouse",
                             ats="greenhouse", raw_text="d"))

    gw = _FakeGateway(verdict={
        "grade": "B", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    # Make the error job raise by swapping gateway per-call is overkill; assert the
    # happy path here and error path via monkeypatch below.
    score.run_scoring(conn, intent_md="intent", gateway=gw)
    assert len(dbmod.jobs_by_status(conn, "scored")) == 2
    assert len(dbmod.jobs_by_status(conn, "filtered_out")) == 1


def test_run_scoring_marks_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job("AI Engineer"))
    gw = _FakeGateway(exc=RuntimeError("gateway down"))
    score.run_scoring(conn, intent_md="intent", gateway=gw)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 1
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_score.py -k "grade or run_scoring" -v`
Expected: FAIL — `grade_job` / `run_scoring` undefined.

- [ ] **Step 3: Add grader + orchestrator to `score.py`**

Add imports and functions:

```python
import json
import logging
import os
import sqlite3
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
from gateway import Gateway

load_dotenv()
log = logging.getLogger(__name__)

_SYSTEM = (
    "You grade a job posting for a specific candidate. Reply with a JSON object: "
    '{"grade": "A|B|C", "reasoning": str, "archetype": str, "comp_signal": str, '
    '"red_flags": [str]}. Grade A = strong co-primary fit meeting hard constraints; '
    "B = plausible with friction; C = weak. Use ONLY the candidate intent provided."
)


def grade_job(job: Job, *, intent_md: str, gateway: Gateway) -> Verdict:
    user = (
        f"# Candidate intent\n{intent_md}\n\n"
        f"# Job posting\nCompany: {job.company}\nTitle: {job.title}\n"
        f"Location: {job.location}\n\n{job.raw_text[:6000]}"
    )
    data = gateway.chat_json(_SYSTEM, user)
    return Verdict(
        grade=str(data.get("grade", "C")).strip().upper()[:1] or "C",
        reasoning=str(data.get("reasoning", "")),
        archetype=str(data.get("archetype", "")),
        comp_signal=str(data.get("comp_signal", "")),
        red_flags=list(data.get("red_flags", []) or []),
    )


def run_scoring(conn: sqlite3.Connection, *, intent_md: str, gateway: Gateway) -> None:
    """Score every `discovered` job: rules first, then LLM. Updates status to
    filtered_out / scored / score_error."""
    for job in dbmod.jobs_by_status(conn, "discovered"):
        ok, reason = passes_rules(job)
        if not ok:
            dbmod.set_score(conn, job.id, status="filtered_out", grade=None,
                            reasoning=reason, archetype=None, comp_signal=None,
                            red_flags=None)
            continue
        try:
            v = grade_job(job, intent_md=intent_md, gateway=gateway)
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


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--intent", "intent_path", default="intent.md",
              type=click.Path(exists=True, path_type=Path))
def main(db_path: Path | None, intent_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    key = os.getenv("AI_GATEWAY_API_KEY")
    if not key:
        raise SystemExit("AI_GATEWAY_API_KEY not set.")
    model = os.getenv("HUNTER8_SCORER_MODEL", "anthropic/claude-sonnet-4.5")
    gateway = Gateway(key, model=model)
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    run_scoring(conn, intent_md=intent_path.read_text(), gateway=gateway)
    counts = {s: len(dbmod.jobs_by_status(conn, s))
              for s in ("scored", "filtered_out", "score_error")}
    click.echo(f"Scoring complete: {counts}")


if __name__ == "__main__":
    main()
```

Note: the `Job` type is already imported at the top of `score.py` (Task 7). Ensure the Task 7 import line reads `from db import Job` — it does.

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_score.py -v`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add score.py tests/test_score.py
git commit -m "feat: LLM grader + scoring CLI (rules → grade, visible errors)"
```

---

## Task 9: Tracker append (`tracker.py`)

**Files:**
- Modify: `tracker.py`
- Test: `tests/test_tracker.py` (add tests)

- [ ] **Step 1: Add failing tests (append to `tests/test_tracker.py`)**

```python
def test_append_application_adds_row_with_hyperlink(tmp_tracker):
    from tracker import append_application
    append_application(
        tmp_tracker, company="Hebbia", role="Research Engineer", city="SF",
        url="https://job-boards.greenhouse.io/hebbia/jobs/1", priority="A — strong fit",
        why_fits="agentic AI × finance",
    )
    wb = openpyxl.load_workbook(tmp_tracker)
    ws = wb["Apply Tracker"]
    last = ws.max_row
    assert ws.cell(last, 5).value == "Hebbia"      # Company
    assert ws.cell(last, 6).value == "Research Engineer"  # Role
    assert ws.cell(last, 2).value == "To apply"    # Status
    assert ws.cell(last, 1).value == "A — strong fit"     # Priority
    assert ws.cell(last, 11).hyperlink.target == \
        "https://job-boards.greenhouse.io/hebbia/jobs/1"


def test_append_then_iter_returns_it(tmp_tracker):
    from tracker import append_application, iter_applications
    append_application(
        tmp_tracker, company="Rogo", role="ML Engineer", city="NYC",
        url="https://jobs.ashbyhq.com/rogo/1", priority="A — strong fit",
    )
    companies = [r.company for r in iter_applications(tmp_tracker)]
    assert "Rogo" in companies
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_tracker.py -k append -v`
Expected: FAIL — `ImportError: cannot import name 'append_application'`.

- [ ] **Step 3: Add `append_application` to `tracker.py`**

```python
def append_application(
    tracker_path: Path,
    *,
    company: str,
    role: str,
    city: str,
    url: str,
    priority: str = "A — strong fit",
    why_fits: str = "",
) -> int:
    """Append a new 'To apply' row to the Apply Tracker sheet. Returns the new
    Excel row number. Sets the Link cell's hyperlink so iter_applications picks
    up the URL exactly as apply.py expects."""
    wb = openpyxl.load_workbook(tracker_path)
    ws = wb["Apply Tracker"]
    r = ws.max_row + 1
    ws.cell(r, COL_PRIORITY).value = priority
    ws.cell(r, COL_STATUS).value = "To apply"
    ws.cell(r, COL_COMPANY).value = company
    ws.cell(r, COL_ROLE).value = role
    ws.cell(r, COL_CITY).value = city
    if why_fits:
        ws.cell(r, 9).value = why_fits  # "Why it fits" column
    link_cell = ws.cell(r, COL_LINK)
    link_cell.value = "apply ▸"
    link_cell.hyperlink = url
    wb.save(tracker_path)
    return r
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_tracker.py -v`
Expected: PASS (existing + 2 new).

- [ ] **Step 5: Commit**

```bash
git add tracker.py tests/test_tracker.py
git commit -m "feat: tracker.append_application to queue approved jobs"
```

---

## Task 10: Triage CLI (`triage.py`)

**Files:**
- Create: `triage.py`
- Test: `tests/test_triage.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_triage.py
import openpyxl

import db as dbmod
import triage
from db import Job


def _tracker(tmp_path):
    wb = openpyxl.Workbook()
    wb.create_sheet("Profile").append(["key", "value"])
    ws = wb.create_sheet("Apply Tracker")
    wb.remove(wb["Sheet"])
    headers = ["Priority", "Status", "Date applied", "My notes", "Company", "Role",
               "City", "Region", "Why it fits", "Flags", "Link", "Verification",
               "Tailored Resume Path"]
    ws.append(headers)
    p = tmp_path / "tracker.xlsx"
    wb.save(p)
    return p


def _scored_job(conn, title="ML Engineer", grade="A"):
    dbmod.insert_job(conn, Job(url="https://job-boards.greenhouse.io/acme/jobs/1",
                               company="Acme", title=title, location="Remote US",
                               source="ats:greenhouse", ats="greenhouse", raw_text="d"))
    j = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, j.id, status="scored", grade=grade, reasoning="fit",
                    archetype="lab", comp_signal="$180k", red_flags="[]")


def test_apply_decision_approve_writes_tracker_row(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]

    triage.apply_decision(conn, job, "a", tracker)

    assert len(dbmod.jobs_by_status(conn, "approved")) == 1
    wb = openpyxl.load_workbook(tracker)
    ws = wb["Apply Tracker"]
    assert ws.cell(ws.max_row, 5).value == "Acme"


def test_apply_decision_skip_and_snooze(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]
    triage.apply_decision(conn, job, "s", tracker)
    assert len(dbmod.jobs_by_status(conn, "skipped")) == 1

    _scored_job(conn)  # different call reuses same URL → deduped; insert a new one
    dbmod.insert_job(conn, Job(url="https://x/2", company="B", title="AI Engineer",
                               location="Remote US", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    j2 = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, j2.id, status="scored", grade="B", reasoning="",
                    archetype="", comp_signal="", red_flags="[]")
    triage.apply_decision(conn, dbmod.jobs_by_status(conn, "scored")[0], "z", tracker)
    assert len(dbmod.jobs_by_status(conn, "snoozed")) == 1


def test_priority_from_grade():
    assert triage.priority_from_grade("A").startswith("A")
    assert triage.priority_from_grade("B").startswith("B")
    assert triage.priority_from_grade("C").startswith("C")
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_triage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'triage'`.

- [ ] **Step 3: Write `triage.py`**

```python
# triage.py
from __future__ import annotations

import logging
import sqlite3
import webbrowser
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
from db import Job
from tracker import append_application

load_dotenv()
log = logging.getLogger(__name__)

_GRADE_PRIORITY = {
    "A": "A — strong fit",
    "B": "B — good fit",
    "C": "C — possible fit",
}


def priority_from_grade(grade: str | None) -> str:
    return _GRADE_PRIORITY.get((grade or "C").upper(), "C — possible fit")


def apply_decision(conn: sqlite3.Connection, job: Job, choice: str,
                   tracker_path: Path) -> None:
    """Apply one triage decision. 'a' approve → tracker row + approved; 's' skip;
    'z' snooze; anything else is a no-op (job stays scored)."""
    if choice == "a":
        append_application(
            tracker_path, company=job.company, role=job.title, city=job.location,
            url=job.url, priority=priority_from_grade(job.grade),
            why_fits=job.reasoning or "",
        )
        dbmod.set_triage(conn, job.id, status="approved")
    elif choice == "s":
        dbmod.set_triage(conn, job.id, status="skipped")
    elif choice == "z":
        dbmod.set_triage(conn, job.id, status="snoozed")


def _print_job(job: Job) -> None:
    print(f"\n{'='*70}")
    print(f"  [{job.grade}] {job.company} — {job.title}")
    print(f"  {job.location}   {job.comp_signal or ''}")
    print(f"  {job.url}")
    print(f"  {(job.reasoning or '')[:400]}")
    print("  a → approve · s → skip · z → snooze · o → open · q → quit")


@click.command()
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
@click.option("--tracker", "tracker_path", default=None, envvar="TRACKER_PATH",
              required=True, type=click.Path(exists=True, path_type=Path))
def main(db_path: Path | None, tracker_path: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    dbmod.init_db(conn)
    jobs = sorted(dbmod.jobs_by_status(conn, "scored"),
                  key=lambda j: (j.grade or "Z"))
    if not jobs:
        click.echo("No scored jobs to triage.")
        return
    for job in jobs:
        _print_job(job)
        choice = input("  → ").strip().lower()
        if choice == "q":
            break
        if choice == "o":
            webbrowser.open(job.url)
            choice = input("  → ").strip().lower()
            if choice == "q":
                break
        apply_decision(conn, job, choice, tracker_path)
    click.echo("Triage session ended.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_triage.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add triage.py tests/test_triage.py
git commit -m "feat: HITL triage CLI — approve/skip/snooze into apply queue"
```

---

## Task 11: Intent sync from delapan KB (`sync_intent.py`)

**Files:**
- Create: `sync_intent.py`
- Test: `tests/test_sync_intent.py`

Notes: reads findings from the delapan Supabase project via PostgREST using the
service-role key (the exact path validated during design). KB ids for
**Profile & Evidence** (`d9ee3048-f3db-4571-a682-8e29aebecaa2`) and
**Positioning & Narrative** (`4e6a42dd-582f-4347-bc0a-79aa60f1951a`) are the defaults;
overridable via env. No delapan import — hunter8 stays decoupled.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sync_intent.py
import sync_intent


def test_render_intent_groups_by_kb():
    profile = [{"title": "Profile", "content": "agentic × quant", "category": "profile"}]
    positioning = [{"title": "Buy-side", "content": "co-primary", "category": "pos"}]
    md = sync_intent.render_intent(profile, positioning)
    assert "# Candidate Intent" in md
    assert "agentic × quant" in md
    assert "co-primary" in md


def test_fetch_findings_builds_request(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return [{"title": "T", "content": "C", "category": "x"}]

    def fake_get(url, headers, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(sync_intent.httpx, "get", fake_get)
    rows = sync_intent.fetch_findings(
        "https://sb.example.co", "svc-key", "kb-123")
    assert rows[0]["title"] == "T"
    assert "/rest/v1/findings" in captured["url"]
    assert captured["params"]["kb_id"] == "eq.kb-123"
    assert captured["headers"]["apikey"] == "svc-key"
```

- [ ] **Step 2: Run to verify fail**

Run: `.venv/bin/pytest tests/test_sync_intent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sync_intent'`.

- [ ] **Step 3: Write `sync_intent.py`**

```python
# sync_intent.py
from __future__ import annotations

import os
from pathlib import Path

import click
import httpx
from dotenv import load_dotenv

load_dotenv()

KB_PROFILE = "d9ee3048-f3db-4571-a682-8e29aebecaa2"       # Profile & Evidence
KB_POSITIONING = "4e6a42dd-582f-4347-bc0a-79aa60f1951a"   # Positioning & Narrative


def fetch_findings(supabase_url: str, service_key: str, kb_id: str,
                   timeout: float = 30.0) -> list[dict]:
    """Read findings for one KB via PostgREST (service-role, RLS bypassed, scoped
    explicitly by kb_id — mirrors delapan's own service-client convention)."""
    resp = httpx.get(
        f"{supabase_url.rstrip('/')}/rest/v1/findings",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"},
        params={"kb_id": f"eq.{kb_id}", "select": "title,content,category"},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def render_intent(profile: list[dict], positioning: list[dict]) -> str:
    def block(rows: list[dict]) -> str:
        parts = []
        for r in rows:
            title = r.get("title", "").strip()
            content = (r.get("content") or "").strip()
            parts.append(f"### {title}\n{content}" if title else content)
        return "\n\n".join(parts)

    return (
        "# Candidate Intent\n\n"
        "> Generated by sync_intent.py from the delapan KB. Human-editable.\n\n"
        "## Profile & Evidence\n\n" + block(profile) + "\n\n"
        "## Positioning & Narrative\n\n" + block(positioning) + "\n"
    )


@click.command()
@click.option("--out", "out_path", default="intent.md", type=Path)
def main(out_path: Path) -> None:
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY required.")
    profile = fetch_findings(url, key, os.getenv("KB_PROFILE_ID", KB_PROFILE))
    positioning = fetch_findings(url, key, os.getenv("KB_POSITIONING_ID", KB_POSITIONING))
    out_path.write_text(render_intent(profile, positioning), encoding="utf-8")
    click.echo(f"Wrote {out_path} — {len(profile)} profile + "
               f"{len(positioning)} positioning findings.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass**

Run: `.venv/bin/pytest tests/test_sync_intent.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add sync_intent.py tests/test_sync_intent.py
git commit -m "feat: sync_intent — pull delapan KB findings into intent.md"
```

---

## Task 12: Full-suite check, env docs, README

**Files:**
- Modify: `README.md`, `.env.example`

- [ ] **Step 1: Run the whole test suite**

Run: `.venv/bin/pytest -q`
Expected: all tests pass (existing handler/profile/resume/tracker tests + the new ones).

- [ ] **Step 2: Update `.env.example`**

Add the new keys:

```
TRACKER_PATH=/path/to/ML-AI-Roles-Tracker.xlsx
HUNTER8_DB_PATH=hunter8.db
TAVILY_API_KEY=
AI_GATEWAY_API_KEY=
HUNTER8_SCORER_MODEL=anthropic/claude-sonnet-4.5
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
```

- [ ] **Step 3: Add a "Discovery → Triage" section to `README.md`**

```markdown
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
```

- [ ] **Step 4: Commit**

```bash
git add README.md .env.example
git commit -m "docs: document discovery→triage→apply loop and env vars"
```

---

## Self-review

**Spec coverage:**
- Discovery (ATS + Tavily) → Tasks 2, 3, 5. ✓
- Hybrid scoring (rules → LLM) → Tasks 7, 8. ✓
- AI Gateway w/ 402 handling → Task 6 + Task 8 CLI. ✓
- CLI triage + Excel writeback → Tasks 9, 10. ✓
- SQLite state + URL dedup + status machine → Task 1 (+ statuses used throughout). ✓
- Watchlist YAML seeded from KB → Task 4. ✓
- `intent.md` snapshot via `sync_intent.py` → Task 11. ✓
- Manual CLI cadence, cron-friendly → all entry points are plain CLIs. ✓
- Error handling (independent fetches, visible score errors, gateway 402) → Tasks 5, 6, 8. ✓
- Testing mirrors `tests/` layout → every task is TDD with fixtures. ✓
- Deps (`httpx`, `pyyaml`, `openai`) → Tasks 4, 6. ✓

**Type consistency:** `Job` (db.py) and `Verdict` (score.py) are defined once and reused; `set_score`/`set_triage`/`insert_job`/`jobs_by_status` signatures are consistent between Task 1 and their callers in Tasks 5, 8, 10; `append_application` signature matches between Task 9 and its caller in Task 10; `Gateway.chat_json` matches between Task 6 and Task 8.

**Placeholder scan:** No TBD/TODO; every code step contains complete code. The one runtime unknown is the exact ATS board tokens in `watchlist.yaml` (Task 4 Step 6) — explicitly flagged as verify-on-first-run, not a code placeholder.

**Known integration caveats (not blockers):**
- `HUNTER8_SCORER_MODEL` default (`anthropic/claude-sonnet-4.5`) may need adjustment to a model slug the gateway exposes; env-overridable.
- Real ATS/Tavily payload shapes are covered by fixtures; a live run may reveal a field name to adjust in the parsers (Task 2) — cheap to fix, tests pin the contract.
