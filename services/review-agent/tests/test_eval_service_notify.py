from __future__ import annotations

import time

from planqa_review.eval_service_notify import notify_eval_service


def test_notify_is_a_noop_without_eval_service_url(monkeypatch):
    monkeypatch.delenv("EVAL_SERVICE_URL", raising=False)
    notify_eval_service({"issues": []})  # must not raise


def test_notify_returns_immediately_when_eval_service_is_unreachable(monkeypatch):
    # Port 1 — nothing listens there, connection should fail fast, but the point is that
    # notify_eval_service() itself returns right away regardless (fire-and-forget thread),
    # not that the connection succeeds or fails within any particular time.
    monkeypatch.delenv("EVAL_SERVICE_URL", raising=False)
    start = time.perf_counter()
    notify_eval_service({"issues": []}, base_url="http://127.0.0.1:1")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5  # did not block waiting on the HTTP call/timeout
