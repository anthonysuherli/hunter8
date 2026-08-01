import score
from db import Job


def _job(title, location="Remote, US", url=None):
    return Job(url=url or f"https://x/{title.replace(' ', '-')}", company="Acme", title=title, location=location,
               source="ats:greenhouse", ats="greenhouse", raw_text="desc")


import db as dbmod


class _FakeAgent:
    def __init__(self, verdict=None, exc=None, cost=None):
        self._verdict, self._exc = verdict, exc
        self.last_cost_usd = cost
        self.total_cost_usd = 0.0
        self.calls = 0

    def chat_json(self, system, user):
        if self._exc:
            raise self._exc
        return self._verdict


def test_grade_job_parses_verdict():
    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "agentic + finance", "archetype": "ai-finance-startup",
        "comp_signal": "$180k", "red_flags": []})
    v = score.grade_job(
        _job("ML Engineer").to_posting(),
        intent_md="intent",
        agent=agent,
    )
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
    score.run_scoring(conn, intent_md="intent", agent=agent, brief_sha="test")
    assert len(dbmod.jobs_by_status(conn, "scored")) == 2


def test_run_scoring_marks_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 70)
    agent = _FakeAgent(exc=RuntimeError("agent down"))
    score.run_scoring(conn, intent_md="intent", agent=agent, brief_sha="test")
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
        score.run_scoring(conn, intent_md="intent", agent=agent, brief_sha="test")
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 0


def test_run_scoring_since_filters_on_posting_date(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "Old AI Engineer", 90, url="https://x/old")
    _screened(conn, "New AI Engineer", 80, url="https://x/new")
    conn.execute("UPDATE jobs SET posted_at='2026-01-01T00:00:00+00:00' WHERE url='https://x/old'")
    conn.execute("UPDATE jobs SET posted_at='2026-07-27T00:00:00+00:00' WHERE url='https://x/new'")
    conn.commit()

    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    score.run_scoring(conn, intent_md="intent", agent=agent, brief_sha="test",
                      posted_since="2026-07-21T00:00:00+00:00")

    scored = dbmod.jobs_by_status(conn, "scored")
    assert [j.url for j in scored] == ["https://x/new"]


def test_run_scoring_limit_takes_highest_fit_scores_first(tmp_path):
    """A capped run must spend the quota on the most promising jobs."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "Low Fit AI Engineer", 30, url="https://x/low")
    _screened(conn, "High Fit AI Engineer", 95, url="https://x/high")

    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []})
    score.run_scoring(conn, intent_md="intent", agent=agent, limit=1, brief_sha="test")

    scored = dbmod.jobs_by_status(conn, "scored")
    assert len(scored) == 1 and scored[0].url == "https://x/high"


def test_run_scoring_persists_the_cost_of_each_call(tmp_path):
    """Cost has to land on the row, not just in the agent, or the question
    "what did that report cost?" stays unanswerable after the process exits."""
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 80)
    agent = _FakeAgent(verdict={
        "grade": "A", "reasoning": "ok", "archetype": "lab",
        "comp_signal": "", "red_flags": []}, cost=0.0084)
    score.run_scoring(conn, intent_md="intent", agent=agent, brief_sha="test")
    assert dbmod.jobs_by_status(conn, "scored")[0].cost_usd == 0.0084
    assert dbmod.total_cost(conn) == (0.0084, 1)


def test_run_scoring_prices_a_failed_grade(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 70)
    agent = _FakeAgent(exc=RuntimeError("bad json"), cost=0.005)
    score.run_scoring(conn, intent_md="intent", agent=agent, brief_sha="test")
    assert dbmod.jobs_by_status(conn, "score_error")[0].cost_usd == 0.005


def test_run_scoring_records_the_brief_sha_on_every_grade(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/1", company="Acme",
                               title="AI Engineer", location="NYC",
                               source="ats:greenhouse", ats="greenhouse",
                               raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=80,
                     screen_reason="ok")

    score.run_scoring(conn, intent_md="brief", agent=_FakeAgent(verdict={
        "grade": "A", "reasoning": "r", "archetype": "lab",
        "comp_signal": "", "red_flags": []}),
                      brief_sha="sha-under-test")

    shas = [r[0] for r in conn.execute("SELECT brief_sha FROM grade_history")]
    assert shas == ["sha-under-test"]


def test_a_failed_grade_still_records_provenance(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/2", company="Acme",
                               title="AI Engineer", location="NYC",
                               source="ats:greenhouse", ats="greenhouse",
                               raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_screen(conn, job.id, status="screened_in", fit_score=80,
                     screen_reason="ok")

    score.run_scoring(conn, intent_md="brief", agent=_FakeAgent(exc=ValueError("bad json"), cost=0.01),
                      brief_sha="sha-under-test")

    rows = conn.execute(
        "SELECT grade, brief_sha FROM grade_history").fetchall()
    assert [tuple(r) for r in rows] == [(None, "sha-under-test")]


def test_invalid_grade_is_visible_score_error(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 90)
    score.run_scoring(
        conn,
        intent_md="brief",
        agent=_FakeAgent(verdict={
            "grade": "A+",
            "reasoning": "r",
            "archetype": "lab",
            "comp_signal": "",
            "red_flags": [],
        }),
        brief_sha="test",
    )
    errored = dbmod.jobs_by_status(conn, "score_error")
    assert len(errored) == 1
    assert "grade" in errored[0].reasoning


def test_string_red_flags_are_not_split_into_characters(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _screened(conn, "AI Engineer", 90)
    score.run_scoring(
        conn,
        intent_md="brief",
        agent=_FakeAgent(verdict={
            "grade": "A",
            "reasoning": "r",
            "archetype": "lab",
            "comp_signal": "",
            "red_flags": "sponsorship unknown",
        }),
        brief_sha="test",
    )
    assert len(dbmod.jobs_by_status(conn, "score_error")) == 1
