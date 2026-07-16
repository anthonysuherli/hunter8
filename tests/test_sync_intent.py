# tests/test_sync_intent.py
import sync_intent


def test_render_intent_groups_by_kb():
    profile = [{"title": "Profile", "content": "agentic × quant", "category": "profile"}]
    positioning = [{"title": "Buy-side", "content": "co-primary", "category": "pos"}]
    md = sync_intent.render_intent(profile, positioning)
    assert "# Candidate Intent" in md
    assert "agentic × quant" in md
    assert "co-primary" in md


def test_fetch_findings_builds_request(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return [{"title": "T", "content": "C", "category": "x"}]

    def fake_get(url, headers, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["headers"] = headers
        return FakeResp()

    monkeypatch.setattr(sync_intent.httpx, "get", fake_get)
    rows = sync_intent.fetch_findings(
        "https://sb.example.co", "svc-key", "kb-123")
    assert rows[0]["title"] == "T"
    assert "/rest/v1/findings" in captured["url"]
    assert captured["params"]["kb_id"] == "eq.kb-123"
    assert captured["headers"]["apikey"] == "svc-key"
