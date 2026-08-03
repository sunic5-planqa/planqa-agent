from __future__ import annotations

from planqa_eval.review_agent.document import parse_document
from planqa_eval.schema import Level

_SAMPLE = """# 샘플 PRD

## 1. 목적

### a. 배경

배경 설명 문장입니다. 두 번째 문장도 있습니다.

### b. 제안

제안 내용입니다.

## 2. 기능

- 최대 5개까지 노출
- 자동 갱신 간격: 3초

| 항목 | 값 |
|---|---|
| A | 1 |
"""


def test_parse_document_splits_logical_units_by_h2():
    tree = parse_document("DOC-TEST", _SAMPLE)
    assert [chunk.location for chunk in tree.logical_units] == ["1. 목적", "2. 기능"]


def test_parse_document_splits_paragraphs_by_h3_when_present():
    tree = parse_document("DOC-TEST", _SAMPLE)
    locations = [chunk.location for chunk in tree.paragraphs]
    assert "1. 목적 > a. 배경" in locations
    assert "1. 목적 > b. 제안" in locations


def test_parse_document_paragraph_without_subheading_uses_logical_unit_location():
    tree = parse_document("DOC-TEST", _SAMPLE)
    locations = [chunk.location for chunk in tree.paragraphs]
    assert "2. 기능" in locations


def test_parse_document_treats_bullets_and_table_rows_as_single_sentence_units():
    tree = parse_document("DOC-TEST", _SAMPLE)
    texts = [chunk.text for chunk in tree.sentences]
    assert "- 자동 갱신 간격: 3초" in texts
    assert "| A | 1 |" in texts


def test_parse_document_splits_prose_into_multiple_sentences():
    tree = parse_document("DOC-TEST", _SAMPLE)
    background = [c for c in tree.sentences if c.location == "1. 목적 > a. 배경"]
    assert len(background) == 2


def test_document_tier_is_the_whole_text_as_a_single_chunk():
    tree = parse_document("DOC-TEST", _SAMPLE)
    [chunk] = tree.chunks_for(Level.DOCUMENT)
    assert chunk.text == _SAMPLE
    assert chunk.location == "샘플 PRD"


def test_parse_document_falls_back_to_single_logical_unit_without_h2():
    tree = parse_document("DOC-TEST", "# 제목\n\n본문만 있음.")
    assert len(tree.logical_units) == 1
    assert tree.logical_units[0].text.strip() == "본문만 있음."


def test_parse_real_source_document_produces_nested_locations(source_dir):
    path = next(source_dir.glob("DOC-001_*.md"))
    tree = parse_document("DOC-001", path.read_text(encoding="utf-8"))

    labels = [chunk.location for chunk in tree.logical_units]
    assert "1. 프로덕트 목적" in labels
    assert "6. 프로덕트 기능" in labels

    paragraph_labels = [chunk.location for chunk in tree.paragraphs]
    assert "6. 프로덕트 기능 > 6-1. 메인 배너 (캐러셀)" in paragraph_labels

    assert any("3초" in chunk.text for chunk in tree.sentences)
