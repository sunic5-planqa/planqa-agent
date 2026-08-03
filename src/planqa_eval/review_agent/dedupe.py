from __future__ import annotations

from planqa_eval.review_agent.tiers import TIER_ORDER
from planqa_eval.schema import Issue

# Finer tiers are more specific and preferred on a duplicate — SENTENCE=0 ... DOCUMENT=3.
_TIER_SPECIFICITY = {level.value: rank for rank, level in enumerate(reversed(TIER_ORDER))}


def _locations_overlap(a: str, b: str) -> bool:
    """Finer-tier chunk locations extend their parent's with ' > ' (see document.py), so
    containment either direction means one issue sits inside the other's scope."""
    return a == b or a.startswith(f"{b} > ") or b.startswith(f"{a} > ")


def dedupe_issues(issues: list[Issue]) -> list[Issue]:
    """5단계 — §2 assigns several categories (e.g. MI) to more than one tier, so the same
    underlying problem can get flagged at both a coarse and a fine granularity. Collapse
    same-rule_id issues at overlapping locations down to the most specific (finest-tier)
    instance, keeping tier order stable for everything else."""
    ordered = sorted(issues, key=lambda issue: _TIER_SPECIFICITY.get(issue.level, len(TIER_ORDER)))
    kept: list[Issue] = []
    for issue in ordered:
        if any(
            issue.rule_id == existing.rule_id and _locations_overlap(issue.location, existing.location)
            for existing in kept
        ):
            continue
        kept.append(issue)
    return kept
