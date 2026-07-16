# tests/test_triage.py
import openpyxl

import db as dbmod
import triage
from db import Job


def _tracker(tmp_path):
    wb = openpyxl.Workbook()
    wb.create_sheet("Profile").append(["key", "value"])
    ws = wb.create_sheet("Apply Tracker")
    wb.remove(wb["Sheet"])
    headers = ["Priority", "Status", "Date applied", "My notes", "Company", "Role",
               "City", "Region", "Why it fits", "Flags", "Link", "Verification",
               "Tailored Resume Path"]
    ws.append(headers)
    p = tmp_path / "tracker.xlsx"
    wb.save(p)
    return p


def _scored_job(conn, title="ML Engineer", grade="A"):
    if not dbmod.insert_job(conn, Job(url="https://job-boards.greenhouse.io/acme/jobs/1",
                               company="Acme", title=title, location="Remote US",
                               source="ats:greenhouse", ats="greenhouse", raw_text="d")):
        return
    j = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, j.id, status="scored", grade=grade, reasoning="fit",
                    archetype="lab", comp_signal="$180k", red_flags="[]")


def test_apply_decision_approve_writes_tracker_row(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]

    triage.apply_decision(conn, job, "a", tracker)

    assert len(dbmod.jobs_by_status(conn, "approved")) == 1
    wb = openpyxl.load_workbook(tracker)
    ws = wb["Apply Tracker"]
    assert ws.cell(ws.max_row, 5).value == "Acme"


def test_apply_decision_skip_and_snooze(tmp_path):
    tracker = _tracker(tmp_path)
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    _scored_job(conn)
    job = dbmod.jobs_by_status(conn, "scored")[0]
    triage.apply_decision(conn, job, "s", tracker)
    assert len(dbmod.jobs_by_status(conn, "skipped")) == 1

    _scored_job(conn)  # different call reuses same URL → deduped; insert a new one
    dbmod.insert_job(conn, Job(url="https://x/2", company="B", title="AI Engineer",
                               location="Remote US", source="ats:greenhouse",
                               ats="greenhouse", raw_text="d"))
    j2 = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, j2.id, status="scored", grade="B", reasoning="",
                    archetype="", comp_signal="", red_flags="[]")
    triage.apply_decision(conn, dbmod.jobs_by_status(conn, "scored")[0], "z", tracker)
    assert len(dbmod.jobs_by_status(conn, "snoozed")) == 1


def test_priority_from_grade():
    assert triage.priority_from_grade("A").startswith("A")
    assert triage.priority_from_grade("B").startswith("B")
    assert triage.priority_from_grade("C").startswith("C")
