from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document
from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.tiers import TIER_ORDER, rules_for_tier
from planqa_review.verifier import is_reference_excused_by_rule

# 셀3 (방안2×1안): tier 청킹은 baseline(제안5)과 동일하지만, 한 위계에 배정된 카테고리를
# 하나의 프롬프트에 뭉치지 않고 카테고리마다 독립된 screen→confirm pass를 병렬로 돌린다.
# 위계별 카테고리 배정은 §2로 이미 결정론적이라 모델이 "고를" 게 없으므로, 진짜
# function-calling 없이 Python 동시성(스레드풀)만으로 병렬 실행을 구현한다 — baseline이
# 여러 카테고리를 한 콜에 뭉쳐서 처리하는 것과 정확히 대조되는 지점.

# Duplicated rather than imported from models/gemini_lite/context.py — that module is
# baseline structure code (제안5) this structure must not depend on or touch, per the
# additive-only rule (same reasoning as the §3 check below, which comes from verifier.py
# since that module is shared ground, not baseline-specific).
_GLOBAL_CONTEXT_SYSTEM = (
    "You read one Korean product-planning document (기획서) and produce a compact context "
    "summary that will be prepended to every later review prompt about this same document, "
    "so it must stand on its own without the full document attached. Capture: the "
    "document's core purpose, its key policies/constraints, and its target KPIs/goals — "
    "exactly what a reviewer needs to judge whether *other* sections of the document stay "
    "consistent with what this document set out to do. Keep it to a few sentences.\n"
    'Respond with JSON only: {"summary": "<compact Korean summary>"}'
)


def _extract_global_context(document_text: str, llm: LLMClient) -> str:
    response = llm.complete_json(system=_GLOBAL_CONTEXT_SYSTEM, prompt=document_text)
    summary = response.get("summary") if isinstance(response, dict) else None
    return summary.strip() if isinstance(summary, str) and summary.strip() else ""


# github.com/sunic5-planqa/planqa-agent issue #4: only these three categories are
# relationship errors between two locations — everything else stays a single-point issue.
_RELATIONAL_CATEGORIES = frozenset({"LG", "LF", "GA"})

_SCREEN_SYSTEM = (
    "You are the cheap, wide first pass of a two-stage document QA pipeline (screen now, "
    "a stronger model verifies later) — favor recall over precision, flag anything even "
    "mildly suspicious. For each numbered chunk below, check it against the numbered rules "
    "and list every span that might violate one, however uncertain.\n"
    'Respond with JSON only: {"candidates": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"quoted_text": "<exact span from the chunk>", "reason": "<one short line>"}, ...]}'
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
    "applies. For the LG/LF/GA categories specifically, a violation is by definition a "
    "relationship error between two locations in the document (e.g. \"2-2's wording "
    "contradicts what 2-1 said\") — also name the OTHER location involved "
    "(related_location), using the same label style as the location you were given, so the "
    "caller can draw a range frame instead of a single point; leave related_location null "
    "for every other category, or if no specific second location can be identified.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>", "related_location": "<string or null>"}, '
    '...]}'
)


@dataclass(frozen=True, slots=True)
class _Candidate:
    chunk_index: int
    rule_id: str
    quoted_text: str
    reason: str


def _screen_category(chunks: list[Chunk], rules: list[RuleDef], global_context: str, llm: LLMClient) -> list[_Candidate]:
    rule_block = "\n".join(f"{rule.rule_id}: {rule.text}" for rule in rules)
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    prompt = f"{context_block}Rules to check:\n{rule_block}\n\nChunks:\n{chunk_block}\n\nReturn the candidates JSON."

    response = llm.complete_json(system=_SCREEN_SYSTEM, prompt=prompt)
    raw = response.get("candidates", []) if isinstance(response, dict) else []
    valid_rule_ids = {rule.rule_id for rule in rules}

    candidates: list[_Candidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chunk_index, rule_id = item.get("chunk_index"), item.get("rule_id")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)) or rule_id not in valid_rule_ids:
            continue
        candidates.append(
            _Candidate(
                chunk_index=chunk_index,
                rule_id=rule_id,
                quoted_text=str(item.get("quoted_text", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return candidates


def _confirm_category(
    candidates: list[_Candidate],
    chunks: list[Chunk],
    rules_by_id: dict[str, RuleDef],
    doc_id: str,
    level: Level,
    global_context: str,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    blocks = []
    for i, candidate in enumerate(candidates):
        rule = rules_by_id[candidate.rule_id]
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
        excused = bool(values.get("excused")) or is_reference_excused_by_rule(
            candidate.rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
        )
        if excused:
            continue
        related_location = None
        if rules_by_id[candidate.rule_id].category in _RELATIONAL_CATEGORIES:
            raw_related = values.get("related_location")
            related_location = str(raw_related).strip() or None if raw_related else None
        issues.append(
            Issue(
                doc_id=doc_id,
                level=level.value,
                rule_id=candidate.rule_id,
                location=chunk.location,
                description=str(values.get("description") or "").strip(),
                source="review_agent",
                original_text=original_text,
                rationale=str(values.get("rationale") or "").strip() or None,
                fix_direction=str(values.get("fix_direction") or "").strip() or None,
                related_location=related_location,
            )
        )
    return issues


def _review_category(
    level: Level,
    chunks: list[Chunk],
    rules: list[RuleDef],
    global_context: str,
    doc_id: str,
    source_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
    events: list[CallEvent],
) -> list[Issue]:
    """One category's full screen→confirm pass — the unit of work dispatched in parallel
    across every category assigned to a tier. `events` is a shared list `record_call`
    appends to; `list.append` is atomic under the GIL so concurrent appends from the
    thread pool below are safe even though cross-category ordering isn't guaranteed.

    `screen_llm`/`confirm_llm` are shared across every concurrently-dispatched category, so
    each call here goes through a private `isolate_client` copy instead — see
    instrumentation.py's `record_call` docstring for why the shared instance can't be used
    directly under concurrency. The copies' usage is folded back onto the originals below."""
    screen_copy = isolate_client(screen_llm)
    confirm_copy = isolate_client(confirm_llm)
    try:
        rule_ids = tuple(rule.rule_id for rule in rules)
        candidates = record_call(
            screen_copy,
            stage="screen",
            tier=level,
            rule_ids=rule_ids,
            events=events,
            call=lambda: _screen_category(chunks, rules, global_context, screen_copy),
        )
        if not candidates:
            return []
        candidate_rule_ids = tuple(sorted({candidate.rule_id for candidate in candidates}))
        rules_by_id = {rule.rule_id: rule for rule in rules}
        return record_call(
            confirm_copy,
            stage="confirm",
            tier=level,
            rule_ids=candidate_rule_ids,
            events=events,
            call=lambda: _confirm_category(candidates, chunks, rules_by_id, doc_id, level, global_context, source_text, rulebook, confirm_copy),
        )
    finally:
        merge_usage(screen_llm, screen_copy)
        merge_usage(confirm_llm, confirm_copy)


def review_document(
    doc_id: str,
    document_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
    max_workers: int = 4,
) -> ReviewResult:
    """셀3 — 위계별로, 배정된 카테고리마다 독립적인 screen→confirm pass를 병렬 실행한다.
    `max_workers=1`을 주면 순차 실행(테스트에서 `ScriptedLLM`의 순서 결정성을 위해 사용)."""
    tier_errors: list[str] = []
    events: list[CallEvent] = []

    try:
        global_context = record_call(
            confirm_llm,
            stage="context",
            tier=None,
            rule_ids=(),
            events=events,
            call=lambda: _extract_global_context(document_text, confirm_llm),
        )
    except Exception as error:  # noqa: BLE001 - one tier's failure shouldn't sink the whole review
        global_context = ""
        tier_errors.append(f"Global Context 추출 실패: {error}")

    tree = parse_document(doc_id, document_text)
    all_issues: list[Issue] = []

    for level in TIER_ORDER:
        chunks = list(tree.chunks_for(level))
        if not chunks:
            continue
        rules_by_category: dict[str, list[RuleDef]] = {}
        for rule in rules_for_tier(rulebook, level):
            rules_by_category.setdefault(rule.category, []).append(rule)
        if not rules_by_category:
            continue

        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _review_category, level, chunks, rules, global_context, doc_id, document_text, rulebook, screen_llm, confirm_llm, events
                ): category
                for category, rules in rules_by_category.items()
            }
            for future in concurrent.futures.as_completed(futures):
                category = futures[future]
                try:
                    all_issues.extend(future.result())
                except Exception as error:  # noqa: BLE001 - one category's failure shouldn't sink the whole tier
                    tier_errors.append(f"{level.value}/{category} 카테고리 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
