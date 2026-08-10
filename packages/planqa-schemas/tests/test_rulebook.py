from __future__ import annotations

from planqa_schemas.rulebook import parse_rulebook


def test_parses_all_eight_categories(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert set(rb.categories) == {"LG", "LF", "TC", "TM", "AE", "MI", "RD", "GA"}


def test_reference_exception_rules_match_section_3(rulebook_path):
    rb = parse_rulebook(rulebook_path)
    assert rb.reference_exception_rule_ids == {"LG-03", "TC-02", "AE-01", "GA-03"}


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
    assert rb.rule("RD-02").exception_text is None


def test_no_rule_has_a_fixed_level_in_the_current_rulebook(rulebook_path):
    # v1.0 (2026-08-05 revision) dropped the per-rule "위계" column RD/GA used to have —
    # this asserts the current reality rather than the old format, so a future rulebook
    # revision that reintroduces per-rule levels will fail this test loudly.
    rb = parse_rulebook(rulebook_path)
    assert all(rule.fixed_level is None for rule in rb.rules.values())


def test_wrapped_table_cell_is_repaired_not_dropped(rulebook_path):
    # RD-01's exception text contains a literal embedded blank line in the source file,
    # which used to make the whole row fail to match and silently disappear.
    rb = parse_rulebook(rulebook_path)
    rd_01 = rb.rule("RD-01")
    assert rd_01 is not None
    assert rd_01.exception_text is not None
    assert "재사용하는 경우 예외" in rd_01.exception_text


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
