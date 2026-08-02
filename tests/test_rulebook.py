from __future__ import annotations

from planqa_eval.rulebook import parse_rulebook
from planqa_eval.schema import Level


def test_parses_all_eight_categories(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert set(rb.categories) == {"LG", "LF", "TC", "TM", "AE", "MI", "RD", "GA"}


def test_reference_exception_rules_match_section_3(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert rb.reference_exception_rule_ids == {"LG-04", "TC-02", "AE-01", "GA-03"}


def test_rule_fields_parsed(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    rule = rb.rule("LG-01")
    assert rule is not None
    assert rule.category == "LG"
    assert "근거" in rule.text
    assert rule.fixed_level is None
    assert rule.exception_text is not None


def test_dash_exception_becomes_none(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert rb.rule("LG-03").exception_text is None


def test_rd_ga_rules_have_fixed_level(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert rb.rule("RD-01").fixed_level == Level.PARAGRAPH
    assert rb.rule("GA-03").fixed_level == Level.DOCUMENT


def test_authoring_progress_table_does_not_pollute_rule_definitions(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    # the file ends with a "Rule ID | 채워야 할 개수 | 담당자" tracking table that reuses every
    # Rule ID — make sure it never overwrote the real rule definitions with (count, assignee)
    assert rb.rule("LG-01").text != "3"
    assert rb.rule("LG-01").category_label.startswith("논리비약")


def test_unknown_rule_id_returns_none(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert rb.rule("ZZ-99") is None
    assert rb.category_of("ZZ-99") is None
