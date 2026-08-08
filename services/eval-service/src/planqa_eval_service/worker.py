from __future__ import annotations

import json
import os
import time
from pathlib import Path

from planqa_eval_service.ensemble import JudgeAssembly
from planqa_eval_service.judge import judge_review_result
from planqa_eval_service.llm.base import LLMClient
from planqa_eval_service.llm.factory import build_llm_client
from planqa_eval_service.queue import EvalQueue, SQLiteEvalQueue
from planqa_schemas.rulebook import RuleBook, parse_rulebook

_POLL_INTERVAL_SECONDS = 5.0
_DEFAULT_RULEBOOK_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "rulebook_v1.0.md"


def _parse_ensemble_spec(spec: str | None) -> JudgeAssembly | None:
    """EVAL_SERVICE_ENSEMBLE: comma-separated name:backend[:model] — same format as
    tools/eval-agent's --judge-ensemble, unset means tier-1-only (no escalation tier)."""
    if not spec:
        return None
    assembly: JudgeAssembly = []
    for member in spec.split(","):
        name, backend, *rest = member.split(":", 2)
        model = rest[0] if rest else None
        assembly.append((name, build_llm_client(backend, model)))
    return assembly


def process_pending(
    queue: EvalQueue,
    llm: LLMClient,
    rulebook: RuleBook,
    *,
    assembly: JudgeAssembly | None = None,
    arbiter: LLMClient | None = None,
) -> int:
    """One poll tick — pulled out of run_worker's infinite loop so tests can call it
    directly instead of racing a background thread."""
    jobs = queue.dequeue_pending()
    for job in jobs:
        try:
            review_result = json.loads(job.review_result_json)
            result = judge_review_result(review_result, llm, rulebook, assembly=assembly, arbiter=arbiter)
            queue.mark_done(job.id, json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            queue.mark_failed(job.id, str(exc))
    return len(jobs)


def run_worker(
    queue: EvalQueue,
    llm: LLMClient,
    rulebook: RuleBook,
    *,
    assembly: JudgeAssembly | None = None,
    arbiter: LLMClient | None = None,
    poll_interval: float = _POLL_INTERVAL_SECONDS,
) -> None:
    """Runs forever — meant to be started as its own process, separate from the FastAPI
    app's event loop, so a slow/stuck judge call never blocks /evaluate-async from
    accepting new jobs."""
    while True:
        process_pending(queue, llm, rulebook, assembly=assembly, arbiter=arbiter)
        time.sleep(poll_interval)


def main() -> None:
    db_path = Path(os.environ.get("EVAL_SERVICE_DB_PATH", "eval_service.db"))
    rulebook_path = Path(os.environ.get("EVAL_SERVICE_RULEBOOK_PATH", str(_DEFAULT_RULEBOOK_PATH)))
    llm = build_llm_client(os.environ.get("EVAL_SERVICE_BACKEND"))
    assembly = _parse_ensemble_spec(os.environ.get("EVAL_SERVICE_ENSEMBLE"))
    # llm doubles as arbiter, same convention as tools/eval-agent's --judge-ensemble.
    run_worker(SQLiteEvalQueue(db_path), llm, parse_rulebook(rulebook_path), assembly=assembly, arbiter=llm if assembly else None)


if __name__ == "__main__":
    main()
