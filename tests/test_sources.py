# tests/test_sources.py
import json
from pathlib import Path

import sources

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_parse_greenhouse():
    jobs = sources.parse_greenhouse(_load("greenhouse.json"), company="Acme")
    assert len(jobs) == 1
    j = jobs[0]
    assert j.company == "Acme"
    assert j.title == "Research Engineer, Agents"
    assert j.location == "San Francisco, CA"
    assert j.url == "https://job-boards.greenhouse.io/acme/jobs/4017331008"
    assert j.source == "ats:greenhouse" and j.ats == "greenhouse"
    assert "agentic" in j.raw_text.lower()


def test_parse_ashby():
    jobs = sources.parse_ashby(_load("ashby.json"), company="Acme")
    j = jobs[0]
    assert j.title == "ML Engineer, Applied"
    assert j.url == "https://jobs.ashbyhq.com/acme/abc-123"
    assert j.ats == "ashby"


def test_parse_lever():
    jobs = sources.parse_lever(_load("lever.json"), company="Acme")
    j = jobs[0]
    assert j.title == "Staff ML Engineer"
    assert j.location == "New York, NY"
    assert j.url == "https://jobs.lever.co/acme/def-456"
    assert j.ats == "lever"


def test_fetch_greenhouse_builds_url_and_parses(monkeypatch):
    payload = _load("greenhouse.json")

    class FakeResp:
        def raise_for_status(self): pass
        def json(self): return payload

    called = {}

    def fake_get(url, timeout):
        called["url"] = url
        return FakeResp()

    monkeypatch.setattr(sources.httpx, "get", fake_get)
    jobs = sources.fetch_ats("greenhouse", board="acme", company="Acme")
    assert "boards-api.greenhouse.io/v1/boards/acme/jobs" in called["url"]
    assert jobs[0].company == "Acme"


def test_fetch_ats_bad_ats_raises():
    import pytest
    with pytest.raises(ValueError, match="unsupported ATS"):
        sources.fetch_ats("taleo", board="x", company="X")


def test_parse_workday_detail_uses_start_date_not_relative_posted_on():
    """postedOn is "Posted 11 Days Ago" — useless to --since-days. startDate is
    a real day, so that is what must land in posted_at."""
    j = sources.parse_workday_detail(_load("workday_detail.json"), company="Acme",
                                     url="https://acme.wd5.myworkdayjobs.com/External/job/x")
    assert j.title == "Quantitative Research - Client Analytics"
    assert j.posted_at == "2026-07-17T00:00:00+00:00"
    assert j.ats == "workday" and j.source == "ats:workday"
    assert j.location.startswith("New York")


def test_parse_workday_detail_strips_html():
    j = sources.parse_workday_detail(_load("workday_detail.json"), company="Acme",
                                     url="https://x/y")
    assert "<p>" not in j.raw_text and "<b>" not in j.raw_text
    assert "agentic" in j.raw_text and "LLM evaluation" in j.raw_text


def test_parse_workday_detail_skips_untitled_payload():
    assert sources.parse_workday_detail({}, company="Acme", url="https://x/y") is None


def test_parse_workday_detail_tolerates_missing_start_date():
    payload = {"jobPostingInfo": {"title": "T", "startDate": "Posted Today"}}
    j = sources.parse_workday_detail(payload, company="Acme", url="https://x/y")
    assert j.posted_at is None


def test_parse_eightfold_converts_unix_timestamp():
    jobs = sources.parse_eightfold(_load("eightfold.json"), company="Millennium")
    assert len(jobs) == 2
    j = jobs[0]
    assert j.title == "Senior Quantitative Developer"
    assert j.url == "https://mlp.eightfold.ai/careers/job/755957773457"
    assert j.posted_at == "2026-07-27T00:00:00+00:00"
    assert j.ats == "eightfold"
    assert "Information Technology" in j.raw_text


def test_parse_eightfold_falls_back_to_id_when_url_missing():
    jobs = sources.parse_eightfold(_load("eightfold.json"), company="Millennium")
    assert jobs[1].url == "eightfold:999" and jobs[1].posted_at is None


def test_fetch_ats_rejects_malformed_compound_boards():
    import pytest
    with pytest.raises(ValueError, match="tenant/server/site"):
        sources.fetch_workday(board="ms", company="MS")
    with pytest.raises(ValueError, match="sub/domain"):
        sources.fetch_eightfold(board="mlp", company="Millennium")


def test_fetch_eightfold_advances_by_actual_page_size(monkeypatch):
    """Eightfold caps the page below the requested `num`. Stepping by the
    requested size skipped every job in the gap — Millennium yielded 50 of 238."""
    pages = {0: ["a", "b"], 2: ["c"], 3: []}
    seen = []

    class _Resp:
        def __init__(self, names): self._names = names
        def raise_for_status(self): pass
        def json(self):
            return {"positions": [
                {"id": n, "name": n, "location": "NYC", "t_create": 1785110400,
                 "canonicalPositionUrl": f"https://x/{n}"} for n in self._names]}

    class _Client:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url, params=None):
            seen.append(params["start"])
            return _Resp(pages.get(params["start"], []))

    monkeypatch.setattr(sources.httpx, "Client", lambda **kw: _Client())
    jobs = sources.fetch_eightfold(board="mlp/mlp.com", company="Millennium")
    assert [j.title for j in jobs] == ["a", "b", "c"]
    assert seen == [0, 2, 3]
