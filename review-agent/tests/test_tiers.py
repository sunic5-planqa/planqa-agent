from __future__ import annotations

from planqa_review.tiers import TIER_CATEGORIES, TIER_ORDER
from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Level


def test_tier_order_is_coarse_to_fine():
    assert TIER_ORDER == (Level.DOCUMENT, Level.LOGICAL_UNIT, Level.PARAGRAPH, Level.SENTENCE)


def test_word_tier_has_no_assigned_categories():
    assert Level.WORD not in TIER_CATEGORIES


def test_every_assigned_category_exists_in_the_real_rulebook(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    for categories in TIER_CATEGORIES.values():
        for category in categories:
            assert category in rulebook.categories
