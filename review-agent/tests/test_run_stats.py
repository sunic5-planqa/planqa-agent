from __future__ import annotations

from typing import Any

from planqa_review.llm.base import CallStats, LLMClient
from planqa_review.run_stats import build_run_stats


class _FakeLLM(LLMClient):
    def __init__(self, model: str, usage: list[CallStats]) -> None:
        self.model = model
        self.usage = usage

    def complete_json(self, *, system: str, prompt: str) -> Any:
        raise NotImplementedError


def test_build_run_stats_aggregates_both_clients(rulebook_path):
    screen_llm = _FakeLLM("screen-model", [CallStats(1.0, 100, 10, 110), CallStats(2.0, 200, 20, 220)])
    confirm_llm = _FakeLLM("confirm-model", [CallStats(3.0, 300, 30, 330)])

    stats = build_run_stats(
        profile="gemini_lite",
        backend="gemini",
        rulebook_path=rulebook_path,
        screen_llm=screen_llm,
        confirm_llm=confirm_llm,
        total_wall_seconds=10.0,
    )

    assert stats.profile == "gemini_lite"
    assert stats.screen_model == "screen-model"
    assert stats.verify_model == "confirm-model"
    assert stats.total_wall_seconds == 10.0
    assert len(stats.rulebook_hash) == 12
    assert stats.screen.call_count == 2
    assert stats.screen.elapsed_seconds == 3.0
    assert stats.screen.total_tokens == 330
    assert stats.confirm.call_count == 1
    assert stats.confirm.total_tokens == 330


def test_build_run_stats_handles_no_calls_yet(rulebook_path):
    screen_llm = _FakeLLM("screen-model", [])
    confirm_llm = _FakeLLM("confirm-model", [])

    stats = build_run_stats(
        profile="gemini_lite",
        backend="gemini",
        rulebook_path=rulebook_path,
        screen_llm=screen_llm,
        confirm_llm=confirm_llm,
        total_wall_seconds=0.0,
    )

    assert stats.screen.call_count == 0
    assert stats.screen.total_tokens is None


def test_hash_rulebook_is_deterministic(rulebook_path):
    from planqa_review.run_stats import hash_rulebook

    assert hash_rulebook(rulebook_path) == hash_rulebook(rulebook_path)
