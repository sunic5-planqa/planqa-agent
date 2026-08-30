from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.bundled_fewshot import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


def test_review_document_never_leaks_rule_text_into_the_prompt(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM([{"summary": ""}, {"violations": []}, {"violations": []}])
    screen_llm = ScriptedLLM([])

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    mi01_rule = rulebook.rules["MI-01"]
    paragraph_pass_prompt = confirm_llm.calls[1]["prompt"]
    assert mi01_rule.text not in paragraph_pass_prompt


def test_review_document_flags_a_violation(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": "이 문서는 홈 화면의 목적을 설명한다."},
            {
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "MI-01",
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "목적이 구체적이지 않음",
                        "rationale": "MI-01 위반 패턴과 일치",
                        "fix_direction": "목적을 구체화할 것",
                        "excused": False,
                    }
                ]
            },
            {"violations": []},
        ]
    )
    screen_llm = ScriptedLLM([])

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
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "MI-01",
                        "original_text": "x",
                        "description": "d",
                        "rationale": "r",
                        "fix_direction": "f",
                        "excused": True,
                        "excuse_reason": "예외 적용",
                    }
                ]
            },
            {"violations": []},
        ]
    )
    screen_llm = ScriptedLLM([])

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.issues == ()
