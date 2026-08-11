from __future__ import annotations

import concurrent.futures

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document, resolve_reported_level
from planqa_review.instrumentation import CallEvent, isolate_client, merge_usage, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.rulebook import RuleBook, RuleDef
from planqa_review.schema import Issue, Level
from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS
from planqa_review.verifier import is_reference_excused_by_rule

# paragraph_verdict — ② 청킹 실험의 문단형 변형. direct_verdict(①의 잠정 승자: 1단계,
# 콜분리×룰전부)와 판정 방식·세분화는 완전히 동일하게 유지하고 청킹만 바꾼다: 위계형(4단계)
# 대신 문단 단위로만 나누되, GA(상위 목표 정합성)는 문단 하나만 봐서는 판단 불가하므로 문서
# 전체를 놓고 1회 별도 확인한다. 같은 이유로 §1의 부재 확인형(Absence Check) 룰(LG-01/
# TC-02, `tiers.ABSENCE_CHECK_RULE_IDS`)도 문서 전체 단위로 확인한다 — 원래 위계형에서도
# 이 두 룰은 Document 위계에서만 확인되는 것과 같은 근거.

_GA_CATEGORY = "GA"

# Duplicated rather than imported from models/gemini_lite/context.py, same as cell3.py/
# direct_verdict.py — that module is baseline structure code (제안5) this structure must
# not depend on or touch, per the additive-only rule.
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

_DIRECT_SYSTEM = (
    "You are a single-pass document QA reviewer scoped to one review category — there is "
    "no separate cheap screening step before you, so decide directly whether each rule in "
    "this category is actually violated (don't over-flag on the assumption something else "
    "will double-check). For each numbered chunk below, check it against the numbered "
    "rules. If a rule is violated: quote the exact evidence sentence from the chunk "
    "(original_text), state what's wrong (description), explain why it breaks the rule "
    "(rationale), and write a concrete revised version of the text that would fix it "
    "(fix_direction) — phrase it as a suggestion, not a command. Also apply the rule's own "
    "exception condition if given; set excused=true (with excuse_reason) when it applies. "
    "For the LG/LF/GA categories specifically, a violation is by definition a relationship "
    "error between two locations in the document (e.g. \"2-2's wording contradicts what "
    "2-1 said\") — also name the OTHER location involved (related_location), using the "
    "same label style as the location you were given, so the caller can draw a range frame "
    "instead of a single point; leave related_location null for every other category, or "
    "if no specific second location can be identified. When claiming two locations "
    "conflict, first confirm they actually assert different facts — restating the same "
    "fact in different words or at different levels of detail is NOT a conflict; only "
    "flag a genuine logical contradiction. If the same underlying problem repeats across "
    "several of the numbered chunks below, or would technically match more than one rule "
    "listed here, report it ONCE only — pick the single chunk_index and rule_id that best "
    "represents it, don't emit a separate issue for every repeated chunk or every rule it "
    "could arguably fall under. You were given chunks at one specific granularity, but if "
    "the violation actually spans a broader unit than the single chunk you're citing (e.g. "
    "the same defect repeats across every chunk under one heading), say so with \"level\": "
    "name the coarser level it really belongs at (\"Document\", \"Logical Unit\", "
    "\"Paragraph\", or \"Sentence\", coarsest to finest) instead of leaving it at the "
    "chunk's own granularity — omit it (or repeat the chunk's own level) when the finding "
    "genuinely doesn't extend beyond the one chunk you cited. Only report genuine "
    "violations.\n"
    'Respond with JSON only: {"violations": [{"chunk_index": <int>, "rule_id": "<id>", '
    '"original_text": "<quote>", "description": "<what\'s wrong>", "rationale": '
    '"<why it violates the rule>", "fix_direction": "<suggested revision>", "excused": '
    '<bool>, "excuse_reason": "<string or null>", "related_location": "<string or null>", '
    '"level": "<Document|Logical Unit|Paragraph|Sentence, or null>"}, ...]}'
)


def _direct_verdict_category(
    chunks: list[Chunk],
    rules: list[RuleDef],
    global_context: str,
    doc_id: str,
    level: Level,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    rule_block = "\n".join(
        f"{rule.rule_id} ({rule.category_label}): {rule.text}\n  exception condition: {rule.exception_text or '없음'}"
        for rule in rules
    )
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    # Every category dispatched for this pass shares the exact same context_block+chunk_block
    # text (only `rules` differs per category) — split out as `cache_prefix` so a caching-
    # capable backend (AnthropicClient) only bills/reprocesses it in full on the first of
    # the concurrent category calls, not all of them.
    cache_prefix = f"{context_block}Chunks:\n{chunk_block}"
    prompt = f"Rules to check:\n{rule_block}\n\nReturn the violations JSON."

    response = llm.complete_json(system=_DIRECT_SYSTEM, prompt=prompt, cache_prefix=cache_prefix)
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
            call=lambda: _direct_verdict_category(chunks, rules, global_context, doc_id, level, source_text, rulebook, confirm_copy),
        )
    finally:
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
    """paragraph_verdict — direct_verdict와 판정 방식은 동일(1단계, 콜분리×룰전부)하지만
    청킹이 문단형이다: 대부분의 카테고리는 문단 단위 chunk로, GA와 부재 확인형 룰만 문서
    전체 1회로 확인한다. `screen_llm`은 안 씀 — 다른 구조들과 동일한 `ReviewFn` 시그니처를
    맞추기 위해 인자만 유지. `max_workers`를 안 주면(기본값) 그 패스의 카테고리 수만큼
    한꺼번에 병렬 실행(문단 패스 최대 7개, 문서 패스 최대 3개라 배치로 나뉘어 대기할 일이
    없음) — `max_workers=1`을 주면 순차 실행(테스트 결정성용)."""
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
