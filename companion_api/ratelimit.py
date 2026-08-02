"""Per-user in-process rate limiting.

Deliberately in-process and memory-only: this is a five-tester POC on a single
Fly machine. A distributed limiter belongs with the rollout plan, and is noted
there. Keyed on the VERIFIED subject, never on IP.
"""
from __future__ import annotations

import time
from collections import defaultdict

from fastapi import HTTPException

_hits: dict[str, list[float]] = defaultdict(list)


def check(key: str, *, limit: int, window_seconds: float, now: float | None = None) -> None:
    """Raise 429 if `key` has exceeded `limit` calls in the trailing window."""
    stamp = time.monotonic() if now is None else now
    recent = [t for t in _hits[key] if stamp - t < window_seconds]
    if len(recent) >= limit:
        _hits[key] = recent
        raise HTTPException(status_code=429, detail="too many attempts; try again later")
    recent.append(stamp)
    _hits[key] = recent


def reset() -> None:
    """Test seam."""
    _hits.clear()
