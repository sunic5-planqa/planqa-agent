from __future__ import annotations

import os
import time
from typing import Any

import anthropic

from planqa_review.llm.base import CallStats, LLMClient, parse_json_response

DEFAULT_MODEL = "claude-sonnet-5"

# Confirm-stage prompts repeat full chunk text per screened candidate (see confirmer.py),
# so a generous ceiling avoids truncating a legitimate multi-candidate response.
_DEFAULT_MAX_TOKENS = 8192
_MAX_ATTEMPTS = 4
_RETRY_DELAY_SECONDS = 5.0

# Models known to reject an explicit `temperature` outright (seen live: claude-sonnet-5 400s
# with "deprecated for this model") — extend as other models turn out to share the
# restriction. Anything not in this set gets `temperature` sent normally.
_NO_TEMPERATURE_MODELS = {"claude-sonnet-5"}


def _load_api_key(explicit: str | None) -> str:
    key = explicit or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("No Anthropic API key found — set ANTHROPIC_API_KEY in .env")
    return key


class AnthropicClient(LLMClient):
    """Direct Anthropic API access (not the mindlogic gateway) — for the demo confirm stage,
    where the team is paying for its own Claude credit rather than sharing gateway quota."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self.model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self.usage: list[CallStats] = []
        self._client = client or anthropic.Anthropic(api_key=_load_api_key(api_key))

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None) -> Any:
        # `system` is always static per-caller text in this codebase (a module-level
        # constant, never built per-call) — marking it as an ephemeral cache breakpoint is
        # free/safe and pays off across every call this process makes, not just within one
        # document. `cache_prefix`, when given, is the large text several concurrent
        # per-category calls share within one document (e.g. the tier's full chunk text) —
        # a second breakpoint so the *category-specific* suffix in `prompt` is all that's
        # billed at full price on the 2nd+ call. Both are no-ops (silently ignored, not an
        # error) if the combined prefix is under Anthropic's minimum cacheable length.
        system_blocks = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if cache_prefix:
            content: Any = [
                {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": prompt},
            ]
        else:
            content = prompt
        start = time.perf_counter()
        last_error: anthropic.APIError | ValueError | None = None
        for attempt in range(_MAX_ATTEMPTS):
            kwargs: dict[str, Any] = dict(
                model=self.model,
                max_tokens=self._max_tokens,
                # Extended thinking is on by default for this model and isn't useful for a
                # fixed-schema JSON QA task — seen live to roughly 10x call latency, and once
                # to burn the entire max_tokens budget on thinking with zero text left over
                # (a response containing only a ThinkingBlock). Disable it explicitly.
                thinking={"type": "disabled"},
                system=system_blocks,
                messages=[{"role": "user", "content": content}],
            )
            if self.model not in _NO_TEMPERATURE_MODELS:
                kwargs["temperature"] = self._temperature
            try:
                response = self._client.messages.create(**kwargs)
            except anthropic.APIStatusError as error:
                if error.status_code == 429 or error.status_code >= 500:
                    last_error = error
                    if attempt < _MAX_ATTEMPTS - 1:
                        time.sleep(_RETRY_DELAY_SECONDS)
                    continue
                raise
            except anthropic.APIConnectionError as error:
                # Covers APITimeoutError too — no status_code to inspect here, but a
                # connection-level failure/timeout is inherently transient, unlike a 4xx.
                last_error = error
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SECONDS)
                continue
            usage = response.usage
            self.usage.append(
                CallStats(
                    elapsed_seconds=time.perf_counter() - start,
                    prompt_tokens=usage.input_tokens,
                    completion_tokens=usage.output_tokens,
                    total_tokens=usage.input_tokens + usage.output_tokens,
                )
            )
            # claude-sonnet-5 can prepend a ThinkingBlock before the actual answer — the
            # real text isn't reliably at content[0], so scan for the first text block.
            text_block = next((block for block in response.content if block.type == "text"), None)
            try:
                if text_block is None:
                    raise ValueError(f"no text block in Anthropic response (types: {[b.type for b in response.content]})")
                return parse_json_response(text_block.text)
            except ValueError as error:
                # Seen live under concurrent load (several categories firing at once):
                # a 200 response with an empty or truncated text block, or malformed JSON
                # that survives `_repair_json` — the request succeeded (usage recorded
                # above, already billed) but the content itself was bad. Retrying the exact
                # same request has empirically fixed this (not deterministic despite
                # temperature=0.0), unlike a genuine prompt/schema bug which would fail
                # identically every time. json.JSONDecodeError is a ValueError subclass, so
                # this also catches `parse_json_response`'s repair-then-reraise failure.
                last_error = error
                if attempt < _MAX_ATTEMPTS - 1:
                    time.sleep(_RETRY_DELAY_SECONDS)
                continue
        raise last_error
