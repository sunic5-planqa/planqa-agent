from __future__ import annotations

import logging
import os
import threading
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 3.0


def _post(url: str, payload: dict[str, Any], timeout: float) -> None:
    try:
        httpx.post(url, json=payload, timeout=timeout)
    except Exception:
        # eval-service being down/slow/erroring must never surface to review-agent's own
        # caller — this is a best-effort quality-measurement signal, not something
        # review-agent's response depends on. Log and move on.
        logger.warning("eval-service notify failed", exc_info=True)


def notify_eval_service(review_result: dict[str, Any] | list[dict[str, Any]], *, base_url: str | None = None) -> None:
    """Fire-and-forget POST to eval-service's /evaluate-async — runs in a background thread
    so this call returns immediately regardless of eval-service's latency/availability.
    A no-op (not an error) when EVAL_SERVICE_URL isn't set, e.g. local dev without
    eval-service running."""
    url = base_url or os.environ.get("EVAL_SERVICE_URL")
    if not url:
        return
    endpoint = f"{url.rstrip('/')}/evaluate-async"
    payload = {"review_result": review_result}
    thread = threading.Thread(target=_post, args=(endpoint, payload, _DEFAULT_TIMEOUT_SECONDS), daemon=True)
    thread.start()
