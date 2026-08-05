from __future__ import annotations

import pytest

from planqa_review.benchmark import BENCHMARK_DOC_IDS, golden_rows_for_benchmark, resolve_source_path
from planqa_review.scoring import GoldenRow


def test_resolve_source_path_finds_real_file(source_dir):
    path = resolve_source_path(source_dir, "DOC-003")
    assert path.name == "DOC-003_상품상세페이지_PRD.md"


def test_resolve_source_path_raises_for_unknown_doc_id(source_dir):
    with pytest.raises(FileNotFoundError):
        resolve_source_path(source_dir, "DOC-999")


def test_resolve_source_path_raises_when_multiple_files_match(tmp_path):
    (tmp_path / "DOC-050_a.md").write_text("a", encoding="utf-8")
    (tmp_path / "DOC-050_b.md").write_text("b", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_source_path(tmp_path, "DOC-050")


def test_all_benchmark_doc_ids_resolve_against_real_source_dir(source_dir):
    for doc_id in BENCHMARK_DOC_IDS:
        resolve_source_path(source_dir, doc_id)


def test_golden_rows_for_benchmark_filters_to_configured_doc_ids():
    rows = [
        GoldenRow(doc_id="DOC-003", level="Sentence", rule_id="AE-03", location="a"),
        GoldenRow(doc_id="DOC-000", level="Document", rule_id="LG-01", location="b"),
    ]
    filtered = golden_rows_for_benchmark(rows)
    assert filtered == (rows[0],)


def test_golden_rows_for_benchmark_accepts_custom_doc_id_set():
    rows = [GoldenRow(doc_id="DOC-999", level="Sentence", rule_id="AE-03", location="a")]
    filtered = golden_rows_for_benchmark(rows, doc_ids=("DOC-999",))
    assert filtered == (rows[0],)
