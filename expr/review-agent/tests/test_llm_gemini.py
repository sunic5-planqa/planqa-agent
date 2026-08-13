from __future__ import annotations

from planqa_review.instrumentation import isolate_client
from planqa_review.llm.gemini import GeminiClient


def test_isolate_client_shares_key_rotation_state_across_concurrent_copies():
    # Regression test for a real bug found in code review: GeminiClient's key-rotation
    # index used to be a plain int, which copy.copy() (isolate_client's default path)
    # copies by value — each concurrently-dispatched pass would silently get its own
    # disconnected rotation index, so quota-avoiding progress learned by one pass (e.g. "key
    # 0 just 429'd, move on") never reached the other pass or the original client.
    llm = GeminiClient(api_keys=["fake-key-1", "fake-key-2"])
    isolated_a = isolate_client(llm, key="paragraph")
    isolated_b = isolate_client(llm, key="document")

    assert isolated_a._current is llm._current
    assert isolated_b._current is llm._current

    with isolated_a._current_lock:
        isolated_a._current[0] = 1

    assert llm._current[0] == 1
    assert isolated_b._current[0] == 1


def test_isolate_client_still_keeps_usage_independent_per_copy():
    llm = GeminiClient(api_keys=["fake-key-1"])
    isolated_a = isolate_client(llm, key="paragraph")
    isolated_b = isolate_client(llm, key="document")

    assert isolated_a.usage is not llm.usage
    assert isolated_a.usage is not isolated_b.usage
