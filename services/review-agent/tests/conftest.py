from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from planqa_review.llm.base import CallStats, LLMClient
from planqa_review.tiers import TIER_ORDER

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def rulebook_path() -> Path:
    return DATA_DIR / "rulebook" / "rulebook_v1.0.md"


@pytest.fixture
def source_dir() -> Path:
    return DATA_DIR / "source_documents"


@pytest.fixture
def qa_dataset_path() -> Path:
    return DATA_DIR / "qa_dataset" / "qa_dataset_frozen.xlsx"


class ScriptedLLM(LLMClient):
    """Returns whatever `responses` yields next, in call order — lets tests script exact
    LLM replies without any network access. `tier_responses` (aligned to TIER_ORDER) backs
    clone(tier=...) for tests that exercise category_screen.review_document's concurrent
    tier loop, where call order across tiers is no longer deterministic — a None/missing
    entry means that tier's clone should see no calls at all (mirrors a tier whose screening
    pass found nothing, so confirm is never invoked for it)."""

    def __init__(self, responses: list[Any] | None = None, *, tier_responses: list[Any] | None = None) -> None:
        self.model = "fake"
        self._responses = iter(responses or [])
        self.calls: list[dict[str, str]] = []
        self.usage: list[CallStats] = []
        self._tier_responses = tier_responses
        self.clones: dict[Any, "ScriptedLLM"] = {}

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        return next(self._responses)

    def clone(self, *, tier: Any | None = None) -> "ScriptedLLM":
        # Callers that don't route by tier_responses (i.e. every test not exercising
        # category_screen's parallel path) get the same instance back, matching the plain
        # shared-client behavior those tests were already written against.
        if self._tier_responses is None or tier is None:
            return self
        idx = TIER_ORDER.index(tier)
        value = self._tier_responses[idx] if idx < len(self._tier_responses) else None
        child = ScriptedLLM([value] if value is not None else [])
        self.clones[tier] = child
        return child

    @property
    def all_calls(self) -> list[dict[str, str]]:
        return self.calls + [call for child in self.clones.values() for call in child.calls]
