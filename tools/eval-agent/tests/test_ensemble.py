from __future__ import annotations

from typing import Any

from conftest import ScriptedLLM

from planqa_eval.ensemble import aggregate_numeric, majority_vote_categorical, run_ensemble
from planqa_eval.llm.base import LLMClient


class FailingLLM(LLMClient):
    """Always raises — used to exercise run_ensemble's partial-failure tolerance."""

    def __init__(self) -> None:
        self.model = "failing"

    def complete_json(self, *, system: str, prompt: str) -> Any:
        raise RuntimeError("simulated backend failure")


def test_run_ensemble_preserves_assembly_order():
    assembly = [
        ("a", ScriptedLLM([{"v": 1}])),
        ("b", ScriptedLLM([{"v": 2}])),
        ("c", ScriptedLLM([{"v": 3}])),
    ]
    results = run_ensemble(lambda llm: llm.complete_json(system="s", prompt="p"), assembly)
    assert [name for name, _ in results] == ["a", "b", "c"]
    assert [value for _, value in results] == [{"v": 1}, {"v": 2}, {"v": 3}]


def test_run_ensemble_drops_only_the_failing_member():
    assembly = [
        ("ok1", ScriptedLLM([{"v": 1}])),
        ("bad", FailingLLM()),
        ("ok2", ScriptedLLM([{"v": 2}])),
    ]
    results = run_ensemble(lambda llm: llm.complete_json(system="s", prompt="p"), assembly)
    assert [name for name, _ in results] == ["ok1", "ok2"]


def test_run_ensemble_empty_assembly_returns_empty():
    assert run_ensemble(lambda llm: llm.complete_json(system="s", prompt="p"), []) == []


def test_majority_vote_categorical_picks_the_most_common_label():
    winner, consensus = majority_vote_categorical(["a", "b", "a"])
    assert winner == "a"
    assert consensus == 2 / 3


def test_majority_vote_categorical_unanimous_is_consensus_one():
    winner, consensus = majority_vote_categorical(["x", "x", "x"])
    assert winner == "x"
    assert consensus == 1.0


def test_majority_vote_categorical_empty_raises():
    try:
        majority_vote_categorical([])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")


def test_aggregate_numeric_mean_and_stdev():
    mean, stdev = aggregate_numeric([1.0, 1.0, 1.0])
    assert mean == 1.0
    assert stdev == 0.0

    mean, stdev = aggregate_numeric([1.0, 5.0])
    assert mean == 3.0
    assert stdev > 0


def test_aggregate_numeric_empty_raises():
    try:
        aggregate_numeric([])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
