from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from planqa_review.instrumentation import CallEvent
from planqa_review.llm.base import CallStats, LLMClient, total_elapsed_seconds, total_tokens


@dataclass(frozen=True, slots=True)
class ModelUsage:
    call_count: int
    elapsed_seconds: float
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class RunStats:
    """One review run's cost profile — the thing the user actually wants to compare across
    model/profile experiments alongside recall/precision from the eval agent. `profile`,
    the model names, and `rulebook_hash` are recorded here (not just in the output
    directory's timestamp) so a saved review.json is self-describing when comparing many
    runs later — the rulebook file's own "V1.0" label doesn't change even when its rule
    content does, so a content hash is the only reliable way to pin exactly which rulebook
    state produced a given result (cross-reference with `git log -p -- <rulebook path>`).

    `screen`/`confirm` stay as fixed fields since the CLI's two-client design (--screen-
    model/--verify-model) is still exactly two roles. `by_stage`/`by_tier`/`by_rule` are
    derived from the event log instead and make no assumption about how many roles or
    stages a given model profile actually uses — a future 3-stage profile (e.g. an added
    critic pass) just shows up as a third key in `by_stage`, no schema change needed."""

    profile: str
    backend: str
    screen_model: str
    verify_model: str
    rulebook_hash: str
    total_wall_seconds: float
    screen: ModelUsage
    confirm: ModelUsage
    by_stage: dict[str, ModelUsage]
    by_tier: dict[str, ModelUsage]
    by_rule: dict[str, ModelUsage]


def _usage_from_client(llm: LLMClient) -> ModelUsage:
    return ModelUsage(
        call_count=len(llm.usage),
        elapsed_seconds=total_elapsed_seconds(llm.usage),
        total_tokens=total_tokens(llm.usage),
    )


def _usage_from_stats(stats: list[CallStats]) -> ModelUsage:
    return ModelUsage(
        call_count=len(stats),
        elapsed_seconds=total_elapsed_seconds(stats),
        total_tokens=total_tokens(stats),
    )


def _group_by(events: Iterable[CallEvent], keys_of: Callable[[CallEvent], Iterable[str]]) -> dict[str, ModelUsage]:
    """A call spanning several keys (e.g. a batched screen call covering 5 rule_ids)
    attributes its full cost to *each* key — summing every bucket's `elapsed_seconds`/
    `total_tokens` does NOT reproduce the run total. That's intentional: the point is "how
    much did rule X cost across the run", not a non-overlapping partition of the total."""
    buckets: dict[str, list[CallStats]] = defaultdict(list)
    for event in events:
        for key in keys_of(event):
            buckets[key].append(event.stats)
    return {key: _usage_from_stats(stats) for key, stats in buckets.items()}


def usage_by_stage(events: Iterable[CallEvent]) -> dict[str, ModelUsage]:
    return _group_by(events, lambda event: (event.stage,))


def usage_by_tier(events: Iterable[CallEvent]) -> dict[str, ModelUsage]:
    return _group_by(events, lambda event: (event.tier.value if event.tier is not None else "(none)",))


def usage_by_rule(events: Iterable[CallEvent]) -> dict[str, ModelUsage]:
    return _group_by(events, lambda event: event.rule_ids or ("(none)",))


def hash_rulebook(rulebook_path: Path) -> str:
    return hashlib.sha256(rulebook_path.read_bytes()).hexdigest()[:12]


def build_run_stats(
    *,
    profile: str,
    backend: str,
    rulebook_path: Path,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
    total_wall_seconds: float,
    call_events: Iterable[CallEvent] = (),
) -> RunStats:
    events = tuple(call_events)
    return RunStats(
        profile=profile,
        backend=backend,
        screen_model=screen_llm.model,
        verify_model=confirm_llm.model,
        rulebook_hash=hash_rulebook(rulebook_path),
        total_wall_seconds=total_wall_seconds,
        screen=_usage_from_client(screen_llm),
        confirm=_usage_from_client(confirm_llm),
        by_stage=usage_by_stage(events),
        by_tier=usage_by_tier(events),
        by_rule=usage_by_rule(events),
    )
