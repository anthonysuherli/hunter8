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


def test_clients_get_read_only_access():
    sql = _sql()
    assert re.search(r"grant select on all tables in schema hunter8 to authenticated", sql, re.I)
    assert not re.search(r"grant[^;]*insert[^;]*to authenticated", sql, re.I), (
        "clients must not hold write privileges — every write goes through the service role"
    )


def test_no_policy_grants_client_writes():
    sql = _sql()
    assert "with check" not in sql.lower(), "a with-check clause implies a client write path"
    assert not re.search(r"for all\b", sql, re.I), "policies must be select-only"


def test_rls_is_forced_on_every_table():
    sql = _sql()
    for table in TABLES:
        assert re.search(rf"alter table hunter8\.{table} force row level security", sql, re.I), table


def test_service_role_can_reach_the_schema():
    sql = _sql()
    assert re.search(r"grant usage on schema hunter8 to service_role", sql, re.I)
    assert re.search(r"grant all on all tables in schema hunter8 to service_role", sql, re.I)


def test_invite_tokens_are_single_use():
    sql = _sql()
    assert re.search(r"invite_token\s+text\s+unique\s+references", sql, re.I)
