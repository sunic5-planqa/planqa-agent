from __future__ import annotations

import os
import time
from typing import Any

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from planqa_review.llm.base import CallStats, LLMClient, parse_json_response

DEFAULT_MODEL = "gemini-2.5-flash"

# The free tier caps out fast (as low as 5 RPM, or 20 requests/day on some models), and a
# batch run naturally fires many calls back to back. GEMINI_API_KEYS lets several free-tier
# keys/projects be round-robined to multiply the effective daily quota; _MAX_CYCLES guards
# against looping forever once every key is genuinely exhausted for the day.
_MAX_CYCLES = 3
_DEFAULT_RETRY_DELAY_SECONDS = 20.0


def _load_api_keys(explicit: list[str] | None) -> list[str]:
    if explicit:
        return explicit
    multi = os.environ.get("GEMINI_API_KEYS")
    if multi:
        keys = [key.strip() for key in multi.split(",") if key.strip()]
        if keys:
            return keys
    single = os.environ.get("GEMINI_API_KEY")
    if single:
        return [single]
    raise RuntimeError(
        "No Gemini API key found — set GEMINI_API_KEY (one key) or GEMINI_API_KEYS "
        "(comma-separated, to round-robin across multiple free-tier quotas) in .env"
    )


def _call_stats(response: Any, elapsed_seconds: float) -> CallStats:
    usage = response.usage_metadata
    return CallStats(
        elapsed_seconds=elapsed_seconds,
        prompt_tokens=usage.prompt_token_count if usage else None,
        completion_tokens=usage.candidates_token_count if usage else None,
        total_tokens=usage.total_token_count if usage else None,
    )


def _retry_delay_seconds(error: genai_errors.APIError) -> float:
    details = error.details if isinstance(error.details, dict) else {}
    for detail in details.get("error", {}).get("details", []):
        if detail.get("@type", "").endswith("RetryInfo"):
            raw = detail.get("retryDelay", "")
            if raw.endswith("s"):
                try:
                    return float(raw[:-1])
                except ValueError:
                    pass
    return _DEFAULT_RETRY_DELAY_SECONDS


class GeminiClient(LLMClient):
    # Defaults to 0.0 (not the API's own default) so re-running the same config for an
    # ablation comparison isn't confounded by sampling noise on top of the variable actually
    # being tested. Override explicitly if a run genuinely wants sampling diversity.
    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_keys: list[str] | None = None,
        temperature: float = 0.0,
    ) -> None:
        self.model = model
        self._clients = [genai.Client(api_key=key) for key in _load_api_keys(api_keys)]
        self._current = 0
        self._temperature = temperature
        self.usage: list[CallStats] = []

    def complete_json(self, *, system: str, prompt: str) -> Any:
        start = time.perf_counter()
        last_error: genai_errors.APIError | None = None
        for _cycle in range(_MAX_CYCLES):
            for _ in range(len(self._clients)):
                client = self._clients[self._current]
                try:
                    response = client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system,
                            response_mime_type="application/json",
                            temperature=self._temperature,
                        ),
                    )
                    # Elapsed includes any 429/5xx backoff above — a model that gets
                    # throttled a lot on the free tier really is slower in practice for
                    # this run.
                    self.usage.append(_call_stats(response, time.perf_counter() - start))
                    return parse_json_response(response.text)
                except genai_errors.ClientError as error:
                    if error.code != 429:
                        raise
                    last_error = error
                    self._current = (self._current + 1) % len(self._clients)
                except genai_errors.ServerError as error:
                    # 5xx ("model overloaded") is transient and unrelated to quota — worth
                    # retrying the same way as 429 rather than failing the whole run.
                    last_error = error
                    self._current = (self._current + 1) % len(self._clients)
            # every key hit an error this cycle — back off before cycling through again
            time.sleep(_retry_delay_seconds(last_error))
        raise last_error
