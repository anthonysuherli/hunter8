# tests/test_rubric.py
from pathlib import Path

import rubric


class _FakeAgent:
    """Records how many times Claude was asked to distil."""

    def __init__(self, body="HARD CONSTRAINTS: US only."):
        self.body, self.calls = body, 0

    def chat_json(self, system, user):
        self.calls += 1
        return {"rubric": self.body}


def _paths(tmp_path, intent_text="profile v1"):
    intent = tmp_path / "intent.md"
    intent.write_text(intent_text, encoding="utf-8")
    return intent, tmp_path / "rubric.md"


def test_builds_rubric_on_first_run(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    body = rubric.load_or_build(intent, rub, agent)
    assert "US only" in body
    assert agent.calls == 1
    assert rub.exists()


def test_reuses_cached_rubric_when_intent_unchanged(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    rubric.load_or_build(intent, rub, agent)
    rubric.load_or_build(intent, rub, agent)
    assert agent.calls == 1


def test_regenerates_when_intent_changes(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    rubric.load_or_build(intent, rub, agent)
    intent.write_text("profile v2 — now targeting FDE roles", encoding="utf-8")
    rubric.load_or_build(intent, rub, agent)
    assert agent.calls == 2


def test_human_block_survives_regeneration(tmp_path):
    intent, rub = _paths(tmp_path)
    agent = _FakeAgent()
    rubric.load_or_build(intent, rub, agent)

    text = rub.read_text(encoding="utf-8")
    edited = text.replace(
        f"{rubric.HUMAN_BEGIN}\n\n\n{rubric.HUMAN_END}",
        f"{rubric.HUMAN_BEGIN}\n\nNever surface contract roles.\n\n{rubric.HUMAN_END}",
    )
    rub.write_text(edited, encoding="utf-8")

    intent.write_text("profile v2", encoding="utf-8")
    body = rubric.load_or_build(intent, rub, agent)
    assert "Never surface contract roles." in body
    assert "Never surface contract roles." in rub.read_text(encoding="utf-8")
