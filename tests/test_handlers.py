# tests/test_handlers.py
import pytest
from unittest.mock import MagicMock
from pathlib import Path
from handlers.base import BaseHandler, ApplicationResult


class ConcreteHandler(BaseHandler):
    def apply(self, page, profile, resume_pdf):
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
