from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.bundled_verdict import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


def test_review_document_two_passes_end_to_end(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    # 문단형 청킹 = 딱 2패스(Paragraph, Document) — 위계형(4틴어)과 달리 Logical Unit/
    # Sentence 패스가 없음.
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
                        "rationale": "MI-01 위반",
                        "fix_direction": "목적을 구체화할 것",
                        "excused": False,
                    }
                ]
            },  # Paragraph pass
            {"violations": []},  # Document pass
        ]
    )
    screen_llm = ScriptedLLM([])  # unused by this structure

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    assert len(screen_llm.calls) == 0
    assert len(confirm_llm.calls) == 3  # 1 context + 2 passes
    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Paragraph"

    single_pass_events = [e for e in result.call_events if e.stage == "single_pass"]
    assert len(single_pass_events) == 2


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


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": ""},
            {"violations": []},  # Paragraph pass
            {
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "GA-01",
                        "original_text": "x",
                        "description": "d",
                        "rationale": "r",
                        "fix_direction": "f",
                        "excused": False,
                    }
                ]
            },  # Document pass
        ]
    )
    screen_llm = ScriptedLLM([])

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "GA-01"
    assert issue.level == "Document"
