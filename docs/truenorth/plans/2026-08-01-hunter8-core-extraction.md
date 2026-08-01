# hunter8 Core Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use truenorth:subagent-driven-development (recommended) or truenorth:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extract the complete provider-neutral domain and adapter contracts from the hosted-companion design while adapting the working local pipeline without changing its observable behavior.

**Architecture:** Add a small stdlib-only `hunter8_core` package containing immutable posting, profile, company-thesis, and ranking values plus source/model/workflow protocols and strict assessment payload parsing. Keep SQLite workflow state, YAML, Tavily, Ollama, Claude CLI, Excel, Playwright, and all hosted implementations outside the package; adapt the current local runtime only at explicit posting and assessment boundaries.

**Vision goals served:** End Goal 5 (prove the transferable product thesis without productizing the personal runtime) while preserving End Goals 2–4 and all local privacy, failure-visibility, and human-approval invariants.

**Tech Stack:** Python 3.11 typing/dataclasses, pytest 8.2, SQLite, httpx; no new runtime dependency.

> **Deviation (2026-08-01, execution):** the project venv is Python 3.9.6, not
> the 3.11 assumed above, and `@dataclass(slots=True)` requires 3.10+. Every
> core dataclass therefore uses `@dataclass(frozen=True)` without `slots`.
> Immutability — the only property the plan's tests assert — is unaffected;
> `slots` is a memory and attribute-typo optimization. `slots=True` was the sole
> 3.10+ construct in this plan, so nothing else changes. Restore it if the venv
> is ever rebuilt on 3.10+.

## Global Constraints

- Keep hunter8's personal database, profile artifacts, watchlist, tracker, résumé files, and application automation outside `hunter8_core`.
- `hunter8_core` imports only the Python standard library.
- Preserve exact URL deduplication, source-failure isolation, dated-run behavior, threshold semantics, append-only grade history, and cost recording.
- Keep Tavily local-only; it is not a hosted `CompanySource`.
- Keep the existing `db.Job` row model until hosted persistence exists; separate it from public `JobPosting` through conversion methods.
- Define the hosted profile, company, and ranking contracts, but do not add résumé parsers, model implementations, auth, queues, Supabase, HTTP APIs, or deployment code in this plan.
- Model payloads fail visibly when malformed; never coerce an invalid grade or a string `red_flags` into an apparently valid assessment.
- Run `.venv/bin/pytest tests/ -q` before declaring the extraction complete.

---

## File map

**Create**

- `hunter8_core/__init__.py` — public exports for stable domain contracts.
- `hunter8_core/models.py` — immutable posting, profile, company, and ranking values.
- `hunter8_core/ports.py` — every provider-neutral adapter protocol from the umbrella spec.
- `hunter8_core/assessment.py` — validated `ScreenAssessment` and `GradeAssessment`.
- `hunter8_core/README.md` — allowed dependencies and local/hosted boundary.
- `tests/test_core_models.py` — domain-value and database-conversion tests.
- `tests/test_core_contracts.py` — complete profile, company, ranking, and protocol contract tests.
- `tests/test_core_ports.py` — source injection and dependency-boundary tests.
- `tests/test_core_assessment.py` — strict payload validation tests.

**Modify**

- `db.py` — map between local workflow rows and `JobPosting`; add `insert_posting`.
- `sources.py` — return `JobPosting` from every fetch/parser; expose local `ATSCompanySource`.
- `watchlist.py` — convert a local YAML `Company` into `SourceConfig`.
- `discover.py` — consume `CompanySource` and persist `JobPosting`.
- `screen.py` — prompt from `JobPosting` and parse `ScreenAssessment`.
- `score.py` — prompt from `JobPosting` and parse `GradeAssessment`.
- `tests/test_sources.py` — assert deterministic adapters return core postings.
- `tests/test_discover.py` — inject a fake `CompanySource`.
- `tests/test_screen.py` — verify invalid screen payloads become visible errors.
- `tests/test_score.py` — verify invalid grade payloads become visible errors.
- `README.md` — document the extracted boundary.

## Interfaces locked by this plan

```python
# hunter8_core/models.py
@dataclass(frozen=True, slots=True)
class JobPosting:
    url: str
    company: str
    title: str
    location: str
    source: str
    ats: str | None = None
    posted_at: str | None = None
    description: str = ""
    canonical_url: str | None = None
    fetched_at: str | None = None

@dataclass(frozen=True, slots=True)
class SourceConfig:
    ats: str
    board: str
    company: str
```

```python
# hunter8_core/ports.py (all protocols use immutable values from models.py)
class JsonModel(Protocol):
    def chat_json(self, system: str, user: str) -> Mapping[str, Any]: ...

class ResumeToProfile(Protocol):
    def extract(self, document_text: str) -> ProfileDraft: ...

class QuestionPlanner(Protocol):
    def plan(self, draft: ProfileDraft) -> Sequence[ProfileQuestion]: ...

class CompanyRecommender(Protocol):
    def recommend(self, profile: ConfirmedProfile) -> CompanyThesis: ...

class CompanySource(Protocol):
    def fetch(
        self, config: SourceConfig, *, timeout: float = 20.0
    ) -> Sequence[JobPosting]: ...

class EvidenceRanker(Protocol):
    def assess(
        self, profile: ConfirmedProfile, posting: JobPosting
    ) -> MatchAssessment: ...

class ShortlistRanker(Protocol):
    def order(
        self, assessments: Sequence[MatchAssessment]
    ) -> Sequence[RankedMatch]: ...
```

```python
# hunter8_core/assessment.py
@dataclass(frozen=True, slots=True)
class ScreenAssessment:
    fit_score: int
    reason: str

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "ScreenAssessment": ...

@dataclass(frozen=True, slots=True)
class GradeAssessment:
    grade: Literal["A", "B", "C"]
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: tuple[str, ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "GradeAssessment": ...
```

```python
# db.py
Job.to_posting() -> JobPosting
insert_posting(conn: sqlite3.Connection, posting: JobPosting) -> bool
insert_job(conn: sqlite3.Connection, job: Job) -> bool  # compatibility wrapper
```

---

### Task 1: Introduce `JobPosting` and the SQLite boundary

**Files:**
- Create: `hunter8_core/__init__.py`
- Create: `hunter8_core/models.py`
- Create: `tests/test_core_models.py`
- Modify: `db.py:4-5,49-72,107-119`

**Interfaces:**
- Produces: `JobPosting`, `SourceConfig`, `Job.to_posting()`, `insert_posting()`.
- Preserves: `insert_job()` for existing local callers and tests.

- [x] **Step 1: Write failing core-model and mapping tests**

```python
# tests/test_core_models.py
from dataclasses import FrozenInstanceError, replace

import pytest

import db as dbmod
from hunter8_core import JobPosting, SourceConfig


def _posting(url: str = "https://x/1") -> JobPosting:
    return JobPosting(
        url=url,
        company="Acme",
        title="AI Engineer",
        location="New York, NY",
        source="ats:greenhouse",
        ats="greenhouse",
        posted_at="2026-08-01T00:00:00+00:00",
        description="Build agent systems.",
    )


def test_job_posting_is_immutable():
    posting = _posting()
    with pytest.raises(FrozenInstanceError):
        posting.title = "Changed"


def test_source_config_requires_explicit_values():
    with pytest.raises(ValueError, match="ats, board, and company"):
        SourceConfig(ats="", board="acme", company="Acme")


def test_insert_posting_round_trips_through_local_job(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)

    assert dbmod.insert_posting(conn, _posting()) is True
    stored = dbmod.jobs_by_status(conn, "discovered")[0]

    assert stored.raw_text == "Build agent systems."
    assert stored.to_posting() == replace(
        _posting(), fetched_at=stored.discovered_at
    )


def test_insert_job_remains_a_compatibility_wrapper(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    job = dbmod.Job(
        url="https://x/legacy",
        company="Acme",
        title="ML Engineer",
        location="Remote US",
        source="ats:lever",
        ats="lever",
        raw_text="Legacy caller.",
    )

    assert dbmod.insert_job(conn, job) is True
    assert dbmod.insert_job(conn, job) is False
```

- [x] **Step 2: Run the new tests and verify the boundary does not exist**

Run:

```bash
.venv/bin/pytest tests/test_core_models.py -q
```

Expected: collection fails because `hunter8_core` does not exist.

- [x] **Step 3: Implement immutable core models**

```python
# hunter8_core/models.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class JobPosting:
    url: str
    company: str
    title: str
    location: str
    source: str
    ats: str | None = None
    posted_at: str | None = None
    description: str = ""
    canonical_url: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True, slots=True)
class SourceConfig:
    ats: str
    board: str
    company: str

    def __post_init__(self) -> None:
        if not self.ats or not self.board or not self.company:
            raise ValueError("ats, board, and company must be non-empty")
```

```python
# hunter8_core/__init__.py
from hunter8_core.models import JobPosting, SourceConfig

__all__ = ["JobPosting", "SourceConfig"]
```

- [x] **Step 4: Add explicit conversion and persistence methods**

Add the import:

```python
# db.py
from hunter8_core import JobPosting
```

Add this method to `Job` after `cost_usd`:

```python
    def to_posting(self) -> JobPosting:
        return JobPosting(
            url=self.url,
            company=self.company,
            title=self.title,
            location=self.location,
            source=self.source,
            ats=self.ats,
            posted_at=self.posted_at,
            description=self.raw_text,
            fetched_at=self.discovered_at,
        )
```

Replace the insertion function with:

```python
def insert_posting(conn: sqlite3.Connection, posting: JobPosting) -> bool:
    """Persist public posting data in the local workflow table."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO jobs
           (url, company, title, location, source, ats, posted_at, raw_text,
            status, discovered_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            posting.url,
            posting.company,
            posting.title,
            posting.location,
            posting.source,
            posting.ats,
            posting.posted_at,
            posting.description,
            "discovered",
            posting.fetched_at or _now(),
        ),
    )
    conn.commit()
    return cur.rowcount == 1


def insert_job(conn: sqlite3.Connection, job: Job) -> bool:
    """Compatibility wrapper for local workflow callers."""
    return insert_posting(conn, job.to_posting())
```

- [x] **Step 5: Run focused database tests**

Run:

```bash
.venv/bin/pytest tests/test_core_models.py tests/test_db.py -q
```

Expected: PASS.

- [x] **Step 6: Commit the domain boundary**

```bash
git add hunter8_core/__init__.py hunter8_core/models.py \
  tests/test_core_models.py db.py
git commit -m "refactor: separate public job postings from workflow rows"
```

---

### Task 2: Make every source adapter return `JobPosting`

**Files:**
- Modify: `sources.py:7-11,33-88,114-157,178-275`
- Modify: `tests/test_sources.py:1-6,15-42,69-105`

**Interfaces:**
- Consumes: `JobPosting`.
- Produces: all `parse_*`, `fetch_ats`, `fetch_workday`, `fetch_eightfold`, and
  local-only `fetch_tavily` return `list[JobPosting]`.
- Preserves: function names and HTTP behavior.

- [x] **Step 1: Add failing type assertions to source tests**

Add:

```python
from hunter8_core import JobPosting
```

Add this assertion after each parser call in
`test_parse_greenhouse`, `test_parse_ashby`, `test_parse_lever`,
`test_parse_workday_detail_uses_start_date_not_relative_posted_on`, and
`test_parse_eightfold_converts_unix_timestamp`:

```python
assert isinstance(jobs[0], JobPosting)
```

For the Workday test, where the variable is `j`, add:

```python
assert isinstance(j, JobPosting)
```

- [x] **Step 2: Run parser tests and verify they fail**

Run:

```bash
.venv/bin/pytest tests/test_sources.py -q
```

Expected: FAIL because parsers still return `db.Job`.

- [x] **Step 3: Change source imports, annotations, and constructors**

Replace:

```python
from db import Job
```

with:

```python
from hunter8_core import JobPosting
```

Use these exact signatures:

```python
def parse_greenhouse(
    payload: dict[str, Any], *, company: str
) -> list[JobPosting]:

def parse_ashby(
    payload: dict[str, Any], *, company: str
) -> list[JobPosting]:

def parse_lever(
    payload: list[dict[str, Any]], *, company: str
) -> list[JobPosting]:

def parse_workday_detail(
    payload: dict[str, Any], *, company: str, url: str
) -> JobPosting | None:

def parse_eightfold(
    payload: dict[str, Any], *, company: str
) -> list[JobPosting]:

def fetch_workday(
    *, board: str, company: str, timeout: float = 20.0,
    max_jobs: int = WORKDAY_MAX_JOBS
) -> list[JobPosting]:

def fetch_eightfold(
    *, board: str, company: str, timeout: float = 20.0,
    max_jobs: int = 500
) -> list[JobPosting]:

def fetch_ats(
    ats: str, *, board: str, company: str, timeout: float = 20.0
) -> list[JobPosting]:

def fetch_tavily(
    query: str, api_key: str, *, max_results: int = 5,
    timeout: float = 30.0
) -> list[JobPosting]:
```

For every parser constructor, use `JobPosting` and rename `raw_text` to
`description`. The five constructor shapes are:

```python
JobPosting(
    url=j["absolute_url"],
    company=company,
    title=j.get("title", ""),
    location=loc,
    source="ats:greenhouse",
    ats="greenhouse",
    posted_at=j.get("updated_at"),
    description=j.get("content", "") or "",
)

JobPosting(
    url=j["jobUrl"],
    company=company,
    title=j.get("title", ""),
    location=loc or "",
    source="ats:ashby",
    ats="ashby",
    posted_at=j.get("publishedAt"),
    description=j.get("descriptionPlain", "") or "",
)

JobPosting(
    url=j["hostedUrl"],
    company=company,
    title=j.get("text", ""),
    location=cats.get("location", ""),
    source="ats:lever",
    ats="lever",
    posted_at=_epoch_ms_to_iso(j.get("createdAt")),
    description=j.get("descriptionPlain", "") or "",
)

JobPosting(
    url=url,
    company=company,
    title=title,
    location=info.get("location", "") or "",
    source="ats:workday",
    ats="workday",
    posted_at=posted,
    description=_detag(info.get("jobDescription", "")),
)

JobPosting(
    url=url,
    company=company,
    title=p.get("name", ""),
    location=p.get("location", "") or "",
    source="ats:eightfold",
    ats="eightfold",
    posted_at=posted,
    description="\n".join(b for b in bits if b),
)
```

Use this local-only Tavily constructor:

```python
JobPosting(
    url=r["url"],
    company="(tavily)",
    title=r.get("title", "")[:200],
    location="",
    source="tavily",
    ats=None,
    description=r.get("content", "") or "",
)
```

Change local accumulator annotations and Workday's nested helper:

```python
out: list[JobPosting] = []

def one(path: str) -> JobPosting | None:
```

- [x] **Step 4: Update description assertions**

Change parser-result assertions in `tests/test_sources.py` from `.raw_text` to
`.description`. Do not change repair tests: they intentionally exercise local
`db.Job` rows.

- [x] **Step 5: Run source tests**

Run:

```bash
.venv/bin/pytest tests/test_sources.py -q
```

Expected: PASS with the same parsed values, dates, paging, and malformed-row
behavior.

- [x] **Step 6: Commit the source boundary**

```bash
git add sources.py tests/test_sources.py
git commit -m "refactor: return core postings from job sources"
```

---

### Task 3: Define the complete hosted-companion domain contract

**Files:**
- Create: `hunter8_core/ports.py`
- Create: `tests/test_core_contracts.py`
- Modify: `hunter8_core/models.py`
- Modify: `hunter8_core/__init__.py`

**Interfaces:**
- Produces: `ProfileDraft`, `ConfirmedProfile`, `CompanyThesis`,
  `WatchedCompany`, `MatchAssessment`, `RankedMatch`, and every adapter protocol
  named in the umbrella spec.
- Preserves: stdlib-only immutable values; no parser, model, persistence, or
  hosted-service implementation.

- [x] **Step 1: Write failing domain-contract tests**

```python
# tests/test_core_contracts.py
import pytest

from hunter8_core import (
    CompanyRecommendation,
    CompanyRecommender,
    CompanySource,
    CompanyThesis,
    ConfirmedProfile,
    ConstraintResult,
    EvidenceItem,
    EvidenceRanker,
    JobPosting,
    MatchAssessment,
    ProfileDraft,
    ProfileQuestion,
    QuestionPlanner,
    RankedMatch,
    ResumeToProfile,
    ShortlistRanker,
    SourceConfig,
    WatchedCompany,
)


def _evidence(state: str = "confirmed") -> EvidenceItem:
    return EvidenceItem(
        evidence_id="ev-1",
        claim="Built production agent systems.",
        category="experience",
        source_excerpt="Built production agent systems",
        source_locator="page 1, Vanguard",
        source_hash="sha256:abc",
        confidence=0.95,
        state=state,
    )


def _profile() -> ConfirmedProfile:
    return ConfirmedProfile(
        profile_id="profile-1",
        version=1,
        target_role_shapes=("agent infrastructure",),
        hard_constraints=("New York or remote",),
        preferred_work=("production ML",),
        excluded_work=("pure dashboarding",),
        evidence=(_evidence(),),
        known_gaps=("buy-side experience",),
        employer_thesis="AI systems roles near investment decisions.",
    )


def test_profile_draft_keeps_uncertainty_explicit():
    draft = ProfileDraft(
        target_role_shapes=("agent infrastructure",),
        hard_constraints=(),
        preferred_work=("production ML",),
        excluded_work=(),
        evidence=(_evidence("draft"),),
        known_gaps=("work authorization",),
        employer_thesis="",
    )
    assert draft.known_gaps == ("work authorization",)
    assert draft.evidence[0].state == "draft"


def test_confirmed_profile_requires_positive_version():
    with pytest.raises(ValueError, match="version"):
        ConfirmedProfile(
            profile_id="profile-1",
            version=0,
            target_role_shapes=(),
            hard_constraints=(),
            preferred_work=(),
            excluded_work=(),
            evidence=(),
            known_gaps=(),
            employer_thesis="",
        )


def test_confirmed_profile_rejects_unconfirmed_evidence():
    with pytest.raises(ValueError, match="confirmed evidence"):
        ConfirmedProfile(
            profile_id="profile-1",
            version=1,
            target_role_shapes=(),
            hard_constraints=(),
            preferred_work=(),
            excluded_work=(),
            evidence=(_evidence("draft"),),
            known_gaps=(),
            employer_thesis="",
        )


def test_company_thesis_links_reasons_to_evidence():
    thesis = CompanyThesis(
        profile_id="profile-1",
        profile_version=1,
        recommendations=(
            CompanyRecommendation(
                name="Acme Capital",
                tier="core",
                reason="Agent infrastructure maps to the candidate's work.",
                evidence_ids=("ev-1",),
                official_careers_url="https://acme.example/careers",
                verification_status="verified",
            ),
        ),
    )
    assert thesis.recommendations[0].evidence_ids == ("ev-1",)


def test_watched_company_requires_a_verified_source_config():
    company = WatchedCompany(
        name="Acme Capital",
        tier="core",
        careers_url="https://acme.example/careers",
        source=SourceConfig(
            ats="greenhouse", board="acme", company="Acme Capital"
        ),
        evidence_ids=("ev-1",),
    )
    assert company.source.board == "acme"


def test_match_assessment_exposes_constraint_precedence():
    assessment = MatchAssessment(
        posting_url="https://x/1",
        profile_id="profile-1",
        profile_version=1,
        constraint_results=(
            ConstraintResult(
                constraint="New York or remote",
                status="unknown",
                explanation="Location is not stated.",
            ),
            ConstraintResult(
                constraint="No sponsorship required",
                status="fail",
                explanation="Posting requires unrestricted authorization.",
            ),
        ),
        score=72,
        explanation="Strong role fit with a hard-constraint failure.",
        evidence_ids=("ev-1",),
        tradeoffs=("Industry transition",),
        uncertainties=("Compensation missing",),
        provider="ai-gateway",
        model="configured-model",
    )
    assert assessment.constraint_status == "fail"


def test_match_assessment_rejects_unbounded_score():
    with pytest.raises(ValueError, match="score"):
        MatchAssessment(
            posting_url="https://x/1",
            profile_id="profile-1",
            profile_version=1,
            constraint_results=(),
            score=101,
            explanation="",
            evidence_ids=(),
            tradeoffs=(),
            uncertainties=(),
            provider="ai-gateway",
            model="configured-model",
        )


def test_ranked_match_requires_one_based_rank():
    assessment = MatchAssessment(
        posting_url="https://x/1",
        profile_id="profile-1",
        profile_version=1,
        constraint_results=(),
        score=90,
        explanation="Strong fit.",
        evidence_ids=("ev-1",),
        tradeoffs=(),
        uncertainties=(),
        provider="ai-gateway",
        model="configured-model",
    )
    with pytest.raises(ValueError, match="rank"):
        RankedMatch(rank=0, assessment=assessment)


def test_question_and_posting_contracts_are_plain_values():
    question = ProfileQuestion(
        key="location",
        prompt="Which locations are acceptable?",
        reason="Location changes hard-constraint evaluation.",
    )
    posting = JobPosting(
        url="https://x/1",
        canonical_url="https://x/1",
        company="Acme",
        title="AI Engineer",
        location="New York",
        source="ats:greenhouse",
        fetched_at="2026-08-01T00:00:00+00:00",
    )
    assert question.key == "location"
    assert posting.canonical_url == posting.url


@pytest.mark.parametrize(
    ("protocol", "method_name"),
    [
        (ResumeToProfile, "extract"),
        (QuestionPlanner, "plan"),
        (CompanyRecommender, "recommend"),
        (CompanySource, "fetch"),
        (EvidenceRanker, "assess"),
        (ShortlistRanker, "order"),
    ],
)
def test_adapter_protocol_exports_have_locked_method_names(
    protocol, method_name
):
    assert callable(getattr(protocol, method_name))
```

- [x] **Step 2: Run the contract tests and verify the types are missing**

Run:

```bash
.venv/bin/pytest tests/test_core_contracts.py -q
```

Expected: collection fails on the first missing domain export.

- [x] **Step 3: Add the remaining immutable domain values**

Add `from typing import Literal` beside the existing imports in
`hunter8_core/models.py`, then append:

```python
EvidenceState = Literal["draft", "confirmed", "rejected"]
CompanyTier = Literal["core", "adjacent", "exploratory"]
VerificationStatus = Literal["verified", "pending", "rejected"]
ConstraintStatus = Literal["pass", "fail", "unknown"]


@dataclass(frozen=True, slots=True)
class EvidenceItem:
    evidence_id: str
    claim: str
    category: str
    source_excerpt: str
    source_locator: str
    source_hash: str
    confidence: float
    state: EvidenceState

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.state not in {"draft", "confirmed", "rejected"}:
            raise ValueError("state must be draft, confirmed, or rejected")


@dataclass(frozen=True, slots=True)
class ProfileQuestion:
    key: str
    prompt: str
    reason: str


@dataclass(frozen=True, slots=True)
class ProfileDraft:
    target_role_shapes: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    preferred_work: tuple[str, ...]
    excluded_work: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    known_gaps: tuple[str, ...]
    employer_thesis: str


@dataclass(frozen=True, slots=True)
class ConfirmedProfile:
    profile_id: str
    version: int
    target_role_shapes: tuple[str, ...]
    hard_constraints: tuple[str, ...]
    preferred_work: tuple[str, ...]
    excluded_work: tuple[str, ...]
    evidence: tuple[EvidenceItem, ...]
    known_gaps: tuple[str, ...]
    employer_thesis: str

    def __post_init__(self) -> None:
        if self.version < 1:
            raise ValueError("profile version must be at least 1")
        if any(item.state != "confirmed" for item in self.evidence):
            raise ValueError("ConfirmedProfile accepts confirmed evidence only")


@dataclass(frozen=True, slots=True)
class CompanyRecommendation:
    name: str
    tier: CompanyTier
    reason: str
    evidence_ids: tuple[str, ...]
    official_careers_url: str | None
    verification_status: VerificationStatus

    def __post_init__(self) -> None:
        if self.tier not in {"core", "adjacent", "exploratory"}:
            raise ValueError("tier must be core, adjacent, or exploratory")
        if self.verification_status not in {"verified", "pending", "rejected"}:
            raise ValueError(
                "verification_status must be verified, pending, or rejected"
            )


@dataclass(frozen=True, slots=True)
class CompanyThesis:
    profile_id: str
    profile_version: int
    recommendations: tuple[CompanyRecommendation, ...]


@dataclass(frozen=True, slots=True)
class WatchedCompany:
    name: str
    tier: CompanyTier
    careers_url: str
    source: SourceConfig
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.tier not in {"core", "adjacent", "exploratory"}:
            raise ValueError("tier must be core, adjacent, or exploratory")


@dataclass(frozen=True, slots=True)
class ConstraintResult:
    constraint: str
    status: ConstraintStatus
    explanation: str

    def __post_init__(self) -> None:
        if self.status not in {"pass", "fail", "unknown"}:
            raise ValueError("status must be pass, fail, or unknown")


@dataclass(frozen=True, slots=True)
class MatchAssessment:
    posting_url: str
    profile_id: str
    profile_version: int
    constraint_results: tuple[ConstraintResult, ...]
    score: int
    explanation: str
    evidence_ids: tuple[str, ...]
    tradeoffs: tuple[str, ...]
    uncertainties: tuple[str, ...]
    provider: str
    model: str

    def __post_init__(self) -> None:
        if isinstance(self.score, bool) or not isinstance(self.score, int):
            raise ValueError("score must be an integer")
        if not 0 <= self.score <= 100:
            raise ValueError("score must be between 0 and 100")
        if self.profile_version < 1:
            raise ValueError("profile_version must be at least 1")

    @property
    def constraint_status(self) -> ConstraintStatus:
        statuses = {result.status for result in self.constraint_results}
        if "fail" in statuses:
            return "fail"
        if "unknown" in statuses:
            return "unknown"
        return "pass"


@dataclass(frozen=True, slots=True)
class RankedMatch:
    rank: int
    assessment: MatchAssessment

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("rank must be at least 1")
```

- [x] **Step 4: Implement every provider-neutral adapter protocol**

```python
# hunter8_core/ports.py
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from hunter8_core.models import (
    CompanyThesis,
    ConfirmedProfile,
    JobPosting,
    MatchAssessment,
    ProfileDraft,
    ProfileQuestion,
    RankedMatch,
    SourceConfig,
)


class JsonModel(Protocol):
    def chat_json(self, system: str, user: str) -> Mapping[str, Any]:
        ...


class ResumeToProfile(Protocol):
    def extract(self, document_text: str) -> ProfileDraft:
        ...


class QuestionPlanner(Protocol):
    def plan(self, draft: ProfileDraft) -> Sequence[ProfileQuestion]:
        ...


class CompanyRecommender(Protocol):
    def recommend(self, profile: ConfirmedProfile) -> CompanyThesis:
        ...


class CompanySource(Protocol):
    def fetch(
        self, config: SourceConfig, *, timeout: float = 20.0
    ) -> Sequence[JobPosting]:
        ...


class EvidenceRanker(Protocol):
    def assess(
        self, profile: ConfirmedProfile, posting: JobPosting
    ) -> MatchAssessment:
        ...


class ShortlistRanker(Protocol):
    def order(
        self, assessments: Sequence[MatchAssessment]
    ) -> Sequence[RankedMatch]:
        ...
```

- [x] **Step 5: Export the full contract**

Use explicit imports and `__all__` in `hunter8_core/__init__.py`:

```python
from hunter8_core.models import (
    CompanyRecommendation,
    CompanyThesis,
    ConfirmedProfile,
    ConstraintResult,
    EvidenceItem,
    JobPosting,
    MatchAssessment,
    ProfileDraft,
    ProfileQuestion,
    RankedMatch,
    SourceConfig,
    WatchedCompany,
)
from hunter8_core.ports import (
    CompanyRecommender,
    CompanySource,
    EvidenceRanker,
    JsonModel,
    QuestionPlanner,
    ResumeToProfile,
    ShortlistRanker,
)

__all__ = [
    "CompanyRecommendation",
    "CompanyRecommender",
    "CompanySource",
    "CompanyThesis",
    "ConfirmedProfile",
    "ConstraintResult",
    "EvidenceItem",
    "EvidenceRanker",
    "JobPosting",
    "JsonModel",
    "MatchAssessment",
    "ProfileDraft",
    "ProfileQuestion",
    "QuestionPlanner",
    "RankedMatch",
    "ResumeToProfile",
    "ShortlistRanker",
    "SourceConfig",
    "WatchedCompany",
]
```

- [x] **Step 6: Run domain-contract tests**

Run:

```bash
.venv/bin/pytest tests/test_core_contracts.py tests/test_core_models.py -q
```

Expected: PASS.

- [x] **Step 7: Commit the complete core contract**

```bash
git add hunter8_core/models.py hunter8_core/ports.py \
  hunter8_core/__init__.py tests/test_core_contracts.py
git commit -m "feat: define hosted companion domain contracts"
```

---

### Task 4: Inject the company-source contract into ATS discovery

**Files:**
- Create: `tests/test_core_ports.py`
- Modify: `sources.py:242-254`
- Modify: `watchlist.py:3-18`
- Modify: `discover.py:19-40`
- Modify: `tests/test_discover.py`

**Interfaces:**
- Produces: `ATSCompanySource.fetch()`.
- Implements: `CompanySource`.
- Consumes: `SourceConfig`, `JobPosting`, `insert_posting()`.
- Preserves: `run_discovery()` callers by making `ats_source` optional.

- [x] **Step 1: Write failing source-port tests**

```python
# tests/test_core_ports.py
import ast
from pathlib import Path

import db as dbmod
import discover
from hunter8_core import JobPosting, SourceConfig


class FakeCompanySource:
    def __init__(self):
        self.seen: list[SourceConfig] = []

    def fetch(self, config: SourceConfig, *, timeout: float = 20.0):
        self.seen.append(config)
        return [
            JobPosting(
                url="https://x/1",
                company=config.company,
                title="AI Engineer",
                location="NYC",
                source=f"ats:{config.ats}",
                ats=config.ats,
                description="Build AI systems.",
            )
        ]


def test_discovery_accepts_a_company_source(tmp_path):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "companies:\n"
        "  - name: Acme\n"
        "    ats: greenhouse\n"
        "    board: acme\n"
        "    archetype: lab\n"
    )
    source = FakeCompanySource()

    inserted = discover.run_discovery(
        watchlist, tmp_path / "h.db", tavily_key=None, ats_source=source
    )

    assert inserted == 1
    assert source.seen == [
        SourceConfig(ats="greenhouse", board="acme", company="Acme")
    ]
    conn = dbmod.connect(tmp_path / "h.db")
    assert dbmod.jobs_by_status(conn, "discovered")[0].raw_text == "Build AI systems."


def test_core_package_has_no_local_or_third_party_imports():
    forbidden = {
        "db", "sources", "watchlist", "screen", "score", "rubric",
        "claude_agent", "local_agent", "httpx", "yaml", "dotenv",
    }
    for path in Path("hunter8_core").glob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        }
        imported |= {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not (imported & forbidden), (path, imported & forbidden)
```

- [x] **Step 2: Run tests and verify missing protocols/injection**

Run:

```bash
.venv/bin/pytest tests/test_core_ports.py tests/test_discover.py -q
```

Expected: FAIL because `ats_source` injection is not implemented.

- [x] **Step 3: Adapt the local watchlist and source implementation**

Add:

```python
# watchlist.py
from hunter8_core import SourceConfig
```

Add to `Company`:

```python
    def source_config(self) -> SourceConfig:
        return SourceConfig(ats=self.ats, board=self.board, company=self.name)
```

Add to `sources.py` after `fetch_ats`:

```python
class ATSCompanySource:
    def fetch(
        self, config: SourceConfig, *, timeout: float = 20.0
    ) -> list[JobPosting]:
        return fetch_ats(
            config.ats,
            board=config.board,
            company=config.company,
            timeout=timeout,
        )
```

Import `SourceConfig` alongside `JobPosting`.

- [x] **Step 4: Inject the source into discovery**

Add:

```python
from hunter8_core import CompanySource
```

Change the signature and setup:

```python
def run_discovery(
    watchlist_path: str | Path,
    db_path: str | Path,
    tavily_key: str | None,
    *,
    ats_source: CompanySource | None = None,
) -> int:
    wl = load_watchlist(watchlist_path)
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)
    source = ats_source or sources.ATSCompanySource()
```

Replace the company fetch and persistence calls:

```python
jobs = source.fetch(c.source_config())

if dbmod.insert_posting(conn, job):
    inserted += 1
```

Use `insert_posting` for Tavily results as well.

- [x] **Step 5: Simplify existing discovery tests to use injection**

In `tests/test_discover.py`, import `JobPosting` instead of `db.Job`, define a
small fake source with `fetch(config, *, timeout=20.0)`, and pass it through the
`ats_source=` keyword. Preserve the existing two assertions:

```python
assert n1 == 1
assert n2 == 0
```

For the failure-isolation test, raise only when `config.company == "Bad"` and
return a `JobPosting` for `"Good"`.

- [x] **Step 6: Run focused discovery and boundary tests**

Run:

```bash
.venv/bin/pytest tests/test_core_ports.py tests/test_discover.py \
  tests/test_sources.py -q
```

Expected: PASS.

- [x] **Step 7: Commit source injection**

```bash
git add tests/test_core_ports.py sources.py watchlist.py discover.py \
  tests/test_discover.py
git commit -m "refactor: inject provider-neutral posting sources"
```

---

### Task 5: Add strict assessment value objects

**Files:**
- Create: `hunter8_core/assessment.py`
- Create: `tests/test_core_assessment.py`
- Modify: `hunter8_core/__init__.py`

**Interfaces:**
- Produces: `ScreenAssessment.from_payload()` and
  `GradeAssessment.from_payload()`.
- Error contract: malformed data raises `ValueError` with the bad field named.

- [x] **Step 1: Write failing validation tests**

```python
# tests/test_core_assessment.py
import pytest

from hunter8_core.assessment import GradeAssessment, ScreenAssessment


def test_screen_assessment_accepts_bounded_integer():
    result = ScreenAssessment.from_payload(
        {"fit_score": 65, "reason": "Plausible match."}
    )
    assert result.fit_score == 65


@pytest.mark.parametrize("value", [-1, 101, True, "65", None])
def test_screen_assessment_rejects_invalid_score(value):
    with pytest.raises(ValueError, match="fit_score"):
        ScreenAssessment.from_payload({"fit_score": value, "reason": "x"})


def test_grade_assessment_accepts_complete_payload():
    result = GradeAssessment.from_payload({
        "grade": "A",
        "reasoning": "Strong evidence.",
        "archetype": "applied-ai",
        "comp_signal": "$200k+",
        "red_flags": ["sponsorship unknown"],
    })
    assert result.grade == "A"
    assert result.red_flags == ("sponsorship unknown",)


@pytest.mark.parametrize("grade", ["", "D", "A+", None, []])
def test_grade_assessment_rejects_invalid_grade(grade):
    with pytest.raises(ValueError, match="grade"):
        GradeAssessment.from_payload({
            "grade": grade,
            "reasoning": "r",
            "archetype": "a",
            "comp_signal": "",
            "red_flags": [],
        })


def test_grade_assessment_rejects_string_red_flags():
    with pytest.raises(ValueError, match="red_flags"):
        GradeAssessment.from_payload({
            "grade": "B",
            "reasoning": "r",
            "archetype": "a",
            "comp_signal": "",
            "red_flags": "sponsorship unknown",
        })
```

- [x] **Step 2: Run tests and verify the module is absent**

Run:

```bash
.venv/bin/pytest tests/test_core_assessment.py -q
```

Expected: collection fails because `hunter8_core.assessment` does not exist.

- [x] **Step 3: Implement strict payload parsing**

```python
# hunter8_core/assessment.py
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast


Grade = Literal["A", "B", "C"]


def _string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


@dataclass(frozen=True, slots=True)
class ScreenAssessment:
    fit_score: int
    reason: str

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> "ScreenAssessment":
        score = payload.get("fit_score")
        if isinstance(score, bool) or not isinstance(score, int):
            raise ValueError("fit_score must be an integer")
        if not 0 <= score <= 100:
            raise ValueError("fit_score must be between 0 and 100")
        return cls(fit_score=score, reason=_string(payload, "reason"))


@dataclass(frozen=True, slots=True)
class GradeAssessment:
    grade: Grade
    reasoning: str
    archetype: str
    comp_signal: str
    red_flags: tuple[str, ...]

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any]
    ) -> "GradeAssessment":
        raw_grade = payload.get("grade")
        if not isinstance(raw_grade, str) or raw_grade not in {"A", "B", "C"}:
            raise ValueError("grade must be one of A, B, C")
        raw_flags = payload.get("red_flags")
        if (
            not isinstance(raw_flags, list)
            or not all(isinstance(flag, str) for flag in raw_flags)
        ):
            raise ValueError("red_flags must be a list of strings")
        return cls(
            grade=cast(Grade, raw_grade),
            reasoning=_string(payload, "reasoning"),
            archetype=_string(payload, "archetype"),
            comp_signal=_string(payload, "comp_signal"),
            red_flags=tuple(raw_flags),
        )
```

Add the assessment import to the existing package exports:

```python
# hunter8_core/__init__.py
from hunter8_core.assessment import GradeAssessment, ScreenAssessment

__all__ += ["GradeAssessment", "ScreenAssessment"]
```

- [x] **Step 4: Run assessment tests**

Run:

```bash
.venv/bin/pytest tests/test_core_assessment.py -q
```

Expected: PASS.

- [x] **Step 5: Commit validation contracts**

```bash
git add hunter8_core/assessment.py hunter8_core/__init__.py \
  tests/test_core_assessment.py
git commit -m "feat: validate provider-neutral assessment payloads"
```

---

### Task 6: Adapt local screening and grading to core contracts

**Files:**
- Modify: `screen.py:18-22,50-81`
- Modify: `score.py:4-31,42-55,66-86`
- Modify: `tests/test_screen.py`
- Modify: `tests/test_score.py`

**Interfaces:**
- Consumes: `Job.to_posting()`, `JsonModel`, `ScreenAssessment`,
  `GradeAssessment`.
- Preserves: local status transitions, fail-fast unavailable-provider behavior,
  grade history, call cost, and queue ordering.

- [x] **Step 1: Add failing malformed-payload regression tests**

Add an optional raw payload to the screen fake:

```python
class _FakeAgent:
    def __init__(self, score=None, exc=None, payload=None):
        self.score, self.exc, self.payload = score, exc, payload

    def chat_json(self, system, user):
        if self.exc:
            raise self.exc
        if self.payload is not None:
            return self.payload
        return {"fit_score": self.score, "reason": "because"}
```

Add:

```python
def test_out_of_range_screen_score_is_visible_error(tmp_path):
    conn = _conn(tmp_path)
    screen.run_screening(
        conn,
        rubric_text="r",
        agent=_FakeAgent(payload={"fit_score": 120, "reason": "bad"}),
        threshold=65,
    )
    errored = dbmod.jobs_by_status(conn, "screen_error")
    assert len(errored) == 1
    assert "fit_score" in errored[0].screen_reason
```

Add to `tests/test_score.py`:

```python
def test_invalid_grade_is_visible_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 90)
    score.run_scoring(
        conn,
        intent_md="brief",
        agent=_FakeAgent(verdict={
            "grade": "A+",
            "reasoning": "r",
            "archetype": "lab",
            "comp_signal": "",
            "red_flags": [],
        }),
        brief_sha="test",
    )
    errored = dbmod.jobs_by_status(conn, "score_error")
    assert len(errored) == 1
    assert "grade" in errored[0].reasoning


def test_string_red_flags_are_not_split_into_characters(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 90)
    score.run_scoring(
        conn,
        intent_md="brief",
        agent=_FakeAgent(verdict={
            "grade": "A",
            "reasoning": "r",
            "archetype": "lab",
            "comp_signal": "",
            "red_flags": "sponsorship unknown",
        }),
        brief_sha="test",
    )
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 1
```

- [x] **Step 2: Run regressions and verify permissive parsing fails them**

Run:

```bash
.venv/bin/pytest tests/test_screen.py tests/test_score.py -q
```

Expected: the new invalid-payload tests fail.

- [x] **Step 3: Refactor screen prompting and parsing**

Use:

```python
from hunter8_core import JobPosting, JsonModel, ScreenAssessment
```

Replace `_prompt`:

```python
def _prompt(posting: JobPosting, rubric_text: str) -> str:
    return (
        f"# Rubric\n{rubric_text}\n\n"
        f"# Job posting\nCompany: {posting.company}\nTitle: {posting.title}\n"
        f"Location: {posting.location}\n\n{posting.description[:6000]}"
    )
```

Type the agent and replace payload coercion in `run_screening`:

```python
def run_screening(
    conn: sqlite3.Connection,
    *,
    rubric_text: str,
    agent: JsonModel,
    threshold: int,
    limit: int | None = None,
    posted_since: str | None = None,
) -> None:
```

Inside the loop:

```python
data = agent.chat_json(_SYSTEM, _prompt(job.to_posting(), rubric_text))
assessment = ScreenAssessment.from_payload(data)
score = assessment.fit_score
reason = assessment.reason
```

Do not change the existing `LocalUnavailable` or per-item exception branches.

- [x] **Step 4: Refactor final grading to `GradeAssessment`**

Remove `dataclass` and the local `Verdict`. Import:

```python
from hunter8_core import GradeAssessment, JobPosting, JsonModel
```

Replace `grade_job`:

```python
def grade_job(
    posting: JobPosting, *, intent_md: str, agent: JsonModel
) -> GradeAssessment:
    user = (
        f"# Candidate intent\n{intent_md}\n\n"
        f"# Job posting\nCompany: {posting.company}\nTitle: {posting.title}\n"
        f"Location: {posting.location}\n\n{posting.description[:6000]}"
    )
    return GradeAssessment.from_payload(agent.chat_json(_SYSTEM, user))
```

In `run_scoring`, call:

```python
v = grade_job(job.to_posting(), intent_md=intent_md, agent=agent)
```

Keep `json.dumps(v.red_flags)`, cost recording, grade history, and
`ClaudeUnavailable` behavior unchanged.

- [x] **Step 5: Update direct grade test input**

In `tests/test_score.py`, change the direct call in
`test_grade_job_parses_verdict` to:

```python
v = score.grade_job(
    _job("ML Engineer").to_posting(),
    intent_md="intent",
    agent=agent,
)
```

- [x] **Step 6: Run screening and grading tests**

Run:

```bash
.venv/bin/pytest tests/test_screen.py tests/test_score.py -q
```

Expected: PASS, including the new visible-error cases.

- [x] **Step 7: Commit assessment integration**

```bash
git add screen.py score.py tests/test_screen.py tests/test_score.py
git commit -m "refactor: grade core postings through validated assessments"
```

---

### Task 7: Document and enforce the core boundary

**Files:**
- Create: `hunter8_core/README.md`
- Modify: `README.md`
- Modify: `tests/test_core_ports.py`

**Interfaces:**
- Documents: what child plans may import from `hunter8_core`.
- Enforces: stdlib-only core and no personal/local runtime imports.

- [ ] **Step 1: Extend the boundary test to all package files**

Replace the single-level glob:

```python
for path in Path("hunter8_core").glob("*.py"):
```

with:

```python
for path in Path("hunter8_core").rglob("*.py"):
```

Run:

```bash
.venv/bin/pytest tests/test_core_ports.py -q
```

Expected: PASS.

- [ ] **Step 2: Write the package boundary document**

```markdown
<!-- hunter8_core/README.md -->
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
```

- [ ] **Step 3: Add a concise root README section**

Add after the final bullet under `## Discovery → Triage → Apply` and before
`## Claude Code / Cursor plugin`:

```markdown
## Core boundary

`hunter8_core/` contains provider-neutral posting, profile, company, source,
assessment, and ranking contracts. Local SQLite workflow state, personal
artifacts, model providers, tracking, and application automation remain outside
the package.
See [hunter8_core/README.md](hunter8_core/README.md).
```

- [ ] **Step 4: Run the full verification suite**

Run:

```bash
.venv/bin/pytest tests/ -q
.venv/bin/python -m compileall -q hunter8_core
git diff --check
```

Expected:

- all tests pass;
- compileall exits 0;
- `git diff --check` prints nothing.

- [ ] **Step 5: Confirm local CLI imports still load**

Run:

```bash
.venv/bin/python -c \
  "import discover, screen, score, analyze; print('local imports: ok')"
```

Expected:

```text
local imports: ok
```

- [ ] **Step 6: Commit boundary documentation**

```bash
git add hunter8_core/README.md README.md tests/test_core_ports.py
git commit -m "docs: define the hunter8 core boundary"
```

## Plan self-review

- **Spec coverage:** This child plan defines every domain type and adapter
  contract named by the umbrella spec and adapts the local posting and
  assessment seams. Hosted auth, parser/model implementations, persistence,
  company verification/ranking infrastructure, and rollout remain in child
  plans 2–5 by design.
- **Placeholders:** No deferred-work markers or implicit implementation steps.
- **Type consistency:** `JobPosting.description`, `SourceConfig.ats`,
  profile/version identifiers, evidence identifiers, `CompanySource.fetch`,
  `EvidenceRanker.assess`, `ShortlistRanker.order`, `ScreenAssessment`, and
  `GradeAssessment` use the same names and signatures in tests, implementations,
  and callers.
- **Behavior preservation:** Existing local insertion, source parsing,
  discovery failure isolation, screening transitions, grading history, and cost
  paths retain focused regression tests.
