from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class EvaluateAsyncRequest(BaseModel):
    review_result: dict[str, Any]


class EvaluateAsyncResponse(BaseModel):
    job_id: str
    status: str = "pending"


class JobStatusResponse(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] | None = None
