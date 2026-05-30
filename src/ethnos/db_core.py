"""SQLite connection, schema, and core document/chunk persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import ChunkRecord, DocumentRecord, PageRecord

SQL_IDENTIFIERS = {
    "chunk_index",
    "chunk_summaries",
    "chunks",
    "content_role",
    "documents",
    "examples",
    "extraction_runs",
    "agent_findings",
    "agent_runs",
    "id",
    "key_terms",
    "model_outputs",
    "page_number",
    "pages",
    "questions",
    "section_confidence",
    "section_label",
    "topics",
}

SQL_COLUMN_DEFINITIONS = {"TEXT", "REAL", "INTEGER"}


def quote_identifier(identifier: str) -> str:
    if identifier not in SQL_IDENTIFIERS:
        raise ValueError(f"Unsafe SQL identifier: {identifier!r}")
    return f'"{identifier}"'


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA cache_size=-32000")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA mmap_size=134217728")
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
            section_label TEXT,
            content_role TEXT,
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
            section_label TEXT,
            content_role TEXT,
            section_confidence REAL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(document_id, chunk_index)
        );

        CREATE TABLE IF NOT EXISTS chunk_summaries (
            id INTEGER PRIMARY KEY,
            chunk_id INTEGER NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
            summary TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(chunk_id)
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

        CREATE TABLE IF NOT EXISTS agent_runs (
            id INTEGER PRIMARY KEY,
            document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
            quiz_path TEXT NOT NULL,
            model_name TEXT NOT NULL,
            model_profile TEXT NOT NULL,
            config_json TEXT NOT NULL DEFAULT '{}',
            started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            finished_at TEXT,
            status TEXT NOT NULL,
            output_path TEXT NOT NULL,
            summary_json TEXT NOT NULL DEFAULT '{}',
            error_message TEXT
        );

        CREATE TABLE IF NOT EXISTS agent_findings (
            id INTEGER PRIMARY KEY,
            run_id INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
            quiz_item_id TEXT NOT NULL,
            verdict TEXT NOT NULL,
            severity TEXT NOT NULL,
            finding_type TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            result_json TEXT NOT NULL DEFAULT '{}',
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
    _ensure_column(conn, "pages", "section_label", "TEXT")
    _ensure_column(conn, "pages", "content_role", "TEXT")
    _ensure_column(conn, "chunks", "section_label", "TEXT")
    _ensure_column(conn, "chunks", "content_role", "TEXT")
    _ensure_column(conn, "chunks", "section_confidence", "REAL")


def _ensure_column(
    conn: sqlite3.Connection, table: str, column: str, column_definition: str
) -> None:
    table_sql = quote_identifier(table)
    column_sql = quote_identifier(column)
    if column_definition not in SQL_COLUMN_DEFINITIONS:
        raise ValueError(f"Unsafe SQL column definition: {column_definition!r}")
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table_sql})")}
    if column not in columns:
        conn.execute(
            f"ALTER TABLE {table_sql} ADD COLUMN {column_sql} {column_definition}"
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
    row = conn.execute(
        "SELECT * FROM documents WHERE id = ?", (document_id,)
    ).fetchone()
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
        "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index",
        (document_id,),
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


def _chunk_from_status_row(row: dict[str, Any]) -> ChunkRecord:
    return ChunkRecord(
        id=row["chunk_id"],
        document_id=row["document_id"],
        page_start=row["page_start"],
        page_end=row["page_end"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        heading=row["heading"],
        char_count=row["char_count"],
        source_citation=row["source_citation"],
    )


def save_chunks(
    conn: sqlite3.Connection, document_id: int, chunks: list[ChunkRecord]
) -> None:
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


def _is_study_content_role(content_role: str | None) -> bool:
    return content_role in (None, "", "core")


def clear_document_outputs(conn: sqlite3.Connection, document_id: int) -> None:
    conn.execute("DELETE FROM extraction_runs WHERE document_id = ?", (document_id,))
