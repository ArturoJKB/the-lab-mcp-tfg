"""Tests for A3.3 — JSON repair helper for small local model outputs."""

from __future__ import annotations

from thelab.agents.json_repair import repair_json, safe_json_loads


def test_parses_valid_json() -> None:
    assert safe_json_loads('{"a": 1}') == {"a": 1}


def test_repairs_markdown_fence() -> None:
    text = '```json\n{"a": 1}\n```'
    assert repair_json(text) == {"a": 1}


def test_repairs_trailing_comma_in_object() -> None:
    text = '{"a": 1,}'
    assert repair_json(text) == {"a": 1}


def test_repairs_trailing_comma_in_array() -> None:
    text = '{"items": [1, 2,]}'
    assert repair_json(text) == {"items": [1, 2]}


def test_repairs_single_quotes() -> None:
    text = "{'a': 1, 'b': 'hello'}"
    assert repair_json(text) == {"a": 1, "b": "hello"}


def test_repairs_unquoted_keys() -> None:
    text = '{a: 1, b: "two"}'
    assert repair_json(text) == {"a": 1, "b": "two"}


def test_repairs_mixed_issues() -> None:
    text = "```json\n{'a': 1, 'b': [2, 3,],}\n```"
    assert repair_json(text) == {"a": 1, "b": [2, 3]}


def test_returns_none_for_unrepairable_text() -> None:
    assert repair_json("not json at all") is None


def test_extracts_first_json_object_from_extra_text() -> None:
    text = "Here is the result: {\"a\": 1} and some trailing text"
    assert repair_json(text) == {"a": 1}


def test_preserves_nested_strings() -> None:
    text = '{"message": "Hello, \\"world\\"!"}'
    assert safe_json_loads(text) == {"message": 'Hello, "world"!'}


def test_does_not_mangle_single_quotes_inside_double_quoted_strings() -> None:
    text = '{"quote": "it\'s fine"}'
    assert safe_json_loads(text) == {"quote": "it's fine"}


def test_array_top_level() -> None:
    assert safe_json_loads("[1, 2, 3]") == [1, 2, 3]


def test_repairs_top_level_array_trailing_comma() -> None:
    text = "[1, 2, 3,]"
    assert repair_json(text) == [1, 2, 3]
