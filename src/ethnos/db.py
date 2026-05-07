"""SQLite storage for documents, pages, chunks, and structured outputs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import ChunkRecord, DocumentRecord, ExtractionResult, PageRecord


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            source_path TEXT NOT NULL,
            filename TEXT NOT NULL,
            sha256 TEXT NOT NULL UNIQUE,
            title TEXT,
            page_count INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            raw_text TEXT NOT NULL,
            cleaned_text TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            extraction_method TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, page_number)
        );

        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            page_start INTEGER NOT NULL,
            page_end INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            heading TEXT,
            char_count INTEGER NOT NULL,
            source_citation TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY,
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            summary TEXT NOT NULL,
            confidence REAL NOT NULL,
            source_pages TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS key_terms (
            id INTEGER PRIMARY KEY,
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            term TEXT NOT NULL,
            definition TEXT NOT NULL,
            context TEXT NOT NULL DEFAULT '',
            source_pages TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS examples (
            id INTEGER PRIMARY KEY,
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            source_pages TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY,
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            difficulty TEXT NOT NULL,
            source_pages TEXT NOT NULL DEFAULT '[]'
        );

        CREATE TABLE IF NOT EXISTS extraction_runs (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            model_name TEXT NOT NULL,
            prompt_name TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            status TEXT NOT NULL,
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS model_outputs (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
            chunk_id INTEGER REFERENCES chunks(id) ON DELETE SET NULL,
            raw_prompt TEXT NOT NULL,
            raw_response TEXT NOT NULL,
            parsed_json TEXT,
            validation_status TEXT NOT NULL,
            validation_error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text,
            heading,
            source_citation,
            content='chunks',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, text, heading, source_citation)
            VALUES (new.id, new.text, new.heading, new.source_citation);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text, heading, source_citation)
            VALUES ('delete', old.id, old.text, old.heading, old.source_citation);
        END;

        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text, heading, source_citation)
            VALUES ('delete', old.id, old.text, old.heading, old.source_citation);
            INSERT INTO chunks_fts(rowid, text, heading, source_citation)
            VALUES (new.id, new.text, new.heading, new.source_citation);
        END;
        """
    )


def save_document_pages(
    conn: sqlite3.Connection, document: DocumentRecord, pages: list[PageRecord]
) -> int:
    metadata_json = json.dumps(document.metadata, sort_keys=True)
    with conn:
        existing = conn.execute(
            "SELECT id FROM documents WHERE sha256 = ?", (document.sha256,)
        ).fetchone()
        if existing:
            document_id = int(existing["id"])
            conn.execute(
                """
                UPDATE documents
                SET source_path = ?, filename = ?, title = ?, page_count = ?, metadata_json = ?
                WHERE id = ?
                """,
                (
                    document.source_path,
                    document.filename,
                    document.title,
                    document.page_count,
                    metadata_json,
                    document_id,
                ),
            )
            clear_document_outputs(conn, document_id)
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
            conn.execute("DELETE FROM pages WHERE document_id = ?", (document_id,))
        else:
            cursor = conn.execute(
                """
                INSERT INTO documents (source_path, filename, sha256, title, page_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document.source_path,
                    document.filename,
                    document.sha256,
                    document.title,
                    document.page_count,
                    metadata_json,
                ),
            )
            document_id = int(cursor.lastrowid)

        for page in pages:
            conn.execute(
                """
                INSERT INTO pages (
                    document_id, page_number, raw_text, cleaned_text, char_count, extraction_method
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    page.page_number,
                    page.raw_text,
                    page.cleaned_text,
                    page.char_count,
                    page.extraction_method,
                ),
            )
    return document_id


def get_document(conn: sqlite3.Connection, document_id: int) -> DocumentRecord:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        raise ValueError(f"No document found with id {document_id}")
    return DocumentRecord(
        id=row["id"],
        source_path=row["source_path"],
        filename=row["filename"],
        sha256=row["sha256"],
        title=row["title"],
        page_count=row["page_count"],
        metadata=json.loads(row["metadata_json"]),
    )


def list_documents(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, filename, page_count, source_path, sha256, created_at
        FROM documents
        ORDER BY id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def list_pages(conn: sqlite3.Connection, document_id: int) -> list[PageRecord]:
    rows = conn.execute(
        "SELECT * FROM pages WHERE document_id = ? ORDER BY page_number", (document_id,)
    ).fetchall()
    return [
        PageRecord(
            id=row["id"],
            document_id=row["document_id"],
            page_number=row["page_number"],
            raw_text=row["raw_text"],
            cleaned_text=row["cleaned_text"],
            char_count=row["char_count"],
            extraction_method=row["extraction_method"],
        )
        for row in rows
    ]


def list_chunks(conn: sqlite3.Connection, document_id: int) -> list[ChunkRecord]:
    rows = conn.execute(
        "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index", (document_id,)
    ).fetchall()
    return [
        ChunkRecord(
            id=row["id"],
            document_id=row["document_id"],
            page_start=row["page_start"],
            page_end=row["page_end"],
            chunk_index=row["chunk_index"],
            text=row["text"],
            heading=row["heading"],
            char_count=row["char_count"],
            source_citation=row["source_citation"],
        )
        for row in rows
    ]


def select_chunks_for_structure(
    conn: sqlite3.Connection,
    document_id: int,
    chunk_id: int | None = None,
    limit: int | None = None,
) -> list[ChunkRecord]:
    if chunk_id is not None:
        rows = conn.execute(
            """
            SELECT *
            FROM chunks
            WHERE document_id = ? AND id = ?
            ORDER BY chunk_index
            """,
            (document_id, chunk_id),
        ).fetchall()
    elif limit is not None:
        rows = conn.execute(
            """
            SELECT *
            FROM chunks c
            WHERE c.document_id = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM model_outputs mo
                  WHERE mo.chunk_id = c.id
                    AND mo.validation_status = 'valid'
              )
            ORDER BY c.chunk_index
            LIMIT ?
            """,
            (document_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index",
            (document_id,),
        ).fetchall()

    return [_chunk_from_row(row) for row in rows]


def _chunk_from_row(row: sqlite3.Row) -> ChunkRecord:
    return ChunkRecord(
        id=row["id"],
        document_id=row["document_id"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        heading=row["heading"],
        char_count=row["char_count"],
        source_citation=row["source_citation"],
    )


def save_chunks(conn: sqlite3.Connection, document_id: int, chunks: list[ChunkRecord]) -> None:
    with conn:
        clear_document_outputs(conn, document_id)
        conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))
        for chunk in chunks:
            conn.execute(
                """
                INSERT INTO chunks (
                    document_id, page_start, page_end, chunk_index, text, heading,
                    char_count, source_citation
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    chunk.page_start,
                    chunk.page_end,
                    chunk.chunk_index,
                    chunk.text,
                    chunk.heading,
                    chunk.char_count,
                    chunk.source_citation,
                ),
            )


def create_extraction_run(
    conn: sqlite3.Connection, document_id: int, model_name: str, prompt_name: str
) -> int:
    with conn:
        cursor = conn.execute(
            """
            INSERT INTO extraction_runs (
                document_id, model_name, prompt_name, schema_version, status
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (document_id, model_name, prompt_name, "extraction-result-v1", "running"),
        )
    return int(cursor.lastrowid)


def finish_extraction_run(
    conn: sqlite3.Connection, run_id: int, status: str, error_message: str | None = None
) -> None:
    with conn:
        conn.execute(
            """
            UPDATE extraction_runs
            SET status = ?, error_message = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (status, error_message, run_id),
        )


def save_model_output(
    conn: sqlite3.Connection,
    run_id: int,
    chunk_id: int,
    raw_prompt: str,
    raw_response: str,
    parsed_json: dict[str, Any] | None,
    validation_status: str,
    validation_error: str | None,
) -> None:
    with conn:
        conn.execute(
            """
            INSERT INTO model_outputs (
                run_id, chunk_id, raw_prompt, raw_response, parsed_json,
                validation_status, validation_error
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                chunk_id,
                raw_prompt,
                raw_response,
                json.dumps(parsed_json, sort_keys=True) if parsed_json is not None else None,
                validation_status,
                validation_error,
            ),
        )


def save_extraction_result(
    conn: sqlite3.Connection, chunk_id: int, result: ExtractionResult
) -> None:
    fallback_source_pages = _chunk_source_pages(conn, chunk_id)
    with conn:
        for topic in result.topics:
            source_pages = _record_source_pages(topic.source_pages, fallback_source_pages)
            conn.execute(
                """
                INSERT INTO topics (chunk_id, name, summary, confidence, source_pages)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    topic.name,
                    topic.summary,
                    topic.confidence,
                    json.dumps(source_pages),
                ),
            )
        for term in result.key_terms:
            source_pages = _record_source_pages(term.source_pages, fallback_source_pages)
            conn.execute(
                """
                INSERT INTO key_terms (chunk_id, term, definition, context, source_pages)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    term.term,
                    term.definition,
                    term.context,
                    json.dumps(source_pages),
                ),
            )
        for example in result.examples:
            source_pages = _record_source_pages(example.source_pages, fallback_source_pages)
            conn.execute(
                """
                INSERT INTO examples (chunk_id, title, body, source_pages)
                VALUES (?, ?, ?, ?)
                """,
                (chunk_id, example.title, example.body, json.dumps(source_pages)),
            )
        for question in result.questions:
            source_pages = _record_source_pages(question.source_pages, fallback_source_pages)
            conn.execute(
                """
                INSERT INTO questions (chunk_id, question, answer, difficulty, source_pages)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    question.question,
                    question.answer,
                    question.difficulty,
                    json.dumps(source_pages),
                ),
            )


def _chunk_source_pages(conn: sqlite3.Connection, chunk_id: int) -> list[int]:
    row = conn.execute(
        "SELECT page_start, page_end FROM chunks WHERE id = ?", (chunk_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"No chunk found with id {chunk_id}")
    return list(range(row["page_start"], row["page_end"] + 1))


def _record_source_pages(model_pages: list[int], fallback_pages: list[int]) -> list[int]:
    return model_pages if model_pages else fallback_pages


def clear_document_outputs(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM extraction_runs WHERE document_id = ?", (document_id,))


def search_chunks(conn: sqlite3.Connection, query: str, limit: int = 10) -> list[dict[str, Any]]:
    try:
        return _search_chunks(conn, query, limit)
    except sqlite3.OperationalError:
        quoted = '"' + query.replace('"', '""') + '"'
        return _search_chunks(conn, quoted, limit)


def _search_chunks(conn: sqlite3.Connection, query: str, limit: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.document_id,
            c.chunk_index,
            c.page_start,
            c.page_end,
            c.source_citation,
            snippet(chunks_fts, 0, '[', ']', '...', 24) AS snippet,
            bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE chunks_fts MATCH ?
        ORDER BY score
        LIMIT ?
        """,
        (query, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def export_document(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    document = get_document(conn, document_id)
    chunks = list_chunks(conn, document_id)
    pages = list_pages(conn, document_id)
    return {
        "document": document.model_dump(),
        "pages": [page.model_dump() for page in pages],
        "chunks": [chunk.model_dump() for chunk in chunks],
        "topics": _rows(conn, "topics", document_id),
        "key_terms": _rows(conn, "key_terms", document_id),
        "examples": _rows(conn, "examples", document_id),
        "questions": _rows(conn, "questions", document_id),
    }


def _rows(conn: sqlite3.Connection, table: str, document_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT t.*
        FROM {table} t
        JOIN chunks c ON c.id = t.chunk_id
        WHERE c.document_id = ?
        ORDER BY t.id
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def db_info(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = [
        "documents",
        "pages",
        "chunks",
        "topics",
        "key_terms",
        "examples",
        "questions",
        "extraction_runs",
        "model_outputs",
    ]
    info = {
        table: conn.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"]
        for table in tables
    }
    try:
        conn.execute("SELECT rowid FROM chunks_fts LIMIT 1").fetchone()
        info["fts5_available"] = True
    except sqlite3.OperationalError:
        info["fts5_available"] = False
    return info
