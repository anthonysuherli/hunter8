import db as dbmod
import discover
from hunter8_core import JobPosting


class FakeSource:
    """Minimal CompanySource: one posting per company, or a raised error."""

    def __init__(self, url="https://x/1", fail_for=None):
        self.url = url
        self.fail_for = fail_for

    def fetch(self, config, *, timeout=20.0):
        if config.company == self.fail_for:
            raise RuntimeError("boom")
        return [JobPosting(url=self.url, company=config.company,
                           title="ML Engineer", location="Remote US",
                           source="ats:greenhouse", ats="greenhouse",
                           description="d")]


def test_run_discovery_inserts_and_dedupes(tmp_path):
    wl_path = tmp_path / "w.yaml"
    wl_path.write_text(
        "companies:\n  - name: Acme\n    ats: greenhouse\n    board: acme\n"
        "    archetype: lab\n"
    )
    db_path = tmp_path / "h.db"
    source = FakeSource()

    n1 = discover.run_discovery(wl_path, db_path, tavily_key=None,
                                ats_source=source)
    n2 = discover.run_discovery(wl_path, db_path, tavily_key=None,
                                ats_source=source)
    assert n1 == 1
    assert n2 == 0  # deduped on second run

    conn = dbmod.connect(db_path)
    assert len(dbmod.jobs_by_status(conn, "discovered")) == 1


def test_run_discovery_continues_past_failing_company(tmp_path):
    wl_path = tmp_path / "w.yaml"
    wl_path.write_text(
        "companies:\n"
        "  - name: Bad\n    ats: greenhouse\n    board: bad\n    archetype: lab\n"
        "  - name: Good\n    ats: greenhouse\n    board: good\n    archetype: lab\n"
    )

    source = FakeSource(url="https://x/2", fail_for="Bad")
    n = discover.run_discovery(wl_path, tmp_path / "h.db", tavily_key=None,
                               ats_source=source)
    assert n == 1  # Good succeeded despite Bad failing
