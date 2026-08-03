from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.review_agent.confirmer import confirm_candidates
from planqa_eval.review_agent.document import Chunk
from planqa_eval.review_agent.screener import ScreenCandidate
from planqa_eval.rulebook import parse_rulebook
from planqa_eval.schema import Level


def _chunk() -> Chunk:
    return Chunk(level=Level.LOGICAL_UNIT, location="1. 목적", text="배경 설명입니다.")


def _candidate(rule_id: str = "MI-01") -> ScreenCandidate:
    return ScreenCandidate(chunk_index=0, rule_id=rule_id, quoted_text="배경 설명입니다.", reason="목적 불명확")


def test_confirm_candidates_creates_issue_when_violated(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM(
        [
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "배경 설명입니다.",
                        "description": "목적이 명시되지 않음",
                        "rationale": "MI-01 위반",
                        "fix_direction": "목적을 구체적으로 설명한다.",
                        "excused": False,
                        "excuse_reason": None,
                    }
                ]
            }
        ]
    )
    [issue] = confirm_candidates(
        [_candidate()], [_chunk()], rulebook, "DOC-TEST", Level.LOGICAL_UNIT, "", "배경 설명입니다.", llm
    )
    assert issue.rule_id == "MI-01"
    assert issue.level == "Logical Unit"
    assert issue.location == "1. 목적"
    assert issue.original_text == "배경 설명입니다."
    assert issue.fix_direction == "목적을 구체적으로 설명한다."


def test_confirm_candidates_skips_when_not_violated(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM([{"verdicts": [{"index": 0, "violated": False}]}])
    issues = confirm_candidates(
        [_candidate()], [_chunk()], rulebook, "DOC-TEST", Level.LOGICAL_UNIT, "", "", llm
    )
    assert issues == []


def test_confirm_candidates_skips_when_llm_marks_excused(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM(
        [{"verdicts": [{"index": 0, "violated": True, "excused": True, "excuse_reason": "예외 적용"}]}]
    )
    issues = confirm_candidates(
        [_candidate()], [_chunk()], rulebook, "DOC-TEST", Level.LOGICAL_UNIT, "", "", llm
    )
    assert issues == []


def test_confirm_candidates_reference_exception_overrides_llm_self_report(rulebook_path):
    # AE-01 is one of §3's reference-exception rules — has_valid_reference_exception (already
    # validated in test_verifier.py) must decide this, not the LLM's own excused=False claim.
    rulebook = parse_rulebook(rulebook_path)
    chunk = Chunk(level=Level.SENTENCE, location="배송", text="「최대 지연 3일」")
    candidate = ScreenCandidate(chunk_index=0, rule_id="AE-01", quoted_text="「최대 지연 3일」", reason="수치 없음")
    source_text = "세부 기준은 운영정책서(DOC-020) 참고. 「최대 지연 3일」로 안내한다."
    llm = ScriptedLLM(
        [
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "「최대 지연 3일」",
                        "description": "정량 표현이나 근거 확인 필요",
                        "excused": False,
                        "excuse_reason": None,
                    }
                ]
            }
        ]
    )
    issues = confirm_candidates(
        [candidate], [chunk], rulebook, "DOC-020", Level.SENTENCE, "", source_text, llm
    )
    assert issues == []


def test_confirm_candidates_skips_index_dropped_from_batch_response(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM([{"verdicts": []}])
    issues = confirm_candidates(
        [_candidate()], [_chunk()], rulebook, "DOC-TEST", Level.LOGICAL_UNIT, "", "", llm
    )
    assert issues == []


def test_confirm_candidates_returns_empty_without_llm_call_when_no_candidates(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    llm = ScriptedLLM([{"verdicts": []}])
    assert confirm_candidates([], [], rulebook, "DOC-TEST", Level.LOGICAL_UNIT, "", "", llm) == []
    assert llm.calls == []
