# watchlist.py
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

_VALID_ATS = {"greenhouse", "ashby", "lever"}


@dataclass
class Company:
    name: str
    ats: str
    board: str
    archetype: str


@dataclass
class Watchlist:
    companies: list[Company] = field(default_factory=list)
    tavily_queries: list[str] = field(default_factory=list)


def load_watchlist(path: str | Path) -> Watchlist:
    data = yaml.safe_load(Path(path).read_text()) or {}
    companies: list[Company] = []
    for c in data.get("companies", []):
        ats = c.get("ats")
        if ats not in _VALID_ATS:
            raise ValueError(f"{c.get('name')}: unsupported ats {ats!r}")
        companies.append(Company(
            name=c["name"], ats=ats, board=c["board"],
            archetype=c.get("archetype", ""),
        ))
    return Watchlist(companies=companies, tavily_queries=data.get("tavily_queries", []))
