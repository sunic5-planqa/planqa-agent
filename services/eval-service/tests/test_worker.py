from __future__ import annotations

import json

from planqa_eval_service.queue import SQLiteEvalQueue
from planqa_eval_service.worker import process_pending


def test_process_pending_judges_and_marks_done(tmp_path):
    queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    job_id = queue.enqueue(json.dumps({"issues": [{"rule_id": "AE-01"}, {"rule_id": "TC-02"}]}))

    processed = process_pending(queue)

    assert processed == 1
    job = queue.get(job_id)
    assert job.status == "done"
    assert json.loads(job.result_json) == {"issue_count": 2, "scores": []}


def test_process_pending_marks_failed_on_bad_json(tmp_path):
    queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    job_id = queue.enqueue("not valid json")

    process_pending(queue)

    assert queue.get(job_id).status == "failed"


def test_process_pending_with_no_jobs_is_a_noop(tmp_path):
    queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    assert process_pending(queue) == 0
