from __future__ import annotations

import json
import os
import time
from pathlib import Path

from planqa_eval_service.judge import judge_review_result
from planqa_eval_service.queue import EvalQueue, SQLiteEvalQueue

_POLL_INTERVAL_SECONDS = 5.0


def process_pending(queue: EvalQueue) -> int:
    """One poll tick — pulled out of run_worker's infinite loop so tests can call it
    directly instead of racing a background thread."""
    jobs = queue.dequeue_pending()
    for job in jobs:
        try:
            review_result = json.loads(job.review_result_json)
            result = judge_review_result(review_result)
            queue.mark_done(job.id, json.dumps(result, ensure_ascii=False))
        except Exception as exc:
            queue.mark_failed(job.id, str(exc))
    return len(jobs)


def run_worker(queue: EvalQueue, poll_interval: float = _POLL_INTERVAL_SECONDS) -> None:
    """Runs forever — meant to be started as its own process, separate from the FastAPI
    app's event loop, so a slow/stuck judge call never blocks /evaluate-async from
    accepting new jobs."""
    while True:
        process_pending(queue)
        time.sleep(poll_interval)


def main() -> None:
    db_path = Path(os.environ.get("EVAL_SERVICE_DB_PATH", "eval_service.db"))
    run_worker(SQLiteEvalQueue(db_path))


if __name__ == "__main__":
    main()
