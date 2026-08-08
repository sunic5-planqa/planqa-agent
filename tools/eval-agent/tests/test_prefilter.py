from __future__ import annotations

from planqa_eval.prefilter import candidate_pairs, category_of, group_by_doc_and_category
from planqa_schemas.schema import Issue


def _issue(doc_id: str, rule_id: str) -> Issue:
    return Issue(doc_id=doc_id, level="Sentence", rule_id=rule_id, location="x", description="y")


def test_category_of():
    assert category_of("AE-03") == "AE"
    assert category_of("LG-01") == "LG"


def test_groups_by_doc_and_category():
    issues = [_issue("DOC-001", "AE-01"), _issue("DOC-001", "AE-03"), _issue("DOC-002", "LG-01")]
    grouped = group_by_doc_and_category(issues)
    assert set(grouped["DOC-001"]["AE"]) == set(issues[:2])
    assert grouped["DOC-002"]["LG"] == [issues[2]]


def test_candidate_pairs_only_buckets_shared_doc_and_category():
    golden = [_issue("DOC-001", "AE-01")]
    predicted = [_issue("DOC-001", "AE-03"), _issue("DOC-002", "LG-01")]
    pairs = candidate_pairs(golden, predicted)
    assert set(pairs) == {"DOC-001", "DOC-002"}
    assert pairs["DOC-001"]["AE"] == (golden, [predicted[0]])
    assert pairs["DOC-002"]["LG"] == ([], [predicted[1]])
