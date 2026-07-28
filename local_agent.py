# local_agent.py
"""Ollama client for the bulk screening tier.

Mirrors claude_agent.ClaudeAgent's chat_json interface so the two tiers are
swappable. Talks HTTP rather than importing an SDK because the venv is Python
3.9 and httpx is already a dependency.
"""
from __future__ import annotations

import httpx

import json_reply

DEFAULT_BASE_URL = "http://localhost:11434"

# Constrain the reply shape at the model level where Ollama supports it.
_SCHEMA = {
    "type": "object",
    "properties": {
        "fit_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "reason": {"type": "string"},
    },
    "required": ["fit_score", "reason"],
}


class LocalError(RuntimeError):
    """A single local call failed."""


class LocalUnavailable(LocalError):
    """Ollama isn't running, or the model isn't pulled — stop the batch."""


class LocalAgent:
    def __init__(self, *, model: str, base_url: str = DEFAULT_BASE_URL,
                 timeout: float = 120.0) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def chat_json(self, system: str, user: str) -> dict:
        """One local turn returning a JSON object. Raises LocalUnavailable when
        the batch should stop, LocalError for a single bad call."""
        try:
            resp = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}],
                    "format": _SCHEMA,
                    "stream": False,
                    "options": {"temperature": 0.2},
                },
                timeout=self.timeout,
            )
        except httpx.ConnectError as exc:
            raise LocalUnavailable(
                f"Cannot reach Ollama at {self.base_url}. Start it with "
                "`ollama serve`, or install it with `brew install ollama`."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LocalError(f"ollama timed out after {self.timeout:.0f}s") from exc

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = str(resp.json())
            except Exception:  # noqa: BLE001 — body is best-effort context
                pass
            if "not found" in body.lower():
                raise LocalUnavailable(
                    f"Model {self.model!r} is not pulled. Run "
                    f"`ollama pull {self.model}`."
                ) from exc
            raise LocalError(f"ollama HTTP {resp.status_code}: {body[:200]}") from exc

        content = (resp.json().get("message") or {}).get("content") or ""
        try:
            return json_reply.parse_object(content)
        except ValueError as exc:
            raise LocalError(str(exc)) from exc
