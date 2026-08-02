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
    # Comments are stripped first: prose explaining a policy (e.g. a warning
    # about `with check`) is not itself a policy, and must not fail this guard.
    sql = re.sub(r"--[^\n]*", "", _sql())
    # Storage policies allow client writes (resumé uploads), so exclude them from this check.
    # Table policies must remain select-only.
    table_sql = re.sub(r"create policy[^;]*on storage\.objects[^;]*;", "", sql, flags=re.I | re.S)
    assert "with check" not in table_sql.lower(), "table policies must not have with-check"
    assert not re.search(r"for all\b", table_sql, re.I), "table policies must be select-only"


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


def test_resume_upload_requires_an_active_membership():
    """Storage is the one client-writable surface and does not route through
    companion_api, so the invite gate must be enforced in the policy itself."""
    sql = _sql()
    insert_policy = re.search(
        r"create policy h8_resumes_insert_own[^;]*;", sql, re.I | re.S
    )
    assert insert_policy, "the resume insert policy is missing"
    body = insert_policy.group(0)
    assert "product_memberships" in body
    assert "'active'" in body


def test_resume_upload_is_pinned_to_a_flat_path():
    """F2: h8_resumes_insert_own only checked the FIRST path segment, so
    "<uid>/a/b/f.pdf" was accepted even though clear_storage_objects lists one
    level and would leave nested files behind while deletion reports done."""
    sql = _sql()
    insert_policy = re.search(
        r"create policy h8_resumes_insert_own[^;]*;", sql, re.I | re.S
    )
    assert insert_policy, "the resume insert policy is missing"
    body = insert_policy.group(0)
    assert "array_length" in body
    assert re.search(r"=\s*1\b", body)


def test_the_bucket_migration_converges_a_preexisting_bucket():
    """`do nothing` would silently leave a pre-existing public bucket public."""
    sql = _sql()
    assert re.search(r"on conflict \(id\) do update set", sql, re.I)
    assert "public = excluded.public" in sql


def test_every_table_referencing_auth_users_is_handled_by_deletion():
    """F1 shipped because the step list was hand-maintained: `invites` has no
    user_id column, only redeemed_by, so it was invisible to review."""
    from companion_api import db

    sql = _sql()
    referencing = set()
    for table in TABLES:
        body = re.search(
            rf"create table if not exists hunter8\.{table}\s*\((.*?)\n\);",
            sql, re.I | re.S,
        )
        if body and re.search(r"references auth\.users", body.group(1), re.I):
            referencing.add(table)

    # Reachable by ON DELETE CASCADE from a table that IS deleted explicitly.
    cascade_reachable = {"profile_questions", "company_theses", "watched_companies",
                         "match_assessments", "shortlist_feedback"}
    handled = set(db._DOMAIN_TABLES) | {"product_memberships", "invites"} | cascade_reachable
    missing = referencing - handled
    assert not missing, f"tables referencing auth.users with no deletion path: {missing}"
