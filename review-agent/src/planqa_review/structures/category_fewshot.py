from __future__ import annotations

import concurrent.futures

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES, VIOLATION_EXAMPLES
from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS
from planqa_review.verifier import is_reference_excused_by_rule

# category_fewshot — ③+④ 콜분리×퓨샷만 셀. paragraph_verdict(②의 청킹 승자)와 판정
# 방식·청킹은 완전히 동일하게 유지하고, 프롬프트에 룰 텍스트를 전혀 주지 않는다 — 대신
# fewshot_bank.py의 리키지 세이프 위반/예외조건 예시만 rule_id 태그와 함께 나열한다.

_GA_CATEGORY = "GA"

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


_RELATIONAL_CATEGORIES = frozenset({"LG", "LF", "GA"})

_FEWSHOT_SYSTEM = (
    "You are a single-pass document QA reviewer scoped to one review category. You are NOT "
    "given the rule text — only each rule's id and a few labeled examples of what a real "
    "violation and a real excused (non-violation) case look like. Learn the pattern each "
    "rule_id represents from its examples, then decide directly whether each numbered chunk "
    "below violates any of them (don't over-flag on the assumption something else will "
    "double-check). If a rule is violated: quote the exact evidence sentence from the chunk "
    "(original_text), state what's wrong (description), explain why it matches the "
    "violation pattern shown for that rule_id (rationale), and write a concrete revised "
    "version of the text that would fix it (fix_direction) — phrase it as a suggestion, not "
    "a command. If the case matches an excused-example pattern instead, set excused=true "
    "(with excuse_reason). For the LG/LF/GA categories specifically, a violation is by "
    "definition a relationship error between two locations in the document — also name the "
    "OTHER location involved (related_location), using the same label style as the location "
    "you were given; leave related_location null for every other category, or if no "
    "specific second location can be identified. When claiming two locations conflict, "
    "first confirm they actually assert different facts — restating the same fact in "
    "different words or at different levels of detail is NOT a conflict; only flag a "
    "genuine logical contradiction. If the same underlying problem repeats across several "
    "of the numbered chunks below, or would technically match more than one rule listed "
    "here, report it ONCE only — pick the single chunk_index and rule_id that best "
    "represents it. You were given chunks at one specific granularity, but if the "
    "violation actually spans a broader unit than the single chunk you're citing (e.g. the "
    "same defect repeats across every chunk under one heading), say so with \"level\": "
    "name the coarser level it really belongs at (\"Document\", \"Logical Unit\", "
    "\"Paragraph\", or \"Sentence\", coarsest to finest) instead of leaving it at the "
    "chunk's own granularity — omit it (or repeat the chunk's own level) when the finding "
    "genuinely doesn't extend beyond the one chunk you cited. You MUST still name a "
    "specific rule_id for every violation — never leave it out even though you weren't "
    "given the rule's own wording. Only report genuine violations.\n"
    'Respond with JSON only: {"violations": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it matches the rule\'s violation pattern>", "fix_direction": "<suggested '
    'revision>", "excused": <bool>, "excuse_reason": "<string or null>", '
    '"related_location": "<string or null>", "level": "<Document|Logical Unit|Paragraph|'
    'Sentence, or null>"}, ...]}'
)


def _fewshot_block(rule: RuleDef) -> str:
    lines = [f"  {rule.rule_id} ({rule.category_label}):"]
    for example in VIOLATION_EXAMPLES.get(rule.rule_id, []):
        lines.append(f"    - VIOLATION example: {example.original_text!r} — {example.rationale}")
    exception = EXCEPTION_EXAMPLES.get(rule.rule_id)
    if exception is not None:
        lines.append(
            f"    - EXCUSED example ({exception.exception_condition}): {exception.original_text!r} — {exception.rationale}"
        )
    if len(lines) == 1:
        lines.append("    - (no curated example available — judge from the rule_id/category label alone)")
    return "\n".join(lines)


def _build_cache_prefix(chunks: list[Chunk], global_context: str) -> str:
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return f"{context_block}Chunks:\n{chunk_block}"


def _build_prompt(rules: list[RuleDef]) -> str:
    fewshot_block = "\n".join(_fewshot_block(rule) for rule in rules)
    return f"Rules (id + examples, no rule text):\n{fewshot_block}\n\nReturn the violations JSON."


def _category_fewshot_verdict(
    chunks: list[Chunk],
    rules: list[RuleDef],
    global_context: str,
    doc_id: str,
    level: Level,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    response = llm.complete_json(
        system=_FEWSHOT_SYSTEM, prompt=_build_prompt(rules), cache_prefix=_build_cache_prefix(chunks, global_context)
    )
    raw_violations = response.get("violations", []) if isinstance(response, dict) else []
    rules_by_id = {rule.rule_id: rule for rule in rules}

    issues: list[Issue] = []
    for item in raw_violations:
        if not isinstance(item, dict):
            continue
        chunk_index, rule_id = item.get("chunk_index"), item.get("rule_id")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)) or rule_id not in rules_by_id:
            continue
        chunk = chunks[chunk_index]
        original_text = str(item.get("original_text") or "").strip()
        excused = bool(item.get("excused")) or is_reference_excused_by_rule(
            rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
        )
        if excused:
            continue
        related_location = None
        if rules_by_id[rule_id].category in _RELATIONAL_CATEGORIES:
            raw_related = item.get("related_location")
            related_location = str(raw_related).strip() or None if raw_related else None
        reported_level, reported_location = resolve_reported_level(level, chunk.location, item.get("level"))
        issues.append(
            Issue(
                doc_id=doc_id,
                level=reported_level.value,
                rule_id=rule_id,
                location=reported_location,
                description=str(item.get("description") or "").strip(),
                source="review_agent",
                original_text=original_text or None,
                rationale=str(item.get("rationale") or "").strip() or None,
                fix_direction=str(item.get("fix_direction") or "").strip() or None,
                related_location=related_location,
            )
        )
    return issues


def _review_category(
    chunks: list[Chunk],
    rules: list[RuleDef],
    global_context: str,
    doc_id: str,
    level: Level,
    source_text: str,
    rulebook: RuleBook,
    confirm_llm: LLMClient,
    events: list[CallEvent],
) -> list[Issue]:
    """`confirm_llm` is shared across every concurrently-dispatched category, so this call
    goes through a private `isolate_client` copy — see instrumentation.py's `record_call`
    docstring for why the shared instance can't be used directly under concurrency."""
    confirm_copy = isolate_client(confirm_llm)
    try:
        return record_call(
            confirm_copy,
            stage="single_pass",
            tier=level,
            rule_ids=tuple(rule.rule_id for rule in rules),
            events=events,
            call=lambda: _category_fewshot_verdict(chunks, rules, global_context, doc_id, level, source_text, rulebook, confirm_copy),
        )
    finally:
        merge_usage(confirm_llm, confirm_copy)


def _rules_by_category(rules: list[RuleDef]) -> dict[str, list[RuleDef]]:
    grouped: dict[str, list[RuleDef]] = {}
    for rule in rules:
        grouped.setdefault(rule.category, []).append(rule)
    return grouped


def _paragraph_and_document_rule_groups(rulebook: RuleBook) -> tuple[dict[str, list[RuleDef]], dict[str, list[RuleDef]]]:
    """Same 문단형 split as paragraph_verdict.py — GA and §1's 부재 확인형 rules go to the
    whole-document pass, everything else is checked per-paragraph."""
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
    """category_fewshot — paragraph_verdict와 청킹·판정 방식은 동일(1단계, 콜분리, 문단형)
    이지만, 프롬프트에 룰 텍스트 대신 `fewshot_bank.py`의 위반/예외조건 예시만 준다.
    `screen_llm`은 안 씀 — 다른 구조들과 동일한 `ReviewFn` 시그니처를 맞추기 위해 인자만
    유지. `max_workers`를 안 주면(기본값) 그 패스의 카테고리 수만큼 한꺼번에 병렬 실행,
    `max_workers=1`을 주면 순차 실행(테스트 결정성용)."""
    del screen_llm
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
                pool.submit(_review_category, chunks, rules, global_context, doc_id, level, document_text, rulebook, confirm_llm, events): category
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
