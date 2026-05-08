"""SQLite storage for documents, pages, chunks, and structured outputs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import ChunkRecord, DocumentRecord, ExtractionResult, PageRecord
from .section_presets import SectionPreset


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
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_definition}")


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
    retry_failed: bool = False,
    force: bool = False,
) -> list[ChunkRecord]:
    status_rows = list_structure_chunk_status(conn, document_id)
    selected = []
    for row in status_rows:
        if chunk_id is not None and row["chunk_id"] != chunk_id:
            continue
        if force:
            selected.append(row)
        elif row["has_valid_output"]:
            continue
        elif retry_failed:
            if row["latest_status"] is not None and row["latest_status"] != "valid":
                selected.append(row)
        elif row["latest_status"] is None:
            selected.append(row)

    if limit is not None:
        selected = selected[:limit]
    return [_chunk_from_status_row(row) for row in selected]


def list_structure_chunk_status(conn: sqlite3.Connection, document_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        WITH latest_output AS (
            SELECT mo.*
            FROM model_outputs mo
            JOIN (
                SELECT chunk_id, MAX(id) AS latest_id
                FROM model_outputs
                GROUP BY chunk_id
            ) latest ON latest.latest_id = mo.id
        ),
        valid_outputs AS (
            SELECT DISTINCT chunk_id
            FROM model_outputs
            WHERE validation_status = 'valid'
        )
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.page_start,
            c.page_end,
            c.chunk_index,
            c.text,
            c.heading,
            c.char_count,
            c.source_citation,
            CASE WHEN vo.chunk_id IS NULL THEN 0 ELSE 1 END AS has_valid_output,
            lo.validation_status AS latest_status,
            lo.validation_error AS latest_error,
            lo.created_at AS latest_created_at,
            lo.id AS latest_model_output_id
        FROM chunks c
        LEFT JOIN latest_output lo ON lo.chunk_id = c.id
        LEFT JOIN valid_outputs vo ON vo.chunk_id = c.id
        WHERE c.document_id = ?
        ORDER BY c.chunk_index
        """,
        (document_id,),
    ).fetchall()
    return [
        {
            **dict(row),
            "has_valid_output": bool(row["has_valid_output"]),
        }
        for row in rows
    ]


def structure_status(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    rows = list_structure_chunk_status(conn, document_id)
    latest_failed = [
        row for row in rows if row["latest_status"] is not None and row["latest_status"] != "valid"
    ]
    never_attempted = [row for row in rows if row["latest_status"] is None]
    valid_outputs = [row for row in rows if row["has_valid_output"]]
    counts = _normalized_record_counts(conn, document_id)
    return {
        "document_id": document_id,
        "total_chunks": len(rows),
        "chunks_with_valid_output": len(valid_outputs),
        "chunks_latest_failed": len(latest_failed),
        "chunks_never_attempted": len(never_attempted),
        "chunk_summaries": counts["chunk_summaries"],
        "topics": counts["topics"],
        "key_terms": counts["key_terms"],
        "examples": counts["examples"],
        "questions": counts["questions"],
        "latest_failed_chunks": latest_failed,
        "never_attempted_chunks": never_attempted,
    }


def apply_section_preset(
    conn: sqlite3.Connection, document_id: int, preset: SectionPreset, dry_run: bool = False
) -> dict[str, Any]:
    page_counts = _count_section_ranges(
        conn,
        table="pages",
        document_id=document_id,
        number_column="page_number",
        ranges=preset.page_ranges,
    )
    chunk_counts = _count_section_ranges(
        conn,
        table="chunks",
        document_id=document_id,
        number_column="chunk_index",
        ranges=preset.chunk_ranges,
    )
    if not dry_run:
        with conn:
            for section_range in preset.page_ranges:
                conn.execute(
                    """
                    UPDATE pages
                    SET section_label = ?, content_role = ?
                    WHERE document_id = ? AND page_number BETWEEN ? AND ?
                    """,
                    (
                        section_range.section_label,
                        section_range.content_role,
                        document_id,
                        section_range.start,
                        section_range.end,
                    ),
                )
            for section_range in preset.chunk_ranges:
                conn.execute(
                    """
                    UPDATE chunks
                    SET section_label = ?, content_role = ?, section_confidence = ?
                    WHERE document_id = ? AND chunk_index BETWEEN ? AND ?
                    """,
                    (
                        section_range.section_label,
                        section_range.content_role,
                        section_range.confidence,
                        document_id,
                        section_range.start,
                        section_range.end,
                    ),
                )
    return {
        "document_id": document_id,
        "preset": preset.name,
        "dry_run": dry_run,
        "pages": page_counts,
        "chunks": chunk_counts,
    }


def section_label_status(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "pages": _section_status_rows(conn, "pages", document_id),
        "chunks": _section_status_rows(conn, "chunks", document_id),
        "unlabeled_pages": _unlabeled_count(conn, "pages", document_id),
        "unlabeled_chunks": _unlabeled_count(conn, "chunks", document_id),
    }


def _count_section_ranges(
    conn: sqlite3.Connection,
    table: str,
    document_id: int,
    number_column: str,
    ranges,
) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for section_range in ranges:
        count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table}
            WHERE document_id = ? AND {number_column} BETWEEN ? AND ?
            """,
            (document_id, section_range.start, section_range.end),
        ).fetchone()["count"]
        if count:
            key = (section_range.section_label, section_range.content_role)
            counts[key] = counts.get(key, 0) + int(count)
    return [
        {"section_label": label, "content_role": role, "count": count}
        for (label, role), count in sorted(counts.items())
    ]


def _section_status_rows(
    conn: sqlite3.Connection, table: str, document_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(section_label, 'unlabeled') AS section_label,
            COALESCE(content_role, 'unlabeled') AS content_role,
            COUNT(*) AS count
        FROM {table}
        WHERE document_id = ?
        GROUP BY section_label, content_role
        ORDER BY section_label, content_role
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _unlabeled_count(conn: sqlite3.Connection, table: str, document_id: int) -> int:
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table}
            WHERE document_id = ? AND (section_label IS NULL OR content_role IS NULL)
            """,
            (document_id,),
        ).fetchone()["count"]
    )


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
        _delete_normalized_chunk_records(conn, chunk_id)
        conn.execute(
            """
            INSERT INTO chunk_summaries (chunk_id, summary)
            VALUES (?, ?)
            """,
            (chunk_id, result.chunk_summary),
        )
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


def backfill_chunk_summaries(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        WITH latest_valid_outputs AS (
            SELECT c.id AS chunk_id, MAX(mo.id) AS model_output_id
            FROM chunks c
            JOIN model_outputs mo ON mo.chunk_id = c.id
            LEFT JOIN chunk_summaries cs ON cs.chunk_id = c.id
            WHERE c.document_id = ?
              AND cs.id IS NULL
              AND mo.validation_status = 'valid'
              AND mo.parsed_json IS NOT NULL
            GROUP BY c.id
        )
        SELECT lvo.chunk_id, lvo.model_output_id, mo.parsed_json
        FROM latest_valid_outputs lvo
        JOIN model_outputs mo ON mo.id = lvo.model_output_id
        ORDER BY lvo.chunk_id
        """,
        (document_id,),
    ).fetchall()
    report: dict[str, Any] = {
        "document_id": document_id,
        "candidates": len(rows),
        "backfilled": 0,
        "skipped_invalid": 0,
        "backfilled_chunks": [],
        "errors": [],
    }
    for row in rows:
        try:
            parsed = json.loads(row["parsed_json"])
            result = ExtractionResult.model_validate(parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            report["skipped_invalid"] += 1
            report["errors"].append(
                {
                    "chunk_id": row["chunk_id"],
                    "model_output_id": row["model_output_id"],
                    "error": str(exc),
                }
            )
            continue
        save_extraction_result(conn, row["chunk_id"], result)
        report["backfilled"] += 1
        report["backfilled_chunks"].append(row["chunk_id"])
    return report


def _delete_normalized_chunk_records(conn: sqlite3.Connection, chunk_id: int) -> None:
    conn.execute("DELETE FROM chunk_summaries WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM topics WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM key_terms WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM examples WHERE chunk_id = ?", (chunk_id,))
    conn.execute("DELETE FROM questions WHERE chunk_id = ?", (chunk_id,))


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


def inspect_page(
    conn: sqlite3.Connection, document_id: int, page_number: int
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            d.filename,
            p.*
        FROM pages p
        JOIN documents d ON d.id = p.document_id
        WHERE p.document_id = ? AND p.page_number = ?
        """,
        (document_id, page_number),
    ).fetchone()
    if row is None:
        raise ValueError(f"No page {page_number} found for document {document_id}")
    return dict(row)


def inspect_chunk(
    conn: sqlite3.Connection, document_id: int, chunk_id: int
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            d.filename,
            c.*
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.document_id = ? AND c.id = ?
        """,
        (document_id, chunk_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"No chunk {chunk_id} found for document {document_id}")
    counts = {}
    for table in ["chunk_summaries", "key_terms", "questions", "topics", "examples"]:
        counts[table] = conn.execute(
            f"SELECT COUNT(*) AS count FROM {table} WHERE chunk_id = ?", (chunk_id,)
        ).fetchone()["count"]
    return {"chunk": dict(row), "counts": counts}


def chunk_records(conn: sqlite3.Connection, chunk_id: int) -> dict[str, list[dict[str, Any]]]:
    return {
        "chunk_summaries": _chunk_table_rows(conn, "chunk_summaries", chunk_id),
        "key_terms": _chunk_table_rows(conn, "key_terms", chunk_id),
        "questions": _chunk_table_rows(conn, "questions", chunk_id),
        "topics": _chunk_table_rows(conn, "topics", chunk_id),
        "examples": _chunk_table_rows(conn, "examples", chunk_id),
    }


def _chunk_table_rows(conn: sqlite3.Connection, table: str, chunk_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT *
        FROM {table}
        WHERE chunk_id = ?
        ORDER BY id
        """,
        (chunk_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def search_chunks(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 10,
    *,
    document_id: int | None = None,
    role: str | None = None,
    section: str | None = None,
) -> list[dict[str, Any]]:
    try:
        return _search_chunks(conn, query, limit, document_id=document_id, role=role, section=section)
    except sqlite3.OperationalError:
        quoted = '"' + query.replace('"', '""') + '"'
        return _search_chunks(conn, quoted, limit, document_id=document_id, role=role, section=section)


def _search_chunks(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    *,
    document_id: int | None,
    role: str | None,
    section: str | None,
) -> list[dict[str, Any]]:
    filters = ["chunks_fts MATCH ?"]
    params: list[Any] = [query]
    if document_id is not None:
        filters.append("c.document_id = ?")
        params.append(document_id)
    if role is not None:
        filters.append("c.content_role = ?")
        params.append(role)
    if section is not None:
        filters.append("c.section_label = ?")
        params.append(section)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.document_id,
            c.chunk_index,
            c.page_start,
            c.page_end,
            c.source_citation,
            c.section_label,
            c.content_role,
            snippet(chunks_fts, 0, '[', ']', '...', 24) AS snippet,
            bm25(chunks_fts) AS score
        FROM chunks_fts
        JOIN chunks c ON c.id = chunks_fts.rowid
        WHERE {" AND ".join(filters)}
        ORDER BY score
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def list_structured_records(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    record_type: str = "all",
    role: str | None = None,
    section: str | None = None,
    chunk_id: int | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    tables = ["chunk_summaries", "key_terms", "questions", "topics", "examples"]
    selected_tables = tables if record_type == "all" else [record_type]
    records: list[dict[str, Any]] = []
    for table in selected_tables:
        records.extend(
            _structured_rows_for_table(
                conn,
                document_id,
                table,
                role=role,
                section=section,
                chunk_id=chunk_id,
            )
        )
    records.sort(key=lambda row: (row["chunk_index"], row["record_type"], row["id"]))
    if limit is not None:
        return records[:limit]
    return records


def _structured_rows_for_table(
    conn: sqlite3.Connection,
    document_id: int,
    table: str,
    *,
    role: str | None,
    section: str | None,
    chunk_id: int | None,
) -> list[dict[str, Any]]:
    filters = ["c.document_id = ?"]
    params: list[Any] = [document_id]
    if role is not None:
        filters.append("c.content_role = ?")
        params.append(role)
    if section is not None:
        filters.append("c.section_label = ?")
        params.append(section)
    if chunk_id is not None:
        filters.append("c.id = ?")
        params.append(chunk_id)
    rows = conn.execute(
        f"""
        SELECT
            t.*,
            c.document_id,
            c.chunk_index,
            c.source_citation,
            c.section_label,
            c.content_role
        FROM {table} t
        JOIN chunks c ON c.id = t.chunk_id
        WHERE {" AND ".join(filters)}
        ORDER BY c.chunk_index, t.id
        """,
        params,
    ).fetchall()
    return [{"record_type": table, **dict(row)} for row in rows]


def context_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    query: str,
    *,
    limit: int = 5,
    role: str | None = "core",
    section: str | None = None,
) -> list[dict[str, Any]]:
    results = search_chunks(
        conn,
        query,
        limit,
        document_id=document_id,
        role=role,
        section=section,
    )
    if not results:
        return []
    chunk_ids = [row["id"] for row in results]
    placeholders = ", ".join("?" for _ in chunk_ids)
    text_rows = conn.execute(
        f"SELECT id, text FROM chunks WHERE id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    text_by_id = {row["id"]: row["text"] for row in text_rows}
    return [{**row, "text": text_by_id.get(row["id"], "")} for row in results]


def add_continuation_context_chunks(
    conn: sqlite3.Connection,
    document_id: int,
    rows: list[dict[str, Any]],
    *,
    role: str | None = "core",
    section: str | None = None,
) -> list[dict[str, Any]]:
    """Add the next chunk when a selected chunk visibly cuts off mid-sentence."""
    if not rows:
        return rows
    expanded: list[dict[str, Any]] = []
    seen_ids = set()
    for row in rows:
        _append_context_row(expanded, seen_ids, row)
        if _looks_like_incomplete_chunk(row.get("text", "")):
            continuation = _next_context_chunk(
                conn,
                document_id,
                int(row["chunk_index"]) + 1,
                role=role,
                section=section,
            )
            if continuation is not None:
                _append_context_row(expanded, seen_ids, continuation)
    return expanded


def _append_context_row(
    rows: list[dict[str, Any]], seen_ids: set[int], row: dict[str, Any]
) -> None:
    chunk_id = int(row["id"])
    if chunk_id in seen_ids:
        return
    seen_ids.add(chunk_id)
    rows.append(row)


def _looks_like_incomplete_chunk(text: str) -> bool:
    stripped = text.rstrip()
    if not stripped:
        return False
    return stripped[-1] not in ".?!)]}\"'"


def _next_context_chunk(
    conn: sqlite3.Connection,
    document_id: int,
    chunk_index: int,
    *,
    role: str | None,
    section: str | None,
) -> dict[str, Any] | None:
    filters = ["document_id = ?", "chunk_index = ?"]
    params: list[Any] = [document_id, chunk_index]
    if role is not None:
        filters.append("content_role = ?")
        params.append(role)
    if section is not None:
        filters.append("section_label = ?")
        params.append(section)
    row = conn.execute(
        f"""
        SELECT
            id,
            document_id,
            chunk_index,
            page_start,
            page_end,
            source_citation,
            section_label,
            content_role,
            '' AS snippet,
            0.0 AS score,
            text
        FROM chunks
        WHERE {" AND ".join(filters)}
        """,
        params,
    ).fetchone()
    return dict(row) if row is not None else None


def quality_report(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    status = section_label_status(conn, document_id)
    latest_rows = list_structure_chunk_status(conn, document_id)
    record_counts = _normalized_record_counts(conn, document_id)
    return {
        "document_id": document_id,
        "sections": status,
        "model_output_status_counts": _model_output_status_counts(conn, document_id),
        "latest_output_status_counts": _latest_output_status_counts(latest_rows),
        "key_terms_by_role": _normalized_count_by_role(conn, "key_terms", document_id),
        "questions_by_role": _normalized_count_by_role(conn, "questions", document_id),
        "top_repeated_key_terms": _top_repeated_key_terms(conn, document_id),
        "chunks_with_no_terms_or_questions": _chunks_with_no_terms_or_questions(conn, document_id),
        "non_core_chunks_with_records": _non_core_chunks_with_records(conn, document_id),
        "chunk_summaries": record_counts["chunk_summaries"],
        "topics": record_counts["topics"],
        "examples": record_counts["examples"],
    }


def _model_output_status_counts(
    conn: sqlite3.Connection, document_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT mo.validation_status, COUNT(*) AS count
        FROM model_outputs mo
        JOIN chunks c ON c.id = mo.chunk_id
        WHERE c.document_id = ?
        GROUP BY mo.validation_status
        ORDER BY mo.validation_status
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _latest_output_status_counts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in rows:
        status = row["latest_status"] or "never_attempted"
        counts[status] = counts.get(status, 0) + 1
    return [
        {"validation_status": status, "count": count}
        for status, count in sorted(counts.items())
    ]


def _normalized_count_by_role(
    conn: sqlite3.Connection, table: str, document_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        f"""
        SELECT COALESCE(c.content_role, 'unlabeled') AS content_role, COUNT(*) AS count
        FROM {table} t
        JOIN chunks c ON c.id = t.chunk_id
        WHERE c.document_id = ?
        GROUP BY content_role
        ORDER BY content_role
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _top_repeated_key_terms(conn: sqlite3.Connection, document_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT LOWER(TRIM(kt.term)) AS term, COUNT(*) AS count
        FROM key_terms kt
        JOIN chunks c ON c.id = kt.chunk_id
        WHERE c.document_id = ?
        GROUP BY LOWER(TRIM(kt.term))
        HAVING COUNT(*) > 1
        ORDER BY count DESC, term
        LIMIT 10
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _chunks_with_no_terms_or_questions(
    conn: sqlite3.Connection, document_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.chunk_index,
            c.source_citation,
            c.section_label,
            c.content_role
        FROM chunks c
        LEFT JOIN key_terms kt ON kt.chunk_id = c.id
        LEFT JOIN questions q ON q.chunk_id = c.id
        WHERE c.document_id = ?
        GROUP BY c.id
        HAVING COUNT(DISTINCT kt.id) = 0 AND COUNT(DISTINCT q.id) = 0
        ORDER BY c.chunk_index
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _non_core_chunks_with_records(
    conn: sqlite3.Connection, document_id: int
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            c.id,
            c.chunk_index,
            c.source_citation,
            c.section_label,
            c.content_role,
            COUNT(DISTINCT kt.id) AS key_terms,
            COUNT(DISTINCT q.id) AS questions
        FROM chunks c
        LEFT JOIN key_terms kt ON kt.chunk_id = c.id
        LEFT JOIN questions q ON q.chunk_id = c.id
        WHERE c.document_id = ? AND COALESCE(c.content_role, 'unknown') != 'core'
        GROUP BY c.id
        HAVING COUNT(DISTINCT kt.id) > 0 OR COUNT(DISTINCT q.id) > 0
        ORDER BY c.chunk_index
        """,
        (document_id,),
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
        "chunk_summaries": _rows(conn, "chunk_summaries", document_id),
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


def _normalized_record_counts(conn: sqlite3.Connection, document_id: int) -> dict[str, int]:
    counts = {}
    for table in ["chunk_summaries", "topics", "key_terms", "examples", "questions"]:
        counts[table] = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table} t
            JOIN chunks c ON c.id = t.chunk_id
            WHERE c.document_id = ?
            """,
            (document_id,),
        ).fetchone()["count"]
    return counts


def db_info(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = [
        "documents",
        "pages",
        "chunks",
        "chunk_summaries",
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
