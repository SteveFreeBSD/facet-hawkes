"""Database quality, export, and inventory reports."""

from __future__ import annotations

import sqlite3
from typing import Any

from .db_core import get_document, list_chunks, list_pages, quote_identifier
from .db_counts import _normalized_record_counts
from .db_sections import section_label_status
from .db_structure import list_structure_chunk_status


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
        "chunks_with_no_terms_or_questions": _chunks_with_no_terms_or_questions(
            conn, document_id
        ),
        "non_core_chunks_with_records": _non_core_chunks_with_records(
            conn, document_id
        ),
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
    table_sql = quote_identifier(table)
    rows = conn.execute(
        f"""
        SELECT COALESCE(c.content_role, 'unlabeled') AS content_role, COUNT(*) AS count
        FROM {table_sql} t
        JOIN chunks c ON c.id = t.chunk_id
        WHERE c.document_id = ?
        GROUP BY content_role
        ORDER BY content_role
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _top_repeated_key_terms(
    conn: sqlite3.Connection, document_id: int
) -> list[dict[str, Any]]:
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
        WHERE c.document_id = ? AND COALESCE(c.content_role, 'core') = 'core'
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


def _rows(
    conn: sqlite3.Connection, table: str, document_id: int
) -> list[dict[str, Any]]:
    table_sql = quote_identifier(table)
    rows = conn.execute(
        f"""
        SELECT t.*
        FROM {table_sql} t
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
        "chunk_summaries",
        "topics",
        "key_terms",
        "examples",
        "questions",
        "extraction_runs",
        "model_outputs",
    ]
    info = {
        table: conn.execute(
            f"SELECT COUNT(*) AS count FROM {quote_identifier(table)}"
        ).fetchone()["count"]
        for table in tables
    }
    try:
        conn.execute("SELECT rowid FROM chunks_fts LIMIT 1").fetchone()
        info["fts5_available"] = True
    except sqlite3.OperationalError:
        info["fts5_available"] = False
    return info
