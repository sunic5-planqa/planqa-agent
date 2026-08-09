from __future__ import annotations

from planqa_schemas.rulebook import RuleBook, RuleDef
from planqa_schemas.schema import Level

# Transcribed from rulebook_v1.0.md §2 "카테고리별 검토 위계". That table's cells contain
# literal newlines inside a single markdown cell (Notion export artifact), which isn't safe
# to regex-parse reliably — the 8 category prefixes below come from the same file's ## N.
# headings (already parsed by rulebook.py), only the tier->category assignment is transcribed
# by hand. Keep this in sync if rulebook_v1.0.md §2 changes.
#
# Word tier (5차) has no categories/input unit listed in §2 yet, so it's intentionally
# excluded from review — see docs/review_agent_architecture.md "확장 포인트".
TIER_CATEGORIES: dict[Level, tuple[str, ...]] = {
    Level.DOCUMENT: ("LG", "LF", "TC", "TM", "MI", "RD", "GA"),
    Level.LOGICAL_UNIT: ("LG", "LF", "TC", "TM", "AE", "MI", "RD", "GA"),
    Level.PARAGRAPH: ("LG", "LF", "TC", "TM", "AE", "MI", "RD"),
    Level.SENTENCE: ("LG", "TC", "TM", "AE", "MI"),
}

# Review call order — coarse-to-fine, matching the 1차~4차 sequence in §2.
TIER_ORDER: tuple[Level, ...] = (
    Level.DOCUMENT,
    Level.LOGICAL_UNIT,
    Level.PARAGRAPH,
    Level.SENTENCE,
)


def rules_for_tier(rulebook: RuleBook, level: Level) -> list[RuleDef]:
    """Shared across every model profile (not just gemini_lite) and by the pipeline's own
    instrumentation, which needs to know which rules a tier's call covers without importing
    a specific profile's internals."""
    categories = TIER_CATEGORIES.get(level, ())
    return [rule for rule in rulebook.rules.values() if rule.category in categories]
