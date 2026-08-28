from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.bundled_screen import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


def test_review_document_two_passes_end_to_end(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    confirm_llm = ScriptedLLM(
        [
            {"summary": "이 문서는 홈 화면의 목적을 설명한다."},  # context
            {  # Paragraph pass confirm
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
            {  # Paragraph pass screen
                "candidates": [
                    {"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "불명확"}
                ]
            },
            {"candidates": []},  # Document pass screen -> no candidates, confirm skipped
        ]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    assert len(screen_llm.calls) == 2  # 문단형 = 2패스, 각 패스마다 screen 1회
    assert len(confirm_llm.calls) == 2  # 1 context + 1 confirm (Document pass had no candidates)
    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Paragraph"

    screen_events = [e for e in result.call_events if e.stage == "screen"]
    confirm_events = [e for e in result.call_events if e.stage == "confirm"]
    assert len(screen_events) == 2
    assert len(confirm_events) == 1


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


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": ""},
            {  # Document pass confirm
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "x",
                        "description": "d",
                        "fix_direction": "f",
                        "excused": False,
                    }
                ]
            },
        ]
    )
    screen_llm = ScriptedLLM(
        [
            {"candidates": []},  # Paragraph pass screen -> nothing
            {"candidates": [{"chunk_index": 0, "rule_id": "GA-01", "quoted_text": "x", "reason": "r"}]},  # Document pass screen
        ]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "GA-01"
    assert issue.level == "Document"
