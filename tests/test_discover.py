import db as dbmod
import discover
from db import Job


def test_run_discovery_inserts_and_dedupes(tmp_path, monkeypatch):
    wl_path = tmp_path / "w.yaml"
    wl_path.write_text(
        "companies:\n  - name: Acme\n    ats: greenhouse\n    board: acme\n"
        "    archetype: lab\n"
    )
    db_path = tmp_path / "h.db"

    def fake_fetch_ats(ats, *, board, company, timeout=20.0):
        return [Job(url="https://x/1", company=company, title="ML Engineer",
                    location="Remote US", source="ats:greenhouse", ats="greenhouse",
                    raw_text="d")]

    monkeypatch.setattr(discover.sources, "fetch_ats", fake_fetch_ats)

    n1 = discover.run_discovery(wl_path, db_path, tavily_key=None)
    n2 = discover.run_discovery(wl_path, db_path, tavily_key=None)
    assert n1 == 1
    assert n2 == 0  # deduped on second run

    conn = dbmod.connect(db_path)
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def test_run_discovery_continues_past_failing_company(tmp_path, monkeypatch):
    wl_path = tmp_path / "w.yaml"
    wl_path.write_text(
        "companies:\n"
        "  - name: Bad\n    ats: greenhouse\n    board: bad\n    archetype: lab\n"
        "  - name: Good\n    ats: greenhouse\n    board: good\n    archetype: lab\n"
    )

    def fake_fetch_ats(ats, *, board, company, timeout=20.0):
        if company == "Bad":
            raise RuntimeError("boom")
        return [Job(url="https://x/2", company=company, title="T", location="",
                    source="ats:greenhouse", ats="greenhouse", raw_text="d")]

    monkeypatch.setattr(discover.sources, "fetch_ats", fake_fetch_ats)
    n = discover.run_discovery(wl_path, tmp_path / "h.db", tavily_key=None)
    assert n == 1  # Good succeeded despite Bad failing
