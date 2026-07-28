import score
from db import Job


def _job(title, location="Remote, US", url=None):
    return Job(url=url or f"https://x/{title.replace(' ', '-')}", company="Acme", title=title, location=location,
               source="ats:greenhouse", ats="greenhouse", raw_text="desc")


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


def _screened(conn, title, score, url=None):
    job = _job(title, url=url)
    dbmod.insert_job(conn, job)
    stored = [j for j in dbmod.jobs_by_status(conn, "discovered")
              if j.url == job.url][0]
    dbmod.set_screen(conn, stored.id, status="screened_in", fit_score=score,
                     screen_reason="r")


def test_run_scoring_grades_screened_in_jobs(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "Machine Learning Engineer", 80)
    _screened(conn, "AI Engineer", 60)

    agent = _FakeAgent(verdict={
        "grade": "B", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "scored")) == 2


def test_run_scoring_marks_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 70)
    agent = _FakeAgent(exc=RuntimeError("agent down"))
    score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 1


def test_run_scoring_fails_fast_when_agent_unavailable(tmp_path):
    """Out of quota or logged out — every remaining job fails the same way."""
    import pytest
    from claude_agent import ClaudeUnavailable
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 70)
    agent = _FakeAgent(exc=ClaudeUnavailable("claude usage limit reached"))
    with pytest.raises(ClaudeUnavailable):
        score.run_scoring(conn, intent_md="intent", agent=agent)
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 0


def test_run_scoring_limit_takes_highest_fit_scores_first(tmp_path):
    """A capped run must spend the quota on the most promising jobs."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "Low Fit AI Engineer", 30, url="https://x/low")
    _screened(conn, "High Fit AI Engineer", 95, url="https://x/high")

    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    score.run_scoring(conn, intent_md="intent", agent=agent, limit=1)

    scored = dbmod.jobs_by_status(conn, "scored")
    assert len(scored) == 1 and scored[0].url == "https://x/high"
