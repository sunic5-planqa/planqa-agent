from __future__ import annotations

import json

from conftest import ScriptedLLM

from planqa_eval_service.queue import SQLiteEvalQueue
from planqa_eval_service.worker import process_pending


def test_process_pending_judges_and_marks_done(tmp_path, rulebook):
    queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    job_id = queue.enqueue(
        json.dumps(
            {
                "issues": [
                    {
                        "issue_id": "i0",
                        "rule_id": "LG-01",
                        "location": "1장",
                        "original_text": "예시",
                        "description": "d",
                        "rationale": "r",
                    }
                ]
            }
        )
    )
    llm = ScriptedLLM([{"verdicts": [{"index": 0, "valid": True, "confidence": "confident", "reason": "fine"}]}])

    processed = process_pending(queue, llm, rulebook)

    assert processed == 1
    job = queue.get(job_id)
    assert job.status == "done"
    result = json.loads(job.result_json)
    assert result["issue_count"] == 1
    assert result["flagged_count"] == 0


def test_process_pending_marks_failed_on_bad_job_json(tmp_path, rulebook):
    queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    job_id = queue.enqueue("not valid json")
    llm = ScriptedLLM([])

    process_pending(queue, llm, rulebook)

    assert queue.get(job_id).status == "failed"


def test_process_pending_with_no_jobs_is_a_noop(tmp_path, rulebook):
    queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    llm = ScriptedLLM([])
    assert process_pending(queue, llm, rulebook) == 0
