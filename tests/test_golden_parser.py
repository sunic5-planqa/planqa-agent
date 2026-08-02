from __future__ import annotations

import json

from planqa_eval.parsers.documents import load_source_text, parse_documents
from planqa_eval.parsers.golden import parse_golden_dataset
from planqa_eval.parsers.review_json import parse_review_output
from planqa_eval.parsers.review_sheet import parse_review_sheets


def test_golden_dataset_reads_confirmed_rows(xlsx_path):
    issues = parse_golden_dataset(xlsx_path)
    assert len(issues) >= 1
    assert all(issue.source == "golden" for issue in issues)
    assert all(issue.doc_id.startswith("DOC-") for issue in issues)
    assert all(issue.rule_id for issue in issues)


def test_golden_dataset_re_reads_the_sheet_every_call(xlsx_path):
    # Nothing must be cached/hardcoded — re-parsing the same file must yield the same set,
    # proving each call goes back to the sheet rather than a frozen list.
    first = {i.doc_id for i in parse_golden_dataset(xlsx_path)}
    second = {i.doc_id for i in parse_golden_dataset(xlsx_path)}
    assert first == second
    assert "DOC-006" in first


def test_review_sheets_discovered_dynamically_not_hardcoded(xlsx_path):
    sheets = parse_review_sheets(xlsx_path)
    assert set(sheets) >= {"Review1", "Review2", "Review3", "Review4", "Review5", "Review6"}
    assert sheets["Review5"] == []  # not started yet, but must not error
    assert len(sheets["Review1"]) > 0
    assert all(issue.source == "review_sheet:Review1" for issue in sheets["Review1"])


def test_documents_and_source_text(xlsx_path, source_dir):
    docs = parse_documents(xlsx_path)
    assert docs["DOC-001"].title.startswith("NxEF")
    text = load_source_text("DOC-001", source_dir)
    assert text and "홈" in text
    assert load_source_text("DOC-999", source_dir) is None


def test_review_json_accepts_bare_array_and_wrapped_object(tmp_path):
    sample = [
        {"doc_id": "DOC-001", "level": "Document", "rule_id": "LG-06", "location": "x", "description": "y"}
    ]
    bare = tmp_path / "bare.json"
    bare.write_text(json.dumps(sample), encoding="utf-8")
    wrapped = tmp_path / "wrapped.json"
    wrapped.write_text(json.dumps({"issues": sample}), encoding="utf-8")

    assert parse_review_output(bare)[0].doc_id == "DOC-001"
    assert parse_review_output(wrapped)[0].doc_id == "DOC-001"
    assert parse_review_output(bare)[0].source == "review_agent"
