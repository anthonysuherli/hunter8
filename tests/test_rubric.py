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


def _agent(payload):
    class _A:
        def __init__(self): self.systems = []
        def chat_json(self, system, user):
            self.systems.append(system)
            return payload
    return _A()


def test_grade_profile_writes_brief_with_its_own_title(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("full profile; work authorization details here")
    out = tmp_path / "brief.md"
    body = "## Hard constraints\nWork authorization rules preserved.\n## Evidence\nRAGAS harness."
    text = rubric.load_or_build(intent, out, _agent({"brief": body}),
                                profile=rubric.GRADE)
    assert text.startswith("# Grading Brief")
    assert "RAGAS harness" in text and out.exists()


def test_grade_profile_refuses_a_brief_that_lost_the_sponsorship_rule(tmp_path):
    """Losing this once invalidated every grade in the corpus. Fail, don't write."""
    import pytest
    intent = tmp_path / "intent.md"
    intent.write_text("full profile")
    out = tmp_path / "brief.md"
    body = "## Hard constraints\nWants NYC. Comp floor $200k.\n## Evidence\nAgents."
    with pytest.raises(SystemExit, match="dropped required term"):
        rubric.load_or_build(intent, out, _agent({"brief": body}),
                             profile=rubric.GRADE)
    assert not out.exists()   # nothing half-written to be silently reused


def test_grade_profile_uses_the_grading_system_prompt(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("profile")
    agent = _agent({"brief": "Work authorization rules kept. Evidence: agents."})
    rubric.load_or_build(intent, tmp_path / "brief.md", agent,
                         profile=rubric.GRADE)
    assert "grading brief" in agent.systems[0]
    assert "VERBATIM" in agent.systems[0]


def test_screen_profile_is_still_the_default(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("profile")
    agent = _agent({"rubric": "disqualifiers"})
    text = rubric.load_or_build(intent, tmp_path / "rubric.md", agent)
    assert text.startswith("# Screening Rubric")
    assert "screening rubric" in agent.systems[0]


def test_brief_is_cached_on_the_intent_hash(tmp_path):
    intent = tmp_path / "intent.md"
    intent.write_text("profile")
    out = tmp_path / "brief.md"
    agent = _agent({"brief": "Work authorization preserved. Evidence."})
    rubric.load_or_build(intent, out, agent, profile=rubric.GRADE)
    rubric.load_or_build(intent, out, agent, profile=rubric.GRADE)
    assert len(agent.systems) == 1   # second call served from cache
