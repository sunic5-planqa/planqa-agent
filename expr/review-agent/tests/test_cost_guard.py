from __future__ import annotations

import pytest

from planqa_review.cost_guard import CostCapExceeded, CostGuard


def test_can_afford_true_when_under_the_cap():
    guard = CostGuard(cap_usd=7.0, spent_usd=2.0)
    assert guard.can_afford(3.0) is True


def test_can_afford_false_when_over_the_cap():
    guard = CostGuard(cap_usd=7.0, spent_usd=6.0)
    assert guard.can_afford(2.0) is False


def test_can_afford_true_exactly_at_the_cap():
    guard = CostGuard(cap_usd=7.0, spent_usd=5.0)
    assert guard.can_afford(2.0) is True


def test_check_or_raise_passes_silently_when_affordable():
    guard = CostGuard(cap_usd=7.0, spent_usd=1.0)
    guard.check_or_raise(1.0, stage="test")  # must not raise
    assert guard.log == []


def test_check_or_raise_raises_and_logs_when_over_the_cap():
    guard = CostGuard(cap_usd=7.0, spent_usd=6.5)
    with pytest.raises(CostCapExceeded):
        guard.check_or_raise(1.0, stage="screen 배치")
    assert len(guard.log) == 1
    assert "screen 배치" in guard.log[0]


def test_record_actual_tokens_converts_tokens_to_usd_at_the_given_rate():
    guard = CostGuard()
    guard.record_actual_tokens(1_000_000, rate_per_million=40.0)
    assert guard.spent_usd == pytest.approx(40.0)


def test_record_actual_tokens_ignores_none_or_zero():
    guard = CostGuard()
    guard.record_actual_tokens(None)
    guard.record_actual_tokens(0)
    assert guard.spent_usd == 0.0


def test_record_actual_usd_accumulates_directly():
    guard = CostGuard()
    guard.record_actual_usd(1.5)
    guard.record_actual_usd(2.5)
    assert guard.spent_usd == pytest.approx(4.0)
