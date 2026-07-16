# sources.py
from __future__ import annotations

from typing import Any

import httpx

from db import Job


def parse_greenhouse(payload: dict[str, Any], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        out.append(Job(
            url=j["absolute_url"], company=company, title=j.get("title", ""),
            location=loc, source="ats:greenhouse", ats="greenhouse",
            posted_at=j.get("updated_at"), raw_text=j.get("content", "") or "",
        ))
    return out


def parse_ashby(payload: dict[str, Any], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload.get("jobs", []):
        loc = j.get("location")
        if isinstance(loc, dict):
            loc = loc.get("name", "")
        out.append(Job(
            url=j["jobUrl"], company=company, title=j.get("title", ""),
            location=loc or "", source="ats:ashby", ats="ashby",
            posted_at=j.get("publishedAt"),
            raw_text=j.get("descriptionPlain", "") or "",
        ))
    return out


def parse_lever(payload: list[dict[str, Any]], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload:
        cats = j.get("categories") or {}
        out.append(Job(
            url=j["hostedUrl"], company=company, title=j.get("text", ""),
            location=cats.get("location", ""), source="ats:lever", ats="lever",
            posted_at=str(j.get("createdAt", "")) or None,
            raw_text=j.get("descriptionPlain", "") or "",
        ))
    return out


_ATS_URL = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true",
    "lever": "https://api.lever.co/v0/postings/{board}?mode=json",
}

_PARSERS = {
    "greenhouse": parse_greenhouse,
    "ashby": parse_ashby,
    "lever": parse_lever,
}


def fetch_ats(ats: str, *, board: str, company: str, timeout: float = 20.0) -> list[Job]:
    """Fetch + parse one company's board. Raises ValueError for unknown ATS;
    lets httpx errors propagate to the caller (discover.py handles per-company)."""
    if ats not in _ATS_URL:
        raise ValueError(f"unsupported ATS: {ats}")
    url = _ATS_URL[ats].format(board=board)
    resp = httpx.get(url, timeout=timeout)
    resp.raise_for_status()
    return _PARSERS[ats](resp.json(), company=company)


def fetch_tavily(query: str, api_key: str, *, max_results: int = 5,
                 timeout: float = 30.0) -> list[Job]:
    """Tavily search → Job rows (source='tavily', ats=None). URL is the result
    link; raw_text is the result content."""
    resp = httpx.post(
        "https://api.tavily.com/search",
        json={"api_key": api_key, "query": query, "max_results": max_results,
              "search_depth": "basic"},
        timeout=timeout,
    )
    resp.raise_for_status()
    out: list[Job] = []
    for r in resp.json().get("results", []):
        out.append(Job(
            url=r["url"], company="(tavily)", title=r.get("title", "")[:200],
            location="", source="tavily", ats=None,
            raw_text=r.get("content", "") or "",
        ))
    return out
