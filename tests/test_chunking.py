from __future__ import annotations

from ethnos.chunking import build_chunks, detect_heading, split_long_text
from ethnos.models import DocumentRecord, PageRecord


def test_chunking_respects_page_metadata():
    document = DocumentRecord(
        id=7,
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="abc",
        title="Course",
        page_count=2,
    )
    pages = [
        PageRecord(
            document_id=7,
            page_number=1,
            raw_text="Photosynthesis\nPlants use light.",
            cleaned_text="Photosynthesis\nPlants use light.",
            char_count=32,
        ),
        PageRecord(
            document_id=7,
            page_number=2,
            raw_text="Respiration\nCells release energy.",
            cleaned_text="Respiration\nCells release energy.",
            char_count=34,
        ),
    ]

    chunks = build_chunks(document, pages, target_chars=1000, max_chars=1000)

    assert len(chunks) == 1
    assert chunks[0].document_id == 7
    assert chunks[0].page_start == 1
    assert chunks[0].page_end == 2
    assert chunks[0].source_citation == "course.pdf pp. 1-2, chunk 1"


def test_split_long_text_uses_overlap():
    text = "\n\n".join([f"Paragraph {index} " + ("x" * 80) for index in range(10)])

    chunks = split_long_text(text, target_chars=250, max_chars=320, overlap_chars=40)

    assert len(chunks) > 1
    assert all(len(chunk) <= 360 for chunk in chunks)


def test_detect_heading_finds_simple_heading():
    assert detect_heading("Cell Biology\nCells are small units.") == "Cell Biology"

