from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval_service.judge import judge_review_result


def _issue(**kwargs) -> dict:
    defaults = dict(
        issue_id="REV-DOC-001-000",
        rule_id="LG-01",
        location="1장",
        original_text="예시 문장",
        description="설명",
        rationale="근거",
    )
    defaults.update(kwargs)
    return defaults


def _review_result(*issues) -> dict:
    return {"issues": list(issues)}


def test_no_issues_short_circuits_with_no_llm_call():
    llm = ScriptedLLM([])
    result = judge_review_result(_review_result(), llm, rulebook=None)
    assert result == {"issue_count": 0, "flagged_count": 0, "verdicts": []}
    assert llm.calls == []


def test_confident_tier1_verdict_is_final_no_escalation(rulebook):
    llm = ScriptedLLM(
        [{"verdicts": [{"index": 0, "valid": True, "confidence": "confident", "reason": "clearly matches"}]}]
    )
    result = judge_review_result(_review_result(_issue()), llm, rulebook)
    assert len(llm.calls) == 1
    assert result["issue_count"] == 1
    assert result["flagged_count"] == 0
    assert result["verdicts"][0]["tier"] == "cheap"
    assert result["verdicts"][0]["valid"] is True


def test_uncertain_tier1_without_assembly_stays_final(rulebook):
    llm = ScriptedLLM(
        [{"verdicts": [{"index": 0, "valid": False, "confidence": "uncertain", "reason": "not sure"}]}]
    )
    result = judge_review_result(_review_result(_issue()), llm, rulebook)
    assert len(llm.calls) == 1  # no assembly given, nothing to escalate to
    assert result["verdicts"][0]["tier"] == "cheap"
    assert result["verdicts"][0]["valid"] is False


def test_uncertain_tier1_escalates_and_ensemble_agrees(rulebook):
    llm = ScriptedLLM(
        [{"verdicts": [{"index": 0, "valid": True, "confidence": "uncertain", "reason": "borderline"}]}]
    )
    assembly = [
        ("a", ScriptedLLM([{"valid": False, "reason": "r-a"}])),
        ("b", ScriptedLLM([{"valid": False, "reason": "r-b"}])),
        ("c", ScriptedLLM([{"valid": True, "reason": "r-c"}])),
    ]
    result = judge_review_result(_review_result(_issue()), llm, rulebook, assembly=assembly)
    verdict = result["verdicts"][0]
    assert verdict["tier"] == "ensemble"
    assert verdict["valid"] is False  # 2/3 majority says invalid
    assert verdict["ambiguous"] is False
    assert result["flagged_count"] == 1


def test_uncertain_tier1_escalates_ensemble_splits_arbiter_decides(rulebook):
    llm = ScriptedLLM(
        [{"verdicts": [{"index": 0, "valid": True, "confidence": "uncertain", "reason": "borderline"}]}]
    )
    assembly = [
        ("a", ScriptedLLM([{"valid": True, "reason": "r-a"}])),
        ("b", ScriptedLLM([{"valid": False, "reason": "r-b"}])),
    ]
    arbiter = ScriptedLLM([{"valid": False, "reason": "arbiter final"}])
    result = judge_review_result(_review_result(_issue()), llm, rulebook, assembly=assembly, arbiter=arbiter)
    verdict = result["verdicts"][0]
    assert verdict["tier"] == "arbiter"
    assert verdict["ambiguous"] is True
    assert verdict["valid"] is False
    assert len(arbiter.calls) == 1


def test_tier1_missing_index_falls_back_to_trusting_confirm(rulebook):
    llm = ScriptedLLM([{"verdicts": []}])  # index 0 missing entirely
    result = judge_review_result(_review_result(_issue()), llm, rulebook)
    verdict = result["verdicts"][0]
    assert verdict["valid"] is True  # conservative default — don't flag on no evidence
    assert verdict["tier"] == "cheap"


def test_multiple_issues_only_uncertain_ones_escalate(rulebook):
    llm = ScriptedLLM(
        [
            {
                "verdicts": [
                    {"index": 0, "valid": True, "confidence": "confident", "reason": "fine"},
                    {"index": 1, "valid": True, "confidence": "uncertain", "reason": "borderline"},
                ]
            }
        ]
    )
    assembly = [
        ("a", ScriptedLLM([{"valid": False, "reason": "r-a"}])),
        ("b", ScriptedLLM([{"valid": False, "reason": "r-b"}])),
    ]
    result = judge_review_result(
        _review_result(_issue(issue_id="i0"), _issue(issue_id="i1")), llm, rulebook, assembly=assembly
    )
    assert result["verdicts"][0]["tier"] == "cheap"
    assert result["verdicts"][1]["tier"] == "ensemble"
    assert result["flagged_count"] == 1
