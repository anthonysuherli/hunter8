import pytest
from fastapi.testclient import TestClient

from companion_api import auth
from companion_api.app import create_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "verify_bearer", lambda h: "user-1")
    return TestClient(create_app())


def test_every_route_requires_authorization():
    unauth = TestClient(create_app())
    for method, path, kwargs in [
        ("get", "/session", {}),
        ("get", "/dossier", {}),
        ("delete", "/account", {}),
        ("post", "/session/redeem", {"json": {"token": "x"}}),
    ]:
        assert getattr(unauth, method)(path, **kwargs).status_code == 401, path


def test_every_data_route_requires_a_membership(client, monkeypatch):
    """A previous version of this suite passed even after both data routes were
    swapped from require_membership to current_user, because the only assertion
    was 401-with-no-header (which current_user also satisfies). Assert 403 with
    a verified identity but no membership, on every membership-gated route."""
    monkeypatch.setattr(auth, "membership_for", lambda uid: None)
    for method, path, kwargs in [
        ("get", "/session", {}),
        ("get", "/dossier", {}),
        ("delete", "/account", {}),
    ]:
        res = getattr(client, method)(
            path, headers={"authorization": "Bearer x"}, **kwargs
        )
        assert res.status_code == 403, path


def test_session_403s_without_a_membership(client, monkeypatch):
    monkeypatch.setattr(auth, "membership_for", lambda uid: None)
    assert client.get("/session", headers={"authorization": "Bearer x"}).status_code == 403


def test_session_returns_the_membership_email(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    res = client.get("/session", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert res.json() == {"user_id": "user-1", "email": "a@b.c", "state": "active"}


def test_redeem_does_not_require_an_existing_membership(client, monkeypatch):
    seen: dict[str, str] = {}
    monkeypatch.setattr(auth, "membership_for", lambda uid: None)
    monkeypatch.setattr(
        auth, "redeem_invite",
        lambda t, u: seen.update({"token": t, "user": u}),
    )
    res = client.post(
        "/session/redeem",
        json={"token": "tok"},
        headers={"authorization": "Bearer x"},
    )
    assert res.status_code == 200
    assert seen == {"token": "tok", "user": "user-1"}


def test_dossier_returns_only_the_callers_state(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    asked: list[str] = []

    def state(user_id: str):
        asked.append(user_id)
        return {"stage": "upload", "profile_version": None, "companies": 0,
                "shortlist": 0}

    monkeypatch.setattr("companion_api.routes.dossier.dossier_state", state)
    res = client.get("/dossier", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert asked == ["user-1"]


def test_delete_account_reports_the_deletion_state(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    monkeypatch.setattr(
        "companion_api.routes.account.delete_everything", lambda uid: "done"
    )
    res = client.delete("/account", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert res.json() == {"state": "done"}


def test_delete_account_surfaces_a_failure_as_delete_error(client, monkeypatch):
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "active"},
    )
    monkeypatch.setattr(
        "companion_api.routes.account.delete_everything", lambda uid: "delete_error"
    )
    res = client.delete("/account", headers={"authorization": "Bearer x"})
    assert res.status_code == 503
    assert res.json() == {"state": "delete_error"}


def test_delete_account_can_be_retried_after_a_previous_delete_error(client, monkeypatch):
    """delete_everything marks the membership delete_pending before running any
    step. Without require_membership_or_deleting, the retry the docstring
    promises would 403 instead of running."""
    monkeypatch.setattr(
        auth, "membership_for",
        lambda uid: {"user_id": uid, "email": "a@b.c", "state": "delete_pending"},
    )
    monkeypatch.setattr(
        "companion_api.routes.account.delete_everything", lambda uid: "done"
    )
    res = client.delete("/account", headers={"authorization": "Bearer x"})
    assert res.status_code == 200
    assert res.json() == {"state": "done"}
