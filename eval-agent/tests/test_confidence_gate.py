from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.harness.confidence_gate import HumanBlindLabel, issue_key, run_confidence_gate
from planqa_eval.schema import Issue

_MATCH_RESPONSE = {"matches": [{"golden_index": 0, "predicted_index": 0}]}


def _pair():
    golden = Issue(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="golden desc")
    predicted = Issue(
        doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="pred desc", issue_id="P1"
    )
    return golden, predicted


def _score_response(value: int) -> dict:
    return {
        "root_cause_accuracy": value,
        "no_hallucination": value,
        "service_tone_fit": value,
        "actionability": value,
    }


def _human_label(golden: Issue) -> HumanBlindLabel:
    return HumanBlindLabel(
        golden_issue_id=issue_key(golden),
        matched_predicted_issue_id="P1",
        root_cause_accuracy=4,
        no_hallucination=4,
        service_tone_fit=4,
        actionability=4,
    )


def test_run_confidence_gate_without_assembly_matches_existing_behavior():
    golden, predicted = _pair()
    llm = ScriptedLLM([_MATCH_RESPONSE, _score_response(4)])

    report = run_confidence_gate([golden], [predicted], [_human_label(golden)], llm)

    assert report.matcher_agreement == 1.0
    assert report.judge_agreement == 1.0
    assert report.rule_level_accuracy == 1.0
    assert report.passed is True
    assert report.judge_prompt_hash is not None
    assert report.log[0]["ambiguous"] is False


def test_run_confidence_gate_with_assembly_scores_via_ensemble():
    golden, predicted = _pair()
    llm = ScriptedLLM([_MATCH_RESPONSE])  # arbiter not needed — ensemble agrees
    assembly = [
        ("a", ScriptedLLM([_score_response(4)])),
        ("b", ScriptedLLM([_score_response(4)])),
        ("c", ScriptedLLM([_score_response(4)])),
    ]

    report = run_confidence_gate([golden], [predicted], [_human_label(golden)], llm, assembly=assembly)

    assert report.judge_agreement == 1.0
    assert report.log[0]["ambiguous"] is False
    assert report.log[0]["judge_average"] == 4.0
