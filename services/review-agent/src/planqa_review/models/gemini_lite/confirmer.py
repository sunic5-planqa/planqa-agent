from __future__ import annotations

from planqa_review.llm.base import LLMClient
from planqa_review.document import Chunk
from planqa_review.models.gemini_lite.screener import ScreenCandidate
from planqa_schemas.rulebook import RuleBook, RuleDef
from planqa_schemas.schema import Issue, Level
from planqa_review.verifier import has_valid_reference_exception

_CRITERIA = (
    "Decide, precisely this time, whether the flagged span actually violates the rule — "
    "the screening pass over-flags on purpose, so most candidates should come back "
    "violated=false. If it does violate: quote the exact evidence sentence from the "
    "document (original_text), state what's wrong (description), explain why it breaks "
    "the rule (rationale), and write a concrete revised version of the text that would fix "
    "it (fix_direction) — phrase it as a suggestion, not a command. Also apply the rule's "
    "own exception condition if given; set excused=true (with excuse_reason) when it "
    "applies."
)

_SYSTEM = (
    "You are the precise, expensive second pass of a two-stage document QA pipeline. "
    f"{_CRITERIA}\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>"}, ...]}'
)


def _candidate_block(index: int, candidate: ScreenCandidate, chunk: Chunk, rule: RuleDef) -> str:
    return (
        f"[{index}] rule {rule.rule_id} ({rule.category_label}): {rule.text}\n"
        f"  exception condition: {rule.exception_text or '없음'}\n"
        f"  location: {chunk.location}\n"
        f"  full unit text: {chunk.text!r}\n"
        f"  screened span: {candidate.quoted_text!r} (screening reason: {candidate.reason})"
    )


def _build_prompt(candidates: list[tuple[ScreenCandidate, Chunk, RuleDef]], global_context: str) -> str:
    blocks = "\n\n".join(_candidate_block(i, c, chunk, rule) for i, (c, chunk, rule) in enumerate(candidates))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return f"{context_block}{blocks}\n\nReturn the verdicts JSON."


def _is_reference_excused(rule_id: str, rulebook: RuleBook, original_text: str, doc_id: str, level: Level, location: str, source_text: str) -> bool:
    """§3: reference-citation exception rules (LG-04/TC-02/AE-01/GA-03) are decided by the
    deterministic proxy the eval-agent already validated (verifier.py), not by the LLM's
    own excused claim — see docs/review_agent_architecture.md."""
    if rule_id not in rulebook.reference_exception_rule_ids:
        return False
    probe = Issue(
        doc_id=doc_id, level=level.value, rule_id=rule_id, location=location, description="", original_text=original_text
    )
    return has_valid_reference_exception(probe, source_text)


def _issue_from_verdict(
    values: dict, candidate: ScreenCandidate, chunk: Chunk, rule: RuleDef, doc_id: str, level: Level, source_text: str, rulebook: RuleBook
) -> Issue | None:
    if not values.get("violated"):
        return None

    original_text = str(values.get("original_text") or candidate.quoted_text).strip()
    excused = bool(values.get("excused")) or _is_reference_excused(
        rule.rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
    )
    if excused:
        return None

    return Issue(
        doc_id=doc_id,
        level=level.value,
        rule_id=rule.rule_id,
        location=chunk.location,
        description=str(values.get("description") or "").strip(),
        source="review_agent",
        original_text=original_text,
        rationale=str(values.get("rationale") or "").strip() or None,
        fix_direction=str(values.get("fix_direction") or "").strip() or None,
    )


def confirm_candidates(
    candidates: list[ScreenCandidate],
    chunks: list[Chunk],
    rulebook: RuleBook,
    doc_id: str,
    level: Level,
    global_context: str,
    source_text: str,
    llm: LLMClient,
) -> list[Issue]:
    """4단계 정밀판정 — one batched call per tier over every screened candidate. Candidates
    whose rule no longer exists (shouldn't happen, screener already filters) are skipped."""
    resolved: list[tuple[ScreenCandidate, Chunk, RuleDef]] = []
    for candidate in candidates:
        rule = rulebook.rule(candidate.rule_id)
        if rule is None or candidate.chunk_index >= len(chunks):
            continue
        resolved.append((candidate, chunks[candidate.chunk_index], rule))
    if not resolved:
        return []

    response = llm.complete_json(system=_SYSTEM, prompt=_build_prompt(resolved, global_context))
    raw_verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw_verdicts if isinstance(item, dict) and "index" in item}

    issues: list[Issue] = []
    for i, (candidate, chunk, rule) in enumerate(resolved):
        values = by_index.get(i)
        if values is None:
            continue  # dropped from a malformed/partial batch response — screen already erred on recall's side
        issue = _issue_from_verdict(values, candidate, chunk, rule, doc_id, level, source_text, rulebook)
        if issue is not None:
            issues.append(issue)
    return issues
