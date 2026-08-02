"""Live tests against the hunter8-spine Supabase BRANCH.

Skipped unless SUPABASE_URL is set from companion_api/.env.branch. These create
and delete two real auth users, so they must never run against production —
the guard below refuses the production project ref outright."""

from __future__ import annotations

import os
import uuid

import pytest

PRODUCTION_REF = "gunqbyddzuwzpncfigro"


def _env(name: str) -> str | None:
    return os.environ.get(name)


@pytest.fixture(scope="session")
def live_env():
    url = _env("SUPABASE_URL")
    if not url or not _env("SUPABASE_SERVICE_ROLE_KEY"):
        pytest.skip("live tests need companion_api/.env.branch loaded")
    if PRODUCTION_REF in url:
        pytest.fail("REFUSING to run live tests against the production project")
    return url


@pytest.fixture
def two_users(live_env):
    """Create two real users on the branch; delete both afterwards."""
    from supabase import create_client

    admin = create_client(live_env, os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    made = []
    for _ in range(2):
        email = f"rls-{uuid.uuid4().hex[:10]}@example.test"
        password = uuid.uuid4().hex
        res = admin.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}
        )
        made.append({"id": res.user.id, "email": email, "password": password})
    yield admin, made[0], made[1]
    for user in made:
        try:
            admin.auth.admin.delete_user(user["id"])
        except Exception:  # noqa: BLE001 — cleanup must not mask a test failure
            pass


def user_client(url: str, email: str, password: str):
    from supabase import create_client

    client = create_client(url, os.environ["SUPABASE_ANON_KEY"])
    client.auth.sign_in_with_password({"email": email, "password": password})
    return client
