import pytest
from fastapi import HTTPException

from companion_api import ratelimit


@pytest.fixture(autouse=True)
def _reset():
    ratelimit.reset()
    yield
    ratelimit.reset()


def test_calls_within_the_limit_all_pass():
    for i in range(5):
        ratelimit.check("k", limit=5, window_seconds=60.0, now=float(i))


def test_the_call_past_the_limit_is_429(monkeypatch):
    for i in range(5):
        ratelimit.check("k", limit=5, window_seconds=60.0, now=float(i))
    with pytest.raises(HTTPException) as exc:
        ratelimit.check("k", limit=5, window_seconds=60.0, now=5.0)
    assert exc.value.status_code == 429


def test_a_different_key_is_unaffected_by_another_keys_limit():
    for i in range(5):
        ratelimit.check("user-a", limit=5, window_seconds=60.0, now=float(i))
    # user-a is now at its limit; user-b must still be allowed.
    ratelimit.check("user-b", limit=5, window_seconds=60.0, now=0.0)


def test_reset_clears_all_keys():
    for i in range(5):
        ratelimit.check("k", limit=5, window_seconds=60.0, now=float(i))
    ratelimit.reset()
    ratelimit.check("k", limit=5, window_seconds=60.0, now=0.0)


def test_calls_outside_the_window_do_not_count_against_the_limit():
    for i in range(5):
        ratelimit.check("k", limit=5, window_seconds=60.0, now=float(i))
    # Far enough past the window that all five earlier hits have expired.
    ratelimit.check("k", limit=5, window_seconds=60.0, now=1000.0)
