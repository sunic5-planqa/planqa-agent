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


def _system_blocks(system: str) -> list[dict[str, Any]]:
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _message_content(prompt: str, cache_prefix: str | None) -> Any:
    if not cache_prefix:
        return prompt
    return [
        {"type": "text", "text": cache_prefix, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": prompt},
    ]


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
        system_blocks = _system_blocks(system)
        content = _message_content(prompt, cache_prefix)
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


# Batch API primitives (50% cheaper than complete_json's per-call price, at the cost of
# unpredictable completion time — official SLA is 24h with no progress visibility while
# in flight). These are standalone functions, not AnthropicClient methods, because a batch
# is inherently many independent (custom_id, request) pairs submitted together, not one
# call — see docs/progress.md 2026-08-12 for why review_document()'s 3 internal stages
# (context/screen/confirm) aren't actually wired to submit through these yet (context's
# result feeds screen's prompt, so they can't be two independent same-batch requests without
# either dropping that dependency or adding a 4th batch stage — a real design gap found
# while building this, not implemented this session). Kept as tested, ready building blocks
# for whichever of those approaches a future session picks.
def build_batch_request(
    custom_id: str,
    system: str,
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    cache_prefix: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = _DEFAULT_MAX_TOKENS,
) -> dict[str, Any]:
    params: dict[str, Any] = dict(
        model=model,
        max_tokens=max_tokens,
        thinking={"type": "disabled"},
        system=_system_blocks(system),
        messages=[{"role": "user", "content": _message_content(prompt, cache_prefix)}],
    )
    if model not in _NO_TEMPERATURE_MODELS:
        params["temperature"] = temperature
    return {"custom_id": custom_id, "params": params}


def submit_batch(client: anthropic.Anthropic, requests: list[dict[str, Any]]) -> str:
    batch = client.messages.batches.create(requests=requests)
    return batch.id


# `processing_status` becomes "ended" once every request in the batch has succeeded, errored,
# been canceled, or expired — `request_counts.processing` reaching 0 is the same signal, kept
# in the return value so a caller can log/report partial progress while polling.
def poll_batch(client: anthropic.Anthropic, batch_id: str) -> tuple[bool, dict[str, int]]:
    batch = client.messages.batches.retrieve(batch_id)
    counts = batch.request_counts
    done = batch.processing_status == "ended"
    return done, {
        "processing": counts.processing,
        "succeeded": counts.succeeded,
        "errored": counts.errored,
        "canceled": counts.canceled,
        "expired": counts.expired,
    }


# Explicit cancellation, not just abandoning the poll loop — an uncancelled batch keeps
# processing (and billing) in the background even after this process stops watching it.
def cancel_batch(client: anthropic.Anthropic, batch_id: str) -> None:
    client.messages.batches.cancel(batch_id)


# Returns {custom_id: parsed_json_or_None} — None marks a request this batch didn't produce
# usable JSON for (errored/canceled/expired, or a succeeded response with no parseable text
# block), so callers can fall back to a synchronous retry for exactly those custom_ids
# instead of re-running the whole batch.
def fetch_batch_results(client: anthropic.Anthropic, batch_id: str) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for entry in client.messages.batches.results(batch_id):
        if entry.result.type != "succeeded":
            results[entry.custom_id] = None
            continue
        text_block = next((block for block in entry.result.message.content if block.type == "text"), None)
        try:
            results[entry.custom_id] = parse_json_response(text_block.text) if text_block is not None else None
        except ValueError:
            results[entry.custom_id] = None
    return results
