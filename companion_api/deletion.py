"""One-action account deletion.

Order is load-bearing. Supabase refuses to delete an auth user that still owns
Storage objects, and a half-deleted account must stay visibly retryable rather
than report success. Every step is a delete-where-exists, so re-running after a
partial failure is safe and converges.

All data access goes through companion_api.db — this module never talks to
the service-role client directly.

Nothing here logs row contents — only step names and user ids."""

from __future__ import annotations

import logging

from companion_api import db

log = logging.getLogger(__name__)

_STEPS = ["storage", "domain_rows", "membership", "invites", "auth_user"]


def deletion_plan(user_id: str) -> list[str]:
    """Ordered step names. Exposed so the ordering is testable and auditable."""
    return list(_STEPS)


def _mark(user_id: str, state: str, detail: str | None = None) -> None:
    db.mark_deletion_state(user_id, state, detail)


def _run_step(step: str, user_id: str) -> None:
    if step == "storage":
        db.clear_storage_objects(user_id)
    elif step == "domain_rows":
        db.delete_domain_rows(user_id)
    elif step == "membership":
        db.delete_membership(user_id)
    elif step == "invites":
        db.delete_invites_for(user_id)
    elif step == "auth_user":
        db.delete_auth_user(user_id)
    else:  # pragma: no cover — _STEPS is closed
        raise ValueError(f"unknown deletion step: {step}")


def delete_everything(user_id: str) -> str:
    """Run every step in order. Returns "done" or "delete_error".

    A failure stops the run — later steps must not proceed past a step that may
    have left data behind — and leaves the request in delete_error, which is
    retryable."""
    _mark(user_id, "delete_pending")
    try:
        db.mark_membership_deleting(user_id)
    except Exception as exc:  # noqa: BLE001 — visible, never silently "done"
        log.warning("deletion step %s failed for %s: %s", "gate", user_id, type(exc).__name__)
        _mark(user_id, "delete_error", f"gate: {type(exc).__name__}"[:200])
        return "delete_error"
    for step in deletion_plan(user_id):
        try:
            _run_step(step, user_id)
        except Exception as exc:  # noqa: BLE001 — visible, never silently "done"
            log.warning("deletion step %s failed for %s: %s", step, user_id, type(exc).__name__)
            _mark(user_id, "delete_error", f"{step}: {type(exc).__name__}"[:200])
            return "delete_error"
    _mark(user_id, "done")
    return "done"
