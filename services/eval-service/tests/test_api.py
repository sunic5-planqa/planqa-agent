from __future__ import annotations

from fastapi.testclient import TestClient

from planqa_eval_service import api
from planqa_eval_service.queue import SQLiteEvalQueue


def _client(tmp_path):
    api._queue = SQLiteEvalQueue(tmp_path / "eval_service.db")
    return TestClient(api.app)


def test_evaluate_async_returns_202_and_a_job_id(tmp_path):
    client = _client(tmp_path)
    response = client.post("/evaluate-async", json={"review_result": {"issues": []}})
    assert response.status_code == 202
    assert response.json()["status"] == "pending"
    assert response.json()["job_id"]


def test_get_job_reflects_pending_status_right_after_enqueue(tmp_path):
    client = _client(tmp_path)
    job_id = client.post("/evaluate-async", json={"review_result": {"issues": []}}).json()["job_id"]
    response = client.get(f"/evaluate-async/{job_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["result"] is None


def test_get_unknown_job_is_404(tmp_path):
    client = _client(tmp_path)
    response = client.get("/evaluate-async/does-not-exist")
    assert response.status_code == 404
