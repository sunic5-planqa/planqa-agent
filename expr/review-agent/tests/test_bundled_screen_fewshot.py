from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.bundled_screen_fewshot import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


def test_review_document_never_leaks_rule_text_into_either_stage(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM([{"summary": ""}, {"verdicts": []}])
    screen_llm = ScriptedLLM(
        [
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "r"}]},
            {"candidates": []},
        ]
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    mi01_rule = rulebook.rules["MI-01"]
    assert mi01_rule.text not in screen_llm.calls[0]["prompt"]
    assert mi01_rule.text not in confirm_llm.calls[1]["prompt"]


def test_review_document_flags_a_violation(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": "이 문서는 홈 화면의 목적을 설명한다."},
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "목적이 구체적이지 않음",
                        "fix_direction": "목적을 구체화할 것",
                        "excused": False,
                    }
                ]
            },
        ]
    )
    screen_llm = ScriptedLLM(
        [
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "불명확"}]},
            {"candidates": []},
        ]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Paragraph"


def test_review_document_respects_excused_flag(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": ""},
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "x",
                        "description": "d",
                        "fix_direction": "f",
                        "excused": True,
                        "excuse_reason": "예외 적용",
                    }
                ]
            },
        ]
    )
    screen_llm = ScriptedLLM(
        [
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "r"}]},
            {"candidates": []},
        ]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.issues == ()
