# tests/test_calibrate.py
import calibrate
import db as dbmod
from db import Job


def test_agreement_reports_recall_per_threshold():
    #      Claude grade, local fit_score
    rows = [("A", 90), ("A", 70), ("B", 60), ("C", 10), ("C", 20)]
    table = {r["threshold"]: r for r in calibrate.agreement(rows)}

    at70 = table[70]
    assert at70["a_recall"] == 1.0        # both A's are >= 70
    assert at70["promoted_fraction"] == 0.4   # 2 of 5

    at80 = table[80]
    assert at80["a_recall"] == 0.5        # the A at 70 would be lost


def test_recommended_threshold_is_highest_with_full_a_recall():
    rows = [("A", 90), ("A", 70), ("C", 10)]
    assert calibrate.recommend(calibrate.agreement(rows)) == 70


def test_collect_does_not_mutate_job_status(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, Job(url="https://x/1", company="Acme",
                               title="ML Engineer", location="NYC",
                               source="ats:greenhouse", ats="greenhouse",
                               raw_text="d"))
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, job.id, status="scored", grade="A", reasoning="r",
                    archetype="lab", comp_signal="", red_flags="[]")

    class _Agent:
        def chat_json(self, system, user):
            return {"fit_score": 88, "reason": "r"}

    rows = calibrate.collect(conn, rubric_text="r", agent=_Agent())
    assert rows == [("A", 88)]
    assert len(dbmod.jobs_by_status(conn, "scored")) == 1   # untouched
    assert dbmod.jobs_by_status(conn, "scored")[0].fit_score is None
