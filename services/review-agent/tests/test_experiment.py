from __future__ import annotations

from conftest import ScriptedLLM

from planqa_review.experiment import (
    ExperimentConfig,
    _summary_dict,
    run_experiment,
    summary_markdown,
    write_experiment_report,
)
from planqa_schemas.rulebook import parse_rulebook
from planqa_review.run_stats import hash_rulebook
from planqa_review.scoring import GoldenRow

_DOC = "# 샘플 PRD\n\n## 1. 목적\n\n간단한 목적 설명입니다.\n"


def _client_pair(fix_direction: str) -> tuple[ScriptedLLM, ScriptedLLM]:
    confirm_llm = ScriptedLLM(
        [
            {"summary": "요약"},
            {
                "verdicts": [
                    {
                        "index": 0,
                        "violated": True,
                        "original_text": "간단한 목적 설명입니다.",
                        "description": "목적이 구체적이지 않음",
                        "fix_direction": fix_direction,
                        "excused": False,
                    }
                ]
            },
        ]
    )
    screen_llm = ScriptedLLM(
        [
            {"candidates": []},
            {
                "candidates": [
                    {"chunk_index": 0, "rule_id": "MI-01", "quoted_text": "간단한 목적 설명입니다.", "reason": "목적 불명확"}
                ]
            },
            {"candidates": []},
            {"candidates": []},
        ]
    )
    return screen_llm, confirm_llm


def _make_build_clients(pairs: list[tuple[ScriptedLLM, ScriptedLLM]]):
    iterator = iter(pairs)
    return lambda: next(iterator)


def test_run_experiment_sweeps_all_documents_and_scores_each(tmp_path, rulebook_path):
    (tmp_path / "DOC-A_test.md").write_text(_DOC, encoding="utf-8")
    (tmp_path / "DOC-B_test.md").write_text(_DOC, encoding="utf-8")
    rulebook = parse_rulebook(rulebook_path)
    golden_rows = [
        GoldenRow(doc_id="DOC-A", level="Logical Unit", rule_id="MI-01", location="1. 목적"),
        GoldenRow(doc_id="DOC-B", level="Logical Unit", rule_id="MI-01", location="1. 목적"),
    ]
    config = ExperimentConfig(profile="gemini_lite", doc_ids=("DOC-A", "DOC-B"))
    build_clients = _make_build_clients([_client_pair("수정 A"), _client_pair("수정 B")])

    experiment = run_experiment(config, rulebook, rulebook_path, tmp_path, golden_rows, build_clients=build_clients)

    assert [doc.doc_id for doc in experiment.documents] == ["DOC-A", "DOC-B"]
    assert experiment.summary.score.overall.true_positives == 2
    assert experiment.summary.score.overall.recall == 1.0
    assert experiment.summary.screen.call_count == 8  # 4 tiers x 2 docs
    assert experiment.summary.confirm.call_count == 4  # (context + 1 verdict batch) x 2 docs


def test_run_experiment_keeps_per_document_stats_isolated(tmp_path, rulebook_path):
    """Each document gets a fresh client pair — one doc's call count must not leak into
    another's, or per-document cost comparisons in the report would be wrong."""
    (tmp_path / "DOC-A_test.md").write_text(_DOC, encoding="utf-8")
    (tmp_path / "DOC-B_test.md").write_text(_DOC, encoding="utf-8")
    rulebook = parse_rulebook(rulebook_path)
    config = ExperimentConfig(profile="gemini_lite", doc_ids=("DOC-A", "DOC-B"))
    build_clients = _make_build_clients([_client_pair("수정 A"), _client_pair("수정 B")])

    experiment = run_experiment(config, rulebook, rulebook_path, tmp_path, [], build_clients=build_clients)

    for doc in experiment.documents:
        assert doc.stats.screen.call_count == 4
        assert doc.stats.confirm.call_count == 2


def test_summary_markdown_includes_recall_and_per_document_table(tmp_path, rulebook_path):
    (tmp_path / "DOC-A_test.md").write_text(_DOC, encoding="utf-8")
    rulebook = parse_rulebook(rulebook_path)
    golden_rows = [GoldenRow(doc_id="DOC-A", level="Logical Unit", rule_id="MI-01", location="1. 목적")]
    config = ExperimentConfig(profile="gemini_lite", doc_ids=("DOC-A",))
    build_clients = _make_build_clients([_client_pair("수정 A")])

    experiment = run_experiment(config, rulebook, rulebook_path, tmp_path, golden_rows, build_clients=build_clients)
    markdown = summary_markdown(experiment)

    assert "DOC-A" in markdown
    assert "recall" in markdown.lower()
    assert "MI" in markdown  # by-category table includes the MI category row


def test_summary_records_temperature_and_rulebook_hash_for_cross_run_comparison(tmp_path, rulebook_path):
    """A later comparison across multiple experiment runs (different model/temperature)
    needs each run's own summary.json to say which config produced it — the output folder
    timestamp alone isn't machine-readable content."""
    (tmp_path / "DOC-A_test.md").write_text(_DOC, encoding="utf-8")
    rulebook = parse_rulebook(rulebook_path)
    config = ExperimentConfig(profile="gemini_lite", doc_ids=("DOC-A",), temperature=0.7)
    build_clients = _make_build_clients([_client_pair("수정 A")])

    experiment = run_experiment(config, rulebook, rulebook_path, tmp_path, [], build_clients=build_clients)

    assert experiment.summary.temperature == 0.7
    assert experiment.summary.rulebook_hash == hash_rulebook(rulebook_path)
    summary_dict = _summary_dict(experiment.summary)
    assert summary_dict["temperature"] == 0.7
    assert summary_dict["rulebook_hash"] == hash_rulebook(rulebook_path)
    markdown = summary_markdown(experiment)
    assert "0.7" in markdown
    assert hash_rulebook(rulebook_path) in markdown


def test_write_experiment_report_writes_per_doc_and_summary_files(tmp_path, rulebook_path):
    (tmp_path / "DOC-A_test.md").write_text(_DOC, encoding="utf-8")
    rulebook = parse_rulebook(rulebook_path)
    golden_rows = [GoldenRow(doc_id="DOC-A", level="Logical Unit", rule_id="MI-01", location="1. 목적")]
    config = ExperimentConfig(profile="gemini_lite", doc_ids=("DOC-A",))
    build_clients = _make_build_clients([_client_pair("수정 A")])

    experiment = run_experiment(config, rulebook, rulebook_path, tmp_path, golden_rows, build_clients=build_clients)
    out_dir = tmp_path / "out"
    write_experiment_report(out_dir, experiment, rulebook)

    assert (out_dir / "DOC-A" / "review.json").exists()
    assert (out_dir / "DOC-A" / "review.md").exists()
    assert (out_dir / "summary.json").exists()
    assert (out_dir / "summary.md").exists()
