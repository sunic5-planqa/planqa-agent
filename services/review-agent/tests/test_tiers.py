from __future__ import annotations

from planqa_review.tiers import ABSENCE_CHECK_RULE_IDS, TIER_CATEGORIES, TIER_ORDER, rules_for_tier
from planqa_schemas.rulebook import parse_rulebook
from planqa_schemas.schema import Level


def test_tier_order_is_coarse_to_fine():
    assert TIER_ORDER == (Level.DOCUMENT, Level.LOGICAL_UNIT, Level.PARAGRAPH, Level.SENTENCE)


def test_word_tier_has_no_assigned_categories():
    assert Level.WORD not in TIER_CATEGORIES


def test_every_assigned_category_exists_in_the_real_rulebook(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    for categories in TIER_CATEGORIES.values():
        for category in categories:
            assert category in rulebook.categories


def test_rules_for_tier_matches_document_declared_categories(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    rules = rules_for_tier(rulebook, Level.LOGICAL_UNIT)
    categories = {rule.category for rule in rules}
    assert categories == set(TIER_CATEGORIES[Level.LOGICAL_UNIT])


def test_rules_for_tier_empty_for_word_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    assert rules_for_tier(rulebook, Level.WORD) == []


def test_tier_categories_matches_rulebook_section_2():
    assert TIER_CATEGORIES[Level.DOCUMENT] == ("LG", "LF", "TC", "TM", "MI", "RD", "GA")
    assert TIER_CATEGORIES[Level.LOGICAL_UNIT] == ("LG", "LF", "TC", "TM", "AE", "MI", "RD", "GA")
    assert TIER_CATEGORIES[Level.PARAGRAPH] == ("LG", "LF", "TC", "TM", "AE", "MI", "RD")
    assert TIER_CATEGORIES[Level.SENTENCE] == ("LG", "TC", "TM", "AE", "MI")


def test_absence_check_rules_are_exactly_what_section_1_names():
    assert ABSENCE_CHECK_RULE_IDS == frozenset({"LG-01", "TC-02"})


def test_rules_for_tier_includes_absence_check_rules_only_at_document_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    document_rule_ids = {rule.rule_id for rule in rules_for_tier(rulebook, Level.DOCUMENT)}
    assert ABSENCE_CHECK_RULE_IDS <= document_rule_ids

    for level in (Level.LOGICAL_UNIT, Level.PARAGRAPH, Level.SENTENCE):
        rule_ids = {rule.rule_id for rule in rules_for_tier(rulebook, level)}
        assert rule_ids.isdisjoint(ABSENCE_CHECK_RULE_IDS)


def test_rules_for_tier_keeps_other_lg_and_tc_rules_outside_document_level(rulebook_path):
    """Excluding LG-01/TC-02 outside Document must not accidentally drop the rest of their
    categories — LG-02..05 and TC-01/03/04/05 still apply at Logical Unit."""
    rulebook = parse_rulebook(rulebook_path)
    rule_ids = {rule.rule_id for rule in rules_for_tier(rulebook, Level.LOGICAL_UNIT)}
    assert "LG-02" in rule_ids
    assert "TC-01" in rule_ids
