from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from planqa_eval.llm.base import LLMClient

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def xlsx_path() -> Path:
    return DATA_DIR / "qa_dataset" / "qa_dataset_2026-08-05.xlsx"


@pytest.fixture
def rulebook_path() -> Path:
    return DATA_DIR / "rulebook" / "rulebook_v1.0.md"


@pytest.fixture
def source_dir() -> Path:
    return DATA_DIR / "source_documents"


class ScriptedLLM(LLMClient):
    """Returns whatever `responses` yields next, in call order — lets tests script exact
    LLM replies without any network access."""

    def __init__(self, responses: list[Any]) -> None:
        self.model = "fake"
        self._responses = iter(responses)
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self.calls.append({"system": system, "prompt": prompt})
        return next(self._responses)


class BrokenBatchLLM(LLMClient):
    """First call raises json.JSONDecodeError (simulating a small local model garbling a
    large batch response), every call after that returns the next scripted reply — lets
    tests verify batch-then-per-item fallback survives a totally unparseable batch response,
    not just one with a missing index."""

    def __init__(self, responses: list[Any]) -> None:
        self.model = "broken-batch"
        self._responses = iter(responses)
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self.calls.append({"system": system, "prompt": prompt})
        if len(self.calls) == 1:
            raise json.JSONDecodeError("simulated garbled batch response", "", 0)
        return next(self._responses)
