from __future__ import annotations

import json
from pathlib import Path

from planqa_eval.parsers.review_json import parse_review_stats


def _write(tmp_path: Path, data) -> Path:
    path = tmp_path / "review.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_parse_review_stats_reads_the_stats_key(tmp_path):
    path = _write(tmp_path, {"issues": [], "stats": {"profile": "gemini_lite"}})
    assert parse_review_stats(path) == {"profile": "gemini_lite"}


def test_parse_review_stats_missing_key_is_none(tmp_path):
    path = _write(tmp_path, {"issues": []})
    assert parse_review_stats(path) is None


def test_parse_review_stats_bare_array_is_none(tmp_path):
    path = _write(tmp_path, [])
    assert parse_review_stats(path) is None
