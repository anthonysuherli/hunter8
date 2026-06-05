# handlers/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any


class ApplicationResult(Enum):
    SUBMITTED = "submitted"
    HITL = "hitl"
    ERROR = "error"


class BaseHandler(ABC):
    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    @abstractmethod
    def apply(self, page: Any, profile: Any, resume_pdf: Path) -> ApplicationResult:
        ...

    def _fill_if_present(self, page: Any, selector: str, value: str) -> None:
        el = page.query_selector(selector)
        if el and el.is_visible():
            el.fill(value)

    def _upload_file(self, page: Any, resume_pdf: Path) -> bool:
        el = page.query_selector('input[type="file"]')
        if el:
            el.set_input_files(str(resume_pdf))
            return True
        return False

    def _has_visible_textareas(self, page: Any) -> list[Any]:
        return [t for t in page.query_selector_all("textarea") if t.is_visible()]

    def _hitl_pause(self, reason: str, company: str = "", title: str = "") -> ApplicationResult:
        print(f"\n🟡 HITL required: {company} — {title}")
        print(f"   Reason: {reason}")
        print("   Fill the field(s) in the browser, then:")
        print("     Enter  → mark Applied")
        print("     's'    → skip")
        print("     'e'    → mark Error")
        input("   → ")
        return ApplicationResult.HITL

    def _hitl_pause_with_choice(
        self, reason: str, company: str = "", title: str = ""
    ) -> tuple[ApplicationResult, str]:
        print(f"\n🟡 HITL required: {company} — {title}")
        print(f"   Reason: {reason}")
        print("   Enter → Applied  |  's' → skip  |  'e' → Error")
        choice = input("   → ").strip().lower()
        if choice == "e":
            return ApplicationResult.ERROR, "e"
        return ApplicationResult.HITL, choice


class FallbackHandler(BaseHandler):
    def apply(self, page: Any, profile: Any, resume_pdf: Path) -> ApplicationResult:
        print("\n🔵 MANUAL: Browser open — complete the form, then:")
        print("     Enter  → mark Applied  |  's' → skip  |  'e' → Error")
        choice = input("   → ").strip().lower()
        if choice == "e":
            return ApplicationResult.ERROR
        return ApplicationResult.HITL
