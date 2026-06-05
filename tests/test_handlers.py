# tests/test_handlers.py
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from handlers.base import BaseHandler, ApplicationResult


class ConcreteHandler(BaseHandler):
    def apply(self, _page: Any, _profile: Any, _resume_pdf: Path) -> ApplicationResult:
        return ApplicationResult.SUBMITTED


def test_application_result_enum_values():
    assert ApplicationResult.SUBMITTED.value == "submitted"
    assert ApplicationResult.HITL.value == "hitl"
    assert ApplicationResult.ERROR.value == "error"


def test_fill_if_present_fills_visible_input():
    handler = ConcreteHandler(dry_run=False)
    page = MagicMock()
    el = MagicMock()
    el.is_visible.return_value = True
    page.query_selector.return_value = el
    handler._fill_if_present(page, 'input[name="email"]', "test@example.com")
    el.fill.assert_called_once_with("test@example.com")


def test_fill_if_present_skips_missing_input():
    handler = ConcreteHandler(dry_run=False)
    page = MagicMock()
    page.query_selector.return_value = None
    handler._fill_if_present(page, 'input[name="missing"]', "value")


def test_hitl_pause_returns_hitl_result(monkeypatch):
    handler = ConcreteHandler(dry_run=False)
    monkeypatch.setattr("builtins.input", lambda _: "")
    result = handler._hitl_pause("textarea detected", company="Acme", title="Engineer")
    assert result == ApplicationResult.HITL


def test_hitl_pause_skip_returns_hitl(monkeypatch):
    handler = ConcreteHandler(dry_run=False)
    monkeypatch.setattr("builtins.input", lambda _: "s")
    result = handler._hitl_pause("textarea detected", company="Acme", title="Engineer")
    assert result == ApplicationResult.HITL


from handlers.greenhouse import GreenhouseHandler


def _make_page(textareas: int = 0) -> MagicMock:
    page = MagicMock()
    page.query_selector.return_value = MagicMock(is_visible=lambda: True)
    ta_mocks = [MagicMock(is_visible=MagicMock(return_value=True)) for _ in range(textareas)]
    page.query_selector_all.return_value = ta_mocks
    return page


def test_greenhouse_auto_submits_when_no_textareas():
    handler = GreenhouseHandler(dry_run=False)
    page = _make_page(textareas=0)
    profile = MagicMock(first_name="Anthony", last_name="Suherli",
                        email="a@b.com", phone="555-0100",
                        linkedin="linkedin.com/in/x", github="github.com/x")
    result = handler.apply(page, profile, Path("/tmp/resume.pdf"))
    assert result == ApplicationResult.SUBMITTED


def test_greenhouse_hitl_when_textarea_present(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    handler = GreenhouseHandler(dry_run=False)
    page = _make_page(textareas=1)
    result = handler.apply(page, MagicMock(first_name="A", last_name="B",
                                            email="a@b.com", phone="5",
                                            linkedin="li", github="gh"),
                           Path("/tmp/resume.pdf"))
    assert result == ApplicationResult.HITL


def test_greenhouse_dry_run_does_not_click_submit():
    handler = GreenhouseHandler(dry_run=True)
    page = _make_page(textareas=0)
    profile = MagicMock(first_name="Anthony", last_name="Suherli",
                        email="a@b.com", phone="555-0100",
                        linkedin="linkedin.com/in/x", github="github.com/x")
    handler.apply(page, profile, Path("/tmp/resume.pdf"))
    submit = page.query_selector.return_value
    submit.click.assert_not_called()


from handlers.ashby import AshbyHandler
from handlers.lever import LeverHandler


def test_ashby_auto_submits_when_no_textareas():
    handler = AshbyHandler(dry_run=False)
    page = _make_page(textareas=0)
    result = handler.apply(page, MagicMock(
        first_name="Anthony", last_name="Suherli",
        email="a@b.com", phone="555-0100",
        linkedin="linkedin.com/in/x", github="github.com/x"
    ), Path("/tmp/resume.pdf"))
    assert result == ApplicationResult.SUBMITTED


def test_lever_always_hitl(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "")
    handler = LeverHandler(dry_run=False)
    page = _make_page(textareas=0)
    result = handler.apply(page, MagicMock(
        full_name="Anthony Suherli", email="a@b.com",
        phone="555", linkedin="li", github="gh"
    ), Path("/tmp/resume.pdf"))
    assert result == ApplicationResult.HITL
