from __future__ import annotations

import threading
import time
from typing import Any

from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import CallStats, LLMClient
from planqa_review.schema import Level


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


class _SlowSharedLLM(LLMClient):
    """Appends to `usage` only after a barrier-synchronized delay, so concurrent callers'
    append windows deliberately overlap — reproduces the real GeminiClient/AnthropicClient
    situation (network latency between call-start and the eventual `usage.append`)."""

    def __init__(self, worker_count: int) -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self._barrier = threading.Barrier(worker_count)

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self._barrier.wait()  # every worker reaches record_call's `before` snapshot together
        time.sleep(0.05)  # then all append at roughly the same moment
        self.usage.append(CallStats(1.0, 1, 1, 2))
        return {"ok": True}


def test_record_call_double_counts_under_real_concurrency_without_isolation():
    """Documents the bug isolate_client/merge_usage fix: several threads sharing one LLM
    instance and calling record_call directly on it race on the before/after `usage` diff,
    so the total events recorded balloons past the true number of calls made."""
    worker_count = 5
    llm = _SlowSharedLLM(worker_count)
    events: list[CallEvent] = []

    def worker():
        record_call(llm, stage="screen", tier=None, rule_ids=(), events=events, call=lambda: llm.complete_json(system="", prompt=""))

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(llm.usage) == worker_count  # the real number of calls made
    assert len(events) > worker_count  # but bookkeeping over-attributed them


def test_isolate_client_and_merge_usage_prevent_double_counting_under_concurrency():
    worker_count = 5
    llm = _SlowSharedLLM(worker_count)
    events: list[CallEvent] = []

    def worker():
        isolated = isolate_client(llm)
        try:
            record_call(isolated, stage="screen", tier=None, rule_ids=(), events=events, call=lambda: isolated.complete_json(system="", prompt=""))
        finally:
            merge_usage(llm, isolated)

    threads = [threading.Thread(target=worker) for _ in range(worker_count)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(llm.usage) == worker_count
    assert len(events) == worker_count
