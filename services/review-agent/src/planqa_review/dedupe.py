from __future__ import annotations

from planqa_review.tiers import TIER_ORDER
from planqa_schemas.schema import Issue

# Finer tiers are more specific and preferred on a duplicate — SENTENCE=0 ... DOCUMENT=3.
_TIER_SPECIFICITY = {level.value: rank for rank, level in enumerate(reversed(TIER_ORDER))}


def _locations_overlap(a: str, b: str) -> bool:
    """Finer-tier chunk locations extend their parent's with ' > ' (see document.py), so
    containment either direction means one issue sits inside the other's scope."""
    return a == b or a.startswith(f"{b} > ") or b.startswith(f"{a} > ")


def _same_relation(a: Issue, b: Issue) -> bool:
    # LG/LF/GA findings carry a second location (related_location) — two issues that
    # otherwise look like duplicates (same rule_id, overlapping location) but point at
    # different related_location values are two distinct relational findings, not a
    # coarse/fine repeat of the same one. Only treat them as the same relation (dedupe-able)
    # when at least one side has no related_location to disagree with.
    if a.related_location is None or b.related_location is None:
        return True
    return a.related_location == b.related_location


def _same_reference(a: Issue, b: Issue) -> bool:
    # XDC(타문서 정합성) findings carry a reference_document — a current-doc location
    # mismatching two different reference documents on the same policy is two distinct
    # findings, same reasoning/pattern as _same_relation above for related_location.
    if a.reference_document is None or b.reference_document is None:
        return True
    return a.reference_document == b.reference_document


def dedupe_issues(issues: list[Issue]) -> list[Issue]:
    """5단계 — §2 assigns several categories (e.g. MI) to more than one tier, so the same
    underlying problem can get flagged at both a coarse and a fine granularity. Collapse
    same-rule_id issues at overlapping locations down to the most specific (finest-tier)
    instance, keeping tier order stable for everything else."""
    ordered = sorted(issues, key=lambda issue: _TIER_SPECIFICITY.get(issue.level, len(TIER_ORDER)))
    kept: list[Issue] = []
    for issue in ordered:
        if any(
            issue.rule_id == existing.rule_id
            and _locations_overlap(issue.location, existing.location)
            and _same_relation(issue, existing)
            and _same_reference(issue, existing)
            for existing in kept
        ):
            continue
        kept.append(issue)
    return kept
