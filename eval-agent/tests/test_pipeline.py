from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.pipeline import run_pipeline
from planqa_eval.rulebook import parse_rulebook
from planqa_eval.schema import Issue

_MATCH_RESPONSE = {"matches": [{"golden_index": 0, "predicted_index": 0}]}


def _pair():
    golden = Issue(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="golden desc")
    predicted = Issue(
        doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="pred desc", issue_id="P1"
    )
    return [golden], [predicted]


def _score_response(value: int) -> dict:
    return {
        "root_cause_accuracy": value,
        "no_hallucination": value,
        "service_tone_fit": value,
        "actionability": value,
    }


def test_run_pipeline_without_assembly_uses_single_llm_judge(rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)
    golden, predicted = _pair()
    llm = ScriptedLLM([_MATCH_RESPONSE, {"scores": [{"index": 0, **_score_response(4)}]}])

    result = run_pipeline(golden, predicted, rulebook, source_dir, llm)

    assert len(result.judge_scores) == 1
    assert result.judge_scores[0].ambiguous is False
    assert len(llm.calls) == 2


def test_run_pipeline_with_judge_assembly_uses_ensemble_judge(rulebook_path, source_dir):
    rulebook = parse_rulebook(rulebook_path)
    golden, predicted = _pair()
    llm = ScriptedLLM([_MATCH_RESPONSE])  # only the Matcher call — ensemble members score, not llm
    assembly = [
        ("a", ScriptedLLM([_score_response(4)])),
        ("b", ScriptedLLM([_score_response(4)])),
        ("c", ScriptedLLM([_score_response(4)])),
    ]

    result = run_pipeline(golden, predicted, rulebook, source_dir, llm, judge_assembly=assembly)

    assert len(result.judge_scores) == 1
    assert result.judge_scores[0].average == 4.0
    assert len(llm.calls) == 1  # arbiter never invoked since the ensemble agreed
