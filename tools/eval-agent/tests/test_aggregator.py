from __future__ import annotations

from planqa_eval.aggregator import AggregateReport, ConfusionCounts, aggregate, compare_to_human_baseline
from planqa_eval.judge import JudgeScore
from planqa_eval.new_rule_triage import TriageResult
from planqa_eval.pipeline import PipelineResult
from planqa_schemas.schema import Issue
from planqa_eval.verifier import VerifiedMatch, VerifiedMiss


def _issue(**kwargs) -> Issue:
    defaults = dict(doc_id="DOC-001", level="Sentence", rule_id="AE-01", location="x", description="y")
    defaults.update(kwargs)
    return Issue(**defaults)


def _judge(golden: Issue, predicted: Issue) -> JudgeScore:
    return JudgeScore(
        golden=golden,
        predicted=predicted,
        root_cause_accuracy=5,
        no_hallucination=5,
        service_tone_fit=5,
        actionability=5,
    )


def _result(**kwargs) -> PipelineResult:
    defaults = dict(verified_matches=[], judge_scores=[], verified_misses=[], triage_results=[])
    defaults.update(kwargs)
    return PipelineResult(**defaults)


def test_fully_correct_match_counts_as_tp_in_its_own_category_and_level():
    golden = _issue(rule_id="AE-01", level="Sentence")
    predicted = _issue(rule_id="AE-01", level="Sentence")
    verified = VerifiedMatch(golden=golden, predicted=predicted, rule_id_match=True, level_match=True)
    report = aggregate(_result(verified_matches=[verified], judge_scores=[_judge(golden, predicted)]))
    assert report.overall.true_positive == 1
    assert report.by_category["AE"].true_positive == 1
    assert report.by_level["Sentence"].true_positive == 1


def test_misclassified_match_is_fn_for_golden_category_and_fp_for_predicted_category():
    golden = _issue(rule_id="AE-01", level="Sentence")
    predicted = _issue(rule_id="LG-01", level="Paragraph")
    verified = VerifiedMatch(golden=golden, predicted=predicted, rule_id_match=False, level_match=False)
    report = aggregate(_result(verified_matches=[verified], judge_scores=[_judge(golden, predicted)]))
    assert report.by_category["AE"].false_negative == 1
    assert report.by_category["LG"].false_positive == 1
    assert report.overall.true_positive == 0


def test_right_rule_wrong_tier_counts_toward_relaxed_tp_not_strict():
    """The exact scenario found on the 20-doc benchmark: rule_id correct, level wrong —
    strict scoring treats this as a total miss+phantom-FP, relaxed scoring credits the
    substance and tier_accuracy carries the "but wrong tier" signal separately."""
    golden = _issue(rule_id="AE-01", level="Sentence")
    predicted = _issue(rule_id="AE-01", level="Document")
    verified = VerifiedMatch(golden=golden, predicted=predicted, rule_id_match=True, level_match=False)
    report = aggregate(_result(verified_matches=[verified], judge_scores=[_judge(golden, predicted)]))

    assert report.overall.true_positive == 0  # strict: still not fully correct
    assert report.overall_relaxed.true_positive == 1  # relaxed: rule_id alone is enough
    assert report.overall_relaxed.false_negative == 0
    assert report.overall_relaxed.false_positive == 0
    assert report.tier_accuracy == 0.0  # 0 of 1 rule_id matches also got the tier right


def test_wrong_rule_entirely_counts_against_relaxed_too():
    golden = _issue(rule_id="AE-01", level="Sentence")
    predicted = _issue(rule_id="LG-01", level="Sentence")
    verified = VerifiedMatch(golden=golden, predicted=predicted, rule_id_match=False, level_match=True)
    report = aggregate(_result(verified_matches=[verified], judge_scores=[_judge(golden, predicted)]))

    assert report.overall_relaxed.false_negative == 1
    assert report.overall_relaxed.false_positive == 1
    assert report.tier_accuracy is None  # no rule_id matches to measure it against


def test_excused_miss_is_dropped_from_recall_entirely():
    golden = _issue(rule_id="AE-01")
    report = aggregate(_result(verified_misses=[VerifiedMiss(golden=golden, excused=True)]))
    assert report.overall.false_negative == 0
    assert report.excused_miss_count == 1


def test_unexcused_miss_counts_as_false_negative():
    golden = _issue(rule_id="AE-01")
    report = aggregate(_result(verified_misses=[VerifiedMiss(golden=golden, excused=False)]))
    assert report.overall.false_negative == 1
    assert report.by_category["AE"].false_negative == 1


def test_new_rule_and_human_review_excluded_from_precision():
    predicted_a = _issue(rule_id="AE-01", issue_id="a")
    predicted_b = _issue(rule_id="LG-01", issue_id="b")
    triage = [
        TriageResult(predicted=predicted_a, verdict="new_rule_candidate"),
        TriageResult(predicted=predicted_b, verdict="human_review"),
    ]
    report = aggregate(_result(triage_results=triage))
    assert report.overall.false_positive == 0
    assert report.new_rule_candidate_count == 1
    assert report.human_review_count == 1


def test_valid_but_unlabeled_excluded_from_precision_and_tracked_separately():
    """A correctly-categorized finding golden just never labeled is a golden-set gap, not
    an agent error — must not drag precision down the same way an actual false_positive
    would (see docs/progress.md: this is what was making real catches on the 20-doc
    benchmark look like a 1% precision agent when most were legitimate, just unlabeled)."""
    predicted = _issue(rule_id="MI-02", issue_id="a")
    triage = [TriageResult(predicted=predicted, verdict="valid_but_unlabeled")]
    report = aggregate(_result(triage_results=triage))
    assert report.overall.false_positive == 0
    assert report.by_category.get("MI", ConfusionCounts()).false_positive == 0
    assert report.valid_unlabeled_count == 1


def test_false_positive_triage_counts_against_predicted_category():
    predicted = _issue(rule_id="TC-01")
    triage = [TriageResult(predicted=predicted, verdict="false_positive")]
    report = aggregate(_result(triage_results=triage))
    assert report.by_category["TC"].false_positive == 1


def test_confusion_counts_recall_precision_none_when_denominator_zero():
    counts = ConfusionCounts()
    assert counts.recall is None
    assert counts.precision is None


def test_compare_to_human_baseline_averages_across_reviewers():
    subject = aggregate(_result())
    baseline_a = AggregateReport(overall=ConfusionCounts(true_positive=8, false_negative=2))  # recall 0.8
    baseline_b = AggregateReport(overall=ConfusionCounts(true_positive=6, false_negative=4))  # recall 0.6
    comparison = compare_to_human_baseline(subject, {"Review1": baseline_a, "Review2": baseline_b})
    assert comparison.baseline_recall_avg == 0.7
