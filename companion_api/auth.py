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
