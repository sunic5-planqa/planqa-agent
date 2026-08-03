from __future__ import annotations

from planqa_eval.review_agent.dedupe import dedupe_issues
from planqa_eval.schema import Issue


def _issue(rule_id: str, level: str, location: str) -> Issue:
    return Issue(doc_id="DOC-TEST", level=level, rule_id=rule_id, location=location, description="d")


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
