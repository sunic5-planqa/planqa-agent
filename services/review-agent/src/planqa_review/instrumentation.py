from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from planqa_review.llm.base import CallStats, LLMClient
from planqa_schemas.schema import Level

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class CallEvent:
    """One LLM call, tagged with what it was for — the thing per-rule/per-category cost
    analysis is built on. `rule_ids` is whatever the caller actually asked about in that
    call: today (gemini_lite) that's every rule assigned to the tier, since screen/confirm
    batch a whole tier per call; a finer-grained future profile that calls per-category or
    per-rule would naturally produce narrower `rule_ids` here, with no changes needed on
    the analysis side. A call spanning N rules attributes its full cost to each of the N —
    summing per-rule costs does NOT equal the run total, by design (see run_stats.py)."""

    stage: str  # "context" | "screen" | "confirm" | profile-defined stage names
    tier: Level | None
    rule_ids: tuple[str, ...]
    stats: CallStats


# record_call runs `call` (expected to append exactly one CallStats to llm.usage on
# success — true for every LLMClient in this repo) and tags whatever got appended with this
# call's semantic context. Wrapping like this means screener.py/confirmer.py/context.py
# need no changes at all — the orchestrator (pipeline.py) already knows the tier/rules and
# is the only thing that needs updating to get attribution.
#
# NOT thread-safe when several concurrent record_call()s share the same `llm` instance — the
# before/after llm.usage length diff races with other threads' appends to the same list,
# silently mis-attributing (and inflating) call counts across categories/rules. Any
# structure that dispatches concurrently (concurrent.futures, asyncio, etc.) over a shared
# screen/confirm client MUST route each concurrent branch through isolate_client() below
# instead of calling this directly on the shared instance — see cell3.py for the pattern. A
# structure that only ever calls this sequentially (one call at a time, no concurrent
# dispatch) needs no such wrapping.
def record_call(
    llm: LLMClient, *, stage: str, tier: Level | None, rule_ids: tuple[str, ...], events: list[CallEvent], call: Callable[[], T]
) -> T:
    before = len(llm.usage)
    result = call()
    for stats in llm.usage[before:]:
        events.append(CallEvent(stage=stage, tier=tier, rule_ids=rule_ids, stats=stats))
    return result


# Gives each concurrent branch (one per category/rule/tier/etc.) its own private usage
# accumulator before passing it to record_call, so branches sharing one real client (same
# API keys/HTTP session, still reused by reference) never race on the same usage list.
# Merge the isolated copy's usage back onto the original with merge_usage once the branch
# finishes, so the original client's own .usage (what run_stats.build_run_stats reads for
# the top-level screen/confirm totals) still reflects every call made through it.
#
# `key` identifies which concurrent branch is asking (e.g. a Level) — real backends ignore
# it and just get a plain shallow copy (a fresh usage list is all they need; each call is a
# live network round-trip, nothing else to isolate). Test doubles that need to route
# scripted responses by branch identity instead of by call order (no longer well-defined
# once branches run on real threads) can define `isolate(self, key)` themselves — see
# conftest.ScriptedLLM — which this calls instead of the default copy.copy() when present.
def isolate_client(llm: LLMClient, *, key: object | None = None) -> LLMClient:
    isolate = getattr(llm, "isolate", None)
    if callable(isolate):
        return isolate(key)
    isolated = copy.copy(llm)
    isolated.usage = []
    return isolated


# Reverses isolate_client: folds an isolated copy's calls back onto the shared client's own
# usage list. list.extend is a single atomic step under the GIL, so this is safe to call
# from several threads concurrently even though `original` is shared.
def merge_usage(original: LLMClient, isolated: LLMClient) -> None:
    original.usage.extend(isolated.usage)
