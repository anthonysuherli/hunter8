# handlers/ashby.py
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseHandler, ApplicationResult

_SPONSORSHIP_PHRASINGS = [
    "require employer sponsorship",
    "visa sponsorship",
    "sponsorship to work",
    "sponsorship now or in the future",
]


class AshbyHandler(BaseHandler):

    def apply(
        self, page: Any, profile: Any, resume_pdf: Path,
        company: str = "", title: str = "",
    ) -> ApplicationResult:
        self._company, self._title = company, title
        try:
            page.wait_for_selector("form, [data-testid='application-form']", timeout=15_000)
        except Exception:
            return self._hitl_pause("Form did not load within 15s", company=company, title=title)

        for placeholder, value in [("First", profile.first_name), ("Last", profile.last_name)]:
            el = page.query_selector(f'input[placeholder*="{placeholder}"]')
            if el and el.is_visible():
                el.fill(value)

        self._fill_if_present(page, 'input[type="email"]', profile.email)
        self._fill_if_present(page, 'input[type="tel"]', profile.phone)

        for fragment, value in [("LinkedIn", profile.linkedin), ("GitHub", profile.github)]:
            for label in page.query_selector_all("label"):
                if fragment.lower() in (label.text_content() or "").lower():
                    for_id = label.get_attribute("for")
                    if for_id:
                        el = page.query_selector(f"#{for_id}")
                        if el and el.is_visible():
                            el.fill(value)
                            break

        self._upload_file(page, resume_pdf)
        self._answer_sponsorship_ashby(page)

        textareas = self._has_visible_textareas(page)
        if textareas:
            return self._hitl_pause(f"{len(textareas)} open-ended textarea(s) detected", company=company, title=title)

        return self._submit(page, company=company, title=title)

    def _answer_sponsorship_ashby(self, page: Any) -> None:
        for el in page.query_selector_all("label"):
            text = (el.text_content() or "").lower()
            if any(p in text for p in _SPONSORSHIP_PHRASINGS):
                for r in page.query_selector_all('input[type="radio"]'):
                    if r.get_attribute("value") in ("Yes", "yes", "true", "1"):
                        if not self.dry_run:
                            r.click()
                        break
                break

    def _submit(self, page: Any, company: str = "", title: str = "") -> ApplicationResult:
        submit = page.query_selector(
            'button[type="submit"], input[type="submit"], button:has-text("Submit")'
        )
        if not submit:
            return self._hitl_pause("Could not locate submit button", company=company, title=title)
        if not self.dry_run:
            submit.click()
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
        return ApplicationResult.SUBMITTED
