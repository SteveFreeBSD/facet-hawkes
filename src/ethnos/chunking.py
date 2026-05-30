"""Page-aware chunking for extracted course text."""

from __future__ import annotations

import re

from .models import ChunkRecord, DocumentRecord, PageRecord


HEADING_RE = re.compile(r"^(\d+(\.\d+)*\.?\s+)?[A-Z][A-Za-z0-9 ,:;()/-]{2,80}$")


def build_chunks(
    document: DocumentRecord,
    pages: list[PageRecord],
    target_chars: int = 3000,
    max_chars: int = 4000,
    overlap_chars: int = 250,
) -> list[ChunkRecord]:
    """Build chunks that keep source page ranges explicit."""
    chunks: list[ChunkRecord] = []
    buffer: list[PageRecord] = []
    buffer_chars = 0

    for page in pages:
        text = page.cleaned_text.strip()
        if not text:
            continue

        if len(text) > max_chars:
            if buffer:
                _append_page_group(chunks, document, buffer)
                buffer = []
                buffer_chars = 0
            for piece in split_long_text(text, target_chars, max_chars, overlap_chars):
                _append_chunk(
                    chunks,
                    document=document,
                    page_start=page.page_number,
                    page_end=page.page_number,
                    text=piece,
                )
            continue

        would_exceed = buffer and buffer_chars + len(text) + 2 > max_chars
        if would_exceed:
            _append_page_group(chunks, document, buffer)
            buffer = []
            buffer_chars = 0

        buffer.append(page)
        buffer_chars += len(text) + 2

        if buffer_chars >= target_chars:
            _append_page_group(chunks, document, buffer)
            buffer = []
            buffer_chars = 0

    if buffer:
        _append_page_group(chunks, document, buffer)

    return chunks


def split_long_text(
    text: str, target_chars: int = 3000, max_chars: int = 4000, overlap_chars: int = 250
) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    pieces: list[str] = []
    current: list[str] = []
    current_len = 0

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                pieces.append("\n\n".join(current).strip())
                current = []
                current_len = 0
            pieces.extend(_split_by_size(paragraph, max_chars, overlap_chars))
            continue

        if current and current_len + len(paragraph) + 2 > max_chars:
            pieces.append("\n\n".join(current).strip())
            overlap = _tail_overlap(pieces[-1], overlap_chars)
            current = [overlap, paragraph] if overlap else [paragraph]
            current_len = sum(len(part) + 2 for part in current)
        else:
            current.append(paragraph)
            current_len += len(paragraph) + 2

        if current_len >= target_chars:
            pieces.append("\n\n".join(current).strip())
            overlap = _tail_overlap(pieces[-1], overlap_chars)
            current = [overlap] if overlap else []
            current_len = len(overlap) if overlap else 0

    if current:
        final = "\n\n".join(current).strip()
        if final and (not pieces or final != pieces[-1]):
            pieces.append(final)
    return pieces


def detect_heading(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip()
        if is_heading(stripped):
            return stripped
    return None


def is_heading(line: str) -> bool:
    if not line or len(line) > 90:
        return False
    if line.endswith(".") and len(line.split()) > 4:
        return False
    return bool(HEADING_RE.match(line)) or line.isupper()


def _append_page_group(
    chunks: list[ChunkRecord], document: DocumentRecord, pages: list[PageRecord]
) -> None:
    text = "\n\n".join(
        page.cleaned_text.strip() for page in pages if page.cleaned_text.strip()
    )
    _append_chunk(
        chunks,
        document=document,
        page_start=pages[0].page_number,
        page_end=pages[-1].page_number,
        text=text,
    )


def _append_chunk(
    chunks: list[ChunkRecord],
    document: DocumentRecord,
    page_start: int,
    page_end: int,
    text: str,
) -> None:
    chunk_index = len(chunks) + 1
    chunks.append(
        ChunkRecord(
            document_id=document.id or 0,
            page_start=page_start,
            page_end=page_end,
            chunk_index=chunk_index,
            text=text,
            heading=detect_heading(text),
            char_count=len(text),
            source_citation=_citation(
                document.filename, page_start, page_end, chunk_index
            ),
        )
    )


def _citation(filename: str, page_start: int, page_end: int, chunk_index: int) -> str:
    pages = (
        f"p. {page_start}" if page_start == page_end else f"pp. {page_start}-{page_end}"
    )
    return f"{filename} {pages}, chunk {chunk_index}"


def _split_by_size(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    pieces = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        pieces.append(text[start:end].strip())
        if end == len(text):
            break
        start = max(0, end - overlap_chars)
    return [piece for piece in pieces if piece]


def _tail_overlap(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    return text[-overlap_chars:].strip()
