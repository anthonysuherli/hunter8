# tests/test_db.py
import db as dbmod


def _job(url="https://x/1", company="Acme", title="ML Engineer"):
    return dbmod.Job(url=url, company=company, title=title,
                     location="Remote US", source="ats:greenhouse", ats="greenhouse",
                     raw_text="desc")


def test_init_and_insert(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert dbmod.insert_job(conn, _job()) is True


def test_insert_is_deduped_on_url(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    assert dbmod.insert_job(conn, _job()) is True
    assert dbmod.insert_job(conn, _job()) is False
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def test_set_score_moves_to_scored(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_score(conn, job.id, status="scored", grade="A",
                    reasoning="great fit", archetype="ai-finance-startup",
                    comp_signal="$180k+", red_flags="")
    scored = dbmod.jobs_by_status(conn, "scored")
    assert len(scored) == 1 and scored[0].grade == "A"


def test_set_triage_records_status(tmp_path):
    conn = dbmod.connect(tmp_path / "h.db")
    dbmod.init_db(conn)
    dbmod.insert_job(conn, _job())
    job = dbmod.jobs_by_status(conn, "discovered")[0]
    dbmod.set_triage(conn, job.id, status="approved")
    assert len(dbmod.jobs_by_status(conn, "approved")) == 1
