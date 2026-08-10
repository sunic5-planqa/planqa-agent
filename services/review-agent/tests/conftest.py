from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from planqa_review.llm.base import CallStats, LLMClient

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
    LLM replies without any network access. `keyed_responses` backs `isolate()` (called by
    instrumentation.isolate_client(llm, key=...) when defined) for structures that run
    several branches concurrently (e.g. bundled_screen_hybrid's Paragraph/Document passes)
    — call order across branches isn't well-defined once they run on real threads, so tests
    route by branch identity (whatever key the structure passes to isolate_client) instead
    of by queue position. A missing key maps to an empty response list, mirroring a branch
    that's expected to make no call at all (e.g. confirm skipped because screen found no
    candidates for that branch)."""

    def __init__(
        self, responses: list[Any] | None = None, *, keyed_responses: dict[Any, list[Any]] | None = None
    ) -> None:
        self.model = "fake"
        self._responses = iter(responses or [])
        self.calls: list[dict[str, str]] = []
        self.usage: list[CallStats] = []
        self._keyed_responses = keyed_responses
        self.isolated: dict[Any, "ScriptedLLM"] = {}

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self.calls.append({"system": system, "prompt": prompt})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        return next(self._responses)

    def isolate(self, key: Any | None) -> "ScriptedLLM":
        # Callers that don't route by keyed_responses (i.e. every test not exercising a
        # concurrent-branch structure) get the same instance back, matching the plain
        # shared-client behavior those tests were already written against.
        if self._keyed_responses is None or key is None:
            return self
        child = ScriptedLLM(list(self._keyed_responses.get(key, [])))
        self.isolated[key] = child
        return child

    @property
    def all_calls(self) -> list[dict[str, str]]:
        return self.calls + [call for child in self.isolated.values() for call in child.calls]
