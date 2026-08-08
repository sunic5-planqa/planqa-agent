from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from planqa_eval.parsers.documents import load_source_text
from planqa_schemas.rulebook import RuleBook
from planqa_schemas.schema import Issue

# "<title>(DOC-XXX) 참고/참조" style citation, e.g. "반품/교환 정책서(DOC-005) 참고."
_CITATION = re.compile(
    r"[「『\"']?([^「『\"'()\n]{2,40}?)[」』\"']?\s*\(?\s*(DOC-\d{3})\s*\)?\s*(?:참고|참조)"
)
_QUOTED = re.compile(r"[「『\"'`]([^」』\"'`]{2,30})[」』\"'`]")


@dataclass(frozen=True, slots=True)
class VerifiedMatch:
    golden: Issue
    predicted: Issue
    rule_id_match: bool
    level_match: bool

    @property
    def fully_correct(self) -> bool:
        return self.rule_id_match and self.level_match


@dataclass(frozen=True, slots=True)
class VerifiedMiss:
    golden: Issue
    excused: bool
    excuse_reason: str | None = None

    @property
    def is_false_negative(self) -> bool:
        return not self.excused


def verify_matches(matched: list[tuple[Issue, Issue]]) -> list[VerifiedMatch]:
    """Rule ID and Level are compared by exact equality, never string similarity —
    the review agent either named the right rule/level or it didn't."""
    return [
        VerifiedMatch(
            golden=golden,
            predicted=predicted,
            rule_id_match=golden.rule_id == predicted.rule_id,
            level_match=golden.level == predicted.level,
        )
        for golden, predicted in matched
    ]


def _paragraph_blocks(document_text: str) -> list[str]:
    return [block for block in re.split(r"\n\s*\n", document_text) if block.strip()]


def _flagged_keywords(issue: Issue) -> list[str]:
    """The specific phrase(s) a rule violation was flagged on, e.g. the individually
    quoted vague-time expressions in an AE-01 issue. Falls back to a text snippet when the
    source text has no quoted spans."""
    text = issue.original_text or issue.description
    quoted = _QUOTED.findall(text)
    return quoted if quoted else [text[:30]]


def has_valid_reference_exception(golden_issue: Issue, source_text: str | None) -> bool:
    """Rulebook §3: a reference citation (문서명 + 섹션) only excuses a miss if it points at
    the *specific* flagged item — not merely appears anywhere in the document. We treat
    "points at" as: the citation and at least one of the flagged phrases fall in the same
    paragraph/bullet block. This is a deterministic proxy for a semantic judgment the
    rulebook itself illustrates with a counter-example (DOC-006 2-3: a "반품/교환
    정책서(DOC-005) 참고" citation sits in its own paragraph, separate from the "빠른 시일
    내" style SLA wording it does NOT excuse) — see tests/test_verifier.py for that case.
    It may under- or over-excuse cases where the citation and the flagged phrase share a
    paragraph without one truly justifying the other; treat this as best-effort pending
    real examples of the other three exception rules (LG-04/TC-02/GA-03) to validate against.
    """
    if not source_text:
        return False
    keywords = _flagged_keywords(golden_issue)
    for block in _paragraph_blocks(source_text):
        if _CITATION.search(block) and any(keyword in block for keyword in keywords):
            return True
    return False


def verify_misses(fn_candidates: list[Issue], rulebook: RuleBook, source_dir: Path) -> list[VerifiedMiss]:
    """Before counting a missed golden issue as a real False Negative, re-check whether its
    rule is subject to the reference-citation exception (rulebook §3: LG-04/TC-02/AE-01/
    GA-03) and, if so, whether the source document actually contains a valid exception."""
    source_cache: dict[str, str | None] = {}
    results: list[VerifiedMiss] = []
    for golden in fn_candidates:
        if golden.rule_id not in rulebook.reference_exception_rule_ids:
            results.append(VerifiedMiss(golden=golden, excused=False))
            continue

        if golden.doc_id not in source_cache:
            source_cache[golden.doc_id] = load_source_text(golden.doc_id, source_dir)
        excused = has_valid_reference_exception(golden, source_cache[golden.doc_id])
        results.append(
            VerifiedMiss(
                golden=golden,
                excused=excused,
                excuse_reason="문서 내 참조 표기로 예외 인정" if excused else None,
            )
        )
    return results
