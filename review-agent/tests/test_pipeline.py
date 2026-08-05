from __future__ import annotations

from typing import Any

from conftest import ScriptedLLM

from planqa_review.models import gemini_lite
from planqa_review.pipeline import review_document
from planqa_review.rulebook import parse_rulebook


class _FailFirstThenScripted:
    """Simulates a backend that throws on its first call (e.g. malformed JSON, a transient
    503) and behaves normally after — for testing that one tier's failure doesn't take down
    the whole review."""

    def __init__(self, responses: list[Any]) -> None:
        self.model = "fake"
        self.usage: list[Any] = []
        self._responses = iter(responses)
        self._call_count = 0

    def complete_json(self, *, system: str, prompt: str) -> Any:
        self._call_count += 1
        if self._call_count == 1:
            raise ValueError("simulated malformed JSON response")
        return next(self._responses)

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

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, gemini_lite)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    assert len(screen_llm.calls) == 4
    assert len(confirm_llm.calls) == 2
    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Logical Unit"
    assert issue.location == "1. 목적"
    assert issue.fix_direction == "목적: 사용자 재탐색 편의성을 높이기 위함."

    # 1 context + 4 screen (one per tier) + 1 confirm (only Logical Unit had a candidate)
    assert len(result.call_events) == 6
    context_events = [e for e in result.call_events if e.stage == "context"]
    assert len(context_events) == 1 and context_events[0].tier is None
    confirm_events = [e for e in result.call_events if e.stage == "confirm"]
    assert len(confirm_events) == 1
    assert confirm_events[0].tier.value == "Logical Unit"
    assert confirm_events[0].rule_ids == ("MI-01",)


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

    result = review_document("DOC-TEST", _DOC_WITH_SUBSECTION, rulebook, screen_llm, confirm_llm, gemini_lite)
    assert len(result.issues) == 1
    assert result.issues[0].level == "Paragraph"
    assert result.issues[0].location == "1. 목적 > a. 배경"


def test_review_document_isolates_a_single_tier_failure(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    # Document tier is first in TIER_ORDER, so this is screen_llm's very first call —
    # simulate it failing (e.g. the model returned malformed JSON) and confirm the other
    # 3 tiers still run and their (empty) results are still returned, not lost.
    screen_llm = _FailFirstThenScripted([{"candidates": []}, {"candidates": []}, {"candidates": []}])
    confirm_llm = ScriptedLLM([{"summary": "요약"}])

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, gemini_lite)

    assert result.issues == ()
    assert len(result.tier_errors) == 1
    assert "Document" in result.tier_errors[0]
    assert result.global_context == "요약"  # Global Context extraction itself wasn't affected
