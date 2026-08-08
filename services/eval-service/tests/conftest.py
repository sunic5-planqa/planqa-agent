from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from planqa_eval_service.llm.base import LLMClient
from planqa_schemas.rulebook import RuleBook, parse_rulebook

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def rulebook() -> RuleBook:
    return parse_rulebook(DATA_DIR / "rulebook_v1.0.md")


class ScriptedLLM(LLMClient):
    """Returns whatever `responses` yields next, in call order — same pattern as
    tools/eval-agent's/review-agent's own conftest.py fakes, reimplemented here (not
    imported, per the workspace's no-cross-service-import convention)."""

    def __init__(self, responses: list[Any]) -> None:
        self.model = "fake"
        self._responses = iter(responses)
        self.calls: list[dict[str, str]] = []

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self.calls.append({"system": system, "prompt": prompt})
        return next(self._responses)
