from __future__ import annotations

import os
import time
from typing import Any

import httpx

from planqa_review.llm.base import CallStats, LLMClient, parse_json_response

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_BASE_URL = "https://factchat-cloud.mindlogic.ai/v1/gateway"

# Cloudflare fronts this gateway and blocks httpx's default User-Agent outright (error 1010,
# a bot-fingerprint rule, not an auth check) — a browser-shaped UA is enough to pass it.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

_MAX_ATTEMPTS = 4
_RETRY_DELAY_SECONDS = 5.0


def _load_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get("MINDLOGIC_GATEWAY_API_KEY")
    if not key:
        raise RuntimeError("No gateway API key found — set MINDLOGIC_GATEWAY_API_KEY in .env")
    return key


class GatewayClient(LLMClient):
    """One OpenAI-compatible REST endpoint fronting many providers (Claude/GPT/Gemini/
    EXAONE/Solar/...) behind a single API key — see docs/review_agent_architecture.md's
    model-pilot section. `model` is any id from `GET /v1/gateway/models/`."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        temperature: float = 0.0,
        base_url: str = DEFAULT_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self.usage: list[CallStats] = []
        self._client = client or httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {_load_api_key(api_key)}", "User-Agent": _USER_AGENT},
            # EXAONE (236B) measured 60s+ on a trivial one-line prompt during smoke testing —
            # real pipeline prompts (full document + rules) need real headroom above that.
            timeout=240.0,
        )

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None) -> Any:
        # No prompt-caching support here — just concatenate, same as passing the combined
        # text as `prompt` alone.
        full_prompt = f"{cache_prefix}\n\n{prompt}" if cache_prefix else prompt
        start = time.perf_counter()
        last_error: httpx.HTTPStatusError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            response = self._client.post(
                "/chat/completions/",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": full_prompt},
                    ],
                    "temperature": self._temperature,
                },
            )
            if response.status_code == 429 or response.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"{response.status_code} from gateway", request=response.request, response=response
                )
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SECONDS)
                continue
            response.raise_for_status()
            body = response.json()
            usage = body.get("usage") or {}
            self.usage.append(
                CallStats(
                    elapsed_seconds=time.perf_counter() - start,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens"),
                )
            )
            return parse_json_response(body["choices"][0]["message"]["content"])
        raise last_error
