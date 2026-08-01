from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class JobPosting:
    url: str
    company: str
    title: str
    location: str
    source: str
    ats: str | None = None
    posted_at: str | None = None
    description: str = ""
    canonical_url: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class SourceConfig:
    ats: str
    board: str
    company: str

    def __post_init__(self) -> None:
        if not self.ats or not self.board or not self.company:
            raise ValueError("ats, board, and company must be non-empty")
