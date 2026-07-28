# claude_agent.py
"""One-shot JSON calls to the local `claude` CLI running headless.

Scoring used to go through the Vercel AI Gateway on a metered key, so a run died
with a 402 whenever the credit ran out. This drives the Claude Code subscription
already logged in on this machine instead — no API key, no per-call billing.
"""
from __future__ import annotations

import json
import subprocess

import json_reply

DEFAULT_MODEL = "claude-opus-5"
DEFAULT_EFFORT = "medium"

# Grading is text in, JSON out. Denying the tools keeps a run from wandering into
# the filesystem or the web, and from stalling on a permission prompt.
_DENIED_TOOLS = "Bash,Edit,Write,Read,Glob,Grep,WebFetch,WebSearch,Task,NotebookEdit"

# Markers meaning every remaining job would fail the same way — stop the batch
# instead of marking each one score_error.
_FATAL_MARKERS = ("usage limit", "rate limit", "not logged in", "/login",
                  "invalid api key", "authentication")


class ClaudeError(RuntimeError):
    """A single call failed."""


class ClaudeUnavailable(ClaudeError):
    """The agent can't run at all — not logged in, or out of subscription quota."""


def _classify(text: str, returncode: int) -> ClaudeError:
    lowered = (text or "").lower()
    if any(m in lowered for m in _FATAL_MARKERS):
        return ClaudeUnavailable(f"claude unavailable: {(text or '').strip()[:200]}")
    return ClaudeError(f"claude failed (exit {returncode}): {(text or '').strip()[:200]}")


class ClaudeAgent:
    def __init__(self, *, model: str = DEFAULT_MODEL, effort: str = DEFAULT_EFFORT,
                 timeout: float = 300.0) -> None:
        self.model = model
        self.effort = effort
        self.timeout = timeout

    def chat_json(self, system: str, user: str) -> dict:
        """One headless turn expected to return a JSON object. Raises ClaudeError
        with an actionable message, or ClaudeUnavailable when the batch should stop."""
        argv = [
            "claude", "-p",
            # A one-shot grading call must not inherit the interactive setup:
            # a Stop hook once replaced the model's reply with its own message,
            # and the harness context (CLAUDE.md, skills, MCP tools) cost ~43k
            # tokens per call. safe-mode drops both — measured 43,119 -> 0
            # cache-creation tokens — and unlike --bare it still uses the
            # logged-in subscription rather than requiring an API key.
            "--safe-mode",
            "--output-format", "json",
            "--model", self.model,
            "--effort", self.effort,
            "--disallowed-tools", _DENIED_TOOLS,
            "--system-prompt",
            system + "\n\nRespond with a single JSON object only. No markdown.",
        ]
        try:
            proc = subprocess.run(argv, input=user, capture_output=True, text=True,
                                  timeout=self.timeout)
        except FileNotFoundError as exc:
            raise ClaudeUnavailable(
                "`claude` CLI not found on PATH. Install Claude Code and run `claude` "
                "once to log in."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ClaudeError(f"claude timed out after {self.timeout:.0f}s") from exc

        if proc.returncode != 0:
            raise _classify(proc.stderr or proc.stdout, proc.returncode)

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise ClaudeError(
                f"claude returned non-JSON envelope: {proc.stdout[:200]!r}") from exc

        if envelope.get("is_error") or envelope.get("subtype") != "success":
            usage = envelope.get("usage") or {}
            spent = sum(int(usage.get(k) or 0) for k in (
                "input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens"))
            if envelope.get("terminal_reason") == "api_error" and spent == 0:
                # The request never reached the model and cost nothing, so this
                # is configuration rather than anything about this job. Every
                # remaining job would fail identically — stop the batch.
                raise ClaudeUnavailable(
                    f"claude rejected the request before calling the model "
                    f"(model={self.model!r}). Check HUNTER8_SCORER_MODEL: a "
                    f"provider-prefixed name like 'anthropic/claude-sonnet-4.5' "
                    f"is a gateway-era string the CLI does not accept.")
            raise _classify(
                str(envelope.get("result") or envelope.get("subtype")), proc.returncode)

        try:
            return json_reply.parse_object(envelope.get("result") or "")
        except ValueError as exc:
            raise ClaudeError(str(exc)) from exc
