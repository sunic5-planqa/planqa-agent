from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures import fewshot_retrieval
from planqa_review.structures.bundled_screen_dynamic_fewshot import review_document
from planqa_review.structures.fewshot_bank import FewShotExample

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n결제 버튼을 누르면 즉시 처리됩니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


def test_review_document_picks_the_example_most_similar_to_the_document(rulebook_path, monkeypatch):
    # k=2 in this structure, so a pool of exactly 3 lets us tell "picked" from "excluded" —
    # the one with zero character overlap with the reference must rank last and drop out.
    monkeypatch.setattr(
        fewshot_retrieval,
        "ALL_VIOLATION_CANDIDATES",
        {
            "MI-01": [
                FewShotExample("zzzqqq999@@@ 완전히 무관함", "전혀 무관한 근거"),
                FewShotExample("배송이 완료되면 알림이 발송됩니다", "배송 관련 근거"),
                FewShotExample("결제 버튼을 누르면 즉시 처리됩니다 관련 예시", "결제 버튼 관련 근거"),
            ]
        },
    )
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM([{"summary": ""}, {"verdicts": []}])
    screen_llm = ScriptedLLM(
        [
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "r"}]},
            {"candidates": []},
        ]
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    screen_prompt = screen_llm.calls[0]["prompt"]
    assert "결제 버튼 관련 근거" in screen_prompt
    assert "전혀 무관한 근거" not in screen_prompt


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
                        "original_text": "결제 버튼을 누르면 즉시 처리됩니다.",
                        "description": "주체 불명확",
                        "fix_direction": "주체를 명시할 것",
                        "excused": False,
                    }
                ]
            },
        ]
    )
    screen_llm = ScriptedLLM(
        [
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "결제 버튼을 누르면 즉시 처리됩니다.", "reason": "불명확"}]},
            {"candidates": []},
        ]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Paragraph"
