"""Hard network guard for the unit suite.

A route whose authorization dependency is wrong falls through to a real
`dossier_state()` call, and delapan's settings resolve live Supabase credentials
from a `.env` on this machine — so a unit test CAN reach the production project.
That happened once during review (it failed closed on PGRST106, reading and
writing nothing) and must not be possible again.

Every unit test monkeypatches its data access, so nothing here legitimately
needs a client. `tests/live/` has its own conftest and is exempt: it opts in
explicitly and refuses the production project ref by name.
"""

from __future__ import annotations

import pytest

import companion_api.db as db


class ProductionReachAttempt(RuntimeError):
    """Raised instead of opening a connection, so the failure names itself."""


@pytest.fixture(autouse=True)
def _no_supabase_client(request, monkeypatch):
    if "live" in request.node.nodeid.split("/"):
        return

    def _refuse(*_args, **_kwargs):
        raise ProductionReachAttempt(
            "a unit test tried to build a Supabase client. Monkeypatch the db "
            "helper instead — this suite must never reach a live project."
        )

    monkeypatch.setattr(db, "service_client", _refuse)
