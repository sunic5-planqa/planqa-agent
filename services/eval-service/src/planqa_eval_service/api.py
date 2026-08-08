from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException

from planqa_eval_service.queue import EvalQueue, SQLiteEvalQueue
from planqa_eval_service.schema import EvaluateAsyncRequest, EvaluateAsyncResponse, JobStatusResponse

app = FastAPI(title="planqa eval-service")


def _default_queue() -> EvalQueue:
    db_path = Path(os.environ.get("EVAL_SERVICE_DB_PATH", "eval_service.db"))
    return SQLiteEvalQueue(db_path)


# Lazily built on first request, not at import time — importing this module (docs tooling,
# a linter, an unrelated test) must not have the side effect of creating a real db file at
# a CWD-relative path. Tests set `api._queue` directly before making a request, which this
# still honors (the lazy build only kicks in when nothing has set it yet).
_queue: EvalQueue | None = None


def _get_queue() -> EvalQueue:
    global _queue
    if _queue is None:
        _queue = _default_queue()
    return _queue


@app.post("/evaluate-async", status_code=202)
def evaluate_async(request: EvaluateAsyncRequest) -> EvaluateAsyncResponse:
    job_id = _get_queue().enqueue(json.dumps(request.review_result, ensure_ascii=False))
    return EvaluateAsyncResponse(job_id=job_id)


@app.get("/evaluate-async/{job_id}")
def get_job(job_id: str) -> JobStatusResponse:
    job = _get_queue().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    result = json.loads(job.result_json) if job.result_json and job.status == "done" else None
    return JobStatusResponse(job_id=job.id, status=job.status, result=result)
