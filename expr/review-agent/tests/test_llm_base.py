from __future__ import annotations

import pytest

from planqa_review.llm.base import CallStats, parse_json_response, total_elapsed_seconds, total_tokens


def test_total_elapsed_seconds_sums_all_calls():
    usage = [CallStats(1.5, 10, 5, 15), CallStats(2.0, 20, 10, 30)]
    assert total_elapsed_seconds(usage) == 3.5


def test_total_elapsed_seconds_empty_is_zero():
    assert total_elapsed_seconds([]) == 0.0


def test_total_tokens_sums_known_values():
    usage = [CallStats(1.0, 10, 5, 15), CallStats(1.0, 20, 10, 30)]
    assert total_tokens(usage) == 45


def test_total_tokens_none_when_backend_never_reports_it():
    usage = [CallStats(1.0, None, None, None), CallStats(1.0, None, None, None)]
    assert total_tokens(usage) is None


def test_total_tokens_ignores_calls_missing_the_field():
    usage = [CallStats(1.0, 10, 5, 15), CallStats(1.0, None, None, None)]
    assert total_tokens(usage) == 15


def test_parse_json_response_parses_valid_json_directly():
    assert parse_json_response('{"a": 1}') == {"a": 1}


def test_parse_json_response_strips_markdown_fence():
    assert parse_json_response('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_response_repairs_stray_backslash():
    # A regex-like fragment in a quoted value — a real pattern seen live where a model
    # quoted "\d+" inside original_text, which isn't a valid JSON escape (\d).
    raw = '{"original_text": "숫자는 \\d+ 패턴을 따른다"}'
    assert parse_json_response(raw) == {"original_text": "숫자는 \\d+ 패턴을 따른다"}


def test_parse_json_response_repairs_invalid_unicode_escape():
    # \u followed by fewer than 4 valid hex digits — another live failure mode
    # ("Invalid \uXXXX escape").
    raw = '{"note": "value \\u12 end"}'
    assert parse_json_response(raw) == {"note": "value \\u12 end"}


def test_parse_json_response_repairs_trailing_comma():
    raw = '{"a": 1, "b": 2,}'
    assert parse_json_response(raw) == {"a": 1, "b": 2}


def test_parse_json_response_still_raises_on_irreparable_json():
    with pytest.raises(ValueError):
        parse_json_response("{not json at all")
