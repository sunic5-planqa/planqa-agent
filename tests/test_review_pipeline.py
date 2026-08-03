from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.review_agent.pipeline import review_document
from planqa_eval.rulebook import parse_rulebook

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"
_DOC_WITH_SUBSECTION = "# 샘플 PRD\n\n## 1. 목적\n\n### a. 배경\n\n간단한 목적 설명입니다.\n"


def test_review_document_end_to_end(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    # confirm_llm handles both Global Context extraction (1st call) and the Logical Unit
    # tier's confirm batch (2nd call, the only tier the screener flags anything for below).
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
                        "rationale": "MI-01 위반 — 목적이 왜 필요한지 근거가 없음",
                        "fix_direction": "목적: 사용자 재탐색 편의성을 높이기 위함.",
                        "excused": False,
                        "excuse_reason": None,
                    }
                ]
            },
        ]
    )
    # One screen call per tier in TIER_ORDER (Document, Logical Unit, Paragraph, Sentence);
    # only Logical Unit returns a candidate so only it triggers a confirm call above.
    screen_llm = ScriptedLLM(
        [
            {"candidates": []},
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "목적 불명확"}]},
            {"candidates": []},
            {"candidates": []},
        ]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    assert len(screen_llm.calls) == 4
    assert len(confirm_llm.calls) == 2
    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Logical Unit"
    assert issue.location == "1. 목적"
    assert issue.fix_direction == "목적: 사용자 재탐색 편의성을 높이기 위함."


def test_review_document_dedupes_across_tiers(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    def _verdict(text: str) -> dict:
        return {
            "verdicts": [
                {
                    "index": 0,
                    "violated": True,
                    "original_text": text,
                    "description": "정보 누락",
                    "fix_direction": text,
                    "excused": False,
                }
            ]
        }

    # Logical Unit tier ("1. 목적") and Paragraph tier ("1. 목적 > a. 배경", nested under it)
    # both flag MI-01 — the more specific (Paragraph) one should win after dedupe.
    confirm_llm = ScriptedLLM(
        [
            {"summary": ""},
            _verdict("간단한 목적 설명입니다. (논리단위 관점)"),
            _verdict("간단한 목적 설명입니다."),
        ]
    )
    screen_llm = ScriptedLLM(
        [
            {"candidates": []},
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "y"}]},
            {"candidates": [{"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "x", "reason": "y"}]},
            {"candidates": []},
        ]
    )

    result = review_document("DOC-TEST", _DOC_WITH_SUBSECTION, rulebook, screen_llm, confirm_llm)
    assert len(result.issues) == 1
    assert result.issues[0].level == "Paragraph"
    assert result.issues[0].location == "1. 목적 > a. 배경"
