# tests/test_claude_agent.py
import json
import subprocess

import pytest

import claude_agent


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _envelope(result, **over):
    body = {"is_error": False, "subtype": "success", "result": result}
    body.update(over)
    return json.dumps(body)


def _run(monkeypatch, proc, capture=None):
    def fake_run(argv, **kwargs):
        if capture is not None:
            capture["argv"], capture["input"] = argv, kwargs.get("input")
        return proc

    monkeypatch.setattr(claude_agent.subprocess, "run", fake_run)
    return claude_agent.ClaudeAgent().chat_json("sys", "user")


def test_chat_json_parses_object(monkeypatch):
    out = _run(monkeypatch, _Proc(stdout=_envelope('{"grade": "A"}')))
    assert out["grade"] == "A"


def test_chat_json_strips_markdown_fence(monkeypatch):
    out = _run(monkeypatch, _Proc(stdout=_envelope('```json\n{"grade": "B"}\n```')))
    assert out["grade"] == "B"


def test_chat_json_extracts_object_from_prose(monkeypatch):
    out = _run(monkeypatch, _Proc(stdout=_envelope('Here you go: {"grade": "C"} — done')))
    assert out["grade"] == "C"


def test_invokes_headless_claude_with_prompt_on_stdin(monkeypatch):
    """No API key anywhere in the invocation — auth is the logged-in subscription."""
    capture = {}
    _run(monkeypatch, _Proc(stdout=_envelope('{"grade": "A"}')), capture)
    argv = capture["argv"]
    assert argv[0] == "claude" and "-p" in argv
    # Without this the call inherits the user's hooks, skills and CLAUDE.md —
    # a Stop hook's message once came back as the model's reply.
    assert "--safe-mode" in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == claude_agent.DEFAULT_MODEL
    assert capture["input"] == "user"


def test_usage_limit_is_unavailable_not_a_plain_error(monkeypatch):
    proc = _Proc(stderr="Claude usage limit reached", returncode=1)
    with pytest.raises(claude_agent.ClaudeUnavailable):
        _run(monkeypatch, proc)


def test_ordinary_failure_is_a_plain_error(monkeypatch):
    proc = _Proc(stderr="something broke", returncode=1)
    with pytest.raises(claude_agent.ClaudeError) as ei:
        _run(monkeypatch, proc)
    assert not isinstance(ei.value, claude_agent.ClaudeUnavailable)


def test_missing_cli_is_unavailable(monkeypatch):
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("claude")

    monkeypatch.setattr(claude_agent.subprocess, "run", fake_run)
    with pytest.raises(claude_agent.ClaudeUnavailable) as ei:
        claude_agent.ClaudeAgent().chat_json("sys", "user")
    assert "not found" in str(ei.value).lower()


def test_timeout_raises_claude_error(monkeypatch):
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(claude_agent.subprocess, "run", fake_run)
    with pytest.raises(claude_agent.ClaudeError):
        claude_agent.ClaudeAgent().chat_json("sys", "user")


def test_error_envelope_raises(monkeypatch):
    proc = _Proc(stdout=_envelope("nope", is_error=True, subtype="error_during_execution"))
    with pytest.raises(claude_agent.ClaudeError):
        _run(monkeypatch, proc)


def test_config_error_stops_the_batch(monkeypatch):
    """A request rejected before reaching the model — a bad model name, say —
    costs nothing and will fail identically for every job, so stop the batch
    instead of marking hundreds of jobs score_error one at a time."""
    body = json.dumps({
        "is_error": True, "subtype": "error", "terminal_reason": "api_error",
        "result": "", "usage": {"input_tokens": 0, "output_tokens": 0,
                                "cache_creation_input_tokens": 0,
                                "cache_read_input_tokens": 0},
    })
    with pytest.raises(claude_agent.ClaudeUnavailable) as ei:
        _run(monkeypatch, _Proc(stdout=body))
    assert "HUNTER8_SCORER_MODEL" in str(ei.value)


def test_api_error_that_burned_tokens_is_per_job(monkeypatch):
    """Tokens were spent, so the model saw it — that is about this job's
    content, not the configuration. Mark it and keep going."""
    body = json.dumps({
        "is_error": True, "subtype": "error", "terminal_reason": "api_error",
        "result": "overloaded", "usage": {"input_tokens": 1200, "output_tokens": 0,
                                          "cache_creation_input_tokens": 0,
                                          "cache_read_input_tokens": 0},
    })
    with pytest.raises(claude_agent.ClaudeError) as ei:
        _run(monkeypatch, _Proc(stdout=body))
    assert not isinstance(ei.value, claude_agent.ClaudeUnavailable)


def test_unparseable_result_raises(monkeypatch):
    with pytest.raises(claude_agent.ClaudeError) as ei:
        _run(monkeypatch, _Proc(stdout=_envelope("not json at all")))
    assert "no json object" in str(ei.value).lower()


def _cost_envelope(**over):
    env = {"subtype": "success", "result": '{"grade": "A"}',
           "total_cost_usd": 0.0084}
    env.update(over)
    return env


def test_agent_records_cost_per_call_and_running_total(monkeypatch):
    import json as _json
    import claude_agent as ca

    class _Proc:
        returncode = 0
        stderr = ""
        def __init__(self, out): self.stdout = out

    outs = iter([_json.dumps(_cost_envelope()), _json.dumps(_cost_envelope(total_cost_usd=0.02))])
    monkeypatch.setattr(ca.subprocess, "run",
                        lambda *a, **k: _Proc(next(outs)))
    agent = ca.ClaudeAgent()
    agent.chat_json("s", "u")
    assert agent.last_cost_usd == 0.0084
    agent.chat_json("s", "u")
    assert agent.last_cost_usd == 0.02
    assert round(agent.total_cost_usd, 4) == 0.0284 and agent.calls == 2


def test_agent_cost_is_none_when_envelope_omits_it(monkeypatch):
    import json as _json
    import claude_agent as ca

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = _json.dumps({"subtype": "success", "result": '{"grade": "A"}'})

    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    agent = ca.ClaudeAgent()
    agent.chat_json("s", "u")
    assert agent.last_cost_usd is None
    assert agent.total_cost_usd == 0.0 and agent.calls == 1


def test_agent_prices_a_failed_call(monkeypatch):
    """A malformed reply still burned tokens; the total must include it."""
    import json as _json
    import pytest
    import claude_agent as ca

    class _Proc:
        returncode = 0
        stderr = ""
        stdout = _json.dumps(_cost_envelope(result="not json at all"))

    monkeypatch.setattr(ca.subprocess, "run", lambda *a, **k: _Proc())
    agent = ca.ClaudeAgent()
    with pytest.raises(ca.ClaudeError):
        agent.chat_json("s", "u")
    assert agent.last_cost_usd == 0.0084 and agent.calls == 1
