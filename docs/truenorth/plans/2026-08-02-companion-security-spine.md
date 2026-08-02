# Hosted Companion Security Spine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use truenorth:subagent-driven-development (recommended) or truenorth:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the companion's authorization and data boundary — invite-bound sign-in, hunter8 product membership, a dedicated Postgres schema with row-level security, a private résumé bucket, and an idempotent deletion path — proven by cross-user denial tests against a live Supabase branch.

**Architecture:** A new `companion_api/` FastAPI service in this repo, deployed as its own Fly app. It installs `delapan[cloud]` as a library and reuses its audited `verify_bearer` (ES256/JWKS with the no-silent-HS256-downgrade rule) and Supabase client factories rather than re-implementing them; the hunter8 product gate, schema, storage, and deletion are new code on top. All companion tables live in a dedicated `hunter8` Postgres schema inside the existing `delapan-ai` project, never in `public`.

**Vision goals served:** End Goal 5, and the invariant "Hosted-companion data is private by default … isolated from hunter8's personal artifacts … and can be permanently deleted in one action."

**Tech Stack:** Python 3.11+ (its own venv — separate from hunter8's 3.9.6 local venv), FastAPI, `delapan[cloud]` (supabase, pyjwt[crypto], slowapi), `hunter8_core` (stdlib-only, imported for domain types), pytest + httpx. Supabase project `delapan-ai` (`gunqbyddzuwzpncfigro`), Postgres 17.

## Global Constraints

- **Never apply a migration to the production `delapan-ai` project.** All DDL is authored as SQL files in `companion_api/migrations/` and applied only to a Supabase **development branch**. Applying migrations is a controller/human step (Task 0), never a subagent action.
- Every companion table lives in the `hunter8` schema. Nothing is created in `public`. No existing delapan table, policy, or bucket is altered.
- Every user-owned row has a direct `user_id uuid references auth.users` or an ownership path terminating there. RLS is enabled on every table with no exceptions.
- `hunter8.job_postings` is the only shared/public-data table; it is readable only through a user's own `match_assessments`.
- Service-role usage is confined to narrow helpers in `companion_api/db.py`, each taking an explicit `user_id` and filtering on it. No route calls the service client directly.
- Do NOT re-implement JWT verification. Import `verify_bearer` from `delapan.api.auth`. A test asserts the import, so a future copy-paste is caught.
- Never log résumé text, profile content, prompts, model output, or `Authorization` headers.
- Invite is enforced **before** any product resource is created — no account-then-allowlist ordering.
- Deletion is idempotent, deletes Storage objects before the auth user, and never reports success early.
- `companion_api/` must not import hunter8's personal runtime (`db`, `sources`, `watchlist`, `screen`, `score`, `discover`, `analyze`, `apply`, `tracker`, `triage`, `calibrate`, `handlers`, `resume_builder`) — enforced by test. `hunter8_core` IS allowed.
- This plan builds no résumé parser, model call, ranking, or company discovery. Routes return persisted state only; the pipeline is child plans 3–4.
- Run `cd companion_api && .venv/bin/pytest -q` before declaring any task complete.

---

## File map

**Create (all under `companion_api/`)**

- `pyproject.toml` — package metadata, `delapan[cloud]` + `hunter8-core` deps, pytest config.
- `fly.toml` — separate Fly app `hunter8-companion-api`.
- `settings.py` — companion-specific settings (bucket name, invite TTL, allowed origins).
- `auth.py` — `current_user`, `require_membership`, `redeem_invite`.
- `db.py` — user-filtered service-role helpers; the only module touching the service client.
- `deletion.py` — the idempotent deletion plan/executor.
- `app.py` — FastAPI factory, CORS, router registration.
- `routes/session.py` — `GET /session`, `POST /session/redeem`.
- `routes/dossier.py` — `GET /dossier` (persisted stage + owned rows).
- `routes/account.py` — `DELETE /account`.
- `migrations/0001_hunter8_schema.sql` — schema, tables, indexes.
- `migrations/0002_hunter8_rls.sql` — RLS enable + policies.
- `migrations/0003_hunter8_storage.sql` — private bucket + storage policies.
- `tests/test_boundary.py`, `tests/test_auth.py`, `tests/test_db_helpers.py`, `tests/test_deletion.py`, `tests/test_routes.py`, `tests/live/test_rls_isolation.py`, `tests/live/test_deletion_live.py`.

**Modify**

- `README.md` — one line pointing at `companion_api/`.

## Interfaces locked by this plan

```python
# companion_api/auth.py
def current_user(request: Request) -> str: ...           # verified Supabase user id, 401 on bad token
def require_membership(request: Request) -> str: ...      # current_user + active hunter8 membership, else 403
def redeem_invite(token: str, user_id: str, email: str) -> None: ...
    # 403 if token unknown/expired/already-redeemed, or if the token's email != the verified email.

# companion_api/db.py  — every helper takes user_id and filters on it
def membership_for(user_id: str) -> dict | None: ...
def invite_by_token(token: str) -> dict | None: ...
def mark_invite_redeemed(token: str, user_id: str) -> None: ...
def create_membership(user_id: str, email: str, invite_token: str) -> None: ...
def dossier_state(user_id: str) -> dict: ...
    # {"stage": str, "profile_version": int | None, "companies": int, "shortlist": int}

# companion_api/deletion.py
def delete_everything(user_id: str) -> str: ...           # returns "done" | "delete_error"; idempotent
def deletion_plan(user_id: str) -> list[str]: ...         # ordered step names, for test + audit
```

```sql
-- schema: hunter8
-- tables: product_memberships, invites, resume_uploads, profile_drafts,
--         profile_questions, confirmed_profiles, company_theses,
--         watched_companies, job_postings, match_assessments,
--         shortlist_feedback, pipeline_runs, deletion_requests
```

---

### Task 0 (CONTROLLER/HUMAN — not a subagent task): create the Supabase dev branch

**Files:** none.

This task exists so no later task guesses at connection details. It is performed once, by the controller, before Task 2's live tests.

- [ ] **Step 1: Create the branch**

Using the Supabase MCP `create_branch` tool on project `gunqbyddzuwzpncfigro`, name `hunter8-spine`. Record the branch's project ref, URL, anon key, and service-role key.

- [ ] **Step 2: Write them to an untracked env file**

```bash
cat > companion_api/.env.branch <<'ENVEOF'
SUPABASE_URL=https://<branch-ref>.supabase.co
SUPABASE_ANON_KEY=<branch anon key>
SUPABASE_SERVICE_ROLE_KEY=<branch service role key>
HUNTER8_BUCKET=hunter8-resumes
ENVEOF
printf '.env.branch\n.venv/\n__pycache__/\n' > companion_api/.gitignore
```

`.env.branch` is git-ignored and must never be committed.

- [ ] **Step 3: Confirm the branch is reachable and is NOT production**

```bash
grep -q "gunqbyddzuwzpncfigro" companion_api/.env.branch && echo "REFUSE: that is production" || echo "branch ref ok"
```

Expected: `branch ref ok`.

---

### Task 1: Package scaffold and the import boundary

**Files:**
- Create: `companion_api/pyproject.toml`, `companion_api/settings.py`, `companion_api/app.py`, `companion_api/__init__.py`, `companion_api/tests/test_boundary.py`

**Interfaces:**
- Produces: an installable package, a running pytest harness, and the boundary test every later task's suite re-runs.

- [ ] **Step 1: Write the failing boundary test**

```python
# companion_api/tests/test_boundary.py
import ast
import re
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent

FORBIDDEN = {
    "db", "sources", "watchlist", "screen", "score", "discover", "analyze",
    "apply", "tracker", "triage", "calibrate", "handlers", "resume_builder",
    "sync_intent", "rubric", "claude_agent", "local_agent", "candidate_profile",
}


def _sources() -> list[Path]:
    files = [p for p in PKG.rglob("*.py") if ".venv" not in p.parts]
    assert files, "no source files found"
    return files


def test_never_imports_the_personal_runtime():
    for path in _sources():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                roots = {(node.module or "").split(".")[0]}
            else:
                continue
            assert not (roots & FORBIDDEN), (path, roots & FORBIDDEN)


def test_never_names_a_personal_artifact():
    pattern = re.compile(r"intent\.md|rubric\.md|brief\.md|hunter8\.db|watchlist\.yaml|resumes/")
    for path in _sources():
        assert not pattern.search(path.read_text()), path


def test_jwt_verification_is_delegated_not_reimplemented():
    """Re-implementing token verification is the one duplication we refuse."""
    auth = (PKG / "auth.py").read_text()
    assert "from delapan.api.auth import verify_bearer" in auth
    for banned in ("jwt.decode", "PyJWKClient", "HS256", "ES256"):
        assert banned not in auth, f"{banned} suggests a re-implementation"
```

- [ ] **Step 2: Run and verify it fails**

```bash
cd companion_api && python3.11 -m venv .venv && .venv/bin/pip install -q pytest && .venv/bin/pytest -q
```

Expected: FAIL — `auth.py` does not exist.

- [ ] **Step 3: Write the package files**

`companion_api/pyproject.toml`:

```toml
[project]
name = "hunter8-companion-api"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "delapan[cloud]",
  "fastapi>=0.122.0",
  "uvicorn[standard]>=0.38.0",
  "pydantic-settings>=2.12.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.4.2", "httpx>=0.28.1"]

[tool.pytest.ini_options]
pythonpath = [".", ".."]
testpaths = ["tests"]
```

`companion_api/__init__.py`: empty file.

`companion_api/settings.py`:

```python
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings


class CompanionSettings(BaseSettings):
    """Companion-only configuration. Supabase credentials come from delapan's
    own settings — this holds what delapan has no opinion about."""

    bucket: str = Field(default="hunter8-resumes", alias="HUNTER8_BUCKET")
    invite_ttl_days: int = Field(default=30, alias="HUNTER8_INVITE_TTL_DAYS")
    allowed_origins: str = Field(
        default="http://localhost:5173", alias="HUNTER8_ALLOWED_ORIGINS"
    )

    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_companion_settings() -> CompanionSettings:
    return CompanionSettings()
```

`companion_api/app.py`:

```python
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from companion_api.settings import get_companion_settings


def create_app() -> FastAPI:
    settings = get_companion_settings()
    app = FastAPI(title="hunter8 companion", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["authorization", "content-type"],
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
```

Create a placeholder `companion_api/auth.py` containing exactly:

```python
from __future__ import annotations

from delapan.api.auth import verify_bearer  # noqa: F401 — the one auth seam
```

- [ ] **Step 4: Install and run**

```bash
cd companion_api && .venv/bin/pip install -q -e "../../delapan[cloud]" 2>/dev/null || .venv/bin/pip install -q -e "$HOME/Projects/delapan[cloud]"
.venv/bin/pip install -q -e ".[dev]"
.venv/bin/pytest -q
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add companion_api
git commit -m "feat(companion-api): scaffold the service with a hard import boundary"
```

---

### Task 2: The `hunter8` schema and its row-level security

> **PLAN DEFECT, fixed during execution (commit `4b7f82a`) — the SQL below is
> superseded; read `companion_api/migrations/` for the corrected version.**
> The policies as written granted `authenticated` insert/update/delete with only
> an `auth.uid() = user_id` check. `authenticated` is a **shared role in a shared
> Supabase project**: every delapan user holds it. So any delapan user with no
> hunter8 invite could write hunter8 rows straight through PostgREST, routing
> around `require_membership` entirely — and inserting a `match_assessments` row
> was enough to unlock reads of `job_postings` (FK validation ignores RLS, so it
> doubled as an existence oracle over the shared corpus).
> Corrections: clients are **select-only** (every write already went through the
> service role); `force row level security` on all 13 tables (the owning
> `postgres` role, which the Supabase SQL editor runs as, bypassed the policies);
> explicit `service_role` grants, without which nothing downstream works; default
> privileges for future tables; single-use `invite_token`; tighter check
> constraints; and the missing RLS-predicate indexes.
> **Operational prerequisite discovered here:** `hunter8` must be added to
> PostgREST's exposed-schemas config or every client `.schema("hunter8")` call
> returns PGRST106.

**Files:**
- Create: `companion_api/migrations/0001_hunter8_schema.sql`, `companion_api/migrations/0002_hunter8_rls.sql`
- Create: `companion_api/tests/test_migrations.py`

**Interfaces:**
- Produces: the `hunter8` schema, 13 tables, and the policies every later task relies on.

- [ ] **Step 1: Write the migration-shape test**

```python
# companion_api/tests/test_migrations.py
import re
from pathlib import Path

MIG = Path(__file__).resolve().parent.parent / "migrations"

TABLES = [
    "product_memberships", "invites", "resume_uploads", "profile_drafts",
    "profile_questions", "confirmed_profiles", "company_theses",
    "watched_companies", "job_postings", "match_assessments",
    "shortlist_feedback", "pipeline_runs", "deletion_requests",
]


def _sql() -> str:
    return "\n".join(p.read_text() for p in sorted(MIG.glob("*.sql")))


def test_every_table_is_created_in_the_hunter8_schema():
    sql = _sql()
    for table in TABLES:
        assert re.search(rf"create table if not exists hunter8\.{table}\b", sql, re.I), table


def test_nothing_is_created_in_public():
    sql = _sql()
    assert not re.search(r"create table[^;]*\bpublic\.", sql, re.I)


def test_rls_is_enabled_on_every_table():
    sql = _sql()
    for table in TABLES:
        assert re.search(
            rf"alter table hunter8\.{table} enable row level security", sql, re.I
        ), table


def test_no_migration_alters_an_existing_delapan_object():
    sql = _sql()
    forbidden = ("drop table", "drop schema", "alter table public.", "drop policy")
    for phrase in forbidden:
        assert phrase not in sql.lower(), phrase


def test_job_postings_is_reachable_only_through_owned_assessments():
    sql = _sql()
    policy = re.search(
        r"create policy[^;]*on hunter8\.job_postings[^;]*;", sql, re.I | re.S
    )
    assert policy, "job_postings needs an explicit select policy"
    assert "match_assessments" in policy.group(0)
    assert "auth.uid()" in policy.group(0)
```

- [ ] **Step 2: Run and verify failure**

```bash
cd companion_api && .venv/bin/pytest tests/test_migrations.py -q
```

Expected: FAIL — no migrations directory.

- [ ] **Step 3: Write `migrations/0001_hunter8_schema.sql`**

```sql
-- Companion product schema. Isolated from delapan's `public` schema; every
-- user-owned row terminates at auth.users. Additive only.
create schema if not exists hunter8;

create table if not exists hunter8.invites (
  token         text primary key,
  email         text not null,
  created_at    timestamptz not null default now(),
  expires_at    timestamptz not null,
  redeemed_at   timestamptz,
  redeemed_by   uuid references auth.users on delete set null
);

create table if not exists hunter8.product_memberships (
  user_id       uuid primary key references auth.users on delete cascade,
  email         text not null,
  invite_token  text references hunter8.invites(token),
  state         text not null default 'active'
                check (state in ('active', 'delete_pending')),
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.resume_uploads (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  object_path   text not null,
  parse_state   text not null default 'uploaded'
                check (parse_state in ('uploaded', 'parsed', 'parse_error')),
  parse_error   text,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.profile_drafts (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  payload       jsonb not null,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.profile_questions (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  draft_id      uuid not null references hunter8.profile_drafts on delete cascade,
  key           text not null,
  prompt        text not null,
  reason        text not null,
  anchor_section text not null,
  answer        text,
  answered_at   timestamptz
);

create table if not exists hunter8.confirmed_profiles (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  version       integer not null check (version >= 1),
  payload       jsonb not null,
  created_at    timestamptz not null default now(),
  unique (user_id, version)
);

create table if not exists hunter8.company_theses (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  profile_id    uuid not null references hunter8.confirmed_profiles on delete cascade,
  payload       jsonb not null,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.watched_companies (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  profile_id    uuid not null references hunter8.confirmed_profiles on delete cascade,
  name          text not null,
  tier          text not null check (tier in ('core', 'adjacent', 'exploratory')),
  careers_url   text,
  ats           text,
  board         text,
  verification  text not null default 'pending'
                check (verification in ('verified', 'pending', 'rejected')),
  evidence_ids  text[] not null default '{}'
);

-- Public posting data, deduplicated independently of users. No user_id: it is
-- shared, and is exposed only through a user's own assessments (see RLS).
create table if not exists hunter8.job_postings (
  url           text primary key,
  canonical_url text,
  company       text not null,
  title         text not null,
  location      text,
  source        text not null,
  ats           text,
  posted_at     text,
  description   text,
  fetched_at    timestamptz not null default now()
);

create table if not exists hunter8.match_assessments (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  profile_id    uuid not null references hunter8.confirmed_profiles on delete cascade,
  posting_url   text not null references hunter8.job_postings on delete cascade,
  score         integer not null check (score between 0 and 100),
  constraint_results jsonb not null default '[]',
  explanation   text,
  evidence_ids  text[] not null default '{}',
  tradeoffs     text[] not null default '{}',
  uncertainties text[] not null default '{}',
  provider      text not null,
  model         text not null,
  created_at    timestamptz not null default now(),
  unique (user_id, profile_id, posting_url)
);

create table if not exists hunter8.shortlist_feedback (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  assessment_id uuid not null references hunter8.match_assessments on delete cascade,
  value         text not null check (value in ('useful', 'not_useful')),
  reason        text,
  created_at    timestamptz not null default now()
);

create table if not exists hunter8.pipeline_runs (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users on delete cascade,
  stage         text not null,
  state         text not null,
  detail        text,
  counters      jsonb not null default '{}',
  updated_at    timestamptz not null default now()
);

create table if not exists hunter8.deletion_requests (
  user_id       uuid primary key,
  state         text not null default 'delete_pending'
                check (state in ('delete_pending', 'done', 'delete_error')),
  detail        text,
  requested_at  timestamptz not null default now(),
  completed_at  timestamptz
);

create index if not exists idx_h8_uploads_user on hunter8.resume_uploads(user_id);
create index if not exists idx_h8_drafts_user on hunter8.profile_drafts(user_id);
create index if not exists idx_h8_questions_user on hunter8.profile_questions(user_id);
create index if not exists idx_h8_profiles_user on hunter8.confirmed_profiles(user_id);
create index if not exists idx_h8_companies_user on hunter8.watched_companies(user_id);
create index if not exists idx_h8_assessments_user on hunter8.match_assessments(user_id);
create index if not exists idx_h8_feedback_user on hunter8.shortlist_feedback(user_id);
create index if not exists idx_h8_runs_user on hunter8.pipeline_runs(user_id);
create index if not exists idx_h8_invites_email on hunter8.invites(email);
```

- [ ] **Step 4: Write `migrations/0002_hunter8_rls.sql`**

```sql
-- RLS for every hunter8 table. The service role bypasses these by design;
-- companion_api/db.py is the only place that uses it, always user-filtered.
alter table hunter8.invites enable row level security;
alter table hunter8.product_memberships enable row level security;
alter table hunter8.resume_uploads enable row level security;
alter table hunter8.profile_drafts enable row level security;
alter table hunter8.profile_questions enable row level security;
alter table hunter8.confirmed_profiles enable row level security;
alter table hunter8.company_theses enable row level security;
alter table hunter8.watched_companies enable row level security;
alter table hunter8.job_postings enable row level security;
alter table hunter8.match_assessments enable row level security;
alter table hunter8.shortlist_feedback enable row level security;
alter table hunter8.pipeline_runs enable row level security;
alter table hunter8.deletion_requests enable row level security;

-- Invites carry no user data and are never client-readable: redemption goes
-- through the service role after the email is verified. No policy = deny all.

create policy h8_membership_self on hunter8.product_memberships
  for select using (auth.uid() = user_id);

create policy h8_uploads_self on hunter8.resume_uploads
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_drafts_self on hunter8.profile_drafts
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_questions_self on hunter8.profile_questions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_profiles_self on hunter8.confirmed_profiles
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_theses_self on hunter8.company_theses
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_companies_self on hunter8.watched_companies
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_assessments_self on hunter8.match_assessments
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_feedback_self on hunter8.shortlist_feedback
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_runs_self on hunter8.pipeline_runs
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);

create policy h8_deletions_self on hunter8.deletion_requests
  for select using (auth.uid() = user_id);

-- Shared posting data is readable only where the caller owns an assessment of
-- it. Writes are service-role only (the discovery pipeline), so no write policy.
create policy h8_postings_via_own_assessment on hunter8.job_postings
  for select using (
    exists (
      select 1 from hunter8.match_assessments a
      where a.posting_url = hunter8.job_postings.url
        and a.user_id = auth.uid()
    )
  );

grant usage on schema hunter8 to authenticated;
grant select, insert, update, delete on all tables in schema hunter8 to authenticated;
```

- [ ] **Step 5: Run the shape tests**

```bash
cd companion_api && .venv/bin/pytest tests/test_migrations.py -q
```

Expected: 5 passed.

- [ ] **Step 6: Apply to the branch (CONTROLLER STEP — not a subagent action)**

The controller applies `0001` then `0002` to the **`hunter8-spine` branch** via the Supabase MCP `apply_migration` tool, then verifies with `list_tables` on schema `hunter8` that 13 tables exist and all report `rls_enabled: true`.

- [ ] **Step 7: Commit**

```bash
git add companion_api/migrations companion_api/tests/test_migrations.py
git commit -m "feat(companion-api): hunter8 schema with row-level security"
```

---

### Task 3: Invite binding and the product gate

> **PLAN DEFECT, fixed during execution (commit `fabed2d`) — the signature below
> is superseded.** `redeem_invite(token, user_id, email)` took the email as a
> caller-supplied argument, but delapan's `verify_bearer` returns only the
> subject claim, so companion_api had **no trusted email source**: anyone
> holding a leaked or forwarded invite token could satisfy the binding by
> echoing the invited address. The real signature is
> `redeem_invite(token, user_id)`; the email now comes from the Supabase auth
> record for the verified user id (`db.auth_email_for`) and must be confirmed.
> Also corrected here: `mark_invite_redeemed`'s conditional-update result was
> discarded (single-use rested entirely on a UNIQUE constraint raising a 500);
> a failed membership write left the invite stamped and the invitee permanently
> locked out (now released, 503); and the membership `upsert` could resurrect a
> `delete_pending` account (now an insert, with a 409 when one already exists).
> **Task 6's `RedeemBody` therefore carries only `token` — no `email` field.**

**Files:**
- Create: `companion_api/db.py`, `companion_api/tests/test_auth.py`, `companion_api/tests/test_db_helpers.py`
- Modify: `companion_api/auth.py`

**Interfaces:**
- Consumes: `verify_bearer` (delapan), the `hunter8.invites` / `product_memberships` tables.
- Produces: `current_user`, `require_membership`, `redeem_invite`, and the `db.py` helpers listed in the locked interfaces.

- [ ] **Step 1: Write the failing tests**

```python
# companion_api/tests/test_auth.py
import pytest
from fastapi import HTTPException

from companion_api import auth


class _Req:
    def __init__(self, header: str | None):
        self.headers = {"authorization": header} if header else {}


def test_current_user_rejects_a_missing_token(monkeypatch):
    with pytest.raises(HTTPException) as exc:
        auth.current_user(_Req(None))
    assert exc.value.status_code == 401


def test_require_membership_403s_without_a_membership(monkeypatch):
    monkeypatch.setattr(auth, "verify_bearer", lambda h: "user-1")
    monkeypatch.setattr(auth, "membership_for", lambda uid: None)
    with pytest.raises(HTTPException) as exc:
        auth.require_membership(_Req("Bearer x"))
    assert exc.value.status_code == 403
    assert "invite" in exc.value.detail.lower()


def test_require_membership_403s_while_deletion_is_pending(monkeypatch):
    monkeypatch.setattr(auth, "verify_bearer", lambda h: "user-1")
    monkeypatch.setattr(
        auth, "membership_for", lambda uid: {"user_id": uid, "state": "delete_pending"}
    )
    with pytest.raises(HTTPException) as exc:
        auth.require_membership(_Req("Bearer x"))
    assert exc.value.status_code == 403


def test_require_membership_returns_the_user_id_when_active(monkeypatch):
    monkeypatch.setattr(auth, "verify_bearer", lambda h: "user-1")
    monkeypatch.setattr(
        auth, "membership_for", lambda uid: {"user_id": uid, "state": "active"}
    )
    assert auth.require_membership(_Req("Bearer x")) == "user-1"


def test_redeem_rejects_an_unknown_token(monkeypatch):
    monkeypatch.setattr(auth, "invite_by_token", lambda t: None)
    with pytest.raises(HTTPException) as exc:
        auth.redeem_invite("nope", "user-1", "a@b.c")
    assert exc.value.status_code == 403


def test_redeem_rejects_a_token_bound_to_a_different_email(monkeypatch):
    monkeypatch.setattr(
        auth, "invite_by_token",
        lambda t: {"token": t, "email": "invited@x.com", "redeemed_at": None,
                   "expires_at": "2099-01-01T00:00:00+00:00"},
    )
    with pytest.raises(HTTPException) as exc:
        auth.redeem_invite("tok", "user-1", "someone.else@x.com")
    assert exc.value.status_code == 403
    assert "email" in exc.value.detail.lower()


def test_redeem_rejects_an_already_redeemed_token(monkeypatch):
    monkeypatch.setattr(
        auth, "invite_by_token",
        lambda t: {"token": t, "email": "a@b.c", "redeemed_at": "2026-01-01T00:00:00+00:00",
                   "expires_at": "2099-01-01T00:00:00+00:00"},
    )
    with pytest.raises(HTTPException) as exc:
        auth.redeem_invite("tok", "user-1", "a@b.c")
    assert exc.value.status_code == 403


def test_redeem_rejects_an_expired_token(monkeypatch):
    monkeypatch.setattr(
        auth, "invite_by_token",
        lambda t: {"token": t, "email": "a@b.c", "redeemed_at": None,
                   "expires_at": "2020-01-01T00:00:00+00:00"},
    )
    with pytest.raises(HTTPException) as exc:
        auth.redeem_invite("tok", "user-1", "a@b.c")
    assert exc.value.status_code == 403
    assert "expired" in exc.value.detail.lower()


def test_redeem_creates_the_membership_only_after_every_check(monkeypatch):
    """Order matters: an account must never exist before the invite is proven."""
    calls: list[str] = []
    monkeypatch.setattr(
        auth, "invite_by_token",
        lambda t: {"token": t, "email": "a@b.c", "redeemed_at": None,
                   "expires_at": "2099-01-01T00:00:00+00:00"},
    )
    monkeypatch.setattr(auth, "mark_invite_redeemed",
                        lambda t, u: calls.append("mark"))
    monkeypatch.setattr(auth, "create_membership",
                        lambda u, e, t: calls.append("create"))
    auth.redeem_invite("tok", "user-1", "a@b.c")
    assert calls == ["mark", "create"]
```

```python
# companion_api/tests/test_db_helpers.py
import inspect

from companion_api import db


def test_every_helper_takes_an_explicit_user_or_token():
    """The service client bypasses RLS, so each helper must scope itself."""
    scoped = {"membership_for", "create_membership", "dossier_state"}
    for name in scoped:
        params = list(inspect.signature(getattr(db, name)).parameters)
        assert params and params[0] == "user_id", (name, params)


def test_service_client_is_confined_to_this_module():
    from pathlib import Path

    pkg = Path(db.__file__).resolve().parent
    for path in pkg.rglob("*.py"):
        if path.name == "db.py" or ".venv" in path.parts:
            continue
        assert "service_client" not in path.read_text(), path
```

- [ ] **Step 2: Run and verify failure**

```bash
cd companion_api && .venv/bin/pytest tests/test_auth.py tests/test_db_helpers.py -q
```

Expected: FAIL — `db` module and the auth functions do not exist.

- [ ] **Step 3: Write `companion_api/db.py`**

```python
"""Service-role data access. This is the ONLY module that touches the service
client, and every helper scopes itself to one user id or one invite token —
the service role bypasses RLS, so the filter is the security boundary.

Nothing here logs row contents."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from delapan.core.clients.supabase import service_client

from companion_api.settings import get_companion_settings

_SCHEMA = "hunter8"


def _table(name: str):
    return service_client().schema(_SCHEMA).table(name)


def membership_for(user_id: str) -> dict[str, Any] | None:
    rows = (
        _table("product_memberships")
        .select("user_id, email, state")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return rows.data[0] if rows.data else None


def invite_by_token(token: str) -> dict[str, Any] | None:
    rows = (
        _table("invites")
        .select("token, email, expires_at, redeemed_at")
        .eq("token", token)
        .limit(1)
        .execute()
    )
    return rows.data[0] if rows.data else None


def mark_invite_redeemed(token: str, user_id: str) -> None:
    _table("invites").update(
        {"redeemed_at": datetime.now(timezone.utc).isoformat(), "redeemed_by": user_id}
    ).eq("token", token).is_("redeemed_at", "null").execute()


def create_membership(user_id: str, email: str, invite_token: str) -> None:
    _table("product_memberships").upsert(
        {"user_id": user_id, "email": email, "invite_token": invite_token,
         "state": "active"},
        on_conflict="user_id",
    ).execute()


def issue_invite(email: str) -> str:
    """Admin helper — mint a single-use token bound to one address."""
    import secrets

    settings = get_companion_settings()
    token = secrets.token_urlsafe(24)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.invite_ttl_days)
    _table("invites").insert(
        {"token": token, "email": email.lower(), "expires_at": expires.isoformat()}
    ).execute()
    return token


def dossier_state(user_id: str) -> dict[str, Any]:
    """Persisted progress for one user. Counts only — no row contents."""
    profiles = (
        _table("confirmed_profiles").select("version").eq("user_id", user_id)
        .order("version", desc=True).limit(1).execute()
    )
    companies = (
        _table("watched_companies").select("id", count="exact")
        .eq("user_id", user_id).execute()
    )
    shortlist = (
        _table("match_assessments").select("id", count="exact")
        .eq("user_id", user_id).execute()
    )
    runs = (
        _table("pipeline_runs").select("stage, state").eq("user_id", user_id)
        .order("updated_at", desc=True).limit(1).execute()
    )
    return {
        "stage": runs.data[0]["stage"] if runs.data else "upload",
        "profile_version": profiles.data[0]["version"] if profiles.data else None,
        "companies": companies.count or 0,
        "shortlist": shortlist.count or 0,
    }
```

- [ ] **Step 4: Write `companion_api/auth.py`**

Replace the placeholder entirely:

```python
"""Companion authorization: a verified Supabase identity, then an invite-bound
hunter8 product membership. Token verification is delegated to delapan's
audited `verify_bearer` — re-implementing it is forbidden (see test_boundary)."""

from __future__ import annotations

from datetime import datetime, timezone

from delapan.api.auth import verify_bearer
from fastapi import HTTPException, Request

from companion_api.db import (
    create_membership,
    invite_by_token,
    mark_invite_redeemed,
    membership_for,
)


def current_user(request: Request) -> str:
    """Verified Supabase user id, or 401. No product check."""
    return verify_bearer(request.headers.get("authorization"))


def require_membership(request: Request) -> str:
    """Verified identity AND an active hunter8 membership, else 403.

    A delapan membership is deliberately not sufficient: this is a separate
    product with a separate invite list."""
    user_id = current_user(request)
    row = membership_for(user_id)
    if row is None:
        raise HTTPException(
            status_code=403, detail="this account has no hunter8 invite"
        )
    if row.get("state") != "active":
        raise HTTPException(status_code=403, detail="account deletion in progress")
    return user_id


def redeem_invite(token: str, user_id: str, email: str) -> None:
    """Bind a single-use invite to a verified identity.

    Every check runs BEFORE any product row is created — the umbrella spec
    forbids creating an account and then testing an allowlist."""
    invite = invite_by_token(token)
    if invite is None:
        raise HTTPException(status_code=403, detail="unknown invite")
    if invite.get("redeemed_at"):
        raise HTTPException(status_code=403, detail="invite already used")
    expires = datetime.fromisoformat(invite["expires_at"])
    if expires <= datetime.now(timezone.utc):
        raise HTTPException(status_code=403, detail="invite expired")
    if invite["email"].lower() != email.lower():
        raise HTTPException(
            status_code=403, detail="invite is bound to a different email"
        )
    mark_invite_redeemed(token, user_id)
    create_membership(user_id, email.lower(), token)
```

- [ ] **Step 5: Run the tests**

```bash
cd companion_api && .venv/bin/pytest -q
```

Expected: all pass (boundary + migrations + auth + db helpers).

- [ ] **Step 6: Commit**

```bash
git add companion_api/auth.py companion_api/db.py companion_api/tests
git commit -m "feat(companion-api): invite binding and the hunter8 product gate"
```

---

### Task 4: Private résumé bucket and storage policies

**Files:**
- Create: `companion_api/migrations/0003_hunter8_storage.sql`
- Modify: `companion_api/tests/test_migrations.py`

**Interfaces:**
- Produces: the `hunter8-resumes` private bucket and its per-user object policies.

- [ ] **Step 1: Add the failing storage assertions**

Append to `companion_api/tests/test_migrations.py`:

```python
def test_the_resume_bucket_is_private():
    sql = _sql()
    assert re.search(r"insert into storage\.buckets", sql, re.I)
    assert re.search(r"'hunter8-resumes'\s*,\s*'hunter8-resumes'\s*,\s*false", sql, re.I), (
        "the bucket must be created with public = false"
    )


def test_storage_objects_are_scoped_by_the_first_path_segment():
    sql = _sql()
    policies = re.findall(r"create policy[^;]*on storage\.objects[^;]*;", sql, re.I | re.S)
    assert len(policies) >= 3, "need select/insert/delete policies"
    for policy in policies:
        assert "hunter8-resumes" in policy
        assert "storage.foldername" in policy
        assert "auth.uid()" in policy
```

- [ ] **Step 2: Run and verify failure**

```bash
cd companion_api && .venv/bin/pytest tests/test_migrations.py -q
```

Expected: FAIL on the two new tests.

- [ ] **Step 3: Write `migrations/0003_hunter8_storage.sql`**

```sql
-- Private résumé bucket. Object paths are "<user_id>/<uuid>", so the first path
-- segment is the ownership check. The raw file is deleted after the profile is
-- confirmed; only structured evidence and minimal excerpts survive.
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values (
  'hunter8-resumes', 'hunter8-resumes', false, 10485760,
  array['application/pdf',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
)
on conflict (id) do nothing;

create policy h8_resumes_read_own on storage.objects
  for select to authenticated
  using (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy h8_resumes_insert_own on storage.objects
  for insert to authenticated
  with check (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy h8_resumes_delete_own on storage.objects
  for delete to authenticated
  using (
    bucket_id = 'hunter8-resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
```

- [ ] **Step 4: Run tests**

```bash
cd companion_api && .venv/bin/pytest tests/test_migrations.py -q
```

Expected: 7 passed.

- [ ] **Step 5: Apply to the branch (CONTROLLER STEP)**

The controller applies `0003` to the `hunter8-spine` branch and confirms the bucket exists with `public = false`.

- [ ] **Step 6: Commit**

```bash
git add companion_api/migrations/0003_hunter8_storage.sql companion_api/tests/test_migrations.py
git commit -m "feat(companion-api): private resume bucket scoped by user id"
```

---

### Task 5: The idempotent deletion path

**Files:**
- Create: `companion_api/deletion.py`, `companion_api/tests/test_deletion.py`

**Interfaces:**
- Produces: `delete_everything(user_id) -> str`, `deletion_plan(user_id) -> list[str]`.
- Order is load-bearing: Storage objects → domain rows → membership → auth user. Supabase refuses to delete an auth user that still owns Storage objects.

- [ ] **Step 1: Write the failing tests**

```python
# companion_api/tests/test_deletion.py
from companion_api import deletion


def test_storage_is_cleared_before_the_auth_user():
    steps = deletion.deletion_plan("user-1")
    assert steps.index("storage") < steps.index("auth_user")
    assert steps.index("membership") < steps.index("auth_user")
    assert steps[-1] == "auth_user"


def test_domain_rows_are_deleted_before_membership():
    steps = deletion.deletion_plan("user-1")
    assert steps.index("domain_rows") < steps.index("membership")


def test_success_marks_done_and_reports_done(monkeypatch):
    marks: list[tuple[str, str]] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: None)
    assert deletion.delete_everything("user-1") == "done"
    assert marks[0][1] == "delete_pending"
    assert marks[-1][1] == "done"


def test_a_failed_step_reports_delete_error_and_never_reports_done(monkeypatch):
    marks: list[tuple[str, str]] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: marks.append((u, s)))

    def boom(step: str, user_id: str) -> None:
        if step == "domain_rows":
            raise RuntimeError("db unreachable")

    monkeypatch.setattr(deletion, "_run_step", boom)
    assert deletion.delete_everything("user-1") == "delete_error"
    assert [s for _, s in marks] == ["delete_pending", "delete_error"]
    assert "done" not in [s for _, s in marks]


def test_a_later_step_never_runs_after_a_failure(monkeypatch):
    ran: list[str] = []
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: None)

    def boom(step: str, user_id: str) -> None:
        ran.append(step)
        if step == "storage":
            raise RuntimeError("storage down")

    monkeypatch.setattr(deletion, "_run_step", boom)
    deletion.delete_everything("user-1")
    assert ran == ["storage"]


def test_rerunning_after_success_is_a_clean_no_op(monkeypatch):
    """Idempotence: every step is a delete-where-exists, so a second pass is safe."""
    monkeypatch.setattr(deletion, "_mark", lambda u, s, d=None: None)
    monkeypatch.setattr(deletion, "_run_step", lambda step, user_id: None)
    assert deletion.delete_everything("user-1") == "done"
    assert deletion.delete_everything("user-1") == "done"
```

- [ ] **Step 2: Run and verify failure**

```bash
cd companion_api && .venv/bin/pytest tests/test_deletion.py -q
```

Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `companion_api/deletion.py`**

```python
"""One-action account deletion.

Order is load-bearing. Supabase refuses to delete an auth user that still owns
Storage objects, and a half-deleted account must stay visibly retryable rather
than report success. Every step is a delete-where-exists, so re-running after a
partial failure is safe and converges.

Nothing here logs row contents — only step names and user ids."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from delapan.core.clients.supabase import service_client

from companion_api.settings import get_companion_settings

log = logging.getLogger(__name__)

_SCHEMA = "hunter8"

# Child rows cascade from their parents, so only the roots are listed; ordering
# within domain_rows is handled by the foreign keys' ON DELETE CASCADE.
_DOMAIN_TABLES = [
    "shortlist_feedback", "match_assessments", "watched_companies",
    "company_theses", "confirmed_profiles", "profile_questions",
    "profile_drafts", "resume_uploads", "pipeline_runs",
]

_STEPS = ["storage", "domain_rows", "membership", "auth_user"]


def deletion_plan(user_id: str) -> list[str]:
    """Ordered step names. Exposed so the ordering is testable and auditable."""
    return list(_STEPS)


def _mark(user_id: str, state: str, detail: str | None = None) -> None:
    payload = {"user_id": user_id, "state": state, "detail": detail}
    if state in ("done", "delete_error"):
        payload["completed_at"] = datetime.now(timezone.utc).isoformat()
    service_client().schema(_SCHEMA).table("deletion_requests").upsert(
        payload, on_conflict="user_id"
    ).execute()


def _run_step(step: str, user_id: str) -> None:
    client = service_client()
    if step == "storage":
        bucket = client.storage.from_(get_companion_settings().bucket)
        existing = bucket.list(user_id)
        paths = [f"{user_id}/{obj['name']}" for obj in existing or []]
        if paths:
            bucket.remove(paths)
    elif step == "domain_rows":
        for table in _DOMAIN_TABLES:
            client.schema(_SCHEMA).table(table).delete().eq(
                "user_id", user_id
            ).execute()
    elif step == "membership":
        client.schema(_SCHEMA).table("product_memberships").delete().eq(
            "user_id", user_id
        ).execute()
    elif step == "auth_user":
        client.auth.admin.delete_user(user_id)
    else:  # pragma: no cover — _STEPS is closed
        raise ValueError(f"unknown deletion step: {step}")


def delete_everything(user_id: str) -> str:
    """Run every step in order. Returns "done" or "delete_error".

    A failure stops the run — later steps must not proceed past a step that may
    have left data behind — and leaves the request in delete_error, which is
    retryable."""
    _mark(user_id, "delete_pending")
    for step in deletion_plan(user_id):
        try:
            _run_step(step, user_id)
        except Exception as exc:  # noqa: BLE001 — visible, never silently "done"
            log.warning("deletion step %s failed for %s: %s", step, user_id, exc)
            _mark(user_id, "delete_error", f"{step}: {exc}"[:200])
            return "delete_error"
    _mark(user_id, "done")
    return "done"
```

- [ ] **Step 4: Run tests**

```bash
cd companion_api && .venv/bin/pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add companion_api/deletion.py companion_api/tests/test_deletion.py
git commit -m "feat(companion-api): idempotent deletion, storage before auth user"
```

---

### Task 6: Product-scoped routes

**Files:**
- Create: `companion_api/routes/__init__.py`, `companion_api/routes/session.py`, `companion_api/routes/dossier.py`, `companion_api/routes/account.py`, `companion_api/tests/test_routes.py`
- Modify: `companion_api/app.py`

**Interfaces:**
- Produces: `GET /session`, `POST /session/redeem`, `GET /dossier`, `DELETE /account`.
- Every route except `POST /session/redeem` depends on `require_membership`. `redeem` uses `current_user` only — by definition the caller has no membership yet.

- [ ] **Step 1: Write the failing tests**

```python
# companion_api/tests/test_routes.py
import pytest
from fastapi.testclient import TestClient

from companion_api import auth, deletion
from companion_api.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "verify_bearer", lambda h: "user-1")
    return TestClient(create_app())


def test_every_route_requires_authorization():
    unauth = TestClient(create_app())
    for method, path in [("get", "/session"), ("get", "/dossier"),
                         ("delete", "/account")]:
        assert getattr(unauth, method)(path).status_code == 401, path


def test_session_403s_without_a_membership(client, monkeypatch):
    monkeypatch.setattr(auth, "membership_for", lambda uid: None)
    assert client.get("/session", headers={"authorization": "Bearer x"}).status_code == 403


def test_session_returns_the_membership_email(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    res = client.get("/session", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert res.json() == {"user_id": "user-1", "email": "a@b.c", "state": "active"}


def test_redeem_does_not_require_an_existing_membership(client, monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(auth, "membership_for", lambda uid: None)
    monkeypatch.setattr(
        auth, "redeem_invite",
        lambda t, u, e: seen.update({"token": t, "user": u, "email": e}),
    )
    res = client.post(
        "/session/redeem",
        json={"token": "tok", "email": "a@b.c"},
        headers={"authorization": "Bearer x"},
    )
    assert res.status_code == 200
    assert seen == {"token": "tok", "user": "user-1", "email": "a@b.c"}


def test_dossier_returns_only_the_callers_state(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    asked: list[str] = []

    def state(user_id: str):
        asked.append(user_id)
        return {"stage": "upload", "profile_version": None, "companies": 0,
                "shortlist": 0}

    monkeypatch.setattr("companion_api.routes.dossier.dossier_state", state)
    res = client.get("/dossier", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert asked == ["user-1"]


def test_delete_account_reports_the_deletion_state(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    monkeypatch.setattr(
        "companion_api.routes.account.delete_everything", lambda uid: "done"
    )
    res = client.delete("/account", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert res.json() == {"state": "done"}


def test_delete_account_surfaces_a_failure_as_delete_error(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    monkeypatch.setattr(
        "companion_api.routes.account.delete_everything", lambda uid: "delete_error"
    )
    res = client.delete("/account", headers={"authorization": "Bearer x"})
    assert res.json() == {"state": "delete_error"}
```

- [ ] **Step 2: Run and verify failure**

```bash
cd companion_api && .venv/bin/pytest tests/test_routes.py -q
```

Expected: FAIL — routes do not exist.

- [ ] **Step 3: Write the routers**

`companion_api/routes/__init__.py`: empty file.

`companion_api/routes/session.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr

from companion_api import auth

router = APIRouter()


class RedeemBody(BaseModel):
    token: str
    email: EmailStr


@router.get("/session")
def read_session(request: Request, user_id: str = Depends(auth.require_membership)):
    row = auth.membership_for(user_id) or {}
    return {"user_id": user_id, "email": row.get("email"), "state": row.get("state")}


@router.post("/session/redeem")
def redeem(body: RedeemBody, request: Request):
    """The one route a member-less identity may call. Invite checks run inside
    redeem_invite BEFORE any product row exists."""
    user_id = auth.current_user(request)
    auth.redeem_invite(body.token, user_id, str(body.email))
    return {"state": "active"}
```

`companion_api/routes/dossier.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from companion_api.auth import require_membership
from companion_api.db import dossier_state

router = APIRouter()


@router.get("/dossier")
def read_dossier(user_id: str = Depends(require_membership)):
    """Persisted progress for the caller only. The pipeline that fills these
    rows is child plans 3-4; this returns whatever exists."""
    return dossier_state(user_id)
```

`companion_api/routes/account.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from companion_api.auth import require_membership
from companion_api.deletion import delete_everything

router = APIRouter()


@router.delete("/account")
def delete_account(user_id: str = Depends(require_membership)):
    """One action. Returns the terminal state; a delete_error is retryable and
    is never reported as done."""
    return {"state": delete_everything(user_id)}
```

- [ ] **Step 4: Register the routers**

In `companion_api/app.py`, inside `create_app()` before `return app`:

```python
    from companion_api.routes import account, dossier, session

    app.include_router(session.router)
    app.include_router(dossier.router)
    app.include_router(account.router)
```

Also add to `auth.py` a re-export so routes and tests share one seam:

```python
membership_for = membership_for  # noqa: PLW0127 — explicit re-export for monkeypatching
```

(If the linter objects, instead import it as `from companion_api.db import membership_for as membership_for`.)

- [ ] **Step 5: Run tests**

```bash
cd companion_api && .venv/bin/pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add companion_api/routes companion_api/app.py companion_api/auth.py companion_api/tests/test_routes.py
git commit -m "feat(companion-api): product-scoped session, dossier, and account routes"
```

---

### Task 7: Live isolation tests, Fly config, and the full gate

**Files:**
- Create: `companion_api/tests/live/__init__.py`, `companion_api/tests/live/conftest.py`, `companion_api/tests/live/test_rls_isolation.py`, `companion_api/fly.toml`
- Modify: `README.md`

**Interfaces:**
- Produces: the umbrella spec's mandated live cross-user denial proof, run against the `hunter8-spine` branch — never production.

- [ ] **Step 1: Write the live conftest**

```python
# companion_api/tests/live/conftest.py
"""Live tests against the hunter8-spine Supabase BRANCH.

Skipped unless SUPABASE_URL is set from companion_api/.env.branch. These create
and delete two real auth users, so they must never run against production —
the guard below refuses the production project ref outright."""

from __future__ import annotations

import os
import uuid

import pytest

PRODUCTION_REF = "gunqbyddzuwzpncfigro"


def _env(name: str) -> str | None:
    return os.environ.get(name)


@pytest.fixture(scope="session")
def live_env():
    url = _env("SUPABASE_URL")
    if not url or not _env("SUPABASE_SERVICE_ROLE_KEY"):
        pytest.skip("live tests need companion_api/.env.branch loaded")
    if PRODUCTION_REF in url:
        pytest.fail("REFUSING to run live tests against the production project")
    return url


@pytest.fixture
def two_users(live_env):
    """Create two real users on the branch; delete both afterwards."""
    from supabase import create_client

    admin = create_client(live_env, os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    made = []
    for _ in range(2):
        email = f"rls-{uuid.uuid4().hex[:10]}@example.test"
        password = uuid.uuid4().hex
        res = admin.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        made.append({"id": res.user.id, "email": email, "password": password})
    yield admin, made[0], made[1]
    for user in made:
        try:
            admin.auth.admin.delete_user(user["id"])
        except Exception:  # noqa: BLE001 — cleanup must not mask a test failure
            pass


def user_client(url: str, email: str, password: str):
    from supabase import create_client

    client = create_client(url, os.environ["SUPABASE_ANON_KEY"])
    client.auth.sign_in_with_password({"email": email, "password": password})
    return client
```

- [ ] **Step 2: Write the isolation tests**

```python
# companion_api/tests/live/test_rls_isolation.py
"""The umbrella spec calls this out explicitly: fake-database tests are
insufficient — RLS must be proven with two real users."""

from __future__ import annotations

import os

from companion_api.tests.live.conftest import user_client


def _seed_profile(admin, user_id: str) -> str:
    row = (
        admin.schema("hunter8").table("confirmed_profiles")
        .insert({"user_id": user_id, "version": 1, "payload": {"thesis": "x"}})
        .execute()
    )
    return row.data[0]["id"]


def test_a_user_cannot_read_another_users_profile(two_users, live_env):
    admin, alice, bob = two_users
    _seed_profile(admin, alice["id"])

    as_bob = user_client(live_env, bob["email"], bob["password"])
    rows = as_bob.schema("hunter8").table("confirmed_profiles").select("id").execute()
    assert rows.data == []


def test_a_user_reads_their_own_profile(two_users, live_env):
    admin, alice, _ = two_users
    _seed_profile(admin, alice["id"])

    as_alice = user_client(live_env, alice["email"], alice["password"])
    rows = as_alice.schema("hunter8").table("confirmed_profiles").select("id").execute()
    assert len(rows.data) == 1


def test_a_user_cannot_write_a_row_owned_by_someone_else(two_users, live_env):
    admin, alice, bob = two_users
    as_bob = user_client(live_env, bob["email"], bob["password"])
    try:
        as_bob.schema("hunter8").table("confirmed_profiles").insert(
            {"user_id": alice["id"], "version": 9, "payload": {}}
        ).execute()
    except Exception:
        return  # RLS rejected the write — the expected outcome
    rows = (
        admin.schema("hunter8").table("confirmed_profiles")
        .select("id").eq("user_id", alice["id"]).eq("version", 9).execute()
    )
    assert rows.data == [], "RLS allowed a cross-user insert"


def test_job_postings_are_invisible_without_an_owned_assessment(two_users, live_env):
    admin, alice, bob = two_users
    admin.schema("hunter8").table("job_postings").upsert(
        {"url": "https://x/rls-1", "company": "Acme", "title": "AI Engineer",
         "source": "ats:greenhouse"}
    ).execute()
    profile_id = _seed_profile(admin, alice["id"])
    admin.schema("hunter8").table("match_assessments").insert(
        {"user_id": alice["id"], "profile_id": profile_id,
         "posting_url": "https://x/rls-1", "score": 80,
         "provider": "test", "model": "test"}
    ).execute()

    as_alice = user_client(live_env, alice["email"], alice["password"])
    as_bob = user_client(live_env, bob["email"], bob["password"])
    alice_rows = as_alice.schema("hunter8").table("job_postings").select("url").execute()
    bob_rows = as_bob.schema("hunter8").table("job_postings").select("url").execute()
    assert [r["url"] for r in alice_rows.data] == ["https://x/rls-1"]
    assert bob_rows.data == []


def test_invites_are_never_client_readable(two_users, live_env):
    admin, alice, _ = two_users
    admin.schema("hunter8").table("invites").insert(
        {"token": "live-tok-1", "email": "someone@x.com",
         "expires_at": "2099-01-01T00:00:00+00:00"}
    ).execute()

    as_alice = user_client(live_env, alice["email"], alice["password"])
    rows = as_alice.schema("hunter8").table("invites").select("token").execute()
    assert rows.data == []


def test_a_user_cannot_read_another_users_resume_object(two_users, live_env):
    admin, alice, bob = two_users
    bucket = admin.storage.from_("hunter8-resumes")
    path = f"{alice['id']}/secret.pdf"
    bucket.upload(path, b"%PDF-1.4 alice", {"content-type": "application/pdf"})

    as_bob = user_client(live_env, bob["email"], bob["password"])
    try:
        data = as_bob.storage.from_("hunter8-resumes").download(path)
    except Exception:
        data = None
    assert not data, "storage RLS allowed a cross-user read"
    bucket.remove([path])
```

- [ ] **Step 3: Run the live suite**

```bash
cd companion_api && set -a && . ./.env.branch && set +a && .venv/bin/pytest tests/live -q
```

Expected: 6 passed. If `SUPABASE_URL` is unset the suite skips; if it points at production it fails loudly.

- [ ] **Step 4: Write `companion_api/fly.toml`**

```toml
# Separate Fly app from delapan-api: separate deploy, secrets, and blast radius.
app = 'hunter8-companion-api'
primary_region = 'sjc'

[build]

[env]
  PORT = '8000'
  HUNTER8_BUCKET = 'hunter8-resumes'

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = 'suspend'
  auto_start_machines = true
  min_machines_running = 0

[[vm]]
  size = 'shared-cpu-1x'
  memory = '512mb'
```

Secrets (`SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `HUNTER8_ALLOWED_ORIGINS`) are set with `fly secrets set` at rollout — child plan 5. This plan does not deploy.

- [ ] **Step 5: README pointer**

Append to the root `README.md`'s "Core boundary" section:

```markdown
The companion's API lives in [companion_api/](companion_api/) — a separate Fly
service that reuses delapan's audited auth and owns the `hunter8` Postgres
schema. It imports `hunter8_core` and nothing else from this repo.
```

- [ ] **Step 6: Full verification gate**

```bash
cd companion_api && .venv/bin/pytest -q
set -a && . ./.env.branch && set +a && .venv/bin/pytest tests/live -q
cd .. && .venv/bin/pytest tests/ -q
cd companion && npx vitest run
cd .. && git diff --check
```

Expected: companion_api unit suite green; 6 live tests green; hunter8's Python suite still 216; the frontend's 43 still green; no whitespace errors.

- [ ] **Step 7: Commit**

```bash
git add companion_api README.md
git commit -m "feat(companion-api): live cross-user isolation proof and Fly config"
```

---

## Plan self-review

- **Spec coverage:** the umbrella spec's child-plan-2 scope — "separate frontend/API deployments, invite binding, product authorization, dedicated tables/bucket/RLS, and deletion path" — maps to Tasks 1 (service + boundary), 3 (invite + gate), 2/4 (schema, RLS, bucket), 5 (deletion), 6 (product-scoped routes), 7 (live isolation + Fly config). The frontend deployment config is deliberately deferred to child plan 5's rollout, which is where the spec puts domain attachment and origin allowlisting; noted here so it is not silently lost.
- **Deliberately out of scope:** résumé parsing, model calls, company verification, discovery, ranking, and wiring the frontend's `CompanionApi` to real HTTP. Those are child plans 3–4. The frontend continues to run on `FakeCompanionApi` after this plan.
- **Placeholders:** none. Every step carries the SQL, Python, or exact command it needs.
- **Type consistency:** `user_id: str` throughout; `membership_for`/`invite_by_token`/`create_membership`/`mark_invite_redeemed`/`dossier_state`/`delete_everything`/`deletion_plan` keep one signature across `db.py`, `auth.py`, `deletion.py`, the routers, and their tests.
- **Safety:** production is protected three ways — migrations are applied only by the controller, only to the branch; the live conftest fails on the production project ref; and no migration contains `drop`/`alter table public.`, asserted by test.
- **Known risk:** `auth.py`'s re-export of `membership_for` exists so tests and routes share one monkeypatch seam. If the linter rejects the self-assignment form, use the aliased-import form given in Task 6 Step 4 — behavior is identical.
