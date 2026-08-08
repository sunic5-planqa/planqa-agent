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


# Module-level singleton so a plain `uvicorn planqa_eval_service.api:app` works out of the
# box; tests override this via app.dependency_overrides-style monkeypatching of `_queue`.
_queue: EvalQueue = _default_queue()


@app.post("/evaluate-async", status_code=202)
def evaluate_async(request: EvaluateAsyncRequest) -> EvaluateAsyncResponse:
    job_id = _queue.enqueue(json.dumps(request.review_result, ensure_ascii=False))
    return EvaluateAsyncResponse(job_id=job_id)


@app.get("/evaluate-async/{job_id}")
def get_job(job_id: str) -> JobStatusResponse:
    job = _queue.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    result = json.loads(job.result_json) if job.result_json and job.status == "done" else None
    return JobStatusResponse(job_id=job.id, status=job.status, result=result)
