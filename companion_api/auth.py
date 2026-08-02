"""Companion authorization: a verified Supabase identity, then an invite-bound
hunter8 product membership. Token verification is delegated to delapan's
audited `verify_bearer` — re-implementing it is forbidden (see test_boundary).

Signup-ordering deviation, documented on purpose: the umbrella spec says
"Public signup followed by an allowlist check is insufficient because it
creates an account before access is established." As built here, Supabase
Auth is delapan's shared Auth, and it creates an `auth.users` row before
`redeem_invite` can ever run — so a bare identity may exist with no hunter8
invite behind it. What IS enforced, and is the actual security boundary, is
narrower and precise: no hunter8 membership row, no hunter8 domain row, and no
object in the hunter8 résumé bucket can exist before an invite is redeemed
(see redeem_invite's ordering, and the storage insert policy's membership
check). Closing the wider gap — restricting self-service signup itself — is a
Supabase Auth project setting, not something this module can enforce, and it
is owned by the rollout plan."""

from __future__ import annotations

from datetime import datetime, timezone

from delapan.api.auth import verify_bearer
from fastapi import HTTPException, Request

from companion_api.db import (
    auth_email_for,
    create_membership,
    deletion_state_for,
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
    """DELETE /account only. Admits a membership in any state, and also a caller
    whose membership row is already gone but whose deletion never completed —
    deletion removes the membership at step 3 of 5, so a failure in the last two
    steps would otherwise lock the user out of finishing their own erasure."""
    user_id = current_user(request)
    if membership_for(user_id) is not None:
        return user_id
    state = deletion_state_for(user_id)
    if state is not None and state != "done":
        return user_id
    raise HTTPException(status_code=403, detail="this account has no hunter8 invite")


def redeem_invite(token: str, user_id: str) -> None:
    """Bind a single-use invite to a verified identity.

    Every check runs BEFORE any product row is created — the umbrella spec
    forbids creating an account and then testing an allowlist.

    Per-subject rate limiting for this route lives in routes/session.py
    (companion_api.ratelimit), applied before this function runs — kept out of
    auth.py so this module stays about identity and membership, not traffic
    shaping."""
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
