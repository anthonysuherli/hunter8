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

# Child rows cascade from their parents, so only the roots are listed; ordering
# within domain_rows is handled by the foreign keys' ON DELETE CASCADE.
_DOMAIN_TABLES = [
    "shortlist_feedback", "match_assessments", "watched_companies",
    "company_theses", "confirmed_profiles", "profile_questions",
    "profile_drafts", "resume_uploads", "pipeline_runs",
]


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


def mark_invite_redeemed(token: str, user_id: str) -> bool:
    """Conditional single-statement update; returns False if another caller won
    the race (the UPDATE re-evaluates its WHERE against the updated row)."""
    res = (
        _table("invites")
        .update({"redeemed_at": datetime.now(timezone.utc).isoformat(),
                 "redeemed_by": user_id})
        .eq("token", token)
        .is_("redeemed_at", "null")
        .execute()
    )
    return bool(res.data)


def release_invite(token: str) -> None:
    """Undo a redemption stamp when the membership write failed, so a retry is
    possible. Without this a transient failure locks the invitee out of the
    product's only onboarding path."""
    _table("invites").update({"redeemed_at": None, "redeemed_by": None}).eq(
        "token", token
    ).execute()


def create_membership(user_id: str, email: str, invite_token: str) -> None:
    _table("product_memberships").insert(
        {"user_id": user_id, "email": email, "invite_token": invite_token,
         "state": "active"},
    ).execute()


def auth_email_for(user_id: str) -> str | None:
    """The verified email on the Supabase auth record. This is the ONLY trusted
    email source: verify_bearer returns just the subject, so an email passed in
    by the caller proves nothing."""
    res = service_client().auth.admin.get_user_by_id(user_id)
    user = getattr(res, "user", None)
    if user is None:
        return None
    if not getattr(user, "email_confirmed_at", None):
        return None
    email = getattr(user, "email", None)
    return email.lower() if email else None


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


def deletion_state_for(user_id: str) -> str | None:
    """The terminal-or-pending state of a deletion run, if one was ever started."""
    rows = (
        _table("deletion_requests").select("state").eq("user_id", user_id)
        .limit(1).execute()
    )
    return rows.data[0]["state"] if rows.data else None


def mark_deletion_state(user_id: str, state: str, detail: str | None = None) -> None:
    """Upsert the audit record for an account-deletion run. deletion_requests
    has no FK to auth.users on purpose — the audit record outlives the user.

    completed_at is always included (None unless the state is terminal): a
    merge-duplicates upsert only overwrites columns present in the payload, so
    omitting the key would let a stale terminal timestamp survive onto a
    delete_pending row on retry."""
    payload: dict[str, Any] = {"user_id": user_id, "state": state, "detail": detail}
    payload["completed_at"] = (
        datetime.now(timezone.utc).isoformat() if state in ("done", "delete_error") else None
    )
    _table("deletion_requests").upsert(payload, on_conflict="user_id").execute()


def mark_membership_deleting(user_id: str) -> None:
    """Close the upload gate before anything is removed: the storage insert
    policy requires state = 'active'."""
    _table("product_memberships").update({"state": "delete_pending"}).eq(
        "user_id", user_id
    ).execute()


def clear_storage_objects(user_id: str) -> None:
    """Page through every object under the user's prefix. Raising when objects
    remain keeps the run visibly retryable rather than reporting done with
    files left behind."""
    bucket = service_client().storage.from_(get_companion_settings().bucket)
    for _ in range(100):  # bounded: 100 pages x 1000 = 100k objects
        page = bucket.list(user_id, {"limit": 1000}) or []
        paths = [f"{user_id}/{obj['name']}" for obj in page]
        if not paths:
            return
        bucket.remove(paths)
    raise RuntimeError(f"storage objects remain under {user_id}")


def delete_domain_rows(user_id: str) -> None:
    """Delete every domain root row for the user. Child rows cascade."""
    for table in _DOMAIN_TABLES:
        _table(table).delete().eq("user_id", user_id).execute()


def delete_membership(user_id: str) -> None:
    _table("product_memberships").delete().eq("user_id", user_id).execute()


def delete_invites_for(user_id: str) -> None:
    """Redeemed invites hold the user's email and an ON DELETE SET NULL ref to
    auth.users that collides with the redeemed_at/redeemed_by CHECK — leaving
    one makes the auth-user delete fail permanently."""
    _table("invites").delete().eq("redeemed_by", user_id).execute()


def delete_auth_user(user_id: str) -> None:
    """Idempotent: an already-deleted user is success, not failure."""
    try:
        service_client().auth.admin.delete_user(user_id)
    except Exception as exc:  # noqa: BLE001 — a missing user means done
        if getattr(exc, "status", None) == 404 or "not found" in str(exc).lower():
            return
        raise
