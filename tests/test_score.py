import score
from db import Job


def _job(title, location="Remote, US", url=None):
    return Job(url=url or f"https://x/{title.replace(' ', '-')}", company="Acme", title=title, location=location,
               source="ats:greenhouse", ats="greenhouse", raw_text="desc")


def test_passes_rules_accepts_ml_engineer_remote():
    ok, reason = score.passes_rules(_job("Machine Learning Engineer"))
    assert ok is True


def test_passes_rules_rejects_offtopic_title():
    ok, reason = score.passes_rules(_job("Sales Development Representative"))
    assert ok is False and "title" in reason.lower()


def test_passes_rules_rejects_internship():
    ok, reason = score.passes_rules(_job("ML Engineering Intern"))
    assert ok is False


def test_passes_rules_rejects_hft_core_cpp():
    ok, reason = score.passes_rules(_job("C++ Low-Latency Trading Engineer"))
    assert ok is False


def test_passes_rules_rejects_non_us_location():
    ok, reason = score.passes_rules(_job("ML Engineer", location="London, UK"))
    assert ok is False and "location" in reason.lower()


import db as dbmod


class _FakeAgent:
    def __init__(self, verdict=None, exc=None):
        self._verdict, self._exc = verdict, exc

    def chat_json(self, system, user):
        if self._exc:
            raise self._exc
        return self._verdict


def test_grade_job_parses_verdict():
    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "agentic + finance", "archetype": "ai-finance-startup",
        "comp_signal": "$180k", "red_flags": []})
    v = score.grade_job(_job("ML Engineer"), intent_md="intent", agent=agent)
    assert v.grade == "A" and v.archetype == "ai-finance-startup"


def test_run_scoring_filters_scores_and_flags_errors(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job("Machine Learning Engineer"))   # survives → scored
    dbmod.insert_job(conn, _job("Sales Rep", location="Remote US"))  # filtered_out
    from db import Job as J
    dbmod.insert_job(conn, J(url="https://x/err", company="Acme", title="AI Engineer",
                             location="Remote US", source="ats:greenhouse",
                             ats="greenhouse", raw_text="d"))

    agent = _FakeAgent(verdict={
        "grade": "B", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    # Making one job raise by swapping the agent per-call is overkill; assert the
    # happy path here and the error paths in the tests below.
    score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "scored")) == 2
    assert len(dbmod.jobs_by_status(conn, "filtered_out")) == 1


def test_run_scoring_marks_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job("AI Engineer"))
    agent = _FakeAgent(exc=RuntimeError("agent down"))
    score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 1


def test_run_scoring_fails_fast_when_agent_unavailable(tmp_path):
    """Out of quota or logged out — every remaining job fails the same way."""
    import pytest
    from claude_agent import ClaudeUnavailable
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job("AI Engineer"))
    agent = _FakeAgent(exc=ClaudeUnavailable("claude usage limit reached"))
    with pytest.raises(ClaudeUnavailable):
        score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 0
