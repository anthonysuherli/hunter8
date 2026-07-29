# tests/test_watchlist.py
import watchlist


def test_load_parses_companies_and_queries(tmp_path):
    p = tmp_path / "w.yaml"
    p.write_text(
        "companies:\n"
        "  - name: Hebbia\n"
        "    ats: greenhouse\n"
        "    board: hebbia\n"
        "    archetype: ai-finance-startup\n"
        "tavily_queries:\n"
        "  - 'research engineer agentic AI'\n"
    )
    wl = watchlist.load_watchlist(p)
    assert wl.companies[0].name == "Hebbia"
    assert wl.companies[0].ats == "greenhouse"
    assert wl.tavily_queries == ["research engineer agentic AI"]


def test_load_rejects_bad_ats(tmp_path):
    import pytest
    p = tmp_path / "w.yaml"
    p.write_text(
        "companies:\n  - name: X\n    ats: taleo\n    board: x\n    archetype: lab\n"
    )
    with pytest.raises(ValueError):
        watchlist.load_watchlist(p)


def test_load_accepts_compound_board_platforms(tmp_path):
    """workday and eightfold carry a compound board token, not a bare slug."""
    p = tmp_path / "w.yaml"
    p.write_text(
        "companies:\n"
        "  - name: Morgan Stanley\n    ats: workday\n    board: ms/wd5/External\n"
        "    archetype: bank\n"
        "  - name: Millennium\n    ats: eightfold\n    board: mlp/mlp.com\n"
        "    archetype: buy-side-ai\n"
    )
    wl = watchlist.load_watchlist(p)
    assert [c.ats for c in wl.companies] == ["workday", "eightfold"]
    assert wl.companies[0].board == "ms/wd5/External"
