# sources.py
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import httpx

from db import Job

# Workday and Eightfold sit behind bot management and reject the default httpx
# user-agent; the three JSON boards do not care.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
_HEADERS = {"User-Agent": _UA, "Accept": "application/json"}

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\n{3,}")


def _detag(html: str) -> str:
    """Workday returns jobDescription as an HTML fragment. No parser dependency
    is installed, and the screen only needs prose, so strip tags crudely."""
    text = _TAG.sub("\n", html or "")
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
                .replace("&quot;", '"'))
    return _WS.sub("\n\n", text).strip()


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


def _epoch_ms_to_iso(value) -> str | None:
    """Lever returns createdAt as milliseconds since the epoch. Every other
    source in this module yields ISO, and every date filter in the pipeline
    compares posted_at as a *string* — so a raw epoch sorts below every ISO
    cutoff and silently fails every --since-days run."""
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def parse_lever(payload: list[dict[str, Any]], *, company: str) -> list[Job]:
    out: list[Job] = []
    for j in payload:
        cats = j.get("categories") or {}
        out.append(Job(
            url=j["hostedUrl"], company=company, title=j.get("text", ""),
            location=cats.get("location", ""), source="ats:lever", ats="lever",
            posted_at=_epoch_ms_to_iso(j.get("createdAt")),
            raw_text=j.get("descriptionPlain", "") or "",
        ))
    return out


def repair_lever_posted_at(conn) -> int:
    """Convert stored millisecond-epoch posting dates to ISO. Returns the number
    of rows changed.

    Idempotent: rows already ISO are left alone, so this is safe to re-run. Only
    touches rows whose posted_at is all digits, so it can never mangle a real
    timestamp."""
    rows = conn.execute(
        "SELECT id, posted_at FROM jobs "
        "WHERE posted_at IS NOT NULL AND posted_at <> '' "
        "AND posted_at GLOB '[0-9]*' AND posted_at NOT GLOB '*[^0-9]*'"
    ).fetchall()
    changed = 0
    for job_id, raw in rows:
        iso = _epoch_ms_to_iso(raw)
        if iso is None:
            continue
        conn.execute("UPDATE jobs SET posted_at=? WHERE id=?", (iso, job_id))
        changed += 1
    conn.commit()
    return changed


def parse_workday_detail(payload: dict[str, Any], *, company: str,
                         url: str) -> Job | None:
    """One job from Workday's CxS detail endpoint.

    The list endpoint only carries a title, a location string and a *relative*
    date ("Posted 4 Days Ago"). The detail endpoint carries the description and
    `startDate` as a real ISO day, which is the only reason we pay for a second
    request per job — a relative date cannot drive --since-days."""
    info = payload.get("jobPostingInfo") or {}
    title = info.get("title")
    if not title:
        return None
    start = info.get("startDate") or ""
    posted = f"{start}T00:00:00+00:00" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start) else None
    return Job(
        url=url, company=company, title=title,
        location=info.get("location", "") or "", source="ats:workday",
        ats="workday", posted_at=posted,
        raw_text=_detag(info.get("jobDescription", "")),
    )


def parse_eightfold(payload: dict[str, Any], *, company: str) -> list[Job]:
    """Eightfold's list endpoint. `job_description` comes back empty here and
    there is no public detail endpoint, so these rows carry title, location and
    department only — enough to screen and click through, not to grade deeply."""
    out: list[Job] = []
    for p in payload.get("positions", []):
        pid = p.get("id")
        url = p.get("canonicalPositionUrl") or (pid and f"eightfold:{pid}")
        if not url:
            continue
        created = p.get("t_create")
        posted = (datetime.fromtimestamp(int(created), timezone.utc).isoformat()
                  if created else None)
        bits = [p.get("name", ""), p.get("department", ""),
                p.get("business_unit", ""), p.get("job_description", "")]
        out.append(Job(
            url=url, company=company, title=p.get("name", ""),
            location=p.get("location", "") or "", source="ats:eightfold",
            ats="eightfold", posted_at=posted,
            raw_text="\n".join(b for b in bits if b),
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

# Newest-first, so a cap drops the stale tail rather than this week's postings.
WORKDAY_MAX_JOBS = 300
_WD_PAGE = 20
_EF_PAGE = 10


def fetch_workday(*, board: str, company: str, timeout: float = 20.0,
                  max_jobs: int = WORKDAY_MAX_JOBS) -> list[Job]:
    """`board` is "tenant/server/site", e.g. "ms/wd5/External"."""
    try:
        tenant, server, site = board.split("/")
    except ValueError:
        raise ValueError(f"workday board must be tenant/server/site, got {board!r}")
    base = f"https://{tenant}.{server}.myworkdayjobs.com/wday/cxs/{tenant}/{site}"
    ui = f"https://{tenant}.{server}.myworkdayjobs.com/{site}"

    paths: list[str] = []
    with httpx.Client(timeout=timeout, headers=_HEADERS) as client:
        offset = 0
        while len(paths) < max_jobs:
            resp = client.post(f"{base}/jobs", json={
                "appliedFacets": {}, "limit": _WD_PAGE, "offset": offset,
                "searchText": ""})
            resp.raise_for_status()
            page = resp.json().get("jobPostings") or []
            if not page:
                break
            paths.extend(p["externalPath"] for p in page if p.get("externalPath"))
            offset += _WD_PAGE
        paths = paths[:max_jobs]

        def one(path: str) -> Job | None:
            try:
                r = client.get(f"{base}{path}")
                r.raise_for_status()
                return parse_workday_detail(r.json(), company=company,
                                            url=f"{ui}{path}")
            except Exception:  # noqa: BLE001 — one bad posting must not kill the board
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            return [j for j in pool.map(one, paths) if j is not None]


def fetch_eightfold(*, board: str, company: str, timeout: float = 20.0,
                    max_jobs: int = 500) -> list[Job]:
    """`board` is "subdomain/domain", e.g. "mlp/mlp.com"."""
    try:
        sub, domain = board.split("/")
    except ValueError:
        raise ValueError(f"eightfold board must be sub/domain, got {board!r}")
    url = f"https://{sub}.eightfold.ai/api/apply/v2/jobs"
    out: list[Job] = []
    with httpx.Client(timeout=timeout, headers=_HEADERS) as client:
        start = 0
        while len(out) < max_jobs:
            r = client.get(url, params={"domain": domain, "start": start,
                                        "num": _EF_PAGE, "sort_by": "timestamp"})
            r.raise_for_status()
            batch = parse_eightfold(r.json(), company=company)
            if not batch:
                break
            out.extend(batch)
            # Eightfold silently caps the page size below whatever `num` asks
            # for, so advance by what actually came back — stepping by the
            # requested size skips every job in the gap.
            start += len(batch)
    return out[:max_jobs]


def fetch_ats(ats: str, *, board: str, company: str, timeout: float = 20.0) -> list[Job]:
    """Fetch + parse one company's board. Raises ValueError for unknown ATS;
    lets httpx errors propagate to the caller (discover.py handles per-company)."""
    if ats == "workday":
        return fetch_workday(board=board, company=company, timeout=timeout)
    if ats == "eightfold":
        return fetch_eightfold(board=board, company=company, timeout=timeout)
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
