from __future__ import annotations

import re

from planqa_review.schema import Issue

# "<title>(DOC-XXX) 참고/참조" style citation, e.g. "반품/교환 정책서(DOC-005) 참고."
_CITATION = re.compile(
    r"[「『\"']?([^「『\"'()\n]{2,40}?)[」』\"']?\s*\(?\s*(DOC-\d{3})\s*\)?\s*(?:참고|참조)"
)
_QUOTED = re.compile(r"[「『\"'`]([^」』\"'`]{2,30})[」』\"'`]")


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
    내" style SLA wording it does NOT excuse) — see tests/test_verifier.py (eval-agent) for
    that case. It may under- or over-excuse cases where the citation and the flagged phrase
    share a paragraph without one truly justifying the other; treat this as best-effort.

    Trimmed from eval-agent's verifier.py — this repo only needs the reference-exception
    check itself, not the golden-vs-predicted comparison functions (verify_matches/
    verify_misses) that live alongside it there.
    """
    if not source_text:
        return False
    keywords = _flagged_keywords(golden_issue)
    for block in _paragraph_blocks(source_text):
        if _CITATION.search(block) and any(keyword in block for keyword in keywords):
            return True
    return False
