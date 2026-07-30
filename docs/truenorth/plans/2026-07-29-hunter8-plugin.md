# hunter8 Claude Code Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use truenorth:subagent-driven-development (recommended) or truenorth:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the graded corpus queryable and the approval step usable, so the 25 A-grade jobs that have never been triaged can be reviewed in chat and land in the tracker.

**Architecture:** A new read-only `analyze.py` holds every query as tested Python with `--json` output; a thin in-repo Claude Code plugin calls it and narrates the result. The plugin never opens the database. Exactly one new table, `grade_history`, records which brief produced each grade so grade movement becomes a query instead of a guess.

**Vision goals served:** End Goal 1 (close the loop) — the approval gate moves to where the reasoning is and the never-completed step becomes the default path. End Goal 4 (worth running daily) — one command replaces a five-command sequence, with a preflight that catches the misconfiguration class currently degrading runs.

**Tech Stack:** Python 3.9, sqlite3 (stdlib), click, python-dotenv, pytest, openpyxl. Claude Code plugin conventions (`.claude-plugin/plugin.json`, `commands/`, `agents/`, `skills/`). No new Python dependencies.

## Global Constraints

- **Python 3.9.** The venv is 3.9.6. No `match` statements. `X | Y` unions only inside annotations, and only in modules with `from __future__ import annotations`. (`pyproject.toml` sets pyright to 3.11 — that is a pre-existing inconsistency; the runtime is 3.9 and the runtime wins.)
- **No new Python dependencies.** Everything needed is already in `requirements.txt`.
- **`analyze.py` never writes.** No `INSERT`, no `UPDATE`, no `ALTER`, and it must not call `db.init_db()` (which runs `ALTER TABLE`). On a database predating `grade_history` it degrades with a message, never a traceback.
- **The plugin never opens the database.** Commands shell out to the Python CLIs. No SQL in any `.md` file.
- **Ollama unreachable is a hard stop, never a Claude fallback.** Promoting the corpus to the subscription tier to work around a missing install is the exact invariant violation the tiered design prevents.
- **Failures stay visible.** Error rows are reported, never filtered out of view.
- **A human approves every submission.** Ambiguous approval input gets a question, never an interpretation.
- **Personal artifacts are gitignored:** `reports/` joins `intent.md`, `rubric.md`, `brief.md`, `calibration-report.md`, `resumes/`, `hunter8.db`, the tracker xlsx.
- Tests run with `.venv/bin/python -m pytest`. Project root is on `sys.path` via `conftest.py`.
- Work happens on branch `feat/hunter8-plugin` (already created; spec committed as `bf4ec18`).

---

## File Structure

| File | Responsibility |
|---|---|
| `analyze.py` *(new)* | Read-only query CLI. Four subcommands, each a pure `collect_*` function plus a thin click wrapper. |
| `db.py` | Gains the `grade_history` table in `_SCHEMA`, a `brief_sha` parameter on `set_score`, and one read helper for grade movement. |
| `rubric.py` | Gains one public function returning the provenance sha for whichever document actually graded a job. |
| `score.py` | Supplies `brief_sha` to `set_score`. |
| `screen.py` | Default threshold 25 → 65. |
| `triage.py` | Gains a non-interactive `--approve <ids>` path into the existing `apply_decision`. |
| `plugin/.claude-plugin/plugin.json` *(new)* | Plugin manifest. |
| `plugin/commands/*.md` *(new)* | `triage`, `morning`, `health`, `coverage`. |
| `plugin/skills/hunter8-corpus/SKILL.md` *(new)* | Shared context: schema, status meanings, cost asymmetry, env requirements. |
| `plugin/agents/hunter8-analyst.md` *(new)* | Narrates `--json` output into a report. |
| `tests/test_analyze.py` *(new)* | One test group per subcommand, asserting the JSON contract. |

**Deviation from the spec, deliberate:** the spec says `grade_history` slots into `db._MIGRATIONS`. It does not — that dict drives `ALTER TABLE jobs ADD COLUMN` for individual columns. A new table belongs in `_SCHEMA`, which `init_db` runs through `executescript`, and `CREATE TABLE IF NOT EXISTS` upgrades pre-existing databases on the next startup. Same outcome, correct mechanism.

---

### Task 1: Make the calibrated threshold the default

`calibrate.py` measured 65 as the highest threshold holding 100% A-recall and the vision records it, but `screen.py`'s default and `.env.example` still say 25, and `HUNTER8_SCREEN_THRESHOLD` is absent from `.env`. Every screening run since calibration used the uncalibrated value.

**Files:**
- Modify: `screen.py:29` (the `DEFAULT_THRESHOLD` constant)
- Modify: `.env.example:6`
- Test: `tests/test_screen.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `screen.DEFAULT_THRESHOLD == 65`. Task 6 reads this constant as the fallback when the env var is unset.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_screen.py`:

```python
def test_default_threshold_is_the_calibrated_value():
    """65 is the highest threshold measured to hold 100% A-recall (vision,
    2026-07-28). Shipping 25 as the default meant every run since calibration
    screened at a value nobody chose."""
    assert screen.DEFAULT_THRESHOLD == 65
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_screen.py::test_default_threshold_is_the_calibrated_value -v`
Expected: FAIL — `assert 25 == 65`

- [ ] **Step 3: Change the default**

In `screen.py`, replace the `DEFAULT_THRESHOLD` line:

```python
DEFAULT_THRESHOLD = 65   # calibrated 2026-07-28: highest value holding 100% A-recall
```

In `.env.example`, replace the threshold line:

```
HUNTER8_SCREEN_THRESHOLD=65
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS, 123 passed. If a pre-existing test asserted the boundary at 25, it will fail — update it to build its fixture from `screen.DEFAULT_THRESHOLD` rather than a literal, so the boundary test survives future recalibration.

- [ ] **Step 5: Commit**

```bash
git add screen.py .env.example tests/test_screen.py
git commit -m "fix: default the screen to the calibrated threshold, not 25"
```

---

### Task 2: `grade_history` — record what each grade was, and which brief produced it

`set_score` overwrites `jobs.grade`, so a grade that moved from C to A is unrecoverable today. This table makes grade movement answerable, and `brief_sha` makes it explainable.

**Files:**
- Modify: `db.py` (`_SCHEMA`, `set_score`, new `grade_movements`)
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `db.set_score(conn, job_id, *, status, grade, reasoning, archetype, comp_signal, red_flags, cost_usd=None, brief_sha=None) -> None` — appends one `grade_history` row per call.
  - `db.grade_movements(conn, *, since: str | None = None) -> list[dict]` — one dict per job whose grade changed, keys `job_id`, `company`, `title`, `from_grade`, `to_grade`, `from_brief_sha`, `to_brief_sha`, `changed_at`. Task 4 consumes this.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_grade_history_table_is_created_on_a_legacy_database(tmp_path):
    """A new table must appear via CREATE TABLE IF NOT EXISTS in _SCHEMA, not
    via _MIGRATIONS (which only adds columns to jobs)."""
    path = tmp_path / "legacy.db"
    conn = dbmod.connect(path)
    conn.executescript(_legacy_schema_sql())
    conn.commit()
    dbmod.init_db(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "grade_history" in tables


def test_set_score_appends_history_with_provenance(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, job.id, status="scored", grade="B", reasoning="r",
                    archetype="", comp_signal="", red_flags="[]",
                    brief_sha="abc123")
    rows = conn.execute(
        "SELECT job_id, grade, brief_sha FROM grade_history").fetchall()
    assert [tuple(r) for r in rows] == [(job.id, "B", "abc123")]


def test_rescoring_appends_rather_than_overwrites(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    for grade, sha in (("C", "sha-old"), ("A", "sha-new")):
        dbmod.set_score(conn, job.id, status="scored", grade=grade, reasoning="r",
                        archetype="", comp_signal="", red_flags="[]",
                        brief_sha=sha)
    grades = [r[0] for r in conn.execute(
        "SELECT grade FROM grade_history ORDER BY id")]
    assert grades == ["C", "A"]


def test_grade_movements_reports_only_changed_grades(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job(url="https://x/moved"))
    dbmod.insert_job(conn, _job(url="https://x/stable", company="Stable"))
    moved, stable = dbmod.jobs_by_status(conn, "discovered")

    for grade, sha in (("C", "old"), ("A", "new")):
        dbmod.set_score(conn, moved.id, status="scored", grade=grade,
                        reasoning="r", archetype="", comp_signal="",
                        red_flags="[]", brief_sha=sha)
    for grade, sha in (("B", "old"), ("B", "new")):
        dbmod.set_score(conn, stable.id, status="scored", grade=grade,
                        reasoning="r", archetype="", comp_signal="",
                        red_flags="[]", brief_sha=sha)

    out = dbmod.grade_movements(conn)
    assert len(out) == 1
    assert out[0]["job_id"] == moved.id
    assert (out[0]["from_grade"], out[0]["to_grade"]) == ("C", "A")
    assert (out[0]["from_brief_sha"], out[0]["to_brief_sha"]) == ("old", "new")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_db.py -k "grade_history or appends or movements" -v`
Expected: FAIL — first with `no such table: grade_history`, then `set_score() got an unexpected keyword argument 'brief_sha'`, then `AttributeError: module 'db' has no attribute 'grade_movements'`

- [ ] **Step 3: Add the table to `_SCHEMA`**

In `db.py`, append to the `_SCHEMA` string, after the `idx_jobs_status` line:

```sql
CREATE TABLE IF NOT EXISTS grade_history (
  id        INTEGER PRIMARY KEY,
  job_id    INTEGER NOT NULL,
  grade     TEXT,
  fit_score INTEGER,
  brief_sha TEXT,
  scored_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_grade_history_job ON grade_history(job_id);
```

- [ ] **Step 4: Record history from `set_score`**

Replace `db.set_score` entirely:

```python
def set_score(
    conn: sqlite3.Connection, job_id: int, *, status: str, grade: str | None,
    reasoning: str | None, archetype: str | None, comp_signal: str | None,
    red_flags: str | None, cost_usd: float | None = None,
    brief_sha: str | None = None,
) -> None:
    """Write a grade and append an immutable history row.

    `jobs.grade` is overwritten in place, so without the history append a grade
    that moved is unrecoverable. `brief_sha` identifies the distilled document
    that produced this grade, which is what makes "what did my intent.md edit do
    to the corpus?" a query rather than an inference from wall-clock timestamps."""
    now = _now()
    conn.execute(
        """UPDATE jobs SET status=?, grade=?, reasoning=?, archetype=?,
           comp_signal=?, red_flags=?, cost_usd=?, scored_at=? WHERE id=?""",
        (status, grade, reasoning, archetype, comp_signal, red_flags, cost_usd,
         now, job_id),
    )
    fit_score = conn.execute(
        "SELECT fit_score FROM jobs WHERE id=?", (job_id,)).fetchone()[0]
    conn.execute(
        """INSERT INTO grade_history (job_id, grade, fit_score, brief_sha, scored_at)
           VALUES (?,?,?,?,?)""",
        (job_id, grade, fit_score, brief_sha, now),
    )
    conn.commit()
```

- [ ] **Step 5: Add the read helper**

Add to `db.py`, after `set_score`:

```python
def grade_movements(conn: sqlite3.Connection, *,
                    since: str | None = None) -> list[dict]:
    """Jobs whose grade changed between their first and most recent history row.

    Only movement is reported — a job graded B twice is not news. `since` filters
    on the *later* of the two gradings, so a run's report covers what this run
    changed."""
    sql = """
      WITH firsts AS (
        SELECT job_id, grade, brief_sha, scored_at,
               ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY id ASC) AS rn
        FROM grade_history),
      lasts AS (
        SELECT job_id, grade, brief_sha, scored_at,
               ROW_NUMBER() OVER (PARTITION BY job_id ORDER BY id DESC) AS rn
        FROM grade_history)
      SELECT j.id, j.company, j.title,
             f.grade, l.grade, f.brief_sha, l.brief_sha, l.scored_at
      FROM firsts f
      JOIN lasts  l ON l.job_id = f.job_id AND l.rn = 1
      JOIN jobs   j ON j.id     = f.job_id
      WHERE f.rn = 1 AND IFNULL(f.grade,'') != IFNULL(l.grade,'')
    """
    params: list = []
    if since is not None:
        sql += " AND l.scored_at >= ?"
        params.append(since)
    sql += " ORDER BY l.scored_at DESC"
    keys = ("job_id", "company", "title", "from_grade", "to_grade",
            "from_brief_sha", "to_brief_sha", "changed_at")
    return [dict(zip(keys, tuple(r))) for r in conn.execute(sql, params).fetchall()]
```

Window functions require SQLite 3.25+. macOS system SQLite is well past that; if a run reports `near "OVER": syntax error`, that is the signal to check `sqlite3.sqlite_version`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_db.py -q`
Expected: PASS

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — existing `set_score` callers are unaffected because `brief_sha` defaults to `None`.

- [ ] **Step 8: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: append-only grade history, with the brief that produced each grade"
```

---

### Task 3: `score.py` supplies the provenance sha

`grade_history.brief_sha` is useless unless the scorer fills it. `db.py` must stay ignorant of what a brief is, so the sha is computed in `rubric.py` and passed by `score.py`.

**Files:**
- Modify: `rubric.py` (new public `provenance_sha`)
- Modify: `score.py` (`run_scoring` signature, both `set_score` calls, `main`)
- Test: `tests/test_rubric.py`, `tests/test_score.py`

**Interfaces:**
- Consumes: `db.set_score(..., brief_sha=...)` from Task 2.
- Produces: `rubric.provenance_sha(intent_path: Path, brief_path: Path, *, full_intent: bool) -> str` — never returns `None`; raises `SystemExit` if it cannot determine a sha. `run_scoring(conn, *, intent_md, agent, limit=None, posted_since=None, brief_sha)` — `brief_sha` is keyword-only and required.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rubric.py`:

```python
def test_provenance_sha_reads_the_hash_stamped_in_the_brief(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("profile text", encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text(rubricmod._render("body", "", "deadbeef", "Grading Brief"),
                     encoding="utf-8")
    assert rubricmod.provenance_sha(intent, brief, full_intent=False) == "deadbeef"


def test_provenance_sha_uses_intent_hash_under_full_intent(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("profile text", encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text(rubricmod._render("body", "", "deadbeef", "Grading Brief"),
                     encoding="utf-8")
    expected = rubricmod._hash("profile text")
    assert rubricmod.provenance_sha(intent, brief, full_intent=True) == expected


def test_provenance_sha_refuses_when_the_brief_has_no_stamp(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("profile text", encoding="utf-8")
    brief = tmp_path / "brief.md"
    brief.write_text("# Grading Brief\n\nno hash stamp here\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        rubricmod.provenance_sha(intent, brief, full_intent=False)
```

`tests/test_rubric.py` already imports `rubric as rubricmod`; add `import pytest` at the top if it is not already there.

Append to `tests/test_score.py`:

```python
def test_run_scoring_records_the_brief_sha_on_every_grade(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/1", company="Acme",
                               title="AI Engineer", location="NYC",
                               source="ats:greenhouse", ats="greenhouse",
                               raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=80,
                     screen_reason="ok")

    class _Agent:
        last_cost_usd = None
        total_cost_usd = 0.0
        calls = 0

        def chat_json(self, system, user):
            return {"grade": "A", "reasoning": "r", "archetype": "lab",
                    "comp_signal": "", "red_flags": []}

    score.run_scoring(conn, intent_md="brief", agent=_Agent(),
                      brief_sha="sha-under-test")

    shas = [r[0] for r in conn.execute("SELECT brief_sha FROM grade_history")]
    assert shas == ["sha-under-test"]


def test_a_failed_grade_still_records_provenance(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/2", company="Acme",
                               title="AI Engineer", location="NYC",
                               source="ats:greenhouse", ats="greenhouse",
                               raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=80,
                     screen_reason="ok")

    class _Agent:
        last_cost_usd = 0.01
        total_cost_usd = 0.01
        calls = 1

        def chat_json(self, system, user):
            raise ValueError("bad json")

    score.run_scoring(conn, intent_md="brief", agent=_Agent(),
                      brief_sha="sha-under-test")

    rows = conn.execute(
        "SELECT grade, brief_sha FROM grade_history").fetchall()
    assert [tuple(r) for r in rows] == [(None, "sha-under-test")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_rubric.py tests/test_score.py -k "provenance or brief_sha" -v`
Expected: FAIL — `module 'rubric' has no attribute 'provenance_sha'`, then `run_scoring() got an unexpected keyword argument 'brief_sha'`

- [ ] **Step 3: Add `provenance_sha` to `rubric.py`**

Add to `rubric.py`, after `load_or_build`:

```python
def provenance_sha(intent_path: Path, brief_path: Path, *,
                   full_intent: bool) -> str:
    """The sha256 of whichever document actually graded a job.

    Under `--full-intent` that is `intent.md` itself; otherwise it is the hash
    already stamped into the cached brief by `_render`, read back rather than
    recomputed so the recorded value is exactly what the grader read.

    Refuses rather than returning None: a graded row with no provenance would
    make the grade-movement analysis quietly wrong instead of visibly
    incomplete."""
    if full_intent:
        return _hash(intent_path.read_text(encoding="utf-8"))
    if not brief_path.exists():
        raise SystemExit(f"{brief_path} does not exist — cannot record which "
                         f"brief graded these jobs. Run score.py once to build it.")
    sha = _stored_hash(brief_path.read_text(encoding="utf-8"))
    if not sha:
        raise SystemExit(
            f"{brief_path} carries no {_HASH_PREFIX.strip()} stamp. Delete it and "
            f"let rubric.py regenerate it, or the grade history cannot say which "
            f"brief produced a grade.")
    return sha
```

- [ ] **Step 4: Thread it through `score.py`**

In `score.py`, change `run_scoring`'s signature and both `set_score` calls:

```python
def run_scoring(conn: sqlite3.Connection, *, intent_md: str, agent: ClaudeAgent,
                limit: int | None = None, posted_since: str | None = None,
                brief_sha: str) -> None:
```

Add `brief_sha=brief_sha` to the `score_error` call and to the `scored` call — both, so a failed grade still records what was in play when it failed.

In `main`, after `intent_md` is resolved, add:

```python
    brief_sha = rubric.provenance_sha(intent_path, brief_path,
                                      full_intent=full_intent)
```

and pass `brief_sha=brief_sha` to `run_scoring`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_rubric.py tests/test_score.py -q`
Expected: PASS. Pre-existing `run_scoring` calls in `test_score.py` now need `brief_sha=` — add `brief_sha="test"` to each.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add rubric.py score.py tests/test_rubric.py tests/test_score.py
git commit -m "feat: record which brief graded each job"
```

---

### Task 4: `analyze.py` — skeleton and `shortlist`

The ranked graded queue for a window. This is what both the report and triage read, so it ships first.

**Files:**
- Create: `analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `db.connect`, `db.jobs_by_status`, `db.grade_movements` (Task 2).
- Produces:
  - `analyze.collect_shortlist(conn, *, since_days=None, new_since=None, grades=None) -> dict` with keys `count`, `window_days`, `new_since`, `grades`, `new_count`, `movements`, `jobs`. Each job dict has `id`, `company`, `title`, `location`, `grade`, `fit_score`, `comp_signal`, `reasoning`, `red_flags`, `url`, `posted_at`, `scored_at`, `is_new`.
  - `analyze.cutoff(since_days) -> str | None` — shared by later subcommands.
  - A click group `main` with the `shortlist` command registered.

- [ ] **Step 1: Write the failing test**

Create `tests/test_analyze.py`:

```python
# tests/test_analyze.py
import json

from click.testing import CliRunner

import analyze
import db as dbmod
from db import Job


def _conn(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    return conn


def _scored(conn, *, url, grade, fit_score=80, company="Acme",
            posted_at=None, brief_sha="sha"):
    dbmod.insert_job(conn, Job(url=url, company=company, title="AI Engineer",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", posted_at=posted_at,
                               raw_text="d"))
    job = [j for j in dbmod.jobs_by_status(conn, "discovered") if j.url == url][0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=fit_score,
                     screen_reason="ok")
    dbmod.set_score(conn, job.id, status="scored", grade=grade, reasoning="why",
                    archetype="lab", comp_signal="$200k", red_flags="[]",
                    brief_sha=brief_sha)
    return job.id


def test_shortlist_ranks_by_fit_score_descending(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/lo", grade="B", fit_score=60)
    _scored(conn, url="https://x/hi", grade="A", fit_score=95)
    out = analyze.collect_shortlist(conn)
    assert out["count"] == 2
    assert [j["fit_score"] for j in out["jobs"]] == [95, 60]


def test_shortlist_filters_by_grade(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A")
    _scored(conn, url="https://x/c", grade="C")
    out = analyze.collect_shortlist(conn, grades=["A"])
    assert out["count"] == 1 and out["jobs"][0]["grade"] == "A"


def test_shortlist_marks_rows_graded_since_the_cutoff(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/old", grade="B")
    boundary = conn.execute("SELECT MAX(scored_at) FROM jobs").fetchone()[0]
    _scored(conn, url="https://x/new", grade="A")

    out = analyze.collect_shortlist(conn, new_since=boundary)
    by_url = {j["url"]: j for j in out["jobs"]}
    assert by_url["https://x/new"]["is_new"] is True
    assert by_url["https://x/old"]["is_new"] is False
    assert out["new_count"] == 1


def test_shortlist_reports_an_empty_window_explicitly(tmp_path):
    conn = _conn(tmp_path)
    out = analyze.collect_shortlist(conn, since_days=7)
    assert out["count"] == 0 and out["jobs"] == []


def test_shortlist_includes_grade_movements(tmp_path):
    conn = _conn(tmp_path)
    job_id = _scored(conn, url="https://x/m", grade="C", brief_sha="old")
    dbmod.set_score(conn, job_id, status="scored", grade="A", reasoning="why",
                    archetype="lab", comp_signal="", red_flags="[]",
                    brief_sha="new")
    out = analyze.collect_shortlist(conn)
    assert len(out["movements"]) == 1
    assert out["movements"][0]["to_grade"] == "A"


def test_shortlist_cli_emits_valid_json(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A")
    conn.close()
    result = CliRunner().invoke(
        analyze.main,
        ["shortlist", "--db", str(tmp_path / "h.db"), "--json"])
    assert result.exit_code == 0
    assert json.loads(result.output)["count"] == 1


def test_shortlist_degrades_when_grade_history_is_absent(tmp_path):
    """analyze.py must not call init_db (it runs ALTER TABLE), so it has to
    tolerate a database that predates the table."""
    conn = dbmod.connect(tmp_path / "legacy.db")
    conn.executescript("""CREATE TABLE jobs (
        id INTEGER PRIMARY KEY, url TEXT UNIQUE NOT NULL, company TEXT NOT NULL,
        title TEXT NOT NULL, location TEXT, source TEXT NOT NULL, ats TEXT,
        posted_at TEXT, raw_text TEXT, status TEXT NOT NULL, grade TEXT,
        reasoning TEXT, archetype TEXT, comp_signal TEXT, red_flags TEXT,
        discovered_at TEXT NOT NULL, scored_at TEXT, triaged_at TEXT,
        fit_score INTEGER, screen_reason TEXT, screened_at TEXT, cost_usd REAL);""")
    conn.commit()
    out = analyze.collect_shortlist(conn)
    assert out["movements"] == []
    assert out["movements_unavailable"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'analyze'`

- [ ] **Step 3: Write `analyze.py`**

Create `analyze.py`:

```python
# analyze.py
"""Read-only reporting over hunter8.db.

Every query the plugin needs lives here as tested Python with a --json contract,
rather than as SQL in a prompt. Output is bounded by construction: the corpus is
~104 MB over ~13k rows and raw_text alone runs to 6k characters a row.

This module NEVER writes. It does not call db.init_db(), because that runs
ALTER TABLE — so on a database predating a migration it degrades with a flag
rather than crashing.
"""
from __future__ import annotations

import json as jsonlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod

load_dotenv()

_JOB_FIELDS = ("id", "company", "title", "location", "grade", "fit_score",
               "comp_signal", "reasoning", "red_flags", "url", "posted_at",
               "scored_at")


def cutoff(since_days: int | None) -> str | None:
    """ISO timestamp N days back, or None for no date filter. Mirrors
    screen._cutoff so both tiers mean the same thing by a window."""
    if since_days is None:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()


def _emit(payload: dict, as_json: bool, render) -> None:
    click.echo(jsonlib.dumps(payload, indent=2, default=str)
               if as_json else render(payload))


def collect_shortlist(conn: sqlite3.Connection, *, since_days: int | None = None,
                      new_since: str | None = None,
                      grades: list | None = None) -> dict:
    """The ranked graded queue for a window.

    `since_days` bounds the board's posting date; `new_since` marks which of
    those rows this run graded. Different columns, so they compose."""
    jobs = dbmod.jobs_by_status(conn, "scored", order_by="fit_score DESC",
                                posted_since=cutoff(since_days))
    wanted = {g.strip().upper() for g in grades} if grades else None
    out = []
    for j in jobs:
        if wanted and (j.grade or "").upper() not in wanted:
            continue
        row = {f: getattr(j, f) for f in _JOB_FIELDS}
        row["is_new"] = bool(new_since and (j.scored_at or "") > new_since)
        out.append(row)

    movements: list = []
    unavailable = False
    try:
        movements = dbmod.grade_movements(conn, since=new_since)
    except sqlite3.OperationalError:
        unavailable = True   # database predates grade_history

    return {
        "count": len(out),
        "window_days": since_days,
        "new_since": new_since,
        "grades": sorted(wanted) if wanted else None,
        "new_count": sum(1 for r in out if r["is_new"]),
        "movements": movements,
        "movements_unavailable": unavailable,
        "jobs": out,
    }


def _render_shortlist(p: dict) -> str:
    if not p["count"]:
        window = f"the last {p['window_days']} days" if p["window_days"] else "the corpus"
        return f"No graded jobs in {window}."
    lines = [f"{p['count']} graded job(s), {p['new_count']} new:"]
    for j in p["jobs"]:
        flag = " *new*" if j["is_new"] else ""
        lines.append(f"  [{j['grade']} {j['fit_score']:>3}] {j['company']} — "
                     f"{j['title']} ({j['location']}){flag}")
        lines.append(f"        {j['url']}")
    if p["movements"]:
        lines.append(f"{len(p['movements'])} grade(s) moved:")
        for m in p["movements"]:
            lines.append(f"  {m['company']} — {m['title']}: "
                         f"{m['from_grade']} → {m['to_grade']}")
    elif p["movements_unavailable"]:
        lines.append("(no grade history recorded yet — run the pipeline once "
                     "after upgrading)")
    return "\n".join(lines)


_db_option = click.option("--db", "db_path", default=None,
                          envvar="HUNTER8_DB_PATH", type=Path)
_json_option = click.option("--json", "as_json", is_flag=True,
                            help="Emit JSON instead of prose.")


@click.group()
def main() -> None:
    """Read-only reporting over hunter8.db."""


@main.command()
@_db_option
@click.option("--since-days", default=None, type=int,
              help="Only jobs the board posted within the last N days.")
@click.option("--new-since", default=None,
              help="ISO timestamp; mark rows graded after it as new.")
@click.option("--grade", default=None,
              help="Comma-separated grades to keep, e.g. A or A,B.")
@_json_option
def shortlist(db_path: Path | None, since_days: int | None,
              new_since: str | None, grade: str | None, as_json: bool) -> None:
    """The ranked graded queue for a window."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    grades = grade.split(",") if grade else None
    _emit(collect_shortlist(conn, since_days=since_days, new_since=new_since,
                            grades=grades), as_json, _render_shortlist)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -q`
Expected: PASS

- [ ] **Step 5: Verify it never writes**

Run: `grep -nE "INSERT|UPDATE|DELETE|ALTER|init_db" analyze.py`
Expected: no output. If anything matches, the read-only constraint is broken.

- [ ] **Step 6: Commit**

```bash
git add analyze.py tests/test_analyze.py
git commit -m "feat: analyze.py shortlist — the ranked graded queue, with movements"
```

---

### Task 5: `analyze.py patterns` — where you actually score

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `analyze._emit`, `analyze._db_option`, `analyze._json_option` from Task 4.
- Produces: `analyze.collect_patterns(conn, *, by: str) -> dict` with keys `by`, `total`, `buckets`. Each bucket dict has `key`, `n`, `a`, `b`, `c`, `a_rate`, `ab_rate`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analyze.py`:

```python
def test_patterns_reports_grade_rates_per_bucket(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A", company="Acme")
    _scored(conn, url="https://x/2", grade="C", company="Acme")
    _scored(conn, url="https://x/3", grade="A", company="Beta")
    out = analyze.collect_patterns(conn, by="company")
    buckets = {b["key"]: b for b in out["buckets"]}
    assert buckets["Acme"]["n"] == 2 and buckets["Acme"]["a"] == 1
    assert buckets["Acme"]["a_rate"] == 0.5
    assert buckets["Beta"]["a_rate"] == 1.0
    assert out["total"] == 3


def test_patterns_orders_by_a_rate_then_volume(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A", company="Best")
    _scored(conn, url="https://x/2", grade="C", company="Worst")
    _scored(conn, url="https://x/3", grade="C", company="Worst")
    out = analyze.collect_patterns(conn, by="company")
    assert out["buckets"][0]["key"] == "Best"


def test_patterns_rejects_an_unknown_dimension(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        analyze.collect_patterns(conn, by="favourite_colour")


def test_patterns_handles_an_empty_corpus(tmp_path):
    conn = _conn(tmp_path)
    out = analyze.collect_patterns(conn, by="archetype")
    assert out["total"] == 0 and out["buckets"] == []
```

Add `import pytest` to the top of `tests/test_analyze.py`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -k patterns -v`
Expected: FAIL — `module 'analyze' has no attribute 'collect_patterns'`

- [ ] **Step 3: Implement**

Add to `analyze.py`, after `_render_shortlist`:

```python
# Whitelisted so a --by value can never carry SQL into the query.
_DIMENSIONS = {"company": "company", "archetype": "archetype", "ats": "ats",
               "location": "location", "source": "source"}


def collect_patterns(conn: sqlite3.Connection, *, by: str) -> dict:
    """Grade rates per bucket — which companies, archetypes, boards and
    locations actually convert, rather than which produce the most rows."""
    column = _DIMENSIONS.get(by)
    if column is None:
        raise ValueError(f"by must be one of {sorted(_DIMENSIONS)}, got {by!r}")
    rows = conn.execute(
        f"""SELECT IFNULL(NULLIF({column}, ''), '(unset)') AS k,
                   COUNT(*),
                   SUM(grade='A'), SUM(grade='B'), SUM(grade='C')
            FROM jobs WHERE status='scored' GROUP BY k""").fetchall()
    buckets = []
    for key, n, a, b, c in rows:
        a, b, c = int(a or 0), int(b or 0), int(c or 0)
        buckets.append({"key": key, "n": int(n), "a": a, "b": b, "c": c,
                        "a_rate": a / n if n else 0.0,
                        "ab_rate": (a + b) / n if n else 0.0})
    buckets.sort(key=lambda x: (-x["a_rate"], -x["n"], x["key"]))
    return {"by": by, "total": sum(x["n"] for x in buckets), "buckets": buckets}


def _render_patterns(p: dict) -> str:
    if not p["total"]:
        return "No graded jobs to analyse."
    lines = [f"Grade rates by {p['by']} ({p['total']} graded):",
             f"  {'key':<34} {'n':>4} {'A':>3} {'B':>3} {'C':>3} {'A%':>6} {'AB%':>6}"]
    for b in p["buckets"]:
        lines.append(f"  {b['key'][:34]:<34} {b['n']:>4} {b['a']:>3} {b['b']:>3} "
                     f"{b['c']:>3} {b['a_rate']:>5.0%} {b['ab_rate']:>5.0%}")
    return "\n".join(lines)


@main.command()
@_db_option
@click.option("--by", default="archetype",
              type=click.Choice(sorted(_DIMENSIONS)),
              help="Dimension to bucket by.")
@_json_option
def patterns(db_path: Path | None, by: str, as_json: bool) -> None:
    """Grade rates per bucket."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    _emit(collect_patterns(conn, by=by), as_json, _render_patterns)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add analyze.py tests/test_analyze.py
git commit -m "feat: analyze.py patterns — grade rates by company, archetype, ats, location"
```

---

### Task 6: `analyze.py health` — queue, threshold drift, agreement, cost

This is the subcommand that would have caught the live bug: screening at 25 while the vision records 65.

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `calibrate.agreement(rows) -> list[dict]` and `calibrate.recommend(table) -> int` (both pure — they take rows and return numbers, and make **no model calls**; `calibrate.collect` is the one that drives the model and is deliberately not used here). `screen.DEFAULT_THRESHOLD` from Task 1.
- Produces: `analyze.collect_health(conn, *, threshold_in_effect, calibration_path, intent_path) -> dict` with keys `queue`, `errors`, `threshold`, `agreement`, `cost`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analyze.py`:

```python
_STATUSES = ("discovered", "screened_in", "screened_out", "scored",
             "screen_error", "score_error", "approved", "skipped", "snoozed")


def test_health_counts_every_queue_status(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A")
    dbmod.insert_job(conn, Job(url="https://x/2", company="Acme", title="T",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "missing.md",
                                 intent_path=tmp_path / "intent.md")
    assert out["queue"]["scored"] == 1
    assert out["queue"]["discovered"] == 1
    assert set(out["queue"]) >= set(_STATUSES)


def test_health_flags_a_threshold_that_disagrees_with_calibration(tmp_path):
    conn = _conn(tmp_path)
    report = tmp_path / "calibration-report.md"
    report.write_text("**Recommended threshold: 65** — keeps 100% of Claude-A\n",
                      encoding="utf-8")
    intent = tmp_path / "intent.md"
    intent.write_text("x", encoding="utf-8")
    out = analyze.collect_health(conn, threshold_in_effect=25,
                                 calibration_path=report, intent_path=intent)
    assert out["threshold"]["in_effect"] == 25
    assert out["threshold"]["recommended"] == 65
    assert out["threshold"]["disagrees"] is True


def test_health_reports_a_missing_calibration_report(tmp_path):
    conn = _conn(tmp_path)
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "nope.md",
                                 intent_path=tmp_path / "intent.md")
    assert out["threshold"]["recommended"] is None
    assert out["threshold"]["report_missing"] is True


def test_health_flags_calibration_older_than_intent(tmp_path):
    import os
    import time
    conn = _conn(tmp_path)
    report = tmp_path / "calibration-report.md"
    report.write_text("**Recommended threshold: 65**\n", encoding="utf-8")
    intent = tmp_path / "intent.md"
    intent.write_text("x", encoding="utf-8")
    now = time.time()
    os.utime(report, (now - 600, now - 600))
    os.utime(intent, (now, now))
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=report, intent_path=intent)
    assert out["threshold"]["stale"] is True


def test_health_surfaces_error_rows_with_reasons(tmp_path):
    conn = _conn(tmp_path)
    dbmod.insert_job(conn, Job(url="https://x/e", company="Acme", title="T",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screen_error", fit_score=None,
                     screen_reason="ollama exploded")
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "n.md",
                                 intent_path=tmp_path / "i.md")
    assert out["errors"][0]["reason"] == "ollama exploded"


def test_health_reports_agreement_without_calling_a_model(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/a", grade="A", fit_score=90)
    _scored(conn, url="https://x/c", grade="C", fit_score=10)
    out = analyze.collect_health(conn, threshold_in_effect=65,
                                 calibration_path=tmp_path / "n.md",
                                 intent_path=tmp_path / "i.md")
    assert out["agreement"]["sample"] == 2
    assert out["agreement"]["a_recall_at_threshold"] == 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -k health -v`
Expected: FAIL — `module 'analyze' has no attribute 'collect_health'`

- [ ] **Step 3: Implement**

Add to `analyze.py` — extend the imports at the top with:

```python
import os
import re

import calibrate
import screen as screenmod
```

Then add after `_render_patterns`:

```python
_QUEUE_STATUSES = ("discovered", "screened_in", "screened_out", "scored",
                   "approved", "skipped", "snoozed", "screen_error",
                   "score_error", "filtered_out")
_RECOMMENDED_RE = re.compile(r"Recommended threshold:\s*(\d+)")


def _threshold_state(threshold_in_effect: int, calibration_path: Path,
                     intent_path: Path) -> dict:
    """Compare the threshold actually in force against the calibrated one.

    Three separate failure modes, reported separately: they disagree, the report
    was never generated, or the report predates the profile it was measured
    against."""
    state = {"in_effect": threshold_in_effect, "recommended": None,
             "disagrees": False, "report_missing": False, "stale": False}
    if not calibration_path.exists():
        state["report_missing"] = True
        return state
    match = _RECOMMENDED_RE.search(calibration_path.read_text(encoding="utf-8"))
    if match:
        state["recommended"] = int(match.group(1))
        state["disagrees"] = state["recommended"] != threshold_in_effect
    if intent_path.exists():
        state["stale"] = (os.path.getmtime(calibration_path)
                          < os.path.getmtime(intent_path))
    return state


def collect_health(conn: sqlite3.Connection, *, threshold_in_effect: int,
                   calibration_path: Path, intent_path: Path) -> dict:
    """Pipeline and calibration state: what is queued, what is misconfigured,
    what failed and why, and what it has cost."""
    queue = {s: len(dbmod.jobs_by_status(conn, s)) for s in _QUEUE_STATUSES}

    errors = [
        {"id": r[0], "company": r[1], "title": r[2], "status": r[3],
         "reason": r[4] or r[5] or ""}
        for r in conn.execute(
            """SELECT id, company, title, status, screen_reason, reasoning
               FROM jobs WHERE status IN ('screen_error','score_error')
               ORDER BY id""").fetchall()]

    pairs = [(str(g).upper(), int(f)) for g, f in conn.execute(
        """SELECT grade, fit_score FROM jobs
           WHERE status='scored' AND grade IS NOT NULL
             AND fit_score IS NOT NULL""").fetchall()]
    table = calibrate.agreement(pairs) if pairs else []
    at = next((r for r in table if r["threshold"] == threshold_in_effect), None)
    agreement = {
        "sample": len(pairs),
        "a_recall_at_threshold": at["a_recall"] if at else None,
        "ab_recall_at_threshold": at["ab_recall"] if at else None,
        "promoted_fraction_at_threshold": at["promoted_fraction"] if at else None,
        "highest_threshold_with_full_a_recall":
            calibrate.recommend(table) if table else None,
    }

    total, priced = dbmod.total_cost(conn)
    return {
        "queue": queue,
        "errors": errors,
        "threshold": _threshold_state(threshold_in_effect, calibration_path,
                                      intent_path),
        "agreement": agreement,
        "cost": {"lifetime_usd": total, "priced_rows": priced},
    }


def _render_health(p: dict) -> str:
    lines = ["Queue:"]
    for status, n in p["queue"].items():
        if n:
            lines.append(f"  {status:<14} {n:>6}")
    t = p["threshold"]
    lines.append(f"Threshold in effect: {t['in_effect']}")
    if t["report_missing"]:
        lines.append("  ! no calibration-report.md — run calibrate.py")
    if t["disagrees"]:
        lines.append(f"  ! calibration recommends {t['recommended']}")
    if t["stale"]:
        lines.append("  ! calibration predates intent.md — re-run calibrate.py")
    a = p["agreement"]
    if a["sample"]:
        lines.append(f"Agreement over {a['sample']} graded job(s): "
                     f"A-recall {a['a_recall_at_threshold']:.0%} at the current "
                     f"threshold; 100% A-recall holds to "
                     f"{a['highest_threshold_with_full_a_recall']}")
    if p["errors"]:
        lines.append(f"{len(p['errors'])} error row(s):")
        for e in p["errors"][:10]:
            lines.append(f"  [{e['status']}] {e['company']} — {e['reason'][:60]}")
    c = p["cost"]
    lines.append(f"Cost: ${c['lifetime_usd']:.4f} notional across "
                 f"{c['priced_rows']} priced row(s). Billed $0 — subscription auth.")
    return "\n".join(lines)


@main.command()
@_db_option
@click.option("--threshold", default=None, type=int,
              envvar="HUNTER8_SCREEN_THRESHOLD",
              help="Threshold to report as in force. Defaults to the configured one.")
@click.option("--calibration", "calibration_path", default="calibration-report.md",
              type=Path)
@click.option("--intent", "intent_path", default="intent.md", type=Path)
@_json_option
def health(db_path: Path | None, threshold: int | None, calibration_path: Path,
           intent_path: Path, as_json: bool) -> None:
    """Queue counts, threshold drift, screen-vs-Claude agreement, cost."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    _emit(collect_health(
        conn,
        threshold_in_effect=(threshold if threshold is not None
                             else screenmod.DEFAULT_THRESHOLD),
        calibration_path=calibration_path, intent_path=intent_path),
        as_json, _render_health)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -q`
Expected: PASS

- [ ] **Step 5: Confirm no model call was introduced**

Run: `grep -nE "collect\(|LocalAgent|ClaudeAgent" analyze.py`
Expected: no output. `health` must use `calibrate.agreement` and `calibrate.recommend` only.

- [ ] **Step 6: Commit**

```bash
git add analyze.py tests/test_analyze.py
git commit -m "feat: analyze.py health — queue, threshold drift, agreement, cost"
```

---

### Task 7: `analyze.py coverage` — which watched firms produce nothing

**Files:**
- Modify: `analyze.py`
- Test: `tests/test_analyze.py`

**Interfaces:**
- Consumes: `watchlist.load_watchlist(path) -> Watchlist` with `.companies` of `Company(name, ats, board, archetype)`.
- Produces: `analyze.collect_coverage(conn, *, watchlist_path, stale_days=30) -> dict` with keys `total_companies`, `silent`, `stale`, `entries`. Each entry has `name`, `ats`, `board`, `archetype`, `rows`, `scored`, `newest_posted_at`, `is_silent`, `is_stale`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_analyze.py`:

```python
def _watchlist(tmp_path, body):
    p = tmp_path / "watchlist.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_coverage_flags_a_company_with_no_rows(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A", company="Acme")
    wl = _watchlist(tmp_path, """
companies:
  - name: Acme
    ats: greenhouse
    board: acme
  - name: Ghost
    ats: greenhouse
    board: ghost
""")
    out = analyze.collect_coverage(conn, watchlist_path=wl)
    by_name = {e["name"]: e for e in out["entries"]}
    assert by_name["Acme"]["rows"] == 1 and by_name["Acme"]["is_silent"] is False
    assert by_name["Ghost"]["rows"] == 0 and by_name["Ghost"]["is_silent"] is True
    assert out["silent"] == 1
    assert out["total_companies"] == 2


def test_coverage_flags_a_company_whose_newest_posting_is_old(tmp_path):
    conn = _conn(tmp_path)
    old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    _scored(conn, url="https://x/old", grade="B", company="Stale",
            posted_at=old)
    wl = _watchlist(tmp_path, """
companies:
  - name: Stale
    ats: lever
    board: stale
""")
    out = analyze.collect_coverage(conn, watchlist_path=wl, stale_days=30)
    assert out["entries"][0]["is_stale"] is True
    assert out["stale"] == 1


def test_coverage_orders_silent_companies_first(tmp_path):
    conn = _conn(tmp_path)
    _scored(conn, url="https://x/1", grade="A", company="Loud")
    wl = _watchlist(tmp_path, """
companies:
  - name: Loud
    ats: greenhouse
    board: loud
  - name: Ghost
    ats: greenhouse
    board: ghost
""")
    out = analyze.collect_coverage(conn, watchlist_path=wl)
    assert out["entries"][0]["name"] == "Ghost"
```

Add to the imports at the top of `tests/test_analyze.py`:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -k coverage -v`
Expected: FAIL — `module 'analyze' has no attribute 'collect_coverage'`

- [ ] **Step 3: Implement**

Add `from watchlist import load_watchlist` to `analyze.py`'s imports, then add after `_render_health`:

```python
def collect_coverage(conn: sqlite3.Connection, *, watchlist_path: Path,
                     stale_days: int = 30) -> dict:
    """Per watched company: how many rows it has produced and how fresh they are.

    A configured board returning nothing is indistinguishable from a firm that
    is not hiring, until you look — which is how the funds and banks stayed
    invisible for a week. Read through load_watchlist so an unsupported ATS
    still raises in one place."""
    wl = load_watchlist(watchlist_path)
    horizon = cutoff(stale_days)
    entries = []
    for c in wl.companies:
        row = conn.execute(
            """SELECT COUNT(*), SUM(status='scored'),
                      MAX(COALESCE(NULLIF(posted_at,''), discovered_at))
               FROM jobs WHERE company=?""", (c.name,)).fetchone()
        rows, scored, newest = int(row[0]), int(row[1] or 0), row[2]
        entries.append({
            "name": c.name, "ats": c.ats, "board": c.board,
            "archetype": c.archetype, "rows": rows, "scored": scored,
            "newest_posted_at": newest,
            "is_silent": rows == 0,
            "is_stale": bool(rows and newest and horizon and newest < horizon),
        })
    entries.sort(key=lambda e: (not e["is_silent"], not e["is_stale"],
                                e["rows"], e["name"]))
    return {
        "total_companies": len(entries),
        "silent": sum(1 for e in entries if e["is_silent"]),
        "stale": sum(1 for e in entries if e["is_stale"]),
        "stale_days": stale_days,
        "entries": entries,
    }


def _render_coverage(p: dict) -> str:
    lines = [f"{p['total_companies']} watched company(ies): "
             f"{p['silent']} silent, {p['stale']} stale "
             f"(nothing newer than {p['stale_days']} days)."]
    for e in p["entries"]:
        if e["is_silent"]:
            lines.append(f"  SILENT  {e['name']} ({e['ats']}/{e['board']})")
        elif e["is_stale"]:
            lines.append(f"  STALE   {e['name']} — newest "
                         f"{(e['newest_posted_at'] or '')[:10]}")
    if p["silent"] == 0 and p["stale"] == 0:
        lines.append("  every watched board is producing fresh rows.")
    return "\n".join(lines)


@main.command()
@_db_option
@click.option("--watchlist", "watchlist_path", default="watchlist.yaml",
              type=click.Path(exists=True, path_type=Path))
@click.option("--stale-days", default=30, type=int,
              help="A board with nothing newer than this is stale.")
@_json_option
def coverage(db_path: Path | None, watchlist_path: Path, stale_days: int,
             as_json: bool) -> None:
    """Which watched boards produce nothing, and which have gone quiet."""
    conn = dbmod.connect(db_path or Path(dbmod.DEFAULT_DB))
    _emit(collect_coverage(conn, watchlist_path=watchlist_path,
                           stale_days=stale_days), as_json, _render_coverage)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analyze.py -q`
Expected: PASS

- [ ] **Step 5: Smoke-test all four against the live database**

Run:
```bash
.venv/bin/python analyze.py health
.venv/bin/python analyze.py patterns --by archetype
.venv/bin/python analyze.py coverage
.venv/bin/python analyze.py shortlist --grade A
```
Expected: `health` reports ~432 scored and flags the threshold if `.env` still says 25; `shortlist --grade A` lists 25 jobs.

- [ ] **Step 6: Commit**

```bash
git add analyze.py tests/test_analyze.py
git commit -m "feat: analyze.py coverage — silent and stale watchlist boards"
```

---

### Task 8: `triage.py --approve` — the non-interactive gate

**Files:**
- Modify: `triage.py`
- Test: `tests/test_triage.py`

**Interfaces:**
- Consumes: `triage.apply_decision(conn, job, choice, tracker_path)` — unchanged, so tracker-writing keeps one implementation.
- Produces: `triage.approve_ids(conn, ids: list, tracker_path: Path) -> list[dict]` — one result dict per requested id, keys `id`, `ok`, `detail`. Order matches the input.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_triage.py`:

```python
def test_approve_ids_writes_rows_and_reports_each(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]

    results = triage.approve_ids(conn, [job.id], tracker)

    assert results == [{"id": job.id, "ok": True,
                        "detail": "Acme — ML Engineer"}]
    assert len(dbmod.jobs_by_status(conn, "approved")) == 1


def test_approve_ids_reports_an_unknown_id_without_aborting_the_rest(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]

    results = triage.approve_ids(conn, [99999, job.id], tracker)

    assert results[0]["ok"] is False and "no job" in results[0]["detail"]
    assert results[1]["ok"] is True
    assert len(dbmod.jobs_by_status(conn, "approved")) == 1


def test_approving_an_already_approved_job_is_an_idempotent_no_op(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]
    triage.approve_ids(conn, [job.id], tracker)

    results = triage.approve_ids(conn, [job.id], tracker)

    assert results[0]["ok"] is False
    assert "already approved" in results[0]["detail"]
    wb = openpyxl.load_workbook(tracker)
    assert wb["Apply Tracker"].max_row == 2   # header + one row, not two


def test_approve_ids_on_an_empty_list_does_nothing(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert triage.approve_ids(conn, [], tracker) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_triage.py -k approve -v`
Expected: FAIL — `module 'triage' has no attribute 'approve_ids'`

- [ ] **Step 3: Implement**

Add to `triage.py`, after `apply_decision`:

```python
def approve_ids(conn: sqlite3.Connection, ids: list, tracker_path: Path) -> list:
    """Approve jobs by id without the prompt loop, reporting each outcome.

    Routes through apply_decision, so the interactive and non-interactive paths
    cannot diverge in what they write. Per-id results rather than one boolean:
    the tracker is an .xlsx the user may have open, so a partial write is a real
    outcome that must be visible rather than inferred."""
    results = []
    for job_id in ids:
        rows = dbmod.jobs_by_status(conn, "scored")
        job = next((j for j in rows if j.id == job_id), None)
        if job is None:
            current = conn.execute("SELECT status FROM jobs WHERE id=?",
                                   (job_id,)).fetchone()
            if current is None:
                detail = f"no job with id {job_id}"
            elif current[0] == "approved":
                detail = f"already approved (id {job_id})"
            else:
                detail = f"id {job_id} is {current[0]}, not scored"
            results.append({"id": job_id, "ok": False, "detail": detail})
            continue
        try:
            apply_decision(conn, job, "a", tracker_path)
        except Exception as exc:  # noqa: BLE001 — surfaced per id, never silent
            results.append({"id": job_id, "ok": False,
                            "detail": f"tracker write failed: {exc}"})
            continue
        results.append({"id": job_id, "ok": True,
                        "detail": f"{job.company} — {job.title}"})
    return results
```

- [ ] **Step 4: Add the CLI flag**

In `triage.py`'s `main`, add the option and an early branch. Add above the existing `--tracker` option:

```python
@click.option("--approve", "approve", default=None,
              help="Comma-separated job ids to approve without the prompt loop.")
```

Add `approve: str | None` to `main`'s parameters, and immediately after `dbmod.init_db(conn)`:

```python
    if approve is not None:
        try:
            ids = [int(x) for x in approve.split(",") if x.strip()]
        except ValueError:
            raise SystemExit(f"--approve takes comma-separated integers, got "
                             f"{approve!r}")
        for r in approve_ids(conn, ids, tracker_path):
            mark = "✓" if r["ok"] else "✗"
            click.echo(f"  {mark} {r['detail']}")
        return
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_triage.py -q`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add triage.py tests/test_triage.py
git commit -m "feat: triage.py --approve, a non-interactive path to the same gate"
```

---

### Task 9: Plugin scaffolding and `/hunter8:triage`

The command that clears the backlog. It ships before `morning` because the 25 A-grades are already graded and waiting.

**Files:**
- Create: `plugin/.claude-plugin/plugin.json`
- Create: `plugin/skills/hunter8-corpus/SKILL.md`
- Create: `plugin/commands/triage.md`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `analyze.py shortlist --grade A --json` (Task 4), `triage.py --approve` (Task 8).
- Produces: the plugin root every later command file lives under.

- [ ] **Step 1: Write the manifest**

Create `plugin/.claude-plugin/plugin.json`:

```json
{
  "name": "hunter8",
  "version": "0.1.0",
  "description": "Drive and analyse the hunter8 job-search pipeline: graded shortlists, corpus patterns, pipeline health, and a chat-based approval gate.",
  "author": {
    "name": "Anthony Suherli"
  }
}
```

- [ ] **Step 2: Write the shared skill**

Create `plugin/skills/hunter8-corpus/SKILL.md`:

```markdown
---
name: hunter8-corpus
description: Use when reading or reporting on the hunter8 job corpus — running analyze.py, interpreting job statuses, grades or fit scores, or narrating a shortlist. Provides the schema, what each status means, and the rules that govern how this pipeline is allowed to fail.
---

# The hunter8 corpus

A personal job-search pipeline for one user. `hunter8.db` is SQLite, ~104 MB.

## Status lifecycle

`discovered` → `screened_in` | `screened_out` | `screen_error` → `scored` |
`score_error` → `approved` | `skipped` | `snoozed`

- `screened_*` — the local Ollama model's 0–100 `fit_score` against `rubric.md`.
- `scored` — Claude's A/B/C `grade` against `brief.md`, with `reasoning`,
  `archetype`, `comp_signal`, `red_flags`.
- `filtered_out` — dead residue from a deleted regex filter. Nothing reads it.

## The principle that explains the design

**Cost asymmetry.** A false promote costs ~$0.008 of Claude and is caught
downstream. A false reject loses a job silently and permanently. That is why the
screen is deliberately generous, and why noise in the promoted set is preferred
to a tighter filter.

## Rules

- **Never run `analyze.py` expecting it to write.** It is read-only by design.
- **If Ollama is unreachable, stop and report it. Never fall back to Claude** —
  promoting thousands of jobs to the subscription tier is the failure the tiered
  design exists to prevent.
- **Never filter error rows out of a report.** `screen_error` and `score_error`
  carry their reason; surface them.
- **An empty result is stated, never implied.** "No graded jobs in the last 7
  days" — never an empty report that reads as all-clear.
- **Never guess an approval.** Ambiguous input gets a question.

## Environment

`HUNTER8_DB_PATH`, `HUNTER8_SCREEN_MODEL` (required by `screen.py`),
`HUNTER8_SCREEN_THRESHOLD` (calibrated: 65), `TRACKER_PATH`, `TAVILY_API_KEY`.

## Commands

Run from the repo root with `.venv/bin/python`:

    analyze.py shortlist --since-days N [--grade A,B] [--new-since ISO] [--json]
    analyze.py patterns --by company|archetype|ats|location|source [--json]
    analyze.py health [--json]
    analyze.py coverage [--stale-days N] [--json]
    triage.py --approve 1,2,3 --tracker "$TRACKER_PATH"
```

- [ ] **Step 3: Write the triage command**

Create `plugin/commands/triage.md`:

```markdown
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
```

- [ ] **Step 4: Gitignore the reports directory**

Add to `.gitignore`, after the `jobs-to-apply-*.md` line:

```
reports/
```

- [ ] **Step 5: Verify the manifest parses and the tree is right**

Run:
```bash
.venv/bin/python -c "import json,pathlib; print(json.loads(pathlib.Path('plugin/.claude-plugin/plugin.json').read_text())['name'])"
find plugin -type f | sort
```
Expected: prints `hunter8`, then exactly the manifest, `skills/hunter8-corpus/SKILL.md`, and `commands/triage.md`. No component directory may sit inside `.claude-plugin/`.

- [ ] **Step 6: Commit**

```bash
git add plugin .gitignore
git commit -m "feat: hunter8 plugin scaffolding and the triage command"
```

---

### Task 10: `/hunter8:morning`

**Files:**
- Create: `plugin/commands/morning.md`
- Create: `plugin/agents/hunter8-analyst.md`

**Interfaces:**
- Consumes: all four `analyze.py` subcommands, plus `discover.py`, `screen.py`, `score.py`.
- Produces: `reports/YYYY-MM-DD.md`.

- [ ] **Step 1: Write the analyst subagent**

Create `plugin/agents/hunter8-analyst.md`:

```markdown
---
name: hunter8-analyst
description: Narrates hunter8 analyze.py JSON output into a written report. Use when a shortlist or pattern run needs turning into prose, so the raw rows stay out of the main conversation.
tools: Bash, Read, Write
---

You turn `analyze.py --json` output into a report a job seeker can act on in five
minutes. You exist so that 160+ rows of `reasoning` never enter the main
conversation — return the finished report, not the data.

## What to write

1. **Headline** — how many graded in the window, the A/B/C split, how many are
   new since the last run.
2. **What changed** — new A-grades by name. If `movements` is non-empty, say
   which grades moved and in which direction. If `from_brief_sha` differs from
   `to_brief_sha`, the profile was edited between gradings — say so, because that
   is the cause. If `movements_unavailable` is true, say history is not being
   recorded yet.
3. **The A-grades** — a table: fit, company, role, posted. Then a short paragraph
   on the two or three worth opening first, citing the specific evidence in the
   posting that makes them fit.
4. **What to ignore, and why** — the cluster that looks strong but is a volume
   artifact from one company posting heavily.

## Rules

- **Never invent a number.** Every figure comes from the JSON.
- **State an empty window plainly.** "Nothing graded in the last 7 days." Never
  pad an empty run into a report that reads as progress.
- **Distinguish volume from hit rate.** Thirty roles from one company is not the
  same as a high A-rate, and conflating them is the most common way this report
  misleads.
- **Do not recommend applying.** You describe fit; the human decides.
- **Correct yourself when the data contradicts an earlier report.** Say so
  explicitly rather than quietly changing the story.

Write to `reports/YYYY-MM-DD.md` and return a four-line summary: counts, the top
three A-grades by name, anything that moved, and anything that looks broken.
```

- [ ] **Step 2: Write the morning command**

Create `plugin/commands/morning.md`:

```markdown
---
description: Run the full discovery pipeline, then report and offer triage
argument-hint: "[days, default 7]"
allowed-tools: Bash, Read, Write, Task
---

Run one full morning cycle. Window: $1 days (default 7).

## 1. Preflight — before spending anything

Check, and report all failures together rather than one at a time:

- `analyze.py` exists in the working directory. If not, stop.
- `HUNTER8_SCREEN_MODEL` is set. If not, stop — `screen.py` requires it.
- Ollama answers: `curl -s -m 3 http://localhost:11434/api/tags`. If not, stop
  and print the fix (`ollama serve`, or `brew install ollama`). **Do not offer to
  run the pipeline without the local screen.**
- `intent.md` exists, and `TRACKER_PATH` is set.
- Run `.venv/bin/python analyze.py health --json`. If `threshold.disagrees`,
  `threshold.report_missing`, or `threshold.stale` is true, report it as a
  **warning** and continue — a deliberate override is legitimate.

## 2. Record the boundary

Run:

    .venv/bin/python -c "import db,pathlib;c=db.connect(pathlib.Path('hunter8.db'));print(c.execute('SELECT MAX(scored_at) FROM jobs').fetchone()[0] or '')"

Keep the value as `T0`. Everything graded after it is this run's output. Capture
it **before** the pipeline runs.

## 3. Run the pipeline

    .venv/bin/python discover.py
    .venv/bin/python screen.py --since-days <days>
    .venv/bin/python score.py --limit 25 --since-days <days>

The threshold comes from the configured value reported in step 1; do not pass
`--threshold`.

If `screen.py` stops with an Ollama error, or `score.py` stops with a quota or
login error, report the message verbatim and stop. **Never retry, never fall back
to another model.** For a `score.py` stop, also report how many remain in
`screened_in` so the run can resume with `--limit`.

## 4. Report

Run `.venv/bin/python analyze.py shortlist --since-days <days> --new-since <T0> --json`.

Dispatch the `hunter8-analyst` subagent with that JSON to write
`reports/YYYY-MM-DD.md`. If it returns nothing, present the shortlist table
yourself — never report success with no report.

## 5. Hand over

Show the headline, the new A-grades, and anything `health` flagged. Then offer
`/hunter8:triage`. Do not approve anything yourself.
```

- [ ] **Step 3: Verify the tree**

Run: `find plugin -type f | sort`
Expected: manifest, `agents/hunter8-analyst.md`, `commands/morning.md`, `commands/triage.md`, `skills/hunter8-corpus/SKILL.md`.

- [ ] **Step 4: Commit**

```bash
git add plugin
git commit -m "feat: /hunter8:morning and the analyst subagent"
```

---

### Task 11: `/hunter8:health`, `/hunter8:coverage`, and the README

**Files:**
- Create: `plugin/commands/health.md`
- Create: `plugin/commands/coverage.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `analyze.py health`, `analyze.py patterns`, `analyze.py coverage`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the health command**

Create `plugin/commands/health.md`:

```markdown
---
description: Report pipeline and calibration state, with drift called out
allowed-tools: Bash, Read
---

Run `.venv/bin/python analyze.py health --json` and
`.venv/bin/python analyze.py patterns --by archetype --json`, then report:

1. **Queue** — what is where, and what is stuck. A large `discovered` count
   means screening is behind; a large `screened_in` count means grading is.
2. **Misconfiguration** — every true flag under `threshold`, with the fix.
   `disagrees` means runs are screening at a value nobody chose.
3. **Agreement** — A-recall at the current threshold over the graded sample, and
   the highest threshold still holding 100%. If A-recall is below 1.0, say
   plainly that the screen is currently discarding jobs Claude would have called
   A.
4. **Errors** — every `screen_error` / `score_error` row with its reason,
   grouped if they share a cause.
5. **Cost** — notional lifetime spend and priced rows. Note that billing is $0
   under subscription auth.
6. **Where you convert** — the top and bottom archetypes by A-rate, flagging any
   whose sample is too small to read.

Recommend at most two concrete actions. Do not run them.
```

- [ ] **Step 2: Write the coverage command**

Create `plugin/commands/coverage.md`:

```markdown
---
description: Find watchlist boards producing nothing, and propose additions
argument-hint: "[stale-days, default 30]"
allowed-tools: Bash, Read
---

Run `.venv/bin/python analyze.py coverage --stale-days ${1:-30} --json`.

Report:

1. **Silent boards** — configured and returning zero rows. For each, say whether
   the likely cause is a wrong slug, a board that has moved, or a firm that
   genuinely is not hiring. Do not guess a replacement slug and present it as
   fact — a Workday tenant slug cannot be inferred, only verified.
2. **Stale boards** — producing rows once, nothing recent.
3. **Firms with no entry at all** — read `watchlist.yaml` and name target firms
   absent from it entirely.

Then propose concrete `watchlist.yaml` additions as a YAML block for the user to
paste. Do not edit `watchlist.yaml` yourself. For any Workday or Eightfold
suggestion, say explicitly that the slug is unverified and must be probed before
it is trusted.
```

- [ ] **Step 3: Document the plugin in the README**

Add to `README.md`, after the "Discovery → Triage → Apply" section:

```markdown
## Claude Code plugin

`plugin/` is a local Claude Code plugin wrapping the loop. Install it from this
repo, then run from the repo root:

| Command | Does |
|---|---|
| `/hunter8:morning [days]` | Preflight, run the pipeline, write `reports/YYYY-MM-DD.md`, offer triage |
| `/hunter8:triage [grade]` | Present graded jobs with reasoning, write approvals to the tracker |
| `/hunter8:health` | Queue counts, threshold drift, screen-vs-Claude agreement, cost |
| `/hunter8:coverage [days]` | Silent and stale watchlist boards, proposed additions |

The commands shell out to `analyze.py`, which is read-only and has `--json` on
every subcommand — so the same reports work from a plain terminal with no Claude
session:

```bash
python analyze.py health
python analyze.py shortlist --grade A --since-days 7
python analyze.py patterns --by archetype
python analyze.py coverage
```

Approval is always a human decision made in chat. `apply.py` is still run by
hand; agent-driven submission is a separate spec.
```

- [ ] **Step 4: Run the full suite one last time**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS. Baseline was 122; this plan adds 1 (Task 1) + 4 (Task 2) + 5
(Task 3) + 7 (Task 4) + 4 (Task 5) + 6 (Task 6) + 3 (Task 7) + 4 (Task 8) = 34
tests, so **156 passed**. A lower number means a task's tests were not written.

- [ ] **Step 5: Commit**

```bash
git add plugin README.md
git commit -m "feat: health and coverage commands, and document the plugin"
```

---

### Task 12: Manual verification

Plugin commands and subagent narration have no unit-test coverage — prompt behaviour is not testable by pytest. This task is the substitute, and it is not optional.

**Files:**
- Create: `docs/truenorth/plans/2026-07-29-hunter8-plugin-verification.md`

**Interfaces:**
- Consumes: everything above.
- Produces: a recorded verification log.

- [ ] **Step 1: Install the plugin and confirm the commands resolve**

Install `plugin/` as a local plugin, then confirm all four of `/hunter8:morning`,
`/hunter8:triage`, `/hunter8:health`, `/hunter8:coverage` are listed. Record the
install method that actually worked — the manifest is standard, but the local
install path is the step most likely to differ from expectation.

- [ ] **Step 2: `/hunter8:health` against the live database**

Expected: ~432 `scored`, ~7,022 `discovered`, 0 `approved`. The threshold section
must flag disagreement if `.env` still lacks `HUNTER8_SCREEN_THRESHOLD`. Paste the
output into the verification doc.

- [ ] **Step 3: `/hunter8:triage` on the real backlog**

This is the acceptance test for the whole spec. Expected: 25 A-grade jobs
presented with reasoning; approve two or three; `triage.py --approve` writes
those rows; the tracker gains them with working hyperlinks.

Then confirm the gate held: check that `approved` equals exactly the number you
named, and that nothing else moved.

- [ ] **Step 4: Deliberately break it, twice**

Stop Ollama (`pkill ollama`) and run `/hunter8:morning`. Expected: preflight
stops with the `ollama serve` fix and **does not** offer to run without the
screen. Record what it actually did.

Then restart Ollama, and answer the triage approval question with "approve the
good ones". Expected: it asks again for a concrete list rather than choosing.
Record what it actually did.

- [ ] **Step 5: Write up and commit**

Record each step's actual output, and every gap between expected and actual, in
`docs/truenorth/plans/2026-07-29-hunter8-plugin-verification.md`. A gap is a
finding, not a failure — note it and decide whether it needs a fix now.

```bash
git add docs/truenorth/plans/2026-07-29-hunter8-plugin-verification.md
git commit -m "docs: manual verification of the hunter8 plugin"
```

---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| `analyze.py shortlist` with `--since-days`, `--grade`, `--new-since` | 4 |
| `analyze.py patterns --by` (5 dimensions) | 5 |
| `analyze.py health` — queue, threshold, agreement, cost, errors | 6 |
| `analyze.py coverage --stale-days` | 7 |
| `health` reuses `calibrate.agreement`, makes no model calls | 6 (asserted in step 5) |
| `coverage` reads via `watchlist.load_watchlist` | 7 |
| `analyze.py` never writes, never calls `init_db` | 4 (asserted in step 5), 6 |
| Degrades when `grade_history` is absent | 4 |
| `grade_history` schema, append-only | 2 |
| `brief_sha` provenance, never silently NULL | 3 |
| `set_score` gains `brief_sha`; `db.py` stays brief-ignorant | 2, 3 |
| `triage.py --approve`, per-id outcomes, idempotent | 8 |
| Locked-workbook partial write is visible | 8 |
| Plugin manifest, 4 commands, skill, subagent | 9, 10, 11 |
| Preflight: hard stop vs warning | 10 |
| `T₀` captured before the run | 10 |
| Ollama never falls back to Claude | 9 (skill), 10 (command), 12 (verified) |
| Ambiguous approval gets a question | 9 (command), 12 (verified) |
| Empty result stated explicitly | 4, 10 |
| Analyst fallback if the subagent returns nothing | 10 |
| `reports/` gitignored | 9 |
| Threshold default 25 → 65 | 1 |
| Manual verification step | 12 |

No spec requirement is unimplemented.
