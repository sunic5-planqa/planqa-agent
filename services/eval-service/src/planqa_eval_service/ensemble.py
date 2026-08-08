from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

from planqa_eval_service.llm.base import LLMClient

T = TypeVar("T")

JudgeAssembly = list[tuple[str, LLMClient]]


def run_ensemble(fn: Callable[[LLMClient], T], assembly: JudgeAssembly) -> list[tuple[str, T]]:
    """Same LLM-cascade shape as tools/eval-agent's ensemble.py (not imported — services
    don't share business logic, only planqa-schemas). One flaky/rate-limited member drops
    out of the result instead of failing the whole ensemble."""
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
