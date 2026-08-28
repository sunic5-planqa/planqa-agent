from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS
from planqa_review.verifier import is_reference_excused_by_rule

# paragraph_screen — ①(판정 단계 수) 재검증 후 새로 정한 기준 구조. Sonnet으로 재검증한
# 결과 direct_verdict(1단계)는 과다지적이 심했고 cell3(2단계, screen=Gemini/confirm=
# Sonnet)가 훨씬 낫았다 — 반면 ②(청킹)는 문단형(paragraph_verdict)이 위계형보다 계속
# 우세했다. 이 둘을 합친 게 이 구조: cell3의 screen→confirm 2단계는 그대로 두고, 청킹만
# paragraph_verdict처럼 문단형(GA·부재확인형만 문서 전체 1회)으로 바꾼다. Phase 3
# (세분화×퓨샷)의 "콜분리×룰전부" 콤보는 이제 이 구조가 기준이 된다(paragraph_verdict가
# 아니라).

_GA_CATEGORY = "GA"

# Duplicated rather than imported from models/gemini_lite/context.py — that module is
# baseline structure code (제안5) this structure must not depend on or touch, per the
# additive-only rule.
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
    "for every other category, or if no specific second location can be identified. When "
    "claiming two locations conflict, first confirm they actually assert different facts — "
    "restating the same fact in different words or at different levels of detail is NOT a "
    "conflict; only flag a genuine logical contradiction. If several of the candidates "
    "above are really the same underlying problem (e.g. the same defect repeated across "
    "multiple chunks), confirm violated=true on only ONE of them and set the rest to "
    "violated=false — don't confirm every repeat. Each candidate was screened at one "
    "specific chunk's granularity, but if the violation actually spans a broader unit than "
    "that chunk (e.g. the same defect repeats across every chunk under one heading), say so "
    "with \"level\": name the coarser level it really belongs at (\"Document\", \"Logical "
    "Unit\", \"Paragraph\", or \"Sentence\", coarsest to finest) instead of leaving it at "
    "the chunk's own granularity — omit it (or repeat the chunk's own level) when the "
    "finding genuinely doesn't extend beyond the one chunk.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>", "related_location": "<string or null>", '
    '"level": "<Document|Logical Unit|Paragraph|Sentence, or null>"}, ...]}'
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
    # Every category dispatched for this pass shares the exact same context_block+chunk_block
    # text (only `rules` differs per category) — split out as `cache_prefix` so a caching-
    # capable backend (AnthropicClient) only bills/reprocesses it in full on the first of
    # the concurrent category calls, not all of them.
    cache_prefix = f"{context_block}Chunks:\n{chunk_block}"
    prompt = f"Rules to check:\n{rule_block}\n\nReturn the candidates JSON."

    response = llm.complete_json(system=_SCREEN_SYSTEM, prompt=prompt, cache_prefix=cache_prefix)
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
        reported_level, reported_location = resolve_reported_level(level, chunk.location, values.get("level"))
        issues.append(
            Issue(
                doc_id=doc_id,
                level=reported_level.value,
                rule_id=candidate.rule_id,
                location=reported_location,
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
    across every category assigned to a pass. `screen_llm`/`confirm_llm` are shared across
    every concurrently-dispatched category, so each call here goes through a private
    `isolate_client` copy — see instrumentation.py's `record_call` docstring."""
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


def _rules_by_category(rules: list[RuleDef]) -> dict[str, list[RuleDef]]:
    grouped: dict[str, list[RuleDef]] = {}
    for rule in rules:
        grouped.setdefault(rule.category, []).append(rule)
    return grouped


def _paragraph_and_document_rule_groups(rulebook: RuleBook) -> tuple[dict[str, list[RuleDef]], dict[str, list[RuleDef]]]:
    """Splits every rule in the rulebook into the 문단 pass vs the 문서 전체 pass — GA
    (상위 목표 정합성) can't be judged from a single paragraph, and neither can §1's 부재
    확인형 rules (`ABSENCE_CHECK_RULE_IDS`), so both go to the whole-document pass regardless
    of their normal category. Everything else is checked per-paragraph."""
    paragraph_rules: list[RuleDef] = []
    document_rules: list[RuleDef] = []
    for rule in rulebook.rules.values():
        if rule.category == _GA_CATEGORY or rule.rule_id in ABSENCE_CHECK_RULE_IDS:
            document_rules.append(rule)
        else:
            paragraph_rules.append(rule)
    return _rules_by_category(paragraph_rules), _rules_by_category(document_rules)


def review_document(
    doc_id: str,
    document_text: str,
    rulebook: RuleBook,
    screen_llm: LLMClient,
    confirm_llm: LLMClient,
    max_workers: int | None = None,
) -> ReviewResult:
    """paragraph_screen — ①(판정 단계 수, Sonnet 재검증 후 2단계로 재확정)과 ②(청킹,
    문단형)를 합친 기준 구조. cell3와 동일한 screen→confirm 2단계를 유지하되, 위계형 대신
    paragraph_verdict와 동일한 문단형 청킹(GA·부재확인형만 문서 전체 1회)을 쓴다.
    `max_workers`를 안 주면(기본값) 그 패스의 카테고리 수만큼 한꺼번에 병렬 실행,
    `max_workers=1`을 주면 순차 실행(테스트 결정성용)."""
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
    except Exception as error:  # noqa: BLE001 - one pass's failure shouldn't sink the whole review
        global_context = ""
        tier_errors.append(f"Global Context 추출 실패: {error}")

    tree = parse_document(doc_id, document_text)
    paragraph_rules_by_category, document_rules_by_category = _paragraph_and_document_rule_groups(rulebook)
    all_issues: list[Issue] = []

    passes = (
        (Level.PARAGRAPH, paragraph_rules_by_category, list(tree.chunks_for(Level.PARAGRAPH))),
        (Level.DOCUMENT, document_rules_by_category, list(tree.chunks_for(Level.DOCUMENT))),
    )
    for level, rules_by_category, chunks in passes:
        if not chunks or not rules_by_category:
            continue

        pool_workers = max_workers if max_workers is not None else len(rules_by_category)
        with concurrent.futures.ThreadPoolExecutor(max_workers=pool_workers) as pool:
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
                except Exception as error:  # noqa: BLE001 - one category's failure shouldn't sink the whole pass
                    tier_errors.append(f"{level.value}/{category} 카테고리 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
