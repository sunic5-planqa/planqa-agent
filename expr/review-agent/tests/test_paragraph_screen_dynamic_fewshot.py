from __future__ import annotations

from planqa_review.llm.base import CallStats
from planqa_review.rulebook import parse_rulebook
from planqa_review.schema import Level
from planqa_review.structures import fewshot_retrieval
from planqa_review.structures.fewshot_bank import FewShotExample
from planqa_review.structures.paragraph_screen_dynamic_fewshot import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n결제 버튼을 누르면 즉시 처리됩니다.\n\n## 2. 배경\n\n두번째 문단입니다.\n"


class _ContentAwareLLM:
    def __init__(self, flagged_rule_id: str = "MI-01") -> None:
        self.model = "fake"
        self.usage: list[CallStats] = []
        self.calls: list[dict[str, str]] = []
        self._flagged_rule_id = flagged_rule_id

    def complete_json(self, *, system: str, prompt: str, cache_prefix: str | None = None):
        self.calls.append({"system": system, "prompt": prompt, "cache_prefix": cache_prefix or ""})
        self.usage.append(CallStats(elapsed_seconds=0.0, prompt_tokens=None, completion_tokens=None, total_tokens=None))
        if "verdicts" not in system:  # screening call
            if self._flagged_rule_id in prompt:
                return {
                    "candidates": [
                        {"chunk_index": 0, "rule_id": self._flagged_rule_id, "quoted_text": "결제 버튼을 누르면 즉시 처리됩니다.", "reason": "불명확"}
                    ]
                }
            return {"candidates": []}
        return {  # confirm call
            "verdicts": [
                {
                    "index": 0,
                    "violated": True,
                    "original_text": "결제 버튼을 누르면 즉시 처리됩니다.",
                    "description": "주체가 불명확",
                    "fix_direction": "처리 주체를 명시할 것",
                    "excused": False,
                }
            ]
        }


def test_review_document_picks_the_example_most_similar_to_the_document(rulebook_path, monkeypatch):
    """The whole point of this structure: the example chosen depends on what's actually
    being reviewed, not a fixed static pair — with a pool where one candidate closely
    overlaps the document text and one doesn't, only the overlapping one should appear."""
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
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    screen_calls_for_mi01 = [c for c in screen_llm.calls if "MI-01 (" in c["prompt"]]
    assert screen_calls_for_mi01
    combined = "\n".join(c["prompt"] for c in screen_calls_for_mi01)
    assert "결제 버튼 관련 근거" in combined
    assert "전혀 무관한 근거" not in combined


def test_review_document_dispatches_normal_categories_at_paragraph_level(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    mi_events = [e for e in result.call_events if "MI-01" in e.rule_ids]
    assert any(e.tier == Level.PARAGRAPH and e.stage == "screen" for e in mi_events)
    assert any(issue.rule_id == "MI-01" and issue.level == Level.PARAGRAPH.value for issue in result.issues)


def test_review_document_dispatches_ga_at_document_level_only(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("GA-01")
    confirm_llm = _ContentAwareLLM("GA-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm, max_workers=1)

    ga_events = [e for e in result.call_events if "GA-01" in e.rule_ids]
    assert ga_events
    assert all(e.tier == Level.DOCUMENT for e in ga_events)


def test_review_document_runs_with_real_concurrency(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = _ContentAwareLLM("MI-01")
    confirm_llm = _ContentAwareLLM("MI-01")

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert any(issue.rule_id == "MI-01" for issue in result.issues)
    assert result.tier_errors == ()
