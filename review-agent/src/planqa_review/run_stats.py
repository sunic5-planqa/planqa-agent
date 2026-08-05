from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from planqa_review.llm.base import LLMClient, total_elapsed_seconds, total_tokens


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
    state produced a given result (cross-reference with `git log -p -- <rulebook path>`)."""

    profile: str
    backend: str
    screen_model: str
    verify_model: str
    rulebook_hash: str
    total_wall_seconds: float
    screen: ModelUsage
    confirm: ModelUsage


def _usage_from_client(llm: LLMClient) -> ModelUsage:
    return ModelUsage(
        call_count=len(llm.usage),
        elapsed_seconds=total_elapsed_seconds(llm.usage),
        total_tokens=total_tokens(llm.usage),
    )


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
) -> RunStats:
    return RunStats(
        profile=profile,
        backend=backend,
        screen_model=screen_llm.model,
        verify_model=confirm_llm.model,
        rulebook_hash=hash_rulebook(rulebook_path),
        total_wall_seconds=total_wall_seconds,
        screen=_usage_from_client(screen_llm),
        confirm=_usage_from_client(confirm_llm),
    )
