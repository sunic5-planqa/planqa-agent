from __future__ import annotations

import re
from dataclasses import dataclass

from planqa_review.schema import Level

_H1 = re.compile(r"(?m)^#\s+(.+?)\s*$")
_HEADING = re.compile(r"(?m)^(#{2,6})\s+(.+?)\s*$")
_BULLET_LINE = re.compile(r"^\s*[-*]\s+.+$")
_TABLE_ROW_LINE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_LINE = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=\S)|(?<=다\.)\s+(?=\S)|(?<=요\.)\s+(?=\S)")


@dataclass(frozen=True, slots=True)
class Chunk:
    """One reviewable unit at a given rulebook §1 위계 (hierarchy tier)."""

    level: Level
    location: str
    text: str


@dataclass(frozen=True, slots=True)
class DocumentTree:
    doc_id: str
    full_text: str
    logical_units: tuple[Chunk, ...]
    paragraphs: tuple[Chunk, ...]
    sentences: tuple[Chunk, ...]

    def chunks_for(self, level: Level) -> tuple[Chunk, ...]:
        if level is Level.DOCUMENT:
            return (Chunk(level=Level.DOCUMENT, location=_doc_title(self.full_text), text=self.full_text),)
        if level is Level.LOGICAL_UNIT:
            return self.logical_units
        if level is Level.PARAGRAPH:
            return self.paragraphs
        if level is Level.SENTENCE:
            return self.sentences
        return ()


# Coarser (smaller number) -> finer. Used to decide how much to trust a model-claimed level
# that differs from the chunk it was actually given:
# - *Promotion* (claimed level coarser than the chunk) is a claim about something the chunk
#   never showed the model — only trusted when the call actually had that wider visibility
#   (GA/LG/LF get dispatched at Document tier for exactly this reason; see tiers.py).
# - *Demotion* (claimed level finer than the chunk, e.g. a Paragraph-tier call reporting
#   that only one Sentence within it is the actual problem) is a claim about something
#   *inside* what the model was shown — `original_text` being a real quote from the chunk is
#   its own evidence, so this is trusted the same way promotion within a properly-scoped
#   call is.
# Level.WORD has no entry on purpose here (§2 assigns it no categories/input unit — see
# tiers.py) but it's still a real Level member a model could echo back in a "level" field,
# so resolve_reported_level below must not do a bare [] lookup on this dict without checking
# membership first, or an unrecognized-but-valid Level value crashes instead of being
# ignored like every other unrecognized value.
_LEVEL_COARSENESS: dict[Level, int] = {Level.DOCUMENT: 0, Level.LOGICAL_UNIT: 1, Level.PARAGRAPH: 2, Level.SENTENCE: 3}


# `claimed_level_name` is whatever the model put in an optional "level" field of its JSON
# response; anything that isn't a recognized Level value with a known coarseness is ignored
# and (chunk_level, chunk_location) is returned unchanged.
#
# Promoting a location string works because document.py's own paragraph/sentence
# Chunk.location values are already built as "<logical unit label> > <sub label>" (see
# _split_paragraphs) — trimming at the first " > " recovers the logical-unit-level label.
# There's nothing to trim for a lone label (already document/logical-unit level, or a
# paragraph with no sub-heading) — the caller just gets that label back unchanged, which is
# a reasonable best-effort location for a promoted Document-level report.
#
# Demoting never touches the location string: a Sentence chunk's own `location` is already
# identical to its parent Paragraph's (see _split_sentences), so a Paragraph-tier call
# demoting to Sentence is already pointing at the right label without any adjustment.
def resolve_reported_level(chunk_level: Level, chunk_location: str, claimed_level_name: object) -> tuple[Level, str]:
    if not isinstance(claimed_level_name, str):
        return chunk_level, chunk_location
    try:
        claimed_level = Level(claimed_level_name)
    except ValueError:
        return chunk_level, chunk_location
    if claimed_level not in _LEVEL_COARSENESS:
        return chunk_level, chunk_location

    claimed_rank, chunk_rank = _LEVEL_COARSENESS[claimed_level], _LEVEL_COARSENESS[chunk_level]
    if claimed_rank == chunk_rank:
        return chunk_level, chunk_location
    if claimed_rank > chunk_rank:
        return claimed_level, chunk_location

    promoted_location = chunk_location.split(" > ", 1)[0] if " > " in chunk_location else chunk_location
    return claimed_level, promoted_location


def _doc_title(text: str) -> str:
    match = _H1.search(text)
    return match.group(1).strip() if match else "문서 전체"


def _heading_blocks(text: str, min_level: int, max_level: int | None = None) -> list[tuple[str, str]]:
    """Splits `text` sequentially at every heading whose level falls in [min_level,
    max_level] (max_level defaults to min_level): each match's block runs from right after
    its heading line to the position of the *next matching* heading (headings outside the
    depth range don't interrupt a block, so nested sub-headings stay inside their parent's
    slice unless that depth is included too). Returns (heading_label, block_body) pairs."""
    matches = [
        (m.start(), m.end(), label)
        for m in _HEADING.finditer(text)
        if min_level <= len(m.group(1)) <= (max_level or min_level)
        for label in (m.group(2).strip(),)
    ]
    blocks: list[tuple[str, str]] = []
    for i, (_start, header_end, label) in enumerate(matches):
        end = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        blocks.append((label, text[header_end:end].strip()))
    return blocks


def _split_paragraphs(logical_unit_label: str, body: str) -> list[Chunk]:
    """A 논리단위's body is split into 문단 chunks at every heading level >= 3 inside it. A
    body with no such headings is itself a single 문단 (no further split)."""
    sub_blocks = _heading_blocks(body, min_level=3, max_level=6)
    if not sub_blocks:
        stripped = body.strip()
        return [Chunk(level=Level.PARAGRAPH, location=logical_unit_label, text=stripped)] if stripped else []

    paragraphs: list[Chunk] = []
    for label, sub_body in sub_blocks:
        if sub_body.strip():
            paragraphs.append(Chunk(level=Level.PARAGRAPH, location=f"{logical_unit_label} > {label}", text=sub_body))
    return paragraphs


def _split_sentences(paragraph: Chunk) -> list[Chunk]:
    """§1: a bullet or a table cell counts as one 문장 unit, same as an actual sentence.
    Table rows are kept whole (not split per cell) — a reasonable v1 approximation, see
    docs/review_agent_architecture.md."""
    units: list[str] = []
    prose_buffer: list[str] = []

    def flush_prose() -> None:
        if not prose_buffer:
            return
        prose = " ".join(prose_buffer).strip()
        prose_buffer.clear()
        if prose:
            units.extend(s.strip() for s in _SENTENCE_END.split(prose) if s.strip())

    for line in paragraph.text.splitlines():
        if not line.strip():
            flush_prose()
            continue
        if _TABLE_SEPARATOR_LINE.match(line):
            continue
        if _BULLET_LINE.match(line) or _TABLE_ROW_LINE.match(line):
            flush_prose()
            units.append(line.strip())
        else:
            prose_buffer.append(line.strip())
    flush_prose()

    return [Chunk(level=Level.SENTENCE, location=paragraph.location, text=unit) for unit in units]


def parse_document(doc_id: str, text: str) -> DocumentTree:
    logical_blocks = _heading_blocks(text, min_level=2)
    if not logical_blocks:
        # No H2 headings at all — treat the whole document (minus the H1 title line, if any)
        # as a single 논리단위 rather than silently producing zero reviewable chunks.
        body = _H1.sub("", text, count=1).strip()
        logical_blocks = [(_doc_title(text), body)] if body else []
    logical_units = [Chunk(level=Level.LOGICAL_UNIT, location=label, text=body) for label, body in logical_blocks if body.strip()]

    paragraphs: list[Chunk] = []
    for label, body in logical_blocks:
        paragraphs.extend(_split_paragraphs(label, body))

    sentences: list[Chunk] = []
    for paragraph in paragraphs:
        sentences.extend(_split_sentences(paragraph))

    return DocumentTree(
        doc_id=doc_id,
        full_text=text,
        logical_units=tuple(logical_units),
        paragraphs=tuple(paragraphs),
        sentences=tuple(sentences),
    )
