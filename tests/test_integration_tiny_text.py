from __future__ import annotations

from ethnos.chunking import build_chunks
from ethnos.db import connect, init_db, save_chunks, save_document_pages, search_chunks
from ethnos.models import DocumentRecord, PageRecord


def test_tiny_text_to_sqlite_and_fts(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)

    document = DocumentRecord(
        source_path="/tmp/tiny.pdf",
        filename="tiny.pdf",
        sha256="abc123",
        title="Tiny",
        page_count=1,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="Ecology\nFood webs describe energy transfer.",
            cleaned_text="Ecology\nFood webs describe energy transfer.",
            char_count=43,
        )
    ]

    document_id = save_document_pages(conn, document, pages)
    stored_document = document.model_copy(update={"id": document_id})
    chunks = build_chunks(stored_document, pages)
    save_chunks(conn, document_id, chunks)

    results = search_chunks(conn, "energy", limit=5)

    assert len(results) == 1
    assert results[0]["source_citation"] == "tiny.pdf p. 1, chunk 1"

