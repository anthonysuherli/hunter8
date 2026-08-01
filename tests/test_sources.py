# tests/test_sources.py
import json
from pathlib import Path

import sources
from db import Job
from hunter8_core import JobPosting

FIX = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIX / name).read_text())


def test_parse_greenhouse():
    jobs = sources.parse_greenhouse(_load("greenhouse.json"), company="Acme")
    assert len(jobs) == 1
    assert isinstance(jobs[0], JobPosting)
    j = jobs[0]
    assert j.company == "Acme"
    assert j.title == "Research Engineer, Agents"
    assert j.location == "San Francisco, CA"
    assert j.url == "https://job-boards.greenhouse.io/acme/jobs/4017331008"
    assert j.source == "ats:greenhouse" and j.ats == "greenhouse"
    assert "agentic" in j.description.lower()


def test_parse_ashby():
    jobs = sources.parse_ashby(_load("ashby.json"), company="Acme")
    assert isinstance(jobs[0], JobPosting)
    j = jobs[0]
    assert j.title == "ML Engineer, Applied"
    assert j.url == "https://jobs.ashbyhq.com/acme/abc-123"
    assert j.ats == "ashby"


def test_parse_lever():
    jobs = sources.parse_lever(_load("lever.json"), company="Acme")
    assert isinstance(jobs[0], JobPosting)
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
    assert isinstance(j, JobPosting)
    assert j.title == "Quantitative Research - Client Analytics"
    assert j.posted_at == "2026-07-17T00:00:00+00:00"
    assert j.ats == "workday" and j.source == "ats:workday"
    assert j.location.startswith("New York")


def test_parse_workday_detail_strips_html():
    j = sources.parse_workday_detail(_load("workday_detail.json"), company="Acme",
                                     url="https://x/y")
    assert "<p>" not in j.description and "<b>" not in j.description
    assert "agentic" in j.description and "LLM evaluation" in j.description


def test_parse_workday_detail_skips_untitled_payload():
    assert sources.parse_workday_detail({}, company="Acme", url="https://x/y") is None


def test_parse_workday_detail_tolerates_missing_start_date():
    payload = {"jobPostingInfo": {"title": "T", "startDate": "Posted Today"}}
    j = sources.parse_workday_detail(payload, company="Acme", url="https://x/y")
    assert j.posted_at is None


def test_parse_eightfold_converts_unix_timestamp():
    jobs = sources.parse_eightfold(_load("eightfold.json"), company="Millennium")
    assert len(jobs) == 2
    assert isinstance(jobs[0], JobPosting)
    j = jobs[0]
    assert j.title == "Senior Quantitative Developer"
    assert j.url == "https://mlp.eightfold.ai/careers/job/755957773457"
    assert j.posted_at == "2026-07-27T00:00:00+00:00"
    assert j.ats == "eightfold"
    assert "Information Technology" in j.description


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


def test_lever_posted_at_is_stored_as_iso_not_an_epoch():
    """Lever returns createdAt in milliseconds. Stored raw, it sorts below every
    ISO cutoff as a string, so every --since-days run silently dropped all 301
    Lever jobs."""
    payload = [{"hostedUrl": "https://jobs.lever.co/acme/1", "text": "AI Engineer",
                "categories": {"location": "NYC"}, "createdAt": 1784811226989,
                "descriptionPlain": "d"}]
    jobs = sources.parse_lever(payload, company="Acme")
    assert jobs[0].posted_at == "2026-07-23T12:53:46.989000+00:00"
    assert jobs[0].posted_at > "2026-07-01T00:00:00+00:00"   # sorts correctly now


def test_lever_missing_created_at_is_none_not_a_crash():
    payload = [{"hostedUrl": "https://jobs.lever.co/acme/2", "text": "T",
                "categories": {}, "descriptionPlain": ""}]
    assert sources.parse_lever(payload, company="Acme")[0].posted_at is None


def test_repair_converts_epoch_rows_and_leaves_iso_alone(tmp_path):
    import db as dbmod
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/epoch", company="Palantir", title="T",
                               location="NYC", source="ats:lever", ats="lever",
                               posted_at="1784811226989", raw_text="d"))
    dbmod.insert_job(conn, Job(url="https://x/iso", company="Acme", title="T",
                               location="NYC", source="ats:greenhouse",
                               ats="greenhouse",
                               posted_at="2026-07-23T00:00:00+00:00", raw_text="d"))

    assert sources.repair_lever_posted_at(conn) == 1

    by_url = {j.url: j for j in dbmod.jobs_by_status(conn, "discovered")}
    assert by_url["https://x/epoch"].posted_at == "2026-07-23T12:53:46.989000+00:00"
    assert by_url["https://x/iso"].posted_at == "2026-07-23T00:00:00+00:00"

    assert sources.repair_lever_posted_at(conn) == 0     # idempotent


def test_lever_out_of_range_created_at_yields_none_not_a_crash():
    """int() accepts an absurd number that datetime.fromtimestamp then rejects
    with OSError. Uncaught, one malformed posting cost the entire board fetch."""
    payload = [{"hostedUrl": "https://jobs.lever.co/acme/3", "text": "T",
                "categories": {}, "createdAt": 99999999999999999999,
                "descriptionPlain": ""}]
    jobs = sources.parse_lever(payload, company="Acme")
    assert len(jobs) == 1                    # the board still parses
    assert jobs[0].posted_at is None         # just without a date


def test_repair_skips_an_out_of_range_value_and_keeps_going(tmp_path):
    """One unconvertible row must not abort the repair for the rest."""
    import db as dbmod
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/bad", company="Bad", title="T",
                               location="NYC", source="ats:lever", ats="lever",
                               posted_at="99999999999999999999", raw_text="d"))
    dbmod.insert_job(conn, Job(url="https://x/good", company="Good", title="T",
                               location="NYC", source="ats:lever", ats="lever",
                               posted_at="1784811226989", raw_text="d"))

    assert sources.repair_lever_posted_at(conn) == 1      # the good one converted

    by_url = {j.url: j for j in dbmod.jobs_by_status(conn, "discovered")}
    assert by_url["https://x/good"].posted_at == "2026-07-23T12:53:46.989000+00:00"
    assert by_url["https://x/bad"].posted_at == "99999999999999999999"   # left as-is
