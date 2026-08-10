from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

_JSON_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

_HEX4 = re.compile(r"[0-9a-fA-F]{4}")
# \", \\, \/ are the only backslash escapes assumed intentional regardless of context —
# \b/\f/\n/\r/\t are control-character escapes a model is unlikely to *mean* when quoting
# verbatim Korean document text (original_text/quoted_text/fix_direction are short single-
# line spans), so they're treated the same as any other stray backslash below rather than
# trusted blindly: a prior version trusted them, which silently turned a quoted Windows
# path like "C:\Users\name" into "C:\Users" + a real newline + "ame" with no error raised.
_ALWAYS_VALID_ESCAPE = '"\\/'


def _repair_json(text: str) -> str:
    # Models occasionally emit invalid JSON despite being told "JSON only" — most commonly
    # a stray backslash (a Windows path, a regex fragment) that isn't a valid JSON escape,
    # or a trailing comma before a closing brace/bracket. Seen live across several pilot
    # runs: these silently dropped an entire category's results for that call (real API
    # cost, zero output). A blind regex pass over the raw text can't tell a JSON string's
    # content from its structure, so it can "fix" a comma or backslash that was actually
    # part of a quoted value — this walks the text once, tracking whether each character is
    # inside a JSON string, and only repairs escapes inside strings / commas outside them.
    out: list[str] = []
    in_string = False
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\":
                nxt = text[i + 1] if i + 1 < n else ""
                if nxt == "u" and _HEX4.match(text[i + 2 : i + 6] or ""):
                    out.append(text[i : i + 6])
                    i += 6
                    continue
                if nxt in _ALWAYS_VALID_ESCAPE:
                    out.append(text[i : i + 2])
                    i += 2
                    continue
                out.append("\\\\")  # not a recognized escape — the model meant a literal backslash
                i += 1
                continue
            if ch == '"':
                in_string = False
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1  # trailing comma before a close — drop it, keep the whitespace after
                continue
        out.append(ch)
        i += 1
    return "".join(out)


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

    # Sends `prompt` under `system` instructions and returns the parsed JSON response.
    # Callers must instruct the model (in `prompt`/`system`) to respond with JSON only.
    # Implementations append one CallStats to self.usage per successful call.
    #
    # `cache_prefix`, if given, is content that precedes `prompt` in the actual message —
    # split out for callers making several calls that share a large identical prefix (e.g.
    # cell3/category_fewshot/paragraph_verdict dispatching one call per category, all
    # sharing the same tier's chunk text) so a backend that supports prompt caching
    # (currently only AnthropicClient) can mark it as a cache breakpoint and avoid re-
    # billing/re-processing it on every call. Backends without caching support just
    # concatenate cache_prefix and prompt — behavior is identical to passing the combined
    # text as `prompt` alone, just organized differently for the caching-capable backend's
    # benefit.
    @abstractmethod
    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None) -> Any:
        ...


# Defensive parse for backends without a native JSON-only mode: strips ```json fences a
# model may still wrap its answer in despite instructions, then falls back to repairing
# common invalid-JSON patterns (see _repair_json) if the strict parse fails.
def parse_json_response(text: str) -> Any:
    cleaned = _JSON_FENCE.sub("", text.strip())
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return json.loads(_repair_json(cleaned))
