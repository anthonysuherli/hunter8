"""Companion authorization: a verified Supabase identity, then an invite-bound
hunter8 product membership. Token verification is delegated to delapan's
audited `verify_bearer` — re-implementing it is forbidden (see test_boundary)."""

from __future__ import annotations

from datetime import datetime, timezone

from delapan.api.auth import verify_bearer
from fastapi import HTTPException, Request

from companion_api.db import (
    auth_email_for,
    create_membership,
    invite_by_token,
    mark_invite_redeemed,
    membership_for,
    release_invite,
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


def require_membership_or_deleting(request: Request) -> str:
    """Like require_membership, but also admits a membership already marked
    delete_pending — otherwise a failed deletion could never be retried, and the
    user would be locked out of finishing their own erasure."""
    user_id = current_user(request)
    if membership_for(user_id) is None:
        raise HTTPException(
            status_code=403, detail="this account has no hunter8 invite"
        )
    return user_id


def redeem_invite(token: str, user_id: str) -> None:
    """Bind a single-use invite to a verified identity.

    Every check runs BEFORE any product row is created — the umbrella spec
    forbids creating an account and then testing an allowlist."""
    # Rate limiting for this endpoint is deferred: slowapi is in the plan's
    # stack but not wired yet, and belongs with the rollout plan.
    _INVALID_TOKEN = HTTPException(
        status_code=403, detail="this invite is not valid for your account"
    )
    if membership_for(user_id) is not None:
        raise HTTPException(
            status_code=409, detail="this account already has a membership"
        )
    invite = invite_by_token(token)
    if invite is None:
        raise _INVALID_TOKEN
    if invite.get("redeemed_at"):
        raise _INVALID_TOKEN
    expires = datetime.fromisoformat(invite["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires <= datetime.now(timezone.utc):
        raise _INVALID_TOKEN
    email = auth_email_for(user_id)
    if email is None:
        raise HTTPException(
            status_code=403, detail="a confirmed email address is required"
        )
    if invite["email"].lower() != email:
        raise _INVALID_TOKEN
    if not mark_invite_redeemed(token, user_id):
        raise _INVALID_TOKEN
    try:
        create_membership(user_id, email, token)
    except Exception as exc:  # noqa: BLE001 — must not strand the invitee
        release_invite(token)
        raise HTTPException(
            status_code=503, detail="could not complete redemption; please retry"
        ) from exc
