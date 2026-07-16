# discover.py
from __future__ import annotations

import logging
import os
from pathlib import Path

import click
from dotenv import load_dotenv

import db as dbmod
import sources
from watchlist import load_watchlist

load_dotenv()
log = logging.getLogger(__name__)


def run_discovery(watchlist_path: str | Path, db_path: str | Path,
                  tavily_key: str | None) -> int:
    """Fetch every watchlist company + Tavily query, insert new jobs. Returns the
    count of newly inserted (deduped) jobs. Per-source failures are logged and
    skipped, never fatal."""
    wl = load_watchlist(watchlist_path)
    conn = dbmod.connect(db_path)
    dbmod.init_db(conn)

    inserted = 0
    failures: list[str] = []

    for c in wl.companies:
        try:
            jobs = sources.fetch_ats(c.ats, board=c.board, company=c.name)
        except Exception as exc:  # noqa: BLE001 — one bad board must not abort the run
            failures.append(f"{c.name} ({c.ats}/{c.board}): {exc}")
            log.warning("fetch failed for %s: %s", c.name, exc)
            continue
        for job in jobs:
            if dbmod.insert_job(conn, job):
                inserted += 1

    if tavily_key:
        for q in wl.tavily_queries:
            try:
                jobs = sources.fetch_tavily(q, tavily_key)
            except Exception as exc:  # noqa: BLE001
                failures.append(f"tavily {q!r}: {exc}")
                log.warning("tavily failed for %r: %s", q, exc)
                continue
            for job in jobs:
                if dbmod.insert_job(conn, job):
                    inserted += 1

    if failures:
        log.warning("%d source failure(s):\n  %s", len(failures), "\n  ".join(failures))
    return inserted


@click.command()
@click.option("--watchlist", "watchlist_path", default="watchlist.yaml",
              type=click.Path(exists=True, path_type=Path))
@click.option("--db", "db_path", default=None, envvar="HUNTER8_DB_PATH", type=Path)
def main(watchlist_path: Path, db_path: Path | None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    db_path = db_path or Path(dbmod.DEFAULT_DB)
    tavily_key = os.getenv("TAVILY_API_KEY")
    n = run_discovery(watchlist_path, db_path, tavily_key)
    click.echo(f"Discovery complete: {n} new job(s) queued in {db_path}.")
    if not tavily_key:
        click.echo("(TAVILY_API_KEY not set — skipped web queries.)")


if __name__ == "__main__":
    main()
