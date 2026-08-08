from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EvalJob:
    id: str
    review_result_json: str
    status: str  # "pending" | "processing" | "done" | "failed"
    created_at: str
    result_json: str | None = None


class EvalQueue(Protocol):
    """v2 (Redis/arq, once volume justifies it) swaps in behind this same interface —
    api.py/worker.py never need to change, only which EvalQueue they're constructed with."""

    def enqueue(self, review_result_json: str) -> str: ...
    def dequeue_pending(self, limit: int = 10) -> list[EvalJob]: ...
    def mark_done(self, job_id: str, result_json: str) -> None: ...
    def mark_failed(self, job_id: str, error: str) -> None: ...
    def get(self, job_id: str) -> EvalJob | None: ...


class SQLiteEvalQueue:
    """A SQLite file as a durable outbox — survives a worker restart unlike an in-memory
    queue, no Redis/broker to run. dequeue_pending() flips picked-up rows to 'processing' in
    the same call so a slow judge_review_result() call doesn't get re-picked-up by the next
    poll tick; a worker crash mid-job leaves it stuck in 'processing' (known v1 gap, not
    auto-retried — acceptable at this volume, revisit if it becomes a real problem)."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS eval_jobs (
                    id TEXT PRIMARY KEY,
                    review_result_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    result_json TEXT
                )
                """
            )

    def enqueue(self, review_result_json: str) -> str:
        job_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO eval_jobs (id, review_result_json, status, created_at) VALUES (?, ?, 'pending', ?)",
                (job_id, review_result_json, datetime.now(UTC).isoformat()),
            )
        return job_id

    def dequeue_pending(self, limit: int = 10) -> list[EvalJob]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM eval_jobs WHERE status = 'pending' ORDER BY created_at LIMIT ?",
                (limit,),
            ).fetchall()
            ids = [row["id"] for row in rows]
            if ids:
                placeholders = ",".join("?" * len(ids))
                conn.execute(f"UPDATE eval_jobs SET status = 'processing' WHERE id IN ({placeholders})", ids)
        return [EvalJob(**{**dict(row), "status": "processing"}) for row in rows]

    def mark_done(self, job_id: str, result_json: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE eval_jobs SET status = 'done', result_json = ? WHERE id = ?", (result_json, job_id))

    def mark_failed(self, job_id: str, error: str) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE eval_jobs SET status = 'failed', result_json = ? WHERE id = ?", (error, job_id))

    def get(self, job_id: str) -> EvalJob | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM eval_jobs WHERE id = ?", (job_id,)).fetchone()
        return EvalJob(**dict(row)) if row else None
