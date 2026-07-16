import json

import pytest

import gateway


class _FakeMessage:
    def __init__(self, content): self.content = content


class _FakeChoice:
    def __init__(self, content): self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content): self.choices = [_FakeChoice(content)]


def test_chat_json_parses_object(monkeypatch):
    def fake_create(**kwargs):
        return _FakeCompletion(json.dumps({"grade": "A"}))

    client = gateway.Gateway(api_key="k", model="m")
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    out = client.chat_json("sys", "user")
    assert out["grade"] == "A"


def test_chat_json_raises_clear_message_on_402(monkeypatch):
    import openai

    def fake_create(**kwargs):
        raise openai.APIStatusError(
            "insufficient_funds", response=_Resp(402), body=None)

    class _Resp:
        def __init__(self, code):
            self.status_code = code
            self.headers = {}
        request = None

    client = gateway.Gateway(api_key="k", model="m")
    monkeypatch.setattr(client._client.chat.completions, "create", fake_create)
    with pytest.raises(gateway.GatewayError) as ei:
        client.chat_json("sys", "user")
    assert "credit" in str(ei.value).lower()
