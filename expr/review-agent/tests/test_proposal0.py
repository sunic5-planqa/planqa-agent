from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.rulebook import parse_rulebook
from planqa_review.structures.proposal0 import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"


def test_review_document_single_pass_end_to_end(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    # confirm_llm handles everything: 1 context call + 1 call per tier (Document/Logical
    # Unit/Paragraph/Sentence) that has both chunks and assigned rules — no screening pass
    # to skip a tier early, unlike baseline (제안5).
    confirm_llm = ScriptedLLM(
        [
            {"summary": "이 문서는 홈 화면의 목적을 설명한다."},
            {"violations": []},  # Document tier
            {
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "MI-01",
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "목적이 구체적이지 않음",
                        "rationale": "MI-01 위반 — 목적이 왜 필요한지 근거가 없음",
                        "fix_direction": "목적: 사용자 재탐색 편의성을 높이기 위함.",
                        "excused": False,
                        "excuse_reason": None,
                    }
                ]
            },  # Logical Unit tier
            {"violations": []},  # Paragraph tier
            {"violations": []},  # Sentence tier
        ]
    )
    screen_llm = ScriptedLLM([])  # unused by this structure

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    assert len(screen_llm.calls) == 0
    assert len(confirm_llm.calls) == 5  # 1 context + 4 tiers
    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Logical Unit"
    assert issue.location == "1. 목적"
    assert issue.fix_direction == "목적: 사용자 재탐색 편의성을 높이기 위함."

    assert len(result.call_events) == 5
    context_events = [e for e in result.call_events if e.stage == "context"]
    assert len(context_events) == 1 and context_events[0].tier is None
    single_pass_events = [e for e in result.call_events if e.stage == "single_pass"]
    assert len(single_pass_events) == 4


def test_review_document_respects_excused_flag(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    confirm_llm = ScriptedLLM(
        [
            {"summary": ""},
            {"violations": []},
            {
                "violations": [
                    {
                        "chunk_index": 0,
                        "rule_id": "MI-01",
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "목적이 구체적이지 않음",
                        "fix_direction": "x",
                        "excused": True,
                        "excuse_reason": "다른 곳에 설명됨",
                    }
                ]
            },
            {"violations": []},
            {"violations": []},
        ]
    )
    result = review_document("DOC-TEST", _DOC, rulebook, ScriptedLLM([]), confirm_llm)
    assert result.issues == ()


def test_review_document_isolates_a_single_tier_failure(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    class _FailFirstThenScripted:
        def __init__(self, responses):
            self.model = "fake"
            self.usage = []
            self._responses = iter(responses)
            self._calls = 0

        def complete_json(self, *, system, prompt):
            self._calls += 1
            if self._calls == 2:  # first tier call (after context) fails
                raise ValueError("simulated malformed JSON response")
            return next(self._responses)

    confirm_llm = _FailFirstThenScripted(
        [{"summary": "요약"}, {"violations": []}, {"violations": []}, {"violations": []}]
    )

    result = review_document("DOC-TEST", _DOC, rulebook, ScriptedLLM([]), confirm_llm)

    assert result.issues == ()
    assert len(result.tier_errors) == 1
    assert "Document" in result.tier_errors[0]
    assert result.global_context == "요약"
