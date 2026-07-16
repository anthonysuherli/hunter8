# sources.py
from __future__ import annotations

from typing import Any

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
