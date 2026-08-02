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
