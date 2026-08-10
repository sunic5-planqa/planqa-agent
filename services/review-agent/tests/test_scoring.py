from __future__ import annotations

from planqa_schemas.schema import Issue
from planqa_review.scoring import (
    GoldenRow,
    ScoreCounts,
    category_of,
    load_golden_rows,
    merge_score_results,
    score_issues,
)


def _issue(**overrides) -> Issue:
    defaults = dict(
        doc_id="DOC-003",
        level="Sentence",
        rule_id="AE-03",
        location="4. 상품 컨디션 등급 기준 > 등급표",
        description="모호한 표현",
    )
    defaults.update(overrides)
    return Issue(**defaults)


def _golden(**overrides) -> GoldenRow:
    defaults = dict(
        doc_id="DOC-003",
        level="Sentence",
        rule_id="AE-03",
        location="4. 상품 컨디션 등급 기준 > 등급표 A·B·C 행",
    )
    defaults.update(overrides)
    return GoldenRow(**defaults)


def test_category_of_derives_prefix_from_rule_id():
    assert category_of("AE-03") == "AE"
    assert category_of("LG-01") == "LG"


def test_score_counts_recall_and_precision():
    counts = ScoreCounts(true_positives=3, false_positives=1, false_negatives=2)
    assert counts.recall == 3 / 5
    assert counts.precision == 3 / 4


def test_score_counts_recall_and_precision_are_none_with_no_denominator():
    assert ScoreCounts().recall is None
    assert ScoreCounts().precision is None


def test_score_counts_add_sums_fields():
    total = ScoreCounts(true_positives=1, false_positives=1) + ScoreCounts(true_positives=2, false_negatives=1)
    assert total == ScoreCounts(true_positives=3, false_positives=1, false_negatives=1)


def test_score_issues_matches_same_rule_and_overlapping_location():
    result = score_issues("DOC-003", [_issue()], [_golden()])
    assert result.overall == ScoreCounts(true_positives=1)
    assert result.by_rule["AE-03"] == ScoreCounts(true_positives=1)
    assert result.by_category["AE"] == ScoreCounts(true_positives=1)
    assert result.missed_golden == ()
    assert result.unmatched_issues == ()


def test_score_issues_counts_false_negative_when_golden_row_has_no_matching_issue():
    result = score_issues("DOC-003", [], [_golden()])
    assert result.overall == ScoreCounts(false_negatives=1)
    assert result.missed_golden == (_golden(),)


def test_score_issues_counts_false_positive_when_issue_has_no_matching_golden_row():
    result = score_issues("DOC-003", [_issue(rule_id="MI-01")], [_golden()])
    assert result.overall == ScoreCounts(false_positives=1, false_negatives=1)
    assert result.unmatched_issues == (_issue(rule_id="MI-01"),)


def test_score_issues_requires_matching_rule_id_even_if_location_overlaps():
    result = score_issues("DOC-003", [_issue(rule_id="TM-01")], [_golden(rule_id="AE-03")])
    assert result.overall.true_positives == 0
    assert result.overall.false_positives == 1
    assert result.overall.false_negatives == 1


def test_score_issues_ignores_rows_and_issues_for_other_documents():
    result = score_issues("DOC-003", [_issue(doc_id="DOC-004")], [_golden(doc_id="DOC-005")])
    assert result.overall == ScoreCounts()


def test_score_issues_matches_when_issue_location_is_substring_of_golden_location():
    issue = _issue(location="등급표 A·B·C 행")
    result = score_issues("DOC-003", [issue], [_golden()])
    assert result.overall.true_positives == 1


def test_score_issues_does_not_double_match_one_golden_row_to_two_issues():
    result = score_issues("DOC-003", [_issue(), _issue()], [_golden()])
    assert result.overall.true_positives == 1
    assert result.overall.false_positives == 1


def test_merge_score_results_sums_across_documents():
    result_a = score_issues("DOC-003", [_issue()], [_golden()])
    result_b = score_issues("DOC-004", [], [_golden(doc_id="DOC-004")])
    merged = merge_score_results([result_a, result_b])
    assert merged.overall == ScoreCounts(true_positives=1, false_negatives=1)
    assert merged.by_rule["AE-03"] == ScoreCounts(true_positives=1, false_negatives=1)


def test_load_golden_rows_skips_blank_spacer_rows_and_parses_real_sheet(qa_dataset_path):
    rows = load_golden_rows(qa_dataset_path)
    assert len(rows) == 131
    assert all(row.doc_id and row.rule_id for row in rows)
    doc_001_rows = [row for row in rows if row.doc_id == "DOC-001"]
    assert len(doc_001_rows) == 1
    assert doc_001_rows[0].rule_id == "LG-05"


def test_load_golden_rows_covers_doc_000_and_the_synthetic_range(qa_dataset_path):
    rows = load_golden_rows(qa_dataset_path)
    doc_ids = {row.doc_id for row in rows}
    assert "DOC-000" in doc_ids
    assert "DOC-021" in doc_ids  # synthetic DOC-021..040 range, per progress notes
