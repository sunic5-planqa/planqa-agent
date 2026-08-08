from __future__ import annotations

from typing import Any

from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.llm.base import CallStats, LLMClient
from planqa_schemas.schema import Level


class _FakeLLM(LLMClient):
    def __init__(self, usage_per_call: list[list[CallStats]]) -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self._usage_per_call = iter(usage_per_call)

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self.usage.extend(next(self._usage_per_call))
        return {"ok": True}


def test_record_call_tags_the_stats_appended_by_this_call():
    llm = _FakeLLM([[CallStats(1.0, 10, 5, 15)]])
    events: list[CallEvent] = []

    result = record_call(
        llm, stage="screen", tier=Level.PARAGRAPH, rule_ids=("MI-01", "TM-03"), events=events, call=lambda: llm.complete_json(system="", prompt="")
    )

    assert result == {"ok": True}
    assert len(events) == 1
    assert events[0].stage == "screen"
    assert events[0].tier == Level.PARAGRAPH
    assert events[0].rule_ids == ("MI-01", "TM-03")
    assert events[0].stats.total_tokens == 15


def test_record_call_only_tags_new_usage_entries_not_prior_ones():
    llm = _FakeLLM([[CallStats(2.0, 20, 10, 30)]])
    llm.usage.append(CallStats(9.0, 900, 900, 1800))  # pre-existing, from an earlier call
    events: list[CallEvent] = []

    record_call(llm, stage="confirm", tier=Level.DOCUMENT, rule_ids=("GA-03",), events=events, call=lambda: llm.complete_json(system="", prompt=""))

    assert len(events) == 1
    assert events[0].stats.total_tokens == 30


def test_record_call_appends_nothing_when_the_call_makes_no_llm_request():
    llm = _FakeLLM([])
    events: list[CallEvent] = []

    result = record_call(llm, stage="confirm", tier=Level.SENTENCE, rule_ids=(), events=events, call=lambda: "no-op")

    assert result == "no-op"
    assert events == []


def test_record_call_tags_multiple_stats_if_a_call_appends_more_than_one():
    llm = _FakeLLM([[CallStats(1.0, 1, 1, 2), CallStats(2.0, 2, 2, 4)]])
    events: list[CallEvent] = []

    record_call(llm, stage="screen", tier=None, rule_ids=("AE-01",), events=events, call=lambda: llm.complete_json(system="", prompt=""))

    assert len(events) == 2
    assert {e.stats.total_tokens for e in events} == {2, 4}
