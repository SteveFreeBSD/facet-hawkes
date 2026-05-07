from __future__ import annotations

from ethnos.chunking import build_chunks
from ethnos.cli import main
from ethnos.db import (
    connect,
    init_db,
    list_documents,
    save_chunks,
    save_document_pages,
    search_chunks,
)
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


def test_list_documents_returns_beginner_visible_fields(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/tiny.pdf",
        filename="tiny.pdf",
        sha256="abcdef1234567890",
        title="Tiny",
        page_count=3,
    )

    save_document_pages(conn, document, [])

    documents = list_documents(conn)

    assert documents == [
        {
            "id": 1,
            "filename": "tiny.pdf",
            "page_count": 3,
            "source_path": "/tmp/tiny.pdf",
            "sha256": "abcdef1234567890",
            "created_at": documents[0]["created_at"],
        }
    ]
    assert documents[0]["created_at"]


def test_documents_cli_lists_stored_documents(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="1234567890abcdef",
        title="Course",
        page_count=12,
    )
    save_document_pages(conn, document, [])

    exit_code = main(["--db", str(db_path), "documents"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "id" in output
    assert "filename" in output
    assert "pages" in output
    assert "course.pdf" in output
    assert "12" in output
    assert "1234567890ab" in output
    assert "/tmp/course.pdf" in output
