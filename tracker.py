# tracker.py
from __future__ import annotations
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator
import openpyxl

COL_PRIORITY = 1
COL_STATUS = 2
COL_DATE = 3
COL_NOTES = 4
COL_COMPANY = 5
COL_ROLE = 6
COL_CITY = 7
COL_REGION = 8
COL_LINK = 11
COL_RESUME_PATH = 13


@dataclass
class ApplicationRow:
    excel_row: int
    company: str
    title: str
    city: str
    url: str
    priority: str
    status: str
    resume_path: str | None


def iter_applications(
    tracker_path: Path,
    priority_prefix: str = "A",
    status_filter: str = "To apply",
) -> Iterator[ApplicationRow]:
    wb = openpyxl.load_workbook(tracker_path)
    ws = wb["Apply Tracker"]
    for row in range(2, ws.max_row + 1):
        priority = str(ws.cell(row, COL_PRIORITY).value or "")
        status = str(ws.cell(row, COL_STATUS).value or "")
        if not priority.startswith(priority_prefix):
            continue
        if status != status_filter:
            continue
        link_cell = ws.cell(row, COL_LINK)
        url = link_cell.hyperlink.target if link_cell.hyperlink else ""
        resume_cell = ws.cell(row, COL_RESUME_PATH)
        resume_path = str(resume_cell.value) if resume_cell.value else None
        yield ApplicationRow(
            excel_row=row,
            company=str(ws.cell(row, COL_COMPANY).value or ""),
            title=str(ws.cell(row, COL_ROLE).value or ""),
            city=str(ws.cell(row, COL_CITY).value or ""),
            url=url,
            priority=priority,
            status=status,
            resume_path=resume_path,
        )


def update_status(
    tracker_path: Path,
    excel_row: int,
    status: str,
    notes: str = "",
) -> None:
    wb = openpyxl.load_workbook(tracker_path)
    ws = wb["Apply Tracker"]
    ws.cell(excel_row, COL_STATUS).value = status
    if status == "Applied":
        ws.cell(excel_row, COL_DATE).value = date.today().isoformat()
    if notes:
        existing = str(ws.cell(excel_row, COL_NOTES).value or "")
        ws.cell(excel_row, COL_NOTES).value = (existing + " | " + notes).strip(" | ")
    wb.save(tracker_path)
