from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from planqa_review.llm.base import CallStats, LLMClient
from planqa_review.schema import Level

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


def record_call(
    llm: LLMClient, *, stage: str, tier: Level | None, rule_ids: tuple[str, ...], events: list[CallEvent], call: Callable[[], T]
) -> T:
    """Runs `call` (expected to append exactly one CallStats to llm.usage on success — true
    for every LLMClient in this repo) and tags whatever got appended with this call's
    semantic context. Wrapping like this means screener.py/confirmer.py/context.py need no
    changes at all — the orchestrator (pipeline.py) already knows the tier/rules and is the
    only thing that needs updating to get attribution."""
    before = len(llm.usage)
    result = call()
    for stats in llm.usage[before:]:
        events.append(CallEvent(stage=stage, tier=tier, rule_ids=rule_ids, stats=stats))
    return result
