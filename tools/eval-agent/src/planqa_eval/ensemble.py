from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from statistics import mean, pstdev
from typing import Callable, TypeVar

from planqa_eval.llm.base import LLMClient

T = TypeVar("T")

JudgeAssembly = list[tuple[str, LLMClient]]


def run_ensemble(fn: Callable[[LLMClient], T], assembly: JudgeAssembly) -> list[tuple[str, T]]:
    # Ported from microsoft/llm-as-judge's JudgeEvaluationPlan.run_plan() (asyncio.gather over
    # sub-judges), moved to threads since LLMClient.complete_json is sync. Deliberately
    # diverges from asyncio.gather's default (return_exceptions=False, which fails the whole
    # batch on one exception) — a flaky/rate-limited local model shouldn't sink the others.
    if not assembly:
        return []
    with ThreadPoolExecutor(max_workers=len(assembly)) as pool:
        futures = [(name, pool.submit(fn, llm)) for name, llm in assembly]
        results: list[tuple[str, T]] = []
        for name, future in futures:
            try:
                results.append((name, future.result()))
            except Exception:
                continue
    return results


def majority_vote_categorical(labels: list[str]) -> tuple[str, float]:
    if not labels:
        raise ValueError("majority_vote_categorical requires at least one label")
    winner, count = Counter(labels).most_common(1)[0]
    return winner, count / len(labels)


def aggregate_numeric(scores: list[float]) -> tuple[float, float]:
    if not scores:
        raise ValueError("aggregate_numeric requires at least one score")
    return mean(scores), pstdev(scores)
