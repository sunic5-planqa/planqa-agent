from __future__ import annotations

from dataclasses import dataclass

from planqa_review.llm.base import LLMClient
from planqa_review.document import Chunk
from planqa_review.tiers import rules_for_tier
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Level

_SYSTEM = (
    "You are the cheap, wide first pass of a two-stage document QA pipeline (screen now, "
    "a stronger model verifies later) — favor recall over precision, flag anything even "
    "mildly suspicious. For each numbered chunk below, check it against the numbered rules "
    "and list every span that might violate one, however uncertain.\n"
    'Respond with JSON only: {"candidates": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"quoted_text": "<exact span from the chunk>", "reason": "<one short line>"}, ...]}'
)


@dataclass(frozen=True, slots=True)
class ScreenCandidate:
    chunk_index: int
    rule_id: str
    quoted_text: str
    reason: str


def _build_prompt(chunks: list[Chunk], rules: list[RuleDef], global_context: str) -> str:
    rule_block = "\n".join(f"{rule.rule_id}: {rule.text}" for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return f"{context_block}Rules to check:\n{rule_block}\n\nChunks:\n{chunk_block}\n\nReturn the candidates JSON."


def screen_tier(
    chunks: list[Chunk], rulebook: RuleBook, level: Level, global_context: str, llm: LLMClient
) -> list[ScreenCandidate]:
    """4단계 스크리닝 — one batched call per tier over every chunk at that tier, checked
    against every rule category §2 assigns to that tier."""
    rules = rules_for_tier(rulebook, level)
    if not chunks or not rules:
        return []

    response = llm.complete_json(system=_SYSTEM, prompt=_build_prompt(chunks, rules, global_context))
    raw_candidates = response.get("candidates", []) if isinstance(response, dict) else []

    valid_rule_ids = {rule.rule_id for rule in rules}
    candidates: list[ScreenCandidate] = []
    for item in raw_candidates:
        if not isinstance(item, dict):
            continue
        chunk_index, rule_id = item.get("chunk_index"), item.get("rule_id")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)):
            continue
        if rule_id not in valid_rule_ids:
            continue
        candidates.append(
            ScreenCandidate(
                chunk_index=chunk_index,
                rule_id=rule_id,
                quoted_text=str(item.get("quoted_text", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return candidates
