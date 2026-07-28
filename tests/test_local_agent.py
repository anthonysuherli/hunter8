# tests/test_local_agent.py
import httpx
import pytest

import local_agent


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("err", request=None, response=self)

    def json(self):
        return self._payload


def _reply(content):
    return _Resp({"message": {"role": "assistant", "content": content}})


def _run(monkeypatch, resp, capture=None):
    def fake_post(url, json=None, timeout=None):
        if capture is not None:
            capture["url"], capture["json"] = url, json
        return resp

    monkeypatch.setattr(local_agent.httpx, "post", fake_post)
    return local_agent.LocalAgent(model="m").chat_json("sys", "user")


def test_chat_json_returns_parsed_object(monkeypatch):
    out = _run(monkeypatch, _reply('{"fit_score": 72, "reason": "good"}'))
    assert out["fit_score"] == 72


def test_chat_json_tolerates_fenced_reply(monkeypatch):
    out = _run(monkeypatch, _reply('```json\n{"fit_score": 10, "reason": "no"}\n```'))
    assert out["fit_score"] == 10


def test_posts_to_ollama_chat_endpoint(monkeypatch):
    capture = {}
    _run(monkeypatch, _reply('{"fit_score": 1, "reason": "r"}'), capture)
    assert capture["url"].endswith("/api/chat")
    assert capture["json"]["model"] == "m"
    assert capture["json"]["stream"] is False
    roles = [m["role"] for m in capture["json"]["messages"]]
    assert roles == ["system", "user"]


def test_connection_refused_is_unavailable(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(local_agent.httpx, "post", fake_post)
    with pytest.raises(local_agent.LocalUnavailable) as ei:
        local_agent.LocalAgent(model="m").chat_json("s", "u")
    assert "ollama" in str(ei.value).lower()


def test_missing_model_is_unavailable(monkeypatch):
    resp = _Resp({"error": "model 'm' not found, try pulling it first"}, status=404)
    with pytest.raises(local_agent.LocalUnavailable):
        _run(monkeypatch, resp)


def test_timeout_is_local_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        raise httpx.TimeoutException("slow")

    monkeypatch.setattr(local_agent.httpx, "post", fake_post)
    with pytest.raises(local_agent.LocalError):
        local_agent.LocalAgent(model="m").chat_json("s", "u")


def test_unparseable_reply_is_local_error(monkeypatch):
    with pytest.raises(local_agent.LocalError):
        _run(monkeypatch, _reply("I cannot answer that"))
