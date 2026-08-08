from __future__ import annotations

from typing import Any

from planqa_review.instrumentation import CallEvent
from planqa_review.llm.base import CallStats, LLMClient
from planqa_review.run_stats import build_run_stats, usage_by_rule, usage_by_stage, usage_by_tier
from planqa_schemas.schema import Level


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


def _event(stage: str, tier: Level | None, rule_ids: tuple[str, ...], tokens: int) -> CallEvent:
    return CallEvent(stage=stage, tier=tier, rule_ids=rule_ids, stats=CallStats(1.0, tokens // 2, tokens // 2, tokens))


def test_usage_by_stage_groups_across_tiers():
    events = [
        _event("screen", Level.DOCUMENT, ("LG-01",), 100),
        _event("screen", Level.PARAGRAPH, ("MI-01",), 50),
        _event("confirm", Level.DOCUMENT, ("LG-01",), 200),
    ]
    result = usage_by_stage(events)
    assert result["screen"].call_count == 2
    assert result["screen"].total_tokens == 150
    assert result["confirm"].call_count == 1


def test_usage_by_tier_treats_context_stage_as_none_bucket():
    events = [_event("context", None, (), 40), _event("screen", Level.SENTENCE, ("AE-01",), 60)]
    result = usage_by_tier(events)
    assert result["(none)"].total_tokens == 40
    assert result["Sentence"].total_tokens == 60


def test_usage_by_rule_attributes_full_call_cost_to_every_rule_covered():
    events = [_event("screen", Level.DOCUMENT, ("LG-01", "MI-01"), 100)]
    result = usage_by_rule(events)
    # both rules were covered by the SAME batched call, so each gets the full cost —
    # the two buckets deliberately don't sum back to the run total.
    assert result["LG-01"].total_tokens == 100
    assert result["MI-01"].total_tokens == 100


def test_build_run_stats_populates_breakdowns_from_call_events(rulebook_path):
    screen_llm = _FakeLLM("screen-model", [CallStats(1.0, 50, 50, 100)])
    confirm_llm = _FakeLLM("confirm-model", [])
    events = [_event("screen", Level.DOCUMENT, ("LG-01",), 100)]

    stats = build_run_stats(
        profile="gemini_lite",
        backend="gemini",
        rulebook_path=rulebook_path,
        screen_llm=screen_llm,
        confirm_llm=confirm_llm,
        total_wall_seconds=1.0,
        call_events=events,
    )

    assert stats.by_stage["screen"].total_tokens == 100
    assert stats.by_tier["Document"].total_tokens == 100
    assert stats.by_rule["LG-01"].total_tokens == 100
