# tests/test_core_ports.py
import ast
from pathlib import Path

import db as dbmod
import discover
from hunter8_core import JobPosting, SourceConfig


class FakeCompanySource:
    def __init__(self):
        self.seen: list[SourceConfig] = []

    def fetch(self, config: SourceConfig, *, timeout: float = 20.0):
        self.seen.append(config)
        return [
            JobPosting(
                url="https://x/1",
                company=config.company,
                title="AI Engineer",
                location="NYC",
                source=f"ats:{config.ats}",
                ats=config.ats,
                description="Build AI systems.",
            )
        ]


def test_discovery_accepts_a_company_source(tmp_path):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text(
        "companies:\n"
        "  - name: Acme\n"
        "    ats: greenhouse\n"
        "    board: acme\n"
        "    archetype: lab\n"
    )
    source = FakeCompanySource()

    inserted = discover.run_discovery(
        watchlist, tmp_path / "h.db", tavily_key=None, ats_source=source
    )

    assert inserted == 1
    assert source.seen == [
        SourceConfig(ats="greenhouse", board="acme", company="Acme")
    ]
    conn = dbmod.connect(tmp_path / "h.db")
    assert dbmod.jobs_by_status(conn, "discovered")[0].raw_text == "Build AI systems."


def test_core_package_has_no_local_or_third_party_imports():
    forbidden = {
        "db", "sources", "watchlist", "screen", "score", "rubric",
        "claude_agent", "local_agent", "httpx", "yaml", "dotenv",
    }
    for path in Path("hunter8_core").rglob("*.py"):
        tree = ast.parse(path.read_text(), filename=str(path))
        imported = {
            node.names[0].name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
        }
        imported |= {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        assert not (imported & forbidden), (path, imported & forbidden)
