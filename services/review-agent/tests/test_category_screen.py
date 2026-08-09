from __future__ import annotations

from conftest import ScriptedLLM

from planqa_schemas.rulebook import parse_rulebook
from planqa_schemas.schema import Level
from planqa_review.structures.category_screen import review_document

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"

_EMPTY_CANDIDATES = {"candidates": []}


def test_review_document_resolves_specific_rule_from_category_candidate(rulebook_path):
    """Screening only names a category (MI), never a rule_id — confirm must pick the exact
    rule out of that category's full rule set on its own."""
    rulebook = parse_rulebook(rulebook_path)

    screen_llm = ScriptedLLM(
        tier_responses=[
            _EMPTY_CANDIDATES,  # Document tier
            {
                "candidates": [
                    {"chunk_index": 0, "category": "MI", "quoted_text": "간단한 목적 설명입니다.", "reason": "목적 불명확"}
                ]
            },  # Logical Unit tier
            _EMPTY_CANDIDATES,  # Paragraph tier
            _EMPTY_CANDIDATES,  # Sentence tier
        ]
    )
    confirm_llm = ScriptedLLM(
        [{"summary": "이 문서는 홈 화면의 목적을 설명한다."}],  # context (uncloned, direct call)
        tier_responses=[
            None,  # Document tier — no candidates, confirm never called
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
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
            None,  # Paragraph tier
            None,  # Sentence tier
        ],
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.global_context == "이 문서는 홈 화면의 목적을 설명한다."
    assert len(screen_llm.all_calls) == 4  # one per tier with chunks+rules
    assert len(confirm_llm.all_calls) == 2  # 1 context + 1 confirm (only Logical Unit had candidates)
    # screening prompt must not leak rule text — only the category label
    logical_unit_prompt = screen_llm.clones[Level.LOGICAL_UNIT].calls[0]["prompt"]
    assert "MI-01" not in logical_unit_prompt
    assert "MI" in logical_unit_prompt

    [issue] = result.issues
    assert issue.rule_id == "MI-01"
    assert issue.level == "Logical Unit"
    assert issue.fix_direction == "목적: 사용자 재탐색 편의성을 높이기 위함."
    assert result.tier_errors == ()

    confirm_events = [e for e in result.call_events if e.stage == "confirm"]
    assert len(confirm_events) == 1  # no event emitted for tiers where screening found nothing
    screen_events = [e for e in result.call_events if e.stage == "screen"]
    assert len(screen_events) == 4


def test_review_document_populates_related_location_for_relational_categories(rulebook_path):
    """LG/LF/GA are relationship errors between two locations (issue #4) — confirm's
    related_location must survive into the Issue; other categories must stay None even if
    the model tries to fill it in (defensive against a model ignoring the null instruction)."""
    rulebook = parse_rulebook(rulebook_path)

    screen_llm = ScriptedLLM(
        tier_responses=[
            _EMPTY_CANDIDATES,
            {"candidates": [{"chunk_index": 0, "category": "LG", "quoted_text": "간단한 목적 설명입니다.", "reason": "앞뒤 모순"}]},
            _EMPTY_CANDIDATES,
            _EMPTY_CANDIDATES,
        ]
    )
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        tier_responses=[
            None,
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "rule_id": "LG-02",
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "2절과 모순",
                        "fix_direction": "표현을 통일",
                        "excused": False,
                        "related_location": "2. 배경",
                    }
                ]
            },
            None,
            None,
        ],
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.rule_id == "LG-02"
    assert issue.related_location == "2. 배경"


def test_review_document_ignores_related_location_for_non_relational_categories(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    screen_llm = ScriptedLLM(
        tier_responses=[
            _EMPTY_CANDIDATES,
            {"candidates": [{"chunk_index": 0, "category": "MI", "quoted_text": "x", "reason": "r"}]},
            _EMPTY_CANDIDATES,
            _EMPTY_CANDIDATES,
        ]
    )
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        tier_responses=[
            None,
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "rule_id": "MI-01",
                        "original_text": "x",
                        "description": "d",
                        "fix_direction": "f",
                        "excused": False,
                        "related_location": "이건 무시돼야 함",  # MI is not relational — must be dropped
                    }
                ]
            },
            None,
            None,
        ],
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    [issue] = result.issues
    assert issue.related_location is None


def test_review_document_rejects_rule_id_outside_screened_category(rulebook_path):
    """Confirm naming a rule_id from the wrong category (a malformed/hallucinated response)
    must not turn into an issue — the category boundary is enforced defensively."""
    rulebook = parse_rulebook(rulebook_path)

    screen_llm = ScriptedLLM(
        tier_responses=[
            _EMPTY_CANDIDATES,
            {"candidates": [{"chunk_index": 0, "category": "MI", "quoted_text": "x", "reason": "r"}]},
            _EMPTY_CANDIDATES,
            _EMPTY_CANDIDATES,
        ]
    )
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        tier_responses=[
            None,
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "rule_id": "LG-02",  # not in the MI category given to this candidate
                        "original_text": "x",
                        "description": "d",
                        "fix_direction": "f",
                        "excused": False,
                    }
                ]
            },
            None,
            None,
        ],
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)
    assert result.issues == ()


def test_review_document_respects_excused_flag(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)
    screen_llm = ScriptedLLM(
        tier_responses=[
            _EMPTY_CANDIDATES,
            {"candidates": [{"chunk_index": 0, "category": "MI", "quoted_text": "x", "reason": "r"}]},
            _EMPTY_CANDIDATES,
            _EMPTY_CANDIDATES,
        ]
    )
    confirm_llm = ScriptedLLM(
        [{"summary": ""}],
        tier_responses=[
            None,
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "rule_id": "MI-01",
                        "original_text": "x",
                        "description": "d",
                        "fix_direction": "f",
                        "excused": True,
                        "excuse_reason": "다른 곳에 설명됨",
                    }
                ]
            },
            None,
            None,
        ],
    )

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)
    assert result.issues == ()


def test_review_document_isolates_a_single_tier_failure(rulebook_path):
    rulebook = parse_rulebook(rulebook_path)

    class _TierFailingLLM:
        # Fails specifically on the Document tier's screen call. Real concurrent tier
        # execution means "the first call made" is no longer a stable proxy for "the
        # Document tier's call" — failure has to be keyed off tier identity via clone(),
        # same as ScriptedLLM's tier_responses routing above.
        def __init__(self, *, fail_tier: Level, should_fail: bool = False) -> None:
            self.model = "fake"
            self.usage = []
            self._fail_tier = fail_tier
            self._should_fail = should_fail

        def complete_json(self, *, system, prompt):
            if self._should_fail:
                raise ValueError("simulated malformed JSON response")
            return _EMPTY_CANDIDATES

        def clone(self, *, tier=None):
            return _TierFailingLLM(fail_tier=self._fail_tier, should_fail=tier == self._fail_tier)

    screen_llm = _TierFailingLLM(fail_tier=Level.DOCUMENT)
    confirm_llm = ScriptedLLM([{"summary": "요약"}])

    result = review_document("DOC-TEST", _DOC, rulebook, screen_llm, confirm_llm)

    assert result.issues == ()
    assert len(result.tier_errors) == 1
    assert "Document" in result.tier_errors[0]
    assert result.global_context == "요약"
