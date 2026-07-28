# tests/test_json_reply.py
import pytest

import json_reply


def test_parses_plain_object():
    assert json_reply.parse_object('{"fit_score": 70}') == {"fit_score": 70}


def test_strips_markdown_fence():
    assert json_reply.parse_object('```json\n{"a": 1}\n```') == {"a": 1}


def test_extracts_object_from_surrounding_prose():
    assert json_reply.parse_object('Sure: {"a": 1} — done') == {"a": 1}


def test_raises_value_error_on_garbage():
    with pytest.raises(ValueError):
        json_reply.parse_object("no object here")
