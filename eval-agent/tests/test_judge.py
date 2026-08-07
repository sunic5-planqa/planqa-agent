from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.judge import judge_match_ensemble, judge_matches
from planqa_eval.schema import Issue


def _issue(**kwargs) -> Issue:
    defaults = dict(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="y")
    defaults.update(kwargs)
    return Issue(**defaults)


def _score_response(value: int) -> dict:
    return {
        "root_cause_accuracy": value,
        "no_hallucination": value,
        "service_tone_fit": value,
        "actionability": value,
    }


def test_judge_matches_makes_one_call_for_the_whole_batch():
    pairs = [(_issue(), _issue()), (_issue(), _issue())]
    llm = ScriptedLLM(
        [
            {
                "scores": [
                    {
                        "index": 0,
                        "root_cause_accuracy": 5,
                        "no_hallucination": 5,
                        "service_tone_fit": 4,
                        "actionability": 3,
                    },
                    {
                        "index": 1,
                        "root_cause_accuracy": 2,
                        "no_hallucination": 3,
                        "service_tone_fit": 2,
                        "actionability": 1,
                    },
                ]
            }
        ]
    )
    scores = judge_matches(pairs, llm)
    assert len(llm.calls) == 1
    assert len(scores) == 2
    assert scores[0].average == 4.25
    assert scores[1].average == 2.0


def test_judge_matches_empty_list_makes_no_call():
    llm = ScriptedLLM([])
    assert judge_matches([], llm) == []
    assert llm.calls == []


def test_judge_matches_falls_back_per_pair_when_batch_response_is_missing_an_index():
    pairs = [(_issue(), _issue()), (_issue(), _issue())]
    llm = ScriptedLLM(
        [
            # batch response only has index 0 — index 1 must fall back to a single call
            {
                "scores": [
                    {
                        "index": 0,
                        "root_cause_accuracy": 5,
                        "no_hallucination": 5,
                        "service_tone_fit": 5,
                        "actionability": 5,
                    }
                ]
            },
            {
                "root_cause_accuracy": 1,
                "no_hallucination": 1,
                "service_tone_fit": 1,
                "actionability": 1,
            },
        ]
    )
    scores = judge_matches(pairs, llm)
    assert len(llm.calls) == 2
    assert scores[0].average == 5.0
    assert scores[1].average == 1.0


def test_judge_match_ensemble_converges_when_judges_agree():
    golden, predicted = _issue(), _issue()
    assembly = [
        ("a", ScriptedLLM([_score_response(4)])),
        ("b", ScriptedLLM([_score_response(4)])),
        ("c", ScriptedLLM([_score_response(4)])),
    ]
    score = judge_match_ensemble(golden, predicted, assembly)
    assert score.average == 4.0
    assert score.ambiguous is False


def test_judge_match_ensemble_flags_ambiguous_when_judges_diverge():
    golden, predicted = _issue(), _issue()
    assembly = [
        ("a", ScriptedLLM([_score_response(5)])),
        ("b", ScriptedLLM([_score_response(1)])),
        ("c", ScriptedLLM([_score_response(3)])),
    ]
    score = judge_match_ensemble(golden, predicted, assembly)
    assert score.ambiguous is True
    assert score.average == 3.0  # mean of the three axis-wise means (5, 1, 3)


def test_judge_match_ensemble_escalates_to_arbiter_when_ambiguous():
    golden, predicted = _issue(), _issue()
    assembly = [
        ("a", ScriptedLLM([_score_response(5)])),
        ("b", ScriptedLLM([_score_response(1)])),
        ("c", ScriptedLLM([_score_response(3)])),
    ]
    arbiter = ScriptedLLM([_score_response(2)])
    score = judge_match_ensemble(golden, predicted, assembly, arbiter=arbiter)
    assert score.ambiguous is True
    assert score.average == 2.0
    assert len(arbiter.calls) == 1


def test_judge_match_ensemble_does_not_call_arbiter_when_not_ambiguous():
    golden, predicted = _issue(), _issue()
    assembly = [
        ("a", ScriptedLLM([_score_response(4)])),
        ("b", ScriptedLLM([_score_response(4)])),
        ("c", ScriptedLLM([_score_response(4)])),
    ]
    arbiter = ScriptedLLM([])
    score = judge_match_ensemble(golden, predicted, assembly, arbiter=arbiter)
    assert score.ambiguous is False
    assert arbiter.calls == []
