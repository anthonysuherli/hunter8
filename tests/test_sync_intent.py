# tests/test_sync_intent.py
import pytest

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


def test_fetch_findings_excludes_retired(monkeypatch):
    """Retired findings carry a non-null invalidated_at — they must not reach intent.md."""
    captured = {}

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return []

    def fake_get(url, headers, params, timeout):
        captured["params"] = params
        return FakeResp()

    monkeypatch.setattr(sync_intent.httpx, "get", fake_get)
    sync_intent.fetch_findings("https://sb.example.co", "svc-key", "kb-123")
    assert captured["params"]["invalidated_at"] == "is.null"


def test_extract_human_empty_for_fresh_file(tmp_path):
    assert sync_intent.extract_human(tmp_path / "intent.md") == ""


def test_extract_human_round_trips_through_render(tmp_path):
    """A sync must not eat the hand-authored block: render → write → extract → same text."""
    human = "## Role shapes\n\n5. Forward-deployed engineer"
    out = tmp_path / "intent.md"
    out.write_text(sync_intent.render_intent([], [], human), encoding="utf-8")
    assert sync_intent.extract_human(out) == human


def test_extract_human_refuses_file_without_markers(tmp_path):
    out = tmp_path / "intent.md"
    out.write_text("# Candidate Intent\n\nhand-written, no markers\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="BEGIN human"):
        sync_intent.extract_human(out)
