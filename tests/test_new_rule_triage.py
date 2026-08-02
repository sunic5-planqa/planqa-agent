from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.new_rule_triage import triage_fp_candidates
from planqa_eval.rulebook import parse_rulebook
from planqa_eval.schema import Issue


def _issue(**kwargs) -> Issue:
    defaults = dict(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="y")
    defaults.update(kwargs)
    return Issue(**defaults)


def test_triage_makes_one_call_for_the_whole_batch(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    candidates = [_issue(), _issue()]
    llm = ScriptedLLM(
        [
            {
                "triage": [
                    {"index": 0, "verdict": "false_positive", "reasoning": "r0"},
                    {"index": 1, "verdict": "new_rule_candidate", "reasoning": "r1"},
                ]
            }
        ]
    )
    results = triage_fp_candidates(candidates, rulebook, llm)
    assert len(llm.calls) == 1
    assert [r.verdict for r in results] == ["false_positive", "new_rule_candidate"]


def test_triage_empty_list_makes_no_call(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM([])
    assert triage_fp_candidates([], rulebook, llm) == []
    assert llm.calls == []


def test_triage_invalid_verdict_becomes_human_review(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    candidates = [_issue()]
    llm = ScriptedLLM([{"triage": [{"index": 0, "verdict": "not_a_real_verdict"}]}])
    [result] = triage_fp_candidates(candidates, rulebook, llm)
    assert result.verdict == "human_review"


def test_triage_falls_back_per_item_when_batch_response_is_missing_an_index(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    candidates = [_issue(), _issue()]
    llm = ScriptedLLM(
        [
            {"triage": [{"index": 0, "verdict": "false_positive", "reasoning": "r0"}]},
            {"verdict": "human_review", "reasoning": "fallback"},
        ]
    )
    results = triage_fp_candidates(candidates, rulebook, llm)
    assert len(llm.calls) == 2
    assert [r.verdict for r in results] == ["false_positive", "human_review"]
