from __future__ import annotations

from planqa_eval.llm.base import CallStats, total_elapsed_seconds, total_tokens


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
