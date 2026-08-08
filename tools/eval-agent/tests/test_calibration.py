from __future__ import annotations

import pytest

from planqa_eval.harness.calibration import cohens_kappa, compare_label_sets, is_numeric, spearman


def test_cohens_kappa_perfect_agreement_is_one():
    labels = ["a", "b", "a", "c", "b"]
    assert cohens_kappa(labels, labels) == 1.0


def test_cohens_kappa_systematic_disagreement_is_low():
    a = ["x", "x", "x", "y", "y"]
    b = ["y", "y", "y", "x", "x"]
    assert cohens_kappa(a, b) < 0


def test_spearman_perfect_positive_correlation_is_one():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_perfect_negative_correlation_is_minus_one():
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_constant_sequence_is_zero():
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0


def test_is_numeric():
    assert is_numeric([1, 2.5, "3"]) is True
    assert is_numeric(["a", "b"]) is False


def test_compare_label_sets_auto_detects_categorical_and_numeric_fields():
    reference = {
        "g1": {"match_id": "p1", "score_average": 4.0},
        "g2": {"match_id": "p2", "score_average": 2.0},
        "g3": {"match_id": None, "score_average": None},
    }
    candidate = {
        "g1": {"match_id": "p1", "score_average": 4.5},
        "g2": {"match_id": "px", "score_average": 1.5},
    }
    result = compare_label_sets(reference, candidate)
    assert result["n"] == 2
    assert result["fields"]["match_id"]["metric"] == "kappa"
    assert result["fields"]["score_average"]["metric"] == "spearman"
    assert result["fields"]["score_average"]["n"] == 2


def test_compare_label_sets_no_overlapping_keys_is_empty():
    result = compare_label_sets({"g1": {"match_id": "p1"}}, {"g2": {"match_id": "p2"}})
    assert result == {"n": 0, "fields": {}}
