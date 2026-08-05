from __future__ import annotations

import os
import time
from typing import Any

import httpx

from planqa_eval.llm.base import CallStats, LLMClient, parse_json_response

DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_HOST = "http://localhost:11434"


class OllamaClient(LLMClient):
    """Local Qwen backend via Ollama's REST API — no API key needed, but Ollama and the
    model must already be installed/pulled on this machine."""

    def __init__(self, model: str = DEFAULT_MODEL, host: str | None = None) -> None:
        self.model = model
        self._host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.usage: list[CallStats] = []

    def complete_json(self, *, system: str, prompt: str) -> Any:
        start = time.perf_counter()
        response = httpx.post(
            f"{self._host}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "format": "json",
                "stream": False,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        body = response.json()
        prompt_tokens = body.get("prompt_eval_count")
        completion_tokens = body.get("eval_count")
        self.usage.append(
            CallStats(
                elapsed_seconds=time.perf_counter() - start,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=(
                    prompt_tokens + completion_tokens if prompt_tokens is not None and completion_tokens is not None else None
                ),
            )
        )
        return parse_json_response(body["message"]["content"])
