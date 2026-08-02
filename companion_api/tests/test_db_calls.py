"""Behavioural coverage over db.py's call chains. Every helper was previously
checked only by inspect.signature over parameter NAMES (test_db_helpers.py) —
nothing asserted that _table() pins .schema("hunter8"), or that helpers emit
the .eq(...) filters they claim to. mark_invite_redeemed in particular returns
bool(res.data), which silently depends on postgrest returning a representation
body; a client default of returning=minimal would make it return False for
every caller with no test noticing."""

from __future__ import annotations

from companion_api import db


class _Response:
    def __init__(self, data):
        self.data = data
        self.count = len(data) if data else 0


class _Fake:
    """Records every attribute access and call as a (name, args, kwargs) chain
    entry. Unknown methods return self so any fluent chain resolves; execute()
    returns the queued response (or an empty one)."""

    def __init__(self, response=None):
        self.calls: list[tuple[str, tuple, dict]] = []
        self._response = response if response is not None else _Response([])

    def __getattr__(self, name):
        def _call(*args, **kwargs):
            self.calls.append((name, args, kwargs))
            if name == "execute":
                return self._response
            return self
        return _call


def _install(monkeypatch, response=None):
    fake = _Fake(response)
    monkeypatch.setattr(db, "service_client", lambda: fake)
    return fake


def test_table_pins_the_hunter8_schema(monkeypatch):
    fake = _install(monkeypatch)
    db._table("x")
    names = [c[0] for c in fake.calls]
    assert names[:2] == ["schema", "table"]
    assert fake.calls[0][1] == ("hunter8",)
    assert fake.calls[1][1] == ("x",)


def test_membership_for_filters_by_user_id(monkeypatch):
    fake = _install(monkeypatch)
    db.membership_for("u")
    eq_calls = [c for c in fake.calls if c[0] == "eq"]
    assert ("eq", ("user_id", "u"), {}) in eq_calls


def test_invite_by_token_filters_by_token(monkeypatch):
    fake = _install(monkeypatch)
    db.invite_by_token("t")
    eq_calls = [c for c in fake.calls if c[0] == "eq"]
    assert ("eq", ("token", "t"), {}) in eq_calls


def test_mark_invite_redeemed_filters_token_and_unredeemed(monkeypatch):
    fake = _install(monkeypatch, response=_Response([{"token": "t"}]))
    result = db.mark_invite_redeemed("t", "u")
    eq_calls = [c for c in fake.calls if c[0] == "eq"]
    is_calls = [c for c in fake.calls if c[0] == "is_"]
    assert ("eq", ("token", "t"), {}) in eq_calls
    assert ("is_", ("redeemed_at", "null"), {}) in is_calls
    assert result is True


def test_mark_invite_redeemed_returns_false_when_no_rows_come_back(monkeypatch):
    fake = _install(monkeypatch, response=_Response([]))
    assert db.mark_invite_redeemed("t", "u") is False


def test_delete_invites_for_filters_by_redeemed_by(monkeypatch):
    fake = _install(monkeypatch)
    db.delete_invites_for("u")
    eq_calls = [c for c in fake.calls if c[0] == "eq"]
    assert ("eq", ("redeemed_by", "u"), {}) in eq_calls


def test_dossier_state_filters_every_query_by_user_id(monkeypatch):
    fake = _install(monkeypatch)
    db.dossier_state("u")
    eq_calls = [c for c in fake.calls if c[0] == "eq"]
    # Four queries: confirmed_profiles, watched_companies, match_assessments,
    # pipeline_runs — each must filter on this user, and only this user.
    assert eq_calls.count(("eq", ("user_id", "u"), {})) == 4
