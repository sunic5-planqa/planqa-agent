from __future__ import annotations

from dataclasses import dataclass

from planqa_review.dedupe import dedupe_issues
from planqa_review.document import Chunk, parse_document
from planqa_review.instrumentation import CallEvent, record_call
from planqa_review.llm.base import LLMClient
from planqa_review.pipeline import ReviewResult
from planqa_review.tiers import TIER_ORDER, rules_for_tier
from planqa_review.verifier import is_reference_excused_by_rule
from planqa_schemas.rulebook import RuleBook, RuleDef
from planqa_schemas.schema import Issue, Level

# Duplicated rather than imported from models/gemini_lite/context.py — that module is
# baseline structure code (제안5) this structure must not depend on or touch, per the
# additive-only rule (same reasoning as the §3 check below, which *can* come from
# verifier.py since that module is shared ground, not baseline-specific).
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

# 데모 v1 구조: 위계형 청킹 + 콜통합(baseline/제안5와 동일)은 그대로 두되, 스크리닝 단계는
# 룰 텍스트 대신 카테고리 라벨만 받는 더 가벼운 프롬프트로 바뀐다 — 구체적으로 어떤 룰을
# 위반했는지는 정밀판정 단계에서 해당 카테고리의 룰 전체를 놓고 모델이 직접 고른다. 정적
# 퓨샷 예시는 아직 넣지 않음(후속 작업으로 남겨둠).

_SCREEN_SYSTEM = (
    "You are the cheap, wide first pass of a two-stage document QA pipeline (screen now, "
    "a stronger model verifies later) — favor recall over precision, flag anything even "
    "mildly suspicious. You are NOT given the exact rule text, only the review category — "
    "a stronger model will look up the exact rule afterward. For each numbered chunk below, "
    "check it against the listed categories and list every span that might violate one, "
    "however uncertain.\n"
    'Respond with JSON only: {"candidates": [{"chunk_index": <int>, "category": "<code>", '
    '"quoted_text": "<exact span from the chunk>", "reason": "<one short line>"}, ...]}'
)

_CONFIRM_SYSTEM = (
    "You are the precise, expensive second pass of a two-stage document QA pipeline. The "
    "screening pass only knew the category, not the specific rule — your job is to pick the "
    "exact rule (if any) the flagged span actually violates, out of the candidate rules "
    "listed for its category. The screening pass over-flags on purpose, so most candidates "
    "should come back violated=false. If it does violate: name the exact rule_id, quote the "
    "exact evidence sentence from the document (original_text), state what's wrong "
    "(description), explain why it breaks the rule (rationale), and write a concrete "
    "revised version of the text that would fix it (fix_direction) — phrase it as a "
    "suggestion, not a command. Also apply that rule's own exception condition if given; "
    "set excused=true (with excuse_reason) when it applies. For the LG/LF/GA categories "
    "specifically, a violation is by definition a relationship error between two locations "
    "in the document (e.g. \"2-2's wording contradicts what 2-1 said\") — also name the "
    "OTHER location involved (related_location), using the same label style as the "
    "location you were given, so the caller can draw a range frame instead of a single "
    "point; leave related_location null for every other category, or if no specific second "
    "location can be identified.\n"
    'Respond with JSON only: {"verdicts": [{"index": <int>, "violated": <bool>, "rule_id": '
    '"<id or null>", "original_text": "<quote>", "description": "<what\'s wrong>", '
    '"rationale": "<why it violates the rule>", "fix_direction": "<suggested revision>", '
    '"excused": <bool>, "excuse_reason": "<string or null>", "related_location": '
    '"<string or null>"}, ...]}'
)

# github.com/sunic5-planqa/planqa-agent issue #4: only these three categories are
# relationship errors between two locations — everything else stays a single-point issue.
_RELATIONAL_CATEGORIES = frozenset({"LG", "LF", "GA"})


@dataclass(frozen=True, slots=True)
class _CategoryCandidate:
    chunk_index: int
    category: str
    quoted_text: str
    reason: str


def _category_labels(rules: list[RuleDef]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for rule in rules:
        labels.setdefault(rule.category, rule.category_label)
    return labels


def _build_screen_prompt(chunks: list[Chunk], rules: list[RuleDef], global_context: str) -> str:
    category_block = "\n".join(f"{code}: {label}" for code, label in _category_labels(rules).items())
    chunk_block = "\n\n".join(f"[{i}] ({chunk.location})\n{chunk.text}" for i, chunk in enumerate(chunks))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return (
        f"{context_block}Categories to check:\n{category_block}\n\nChunks:\n{chunk_block}\n\n"
        "Return the candidates JSON."
    )


def _screen_tier(
    chunks: list[Chunk], rules: list[RuleDef], global_context: str, llm: LLMClient
) -> list[_CategoryCandidate]:
    response = llm.complete_json(system=_SCREEN_SYSTEM, prompt=_build_screen_prompt(chunks, rules, global_context))
    raw = response.get("candidates", []) if isinstance(response, dict) else []
    valid_categories = set(_category_labels(rules))

    candidates: list[_CategoryCandidate] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        chunk_index, category = item.get("chunk_index"), item.get("category")
        if not (isinstance(chunk_index, int) and 0 <= chunk_index < len(chunks)) or category not in valid_categories:
            continue
        candidates.append(
            _CategoryCandidate(
                chunk_index=chunk_index,
                category=category,
                quoted_text=str(item.get("quoted_text", "")).strip(),
                reason=str(item.get("reason", "")).strip(),
            )
        )
    return candidates


def _candidate_block(
    index: int, candidate: _CategoryCandidate, chunk: Chunk, category_rules: list[RuleDef]
) -> str:
    rule_lines = "\n".join(
        f"    {rule.rule_id}: {rule.text} (exception: {rule.exception_text or '없음'})" for rule in category_rules
    )
    return (
        f"[{index}] category {candidate.category} ({category_rules[0].category_label}) — candidate rules:\n"
        f"{rule_lines}\n"
        f"  location: {chunk.location}\n"
        f"  full unit text: {chunk.text!r}\n"
        f"  screened span: {candidate.quoted_text!r} (screening reason: {candidate.reason})"
    )


def _build_confirm_prompt(resolved: list[tuple[_CategoryCandidate, Chunk, list[RuleDef]]], global_context: str) -> str:
    blocks = "\n\n".join(_candidate_block(i, c, chunk, rules) for i, (c, chunk, rules) in enumerate(resolved))
    context_block = f"Document context:\n{global_context}\n\n" if global_context else ""
    return f"{context_block}{blocks}\n\nReturn the verdicts JSON."


def _confirm_tier(
    candidates: list[_CategoryCandidate],
    chunks: list[Chunk],
    rules_by_category: dict[str, list[RuleDef]],
    doc_id: str,
    level: Level,
    global_context: str,
    source_text: str,
    rulebook: RuleBook,
    llm: LLMClient,
) -> list[Issue]:
    resolved: list[tuple[_CategoryCandidate, Chunk, list[RuleDef]]] = []
    for candidate in candidates:
        if candidate.chunk_index >= len(chunks):
            continue
        category_rules = rules_by_category.get(candidate.category)
        if not category_rules:
            continue
        resolved.append((candidate, chunks[candidate.chunk_index], category_rules))
    if not resolved:
        return []

    response = llm.complete_json(system=_CONFIRM_SYSTEM, prompt=_build_confirm_prompt(resolved, global_context))
    raw_verdicts = response.get("verdicts", []) if isinstance(response, dict) else []
    by_index = {item["index"]: item for item in raw_verdicts if isinstance(item, dict) and "index" in item}

    issues: list[Issue] = []
    for i, (candidate, chunk, category_rules) in enumerate(resolved):
        values = by_index.get(i)
        if values is None or not values.get("violated"):
            continue
        rule_id = values.get("rule_id")
        if rule_id not in {rule.rule_id for rule in category_rules}:
            continue  # model named a rule outside its given category's set — reject rather than trust
        original_text = str(values.get("original_text") or candidate.quoted_text).strip()
        excused = bool(values.get("excused")) or is_reference_excused_by_rule(
            rule_id, rulebook, original_text, doc_id, level, chunk.location, source_text
        )
        if excused:
            continue
        related_location = None
        if candidate.category in _RELATIONAL_CATEGORIES:
            raw_related = values.get("related_location")
            related_location = str(raw_related).strip() or None if raw_related else None
        issues.append(
            Issue(
                doc_id=doc_id,
                level=level.value,
                rule_id=rule_id,
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


def review_document(
    doc_id: str, document_text: str, rulebook: RuleBook, screen_llm: LLMClient, confirm_llm: LLMClient
) -> ReviewResult:
    # 데모 v1 구조 — 위계형 청킹 + 콜통합은 baseline(제안5)과 동일하지만, 스크리닝은 룰
    # 텍스트가 아니라 카테고리 라벨만 받고, 정밀판정이 카테고리 내 룰 전체를 놓고 구체적
    # rule_id를 직접 고른다. 정적 퓨샷 예시는 아직 없음.
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
        rules = rules_for_tier(rulebook, level)
        if not chunks or not rules:
            continue
        rules_by_category: dict[str, list[RuleDef]] = {}
        for rule in rules:
            rules_by_category.setdefault(rule.category, []).append(rule)
        tier_rule_ids = tuple(rule.rule_id for rule in rules)
        try:
            candidates = record_call(
                screen_llm,
                stage="screen",
                tier=level,
                rule_ids=tier_rule_ids,
                events=events,
                call=lambda: _screen_tier(chunks, rules, global_context, screen_llm),
            )
            candidate_rule_ids = tuple(
                sorted({rule.rule_id for c in candidates for rule in rules_by_category.get(c.category, ())})
            )
            issues = record_call(
                confirm_llm,
                stage="confirm",
                tier=level,
                rule_ids=candidate_rule_ids,
                events=events,
                call=lambda: _confirm_tier(
                    candidates,
                    chunks,
                    rules_by_category,
                    doc_id,
                    level,
                    global_context,
                    document_text,
                    rulebook,
                    confirm_llm,
                ),
            )
            all_issues.extend(issues)
        except Exception as error:  # noqa: BLE001 - see above
            tier_errors.append(f"{level.value} 위계 검토 실패: {error}")

    return ReviewResult(
        doc_id=doc_id,
        global_context=global_context,
        issues=tuple(dedupe_issues(all_issues)),
        tier_errors=tuple(tier_errors),
        call_events=tuple(events),
    )
