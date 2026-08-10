from __future__ import annotations

from conftest import ScriptedLLM

from planqa_eval.harness import full_eval
from planqa_schemas.schema import Issue

_MATCH_RESPONSE = {"matches": [{"golden_index": 0, "predicted_index": 0}]}


def _score_response(value: int) -> dict:
    return {
        "root_cause_accuracy": value,
        "no_hallucination": value,
        "service_tone_fit": value,
        "actionability": value,
    }


def _pair(location: str = "x") -> tuple[list[Issue], list[Issue]]:
    golden = Issue(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location=location, description="golden desc")
    predicted = Issue(
        doc_id="DOC-001", level="Sentence", rule_id="AE-01", location=location, description="pred desc", issue_id="P1"
    )
    return [golden], [predicted]


def test_run_full_evaluation_skips_human_baseline_by_default(monkeypatch, rulebook_path, source_dir):
    golden, predicted = _pair()
    llm = ScriptedLLM([_MATCH_RESPONSE, {"scores": [{"index": 0, **_score_response(4)}]}])

    monkeypatch.setattr(full_eval, "parse_golden_dataset", lambda _path: golden)

    def _fail_if_called(_path):
        raise AssertionError("parse_review_sheets must not run when include_baseline=False")

    monkeypatch.setattr(full_eval, "parse_review_sheets", _fail_if_called)

    from planqa_schemas.rulebook import parse_rulebook

    rulebook = parse_rulebook(rulebook_path)
    result, report, comparison = full_eval.run_full_evaluation(
        "unused.xlsx", predicted, rulebook, source_dir, llm
    )

    assert comparison is None
    assert report.overall.recall == 1.0
    assert len(result.judge_scores) == 1


def test_run_full_evaluation_runs_human_baseline_when_requested(monkeypatch, rulebook_path, source_dir):
    golden, predicted = _pair()
    _, baseline_issues = _pair()
    # Subject pass: 1 match call + 1 judge call. Baseline pass ("Review1" sheet): same shape.
    llm = ScriptedLLM(
        [
            _MATCH_RESPONSE,
            {"scores": [{"index": 0, **_score_response(4)}]},
            _MATCH_RESPONSE,
            {"scores": [{"index": 0, **_score_response(3)}]},
        ]
    )

    monkeypatch.setattr(full_eval, "parse_golden_dataset", lambda _path: golden)
    monkeypatch.setattr(full_eval, "parse_review_sheets", lambda _path: {"Review1": baseline_issues, "Review2": []})

    from planqa_schemas.rulebook import parse_rulebook

    rulebook = parse_rulebook(rulebook_path)
    result, report, comparison = full_eval.run_full_evaluation(
        "unused.xlsx", predicted, rulebook, source_dir, llm, include_baseline=True
    )

    assert comparison is not None
    assert comparison.subject_recall == report.overall.recall
    assert set(comparison.per_reviewer) == {"Review1"}  # Review2 skipped — empty sheet
