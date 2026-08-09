from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document
from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.models.gemini_lite.context import extract_global_context
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.tiers import TIER_ORDER, rules_for_tier
from planqa_review.verifier import has_valid_reference_exception

# 셀3R (방안2, 룰 단위 세분화): 셀3과 똑같은 tier 청킹이지만, 디스패치 단위가 카테고리가
# 아니라 개별 룰이다 — tool-calling은 여전히 없음(셀4로 가기 전, "세분도"와 "tool-calling
# 도입"을 분리해서 보기 위해 끼워 넣은 중간 지점). 셀3.py와 거의 동일한 구조지만, 이미
# 만든 구조(셀3)는 손대지 않는다는 원칙 때문에 참고해서 새 파일로 복제/수정했다.

_SCREEN_SYSTEM = (
    "You are the cheap, wide first pass of a two-stage document QA pipeline (screen now, "
    "a stronger model verifies later) — favor recall over precision, flag anything even "
    "mildly suspicious. For each numbered chunk below, check it against the rule and list "
    "every span that might violate it, however uncertain.\n"
    'Respond with JSON only: {"candidates": [{"chunk_index": <int>, "quoted_text": '
    '"<exact span from the chunk>", "reason": "<one short line>"}, ...]}'
)

_CONFIRM_SYSTEM = (
    "You are the precise, expensive second pass of a two-stage document QA pipeline. "
    "Decide, precisely this time, whether the flagged span actually violates the rule — "
    "the screening pass over-flags on purpose, so most candidates should come back "
    "violated=false. If it does violate: quote the exact evidence sentence from the "
    "document (original_text), state what's wrong (description), explain why it breaks "
    "the rule (rationale), and write a concrete revised version of the text that would fix "
    "it (fix_direction) — phrase it as a suggestion, not a command. Also apply the rule's "
    "own exception condition if given; set excused=true (with excuse_reason) when it "
    "applies.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>"}, ...]}'
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    chunk_index: int
    quoted_text: str
    reason: str


def _screen_rule(chunks: list[Chunk], rule: RuleDef, global_context: str, llm: LLMClient) -> list[_Candidate]:
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}Rule to check: {rule.rule_id}: {rule.text}\n\nChunks:\n{chunk_block}\n\nReturn the candidates JSON."

    response = llm.complete_json(system=_SCREEN_SYSTEM, prompt=prompt)
    raw = response.get("candidates", []) if isinstance(response, dict) else []

    candidates: list[_Candidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chunk_index = item.get("chunk_index")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)):
            continue
        candidates.append(
            _Candidate(chunk_index=chunk_index, quoted_text=str(item.get("quoted_text", "")).strip(), reason=str(item.get("reason", "")).strip())
        )
    return candidates


def _is_reference_excused(rule_id: str, rulebook: RuleBook, original_text: str, doc_id: str, level: Level, location: str, source_text: str) -> bool:
    """Same §3 deterministic proxy gemini_lite's confirmer.py / cell3.py use — duplicated
    per the additive-only rule (no structure may depend on another structure's file)."""
    if rule_id not in rulebook.reference_exception_rule_ids:
        return False
    probe = Issue(doc_id=doc_id, level=level.value, rule_id=rule_id, location=location, description="", original_text=original_text)
    return has_valid_reference_exception(probe, source_text)


def _confirm_rule(
    candidates: list[_Candidate], chunks: list[Chunk], rule: RuleDef, doc_id: str, level: Level, global_context: str, source_text: str, rulebook: RuleBook, llm: LLMClient
) -> list[Issue]:
    blocks = []
    for i, candidate in enumerate(candidates):
        chunk = chunks[candidate.chunk_index]
        blocks.append(
            f"[{i}] rule {rule.rule_id} ({rule.category_label}): {rule.text}\n"
            f"  exception condition: {rule.exception_text or '없음'}\n"
            f"  location: {chunk.location}\n"
            f"  full unit text: {chunk.text!r}\n"
            f"  screened span: {candidate.quoted_text!r} (screening reason: {candidate.reason})"
        )
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}{chr(10).join(blocks)}\n\nReturn the verdicts JSON."

    response = llm.complete_json(system=_CONFIRM_SYSTEM, prompt=prompt)
    raw_verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw_verdicts if isinstance(item, dict) and "index" in item}

    issues: list[Issue] = []
    for i, candidate in enumerate(candidates):
        values = by_index.get(i)
        if values is None or not values.get("violated"):
            continue
        original_text = str(values.get("original_text") or candidate.quoted_text).strip()
        chunk = chunks[candidate.chunk_index]
        excused = bool(values.get("excused")) or _is_reference_excused(rule.rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text)
        if excused:
            continue
        issues.append(
            Issue(
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
        )
    return issues


def _review_rule(
    level: Level, chunks: list[Chunk], rule: RuleDef, global_context: str, doc_id: str, source_text: str, rulebook: RuleBook,
    screen_llm: LLMClient, confirm_llm: LLMClient, events: list[CallEvent],
) -> list[Issue]:
    """One rule's full screen→confirm pass — the unit of work dispatched in parallel
    across every rule assigned to a tier (finer than cell3's per-category dispatch)."""
    candidates = record_call(
        screen_llm, stage="screen", tier=level, rule_ids=(rule.rule_id,), events=events,
        call=lambda: _screen_rule(chunks, rule, global_context, screen_llm),
    )
    if not candidates:
        return []
    return record_call(
        confirm_llm, stage="confirm", tier=level, rule_ids=(rule.rule_id,), events=events,
        call=lambda: _confirm_rule(candidates, chunks, rule, doc_id, level, global_context, source_text, rulebook, confirm_llm),
    )


def review_document(
    doc_id: str, document_text: str, rulebook: RuleBook, screen_llm: LLMClient, confirm_llm: LLMClient, max_workers: int = 8
) -> ReviewResult:
    """셀3R — 위계별로, 배정된 룰 하나하나마다 독립적인 screen→confirm pass를 병렬 실행한다
    (카테고리 단위였던 셀3보다 한 단계 더 세분화, tool-calling은 여전히 없음).
    `max_workers=1`을 주면 순차 실행(테스트 결정성용)."""
    tier_errors: list[str] = []
    events: list[CallEvent] = []

    try:
        global_context = record_call(
            confirm_llm, stage="context", tier=None, rule_ids=(), events=events,
            call=lambda: extract_global_context(document_text, confirm_llm),
        )
    except Exception as error:  # noqa: BLE001 - one tier's failure shouldn't sink the whole review
        global_context = ""
        tier_errors.append(f"Global Context 추출 실패: {error}")

    tree = parse_document(doc_id, document_text)
    all_issues: list[Issue] = []

    for level in TIER_ORDER:
        chunks = list(tree.chunks_for(level))
        rules = rules_for_tier(rulebook, level)
        if not chunks or not rules:
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_review_rule, level, chunks, rule, global_context, doc_id, document_text, rulebook, screen_llm, confirm_llm, events): rule
                for rule in rules
            }
            for future in concurrent.futures.as_completed(futures):
                rule = futures[future]
                try:
                    all_issues.extend(future.result())
                except Exception as error:  # noqa: BLE001 - one rule's failure shouldn't sink the whole tier
                    tier_errors.append(f"{level.value}/{rule.rule_id} 룰 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
