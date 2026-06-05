# handlers/greenhouse.py
from __future__ import annotations
from pathlib import Path
from typing import Any
from .base import BaseHandler, ApplicationResult

_SPONSORSHIP_LABELS = [
    ("sponsor", "Yes"),
    ("visa", "Yes"),
    ("authorized", "Yes"),
    ("legally authorized", "Yes"),
    ("work authorization", "Yes"),
]


class GreenhouseHandler(BaseHandler):

    def apply(
        self, page: Any, profile: Any, resume_pdf: Path,
        company: str = "", title: str = "",
    ) -> ApplicationResult:
        self._company, self._title = company, title
        try:
            page.wait_for_selector("form", timeout=15_000)
        except Exception:
            return self._hitl_pause("Form did not load within 15s", company=self._company, title=self._title)

        self._fill_if_present(page, 'input[name="first_name"]', profile.first_name)
        self._fill_if_present(page, 'input[name="last_name"]', profile.last_name)
        self._fill_if_present(page, 'input[name="email"]', profile.email)
        self._fill_if_present(page, 'input[name="phone"]', profile.phone)

        for label_text, value in [
            ("linkedin", profile.linkedin),
            ("github", profile.github),
            ("website", profile.linkedin),
        ]:
            self._fill_labeled_input(page, label_text, value)

        self._upload_file(page, resume_pdf)
        self._answer_sponsorship_fields(page)

        textareas = self._has_visible_textareas(page)
        if textareas:
            return self._hitl_pause(f"{len(textareas)} open-ended textarea(s) detected", company=self._company, title=self._title)

        return self._submit(page)

    def _fill_labeled_input(self, page: Any, label_fragment: str, value: str) -> None:
        for label in page.query_selector_all("label"):
            text = (label.text_content() or "").lower()
            if label_fragment in text:
                for_attr = label.get_attribute("for")
                if for_attr:
                    el = page.query_selector(f"#{for_attr}")
                    if el and el.is_visible():
                        el.fill(value)
                        return

    def _answer_sponsorship_fields(self, page: Any) -> None:
        for sel in page.query_selector_all("select"):
            try:
                label_el = page.query_selector(f'label[for="{sel.get_attribute("id")}"]')
                label_text = (label_el.text_content() if label_el else "").lower()
            except Exception:
                label_text = ""
            for fragment, answer in _SPONSORSHIP_LABELS:
                if fragment in label_text:
                    try:
                        sel.select_option(label=answer)
                    except Exception:
                        try:
                            sel.select_option(value=answer)
                        except Exception:
                            pass
                    break

    def _submit(self, page: Any) -> ApplicationResult:
        submit = page.query_selector(
            'input[type="submit"], button[type="submit"], button[data-qa="btn-submit"]'
        )
        if not submit:
            return self._hitl_pause("Could not locate submit button", company=self._company, title=self._title)
        if not self.dry_run:
            submit.click()
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
        return ApplicationResult.SUBMITTED
