# apply.py
from __future__ import annotations
import logging
import tempfile
from datetime import date
from pathlib import Path

import click
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from candidate_profile import load_profile
from handlers import route
from handlers.base import ApplicationResult
from resume_builder import build_resume_pdf
from tracker import ApplicationRow, iter_applications, update_status

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


@click.command()
@click.option(
    "--tracker",
    default=None,
    envvar="TRACKER_PATH",
    type=click.Path(exists=True, path_type=Path),
    help="Path to ML-AI-Roles-Tracker.xlsx",
    required=True,
)
@click.option("--dry-run", is_flag=True, help="Navigate and fill but do not submit")
@click.option("--row", default=None, type=int, help="Apply to a single Excel row number only")
@click.option("--ats", default=None, type=str, help="Filter by ATS type: greenhouse|ashby|lever")
@click.option("--headless", is_flag=True, help="Run browser headless")
def main(tracker: Path, dry_run: bool, row: int | None, ats: str | None, headless: bool) -> None:
    profile = load_profile(tracker)
    log.info("Profile loaded: %s", profile.full_name)

    apps = list(iter_applications(tracker))
    if row is not None:
        apps = [a for a in apps if a.excel_row == row]
    if ats is not None:
        apps = [a for a in apps if ats in a.url.lower()]

    if not apps:
        click.echo("No matching applications to process.")
        return

    click.echo(f"Processing {len(apps)} application(s). dry_run={dry_run}\n")

    counts: dict[str, int] = {"applied": 0, "hitl": 0, "skipped": 0, "error": 0}
    log_path = tracker.parent / f"apply-run-{date.today().isoformat()}.log"
    fh = logging.FileHandler(log_path)
    fh.setLevel(logging.DEBUG)
    logging.getLogger().addHandler(fh)

    tmp_dir = Path(tempfile.mkdtemp(prefix="hunter8-"))

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        context = browser.new_context()

        for app in apps:
            click.echo(f"  [{app.excel_row:03d}] {app.company} — {app.title[:50]}")
            log.info("START row=%d company=%s url=%s", app.excel_row, app.company, app.url)

            try:
                result, notes = _process_one(app, context, profile, tmp_dir, dry_run)
            except Exception as exc:
                log.exception("Unhandled error for row %d", app.excel_row)
                result = ApplicationResult.ERROR
                notes = str(exc)[:80]

            _write_result(tracker, app, result, notes, counts)
            _print_result(result)

        context.close()
        browser.close()

    _print_summary(counts, log_path)


def _process_one(
    app: ApplicationRow,
    context: object,
    profile: object,
    tmp_dir: Path,
    dry_run: bool,
) -> tuple[ApplicationResult, str]:
    from playwright.sync_api import BrowserContext
    assert isinstance(context, BrowserContext)

    handler = route(app.url, dry_run=dry_run)
    ats_name = type(handler).__name__.replace("Handler", "").lower()

    resume_pdf: Path | None = None
    if app.resume_path:
        md_path = Path(app.resume_path)
        if md_path.exists():
            resume_pdf = build_resume_pdf(md_path, tmp_dir)
        else:
            log.warning("Resume md not found: %s", md_path)

    if resume_pdf is None:
        log.warning("No resume PDF for row %d — proceeding without upload", app.excel_row)
        resume_pdf = Path("/dev/null")

    page = context.new_page()
    try:
        page.goto(app.url, timeout=20_000, wait_until="domcontentloaded")
        result = handler.apply(page, profile, resume_pdf, company=app.company, title=app.title)
        prefix = "dry-run · " if dry_run else ""
        return result, f"{prefix}{ats_name}"
    except Exception:
        screenshot_dir = Path(app.resume_path).parent if app.resume_path else tmp_dir
        try:
            page.screenshot(path=str(screenshot_dir / "error-screenshot.png"))
        except Exception:
            pass
        raise
    finally:
        page.close()


def _write_result(
    tracker: Path,
    app: ApplicationRow,
    result: ApplicationResult,
    notes: str,
    counts: dict[str, int],
) -> None:
    if result == ApplicationResult.SUBMITTED:
        update_status(tracker, app.excel_row, "Applied", f"auto-submit · {notes}")
        counts["applied"] += 1
    elif result == ApplicationResult.HITL:
        update_status(tracker, app.excel_row, "Applied", f"manual-submit · HITL: {notes}")
        counts["hitl"] += 1
    elif result == ApplicationResult.ERROR:
        update_status(tracker, app.excel_row, "Error", notes)
        counts["error"] += 1


def _print_result(result: ApplicationResult) -> None:
    icons = {
        ApplicationResult.SUBMITTED: "✓",
        ApplicationResult.HITL: "🟡",
        ApplicationResult.ERROR: "✗",
    }
    click.echo(f"       {icons.get(result, '?')} {result.value}")


def _print_summary(counts: dict[str, int], log_path: Path) -> None:
    click.echo(
        f"\nRun complete: {counts['applied']} applied · "
        f"{counts['hitl']} HITL (manual) · "
        f"{counts['skipped']} skipped · "
        f"{counts['error']} error"
    )
    click.echo(f"Log: {log_path}")


if __name__ == "__main__":
    main()
