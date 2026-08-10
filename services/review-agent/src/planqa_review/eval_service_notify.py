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


def notify_eval_service(
    review_result: dict[str, Any] | list[dict[str, Any]], *, base_url: str | None = None
) -> threading.Thread | None:
    # Runs the POST off-thread so cmd_review doesn't wait on eval-service's latency before
    # printing its own summary — but the caller must still join() this with a bounded
    # timeout before the process exits. A daemon thread racing sys.exit() is not "fire and
    # forget", it's "usually never sent": the interpreter can tear down mid-request.
    url = base_url or os.environ.get("EVAL_SERVICE_URL")
    if not url:
        return None
    endpoint = f"{url.rstrip('/')}/evaluate-async"
    payload = {"review_result": review_result}
    thread = threading.Thread(target=_post, args=(endpoint, payload, _DEFAULT_TIMEOUT_SECONDS), daemon=True)
    thread.start()
    return thread
