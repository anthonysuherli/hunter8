import score
from db import Job


def _job(title, location="Remote, US"):
    return Job(url="https://x/1", company="Acme", title=title, location=location,
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
