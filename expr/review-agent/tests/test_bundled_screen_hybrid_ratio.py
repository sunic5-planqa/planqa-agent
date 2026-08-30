from __future__ import annotations

import re

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.fewshot_bank import EXCEPTION_EXAMPLES, EXCEPTION_EXAMPLES_RATIO
from planqa_review.structures.bundled_screen_hybrid_ratio import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


def test_review_document_gives_two_excused_examples_where_baseline_gives_one(rulebook_path):
    assert len(EXCEPTION_EXAMPLES["MI-02"]) == 1
    assert len(EXCEPTION_EXAMPLES_RATIO["MI-02"]) == 2

    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM([{"summary": ""}, {"verdicts": []}])
    screen_llm = ScriptedLLM(
        [
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-02", "quoted_text": "x", "reason": "r"}]},
            {"candidates": []},
        ]
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    screen_prompt = screen_llm.calls[0]["prompt"]
    assert "MI-02 (" in screen_prompt
    # Isolate MI-02's own block — the call bundles every rule in the pass, each with its
    # own EXCUSED example count, so counting across the whole prompt would double-count.
    after_header = screen_prompt.split("MI-02 (", 1)[1]
    mi02_block = re.split(r"\n {2}[A-Z]{2,3}-\d{2} \(", after_header, maxsplit=1)[0]
    assert mi02_block.count("EXCUSED example") == 2


def test_review_document_still_gives_rule_text_in_both_stages(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": ""},
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "간단한 목적 설명입니다.",
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
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "r"}]},
            {"candidates": []},
        ]
    )

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    mi01_rule = rulebook.rules["MI-01"]
    assert mi01_rule.text in screen_llm.calls[0]["prompt"]
    assert mi01_rule.text in confirm_llm.calls[1]["prompt"]


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
