from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class CallStats:
    """One successful complete_json() call's cost — wall time includes any internal retry/
    backoff sleep, since that's a real cost of choosing this backend/model, not noise to
    strip out (a free-tier model that gets rate-limited a lot really is slower in practice).
    Token fields are None when a backend doesn't report them."""

    elapsed_seconds: float
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None


def total_elapsed_seconds(usage: list[CallStats]) -> float:
    return sum(call.elapsed_seconds for call in usage)


def total_tokens(usage: list[CallStats]) -> int | None:
    known = [call.total_tokens for call in usage if call.total_tokens is not None]
    return sum(known) if known else None


class LLMClient(ABC):
    """Every screener/confirmer/context call goes through this — swap the backend by
    changing PLANQA_LLM_BACKEND (see llm/factory.py), not by touching the modules that
    use it. This is review-agent's own copy (kept independent of eval-agent's llm/ package,
    which this repo's owner must not modify) with call-level usage tracking built in — see
    docs/review_agent_architecture.md."""

    model: str
    usage: list[CallStats]

    @abstractmethod
    def complete_json(self, *, system: str, prompt: str) -> Any:
        """Sends `prompt` under `system` instructions and returns the parsed JSON response.
        Callers must instruct the model (in `prompt`/`system`) to respond with JSON only.
        Implementations append one CallStats to self.usage per successful call."""


def parse_json_response(text: str) -> Any:
    """Defensive parse for backends without a native JSON-only mode: strips ```json fences
    a model may still wrap its answer in despite instructions."""
    cleaned = _JSON_FENCE.sub("", text.strip())
    return json.loads(cleaned)
