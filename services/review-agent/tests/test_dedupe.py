from __future__ import annotations

from planqa_review.dedupe import dedupe_issues
from planqa_schemas.schema import Issue


def _issue(
    rule_id: str,
    level: str,
    location: str,
    related_location: str | None = None,
    reference_document: str | None = None,
) -> Issue:
    return Issue(
        doc_id="DOC-TEST",
        level=level,
        rule_id=rule_id,
        location=location,
        description="d",
        related_location=related_location,
        reference_document=reference_document,
    )


def test_dedupe_keeps_finer_tier_when_locations_are_identical():
    coarse = _issue("MI-01", "Paragraph", "1. 목적")
    fine = _issue("MI-01", "Sentence", "1. 목적")
    kept = dedupe_issues([coarse, fine])
    assert kept == [fine]


def test_dedupe_keeps_finer_tier_when_location_is_nested():
    coarse = _issue("MI-01", "Logical Unit", "1. 목적")
    fine = _issue("MI-01", "Paragraph", "1. 목적 > a. 배경")
    kept = dedupe_issues([coarse, fine])
    assert kept == [fine]


def test_dedupe_keeps_both_when_rule_id_differs():
    a = _issue("MI-01", "Paragraph", "1. 목적")
    b = _issue("AE-01", "Paragraph", "1. 목적")
    assert set(dedupe_issues([a, b])) == {a, b}


def test_dedupe_keeps_both_when_locations_are_unrelated():
    a = _issue("MI-01", "Paragraph", "1. 목적")
    b = _issue("MI-01", "Paragraph", "2. 기능")
    assert set(dedupe_issues([a, b])) == {a, b}


def test_dedupe_keeps_both_relational_findings_with_different_related_location():
    # Same rule/location but two genuinely different relational findings (2-2 contradicts
    # both 1-3 and 3-1) — collapsing these would silently drop one, defeating the whole
    # point of related_location.
    a = _issue("LG-02", "Paragraph", "2-2", related_location="1-3")
    b = _issue("LG-02", "Paragraph", "2-2", related_location="3-1")
    assert set(dedupe_issues([a, b])) == {a, b}


def test_dedupe_still_collapses_when_related_location_matches():
    coarse = _issue("LG-02", "Logical Unit", "2. 배경", related_location="1-3")
    fine = _issue("LG-02", "Paragraph", "2. 배경 > 2-2", related_location="1-3")
    assert dedupe_issues([coarse, fine]) == [fine]


def test_dedupe_still_collapses_when_only_one_side_has_related_location():
    coarse = _issue("LG-02", "Logical Unit", "2. 배경")
    fine = _issue("LG-02", "Paragraph", "2. 배경 > 2-2", related_location="1-3")
    assert dedupe_issues([coarse, fine]) == [fine]


def test_dedupe_keeps_both_xdc_findings_against_different_reference_documents():
    # Same rule/location on the current doc but mismatching two different reference
    # documents on the same policy — two distinct findings, same reasoning as
    # related_location above.
    a = _issue("XDC-01", "Paragraph", "1. 신청 기한", reference_document="DOC-005")
    b = _issue("XDC-01", "Paragraph", "1. 신청 기한", reference_document="DOC-007")
    assert set(dedupe_issues([a, b])) == {a, b}


def test_dedupe_still_collapses_xdc_when_only_one_side_has_reference_document():
    coarse = _issue("XDC-01", "Logical Unit", "1. 신청 기한")
    fine = _issue("XDC-01", "Paragraph", "1. 신청 기한 > a", reference_document="DOC-005")
    assert dedupe_issues([coarse, fine]) == [fine]
