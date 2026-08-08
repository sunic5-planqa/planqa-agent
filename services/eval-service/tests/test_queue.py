from __future__ import annotations

from planqa_eval_service.queue import SQLiteEvalQueue


def _queue(tmp_path):
    return SQLiteEvalQueue(tmp_path / "eval_service.db")


def test_enqueue_then_get_is_pending(tmp_path):
    queue = _queue(tmp_path)
    job_id = queue.enqueue('{"issues": []}')
    job = queue.get(job_id)
    assert job is not None
    assert job.status == "pending"
    assert job.review_result_json == '{"issues": []}'


def test_dequeue_pending_flips_status_to_processing(tmp_path):
    queue = _queue(tmp_path)
    job_id = queue.enqueue('{"issues": []}')
    picked = queue.dequeue_pending()
    assert [job.id for job in picked] == [job_id]
    assert picked[0].status == "processing"
    assert queue.get(job_id).status == "processing"


def test_dequeue_pending_does_not_repick_processing_jobs(tmp_path):
    queue = _queue(tmp_path)
    queue.enqueue('{"issues": []}')
    first = queue.dequeue_pending()
    second = queue.dequeue_pending()
    assert len(first) == 1
    assert second == []


def test_mark_done_stores_result(tmp_path):
    queue = _queue(tmp_path)
    job_id = queue.enqueue('{"issues": []}')
    queue.dequeue_pending()
    queue.mark_done(job_id, '{"issue_count": 0}')
    job = queue.get(job_id)
    assert job.status == "done"
    assert job.result_json == '{"issue_count": 0}'


def test_mark_failed_stores_error(tmp_path):
    queue = _queue(tmp_path)
    job_id = queue.enqueue('{"issues": []}')
    queue.dequeue_pending()
    queue.mark_failed(job_id, "boom")
    job = queue.get(job_id)
    assert job.status == "failed"
    assert job.result_json == "boom"


def test_get_missing_job_is_none(tmp_path):
    queue = _queue(tmp_path)
    assert queue.get("does-not-exist") is None
