from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.judge import judge_matches
from planqa_eval.schema import Issue


def _issue(**kwargs) -> Issue:
    defaults = dict(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="y")
    defaults.update(kwargs)
    return Issue(**defaults)


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
