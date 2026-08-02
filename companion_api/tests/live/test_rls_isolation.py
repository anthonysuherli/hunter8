"""The umbrella spec calls this out explicitly: fake-database tests are
insufficient — RLS must be proven with two real users."""

from __future__ import annotations

import os
import uuid

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
    """Clients hold only a select grant on hunter8 tables (migration 0002), so
    this insert is refused at the privilege level for ANY row — not just
    Alice's — before RLS policy evaluation even applies. The outcome the
    umbrella spec cares about (a client can never write another user's row)
    still holds; it is just enforced one layer earlier than by policy alone."""
    admin, alice, bob = two_users
    as_bob = user_client(live_env, bob["email"], bob["password"])
    try:
        as_bob.schema("hunter8").table("confirmed_profiles").insert(
            {"user_id": alice["id"], "version": 9, "payload": {}}
        ).execute()
    except Exception:
        return  # privilege/RLS rejected the write — the expected outcome
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
    # Unique per run and cleaned up: a fixed token made this test pass once and
    # then fail on invites_pkey forever after, which reads like an RLS flake.
    token = f"live-tok-{uuid.uuid4().hex[:12]}"
    admin.schema("hunter8").table("invites").insert(
        {"token": token, "email": "someone@x.com",
         "expires_at": "2099-01-01T00:00:00+00:00"}
    ).execute()
    try:
        as_alice = user_client(live_env, alice["email"], alice["password"])
        rows = as_alice.schema("hunter8").table("invites").select("token").execute()
        assert rows.data == []
    finally:
        admin.schema("hunter8").table("invites").delete().eq("token", token).execute()


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


def test_a_user_without_a_membership_cannot_upload(two_users, live_env):
    """Migration 0003's insert policy on storage.objects additionally requires
    an active hunter8.product_memberships row. The two_users fixture creates
    bare auth users with no membership row, so bob's own upload into his own
    folder must be refused even though the path-ownership check passes."""
    _admin, _alice, bob = two_users
    as_bob = user_client(live_env, bob["email"], bob["password"])
    path = f"{bob['id']}/no-membership.pdf"
    try:
        as_bob.storage.from_("hunter8-resumes").upload(
            path, b"%PDF-1.4 bob", {"content-type": "application/pdf"}
        )
    except Exception:
        return  # refused — the expected outcome
    # Some client versions return a non-2xx without raising; if we get here,
    # confirm nothing actually landed and clean up if it did.
    _admin.storage.from_("hunter8-resumes").remove([path])
    raise AssertionError("storage accepted an upload with no active membership")


def test_a_user_cannot_read_another_users_deletion_record(two_users, live_env):
    admin, alice, bob = two_users
    admin.schema("hunter8").table("deletion_requests").insert(
        {"user_id": alice["id"], "state": "delete_pending"}
    ).execute()

    as_bob = user_client(live_env, bob["email"], bob["password"])
    rows = (
        as_bob.schema("hunter8").table("deletion_requests")
        .select("user_id").eq("user_id", alice["id"]).execute()
    )
    assert rows.data == []
