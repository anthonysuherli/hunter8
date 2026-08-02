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
