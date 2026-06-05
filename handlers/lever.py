# handlers/lever.py
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseHandler, ApplicationResult


class LeverHandler(BaseHandler):
    """Lever forms always include a free-text textarea — always triggers HITL."""

    def apply(self, page: Any, profile: Any, resume_pdf: Path) -> ApplicationResult:
        try:
            page.wait_for_selector("form", timeout=15_000)
        except Exception:
            return self._hitl_pause("Form did not load")

        self._fill_if_present(page, 'input[name="name"]', profile.full_name)
        self._fill_if_present(page, 'input[name="email"]', profile.email)
        self._fill_if_present(page, 'input[name="phone"]', profile.phone)
        self._fill_if_present(page, 'input[name="urls[LinkedIn]"]', profile.linkedin)
        self._fill_if_present(page, 'input[name="urls[GitHub]"]', profile.github)
        self._upload_file(page, resume_pdf)

        return self._hitl_pause(
            "Lever forms always contain an open-ended 'Additional information' textarea"
        )
