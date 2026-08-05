from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.matcher import match_all, match_bucket
from planqa_eval.schema import Issue


def _issue(doc_id: str, rule_id: str, location: str = "x") -> Issue:
    return Issue(
        doc_id=doc_id,
        level="Sentence",
        rule_id=rule_id,
        location=location,
        description="y",
        issue_id=f"{doc_id}-{rule_id}-{location}",
    )


def test_match_bucket_skips_llm_when_golden_empty():
    predicted = [_issue("DOC-001", "AE-01")]
    llm = ScriptedLLM([{"matches": []}])
    result = match_bucket([], predicted, llm)
    assert result.fp_candidates == predicted
    assert llm.calls == []


def test_match_bucket_skips_llm_when_predicted_empty():
    golden = [_issue("DOC-001", "AE-01")]
    llm = ScriptedLLM([{"matches": []}])
    result = match_bucket(golden, [], llm)
    assert result.fn_candidates == golden
    assert llm.calls == []


def test_match_bucket_parses_matches_and_leftovers():
    golden = [_issue("DOC-001", "AE-01", "a"), _issue("DOC-001", "AE-01", "b")]
    predicted = [_issue("DOC-001", "AE-01", "c")]
    llm = ScriptedLLM([{"matches": [{"golden_index": 1, "predicted_index": 0}]}])
    result = match_bucket(golden, predicted, llm)
    assert result.matched == [(golden[1], predicted[0])]
    assert result.fn_candidates == [golden[0]]
    assert result.fp_candidates == []


def test_match_bucket_ignores_duplicate_and_out_of_range_pairs():
    golden = [_issue("DOC-001", "AE-01")]
    predicted = [_issue("DOC-001", "AE-01")]
    llm = ScriptedLLM(
        [{"matches": [{"golden_index": 0, "predicted_index": 0}, {"golden_index": 0, "predicted_index": 5}]}]
    )
    result = match_bucket(golden, predicted, llm)
    assert len(result.matched) == 1


def test_match_all_only_compares_within_same_category_bucket():
    golden = [_issue("DOC-001", "AE-01"), _issue("DOC-001", "LG-01")]
    predicted = [_issue("DOC-001", "AE-01")]
    llm = ScriptedLLM([{"matches": [{"golden_index": 0, "predicted_index": 0}]}])
    result = match_all(golden, predicted, llm)
    assert len(result.matched) == 1
    assert result.fn_candidates == [golden[1]]
