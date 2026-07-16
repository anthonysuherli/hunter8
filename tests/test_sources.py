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
