from __future__ import annotations

import time

from planqa_review.eval_service_notify import notify_eval_service


def test_notify_is_a_noop_without_eval_service_url(monkeypatch):
    monkeypatch.delenv("EVAL_SERVICE_URL", raising=False)
    thread = notify_eval_service({"issues": []})  # must not raise
    assert thread is None


def test_notify_returns_immediately_when_eval_service_is_unreachable(monkeypatch):
    # Port 1 — nothing listens there, connection should fail fast, but the point is that
    # notify_eval_service() itself returns right away regardless (fire-and-forget thread),
    # not that the connection succeeds or fails within any particular time.
    monkeypatch.delenv("EVAL_SERVICE_URL", raising=False)
    start = time.perf_counter()
    thread = notify_eval_service({"issues": []}, base_url="http://127.0.0.1:1")
    elapsed = time.perf_counter() - start
    assert elapsed < 0.5  # did not block waiting on the HTTP call/timeout
    assert thread is not None
    thread.join(timeout=5.0)  # don't leak a running thread past the test


def test_notify_thread_actually_completes_when_joined(monkeypatch):
    # Regression check for the bug where a daemon thread could be killed by interpreter
    # exit before its POST landed — join() must reliably wait for _post() to finish.
    monkeypatch.delenv("EVAL_SERVICE_URL", raising=False)
    thread = notify_eval_service({"issues": []}, base_url="http://127.0.0.1:1")
    assert thread is not None
    thread.join(timeout=5.0)
    assert not thread.is_alive()
