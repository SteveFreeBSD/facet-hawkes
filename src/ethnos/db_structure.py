"""Structured extraction status queries."""

from __future__ import annotations

import sqlite3
from typing import Any

from .models import ChunkRecord
from .db_core import _chunk_from_status_row, _is_study_content_role
from .db_counts import _normalized_record_counts


def select_chunks_for_structure(
    conn: sqlite3.Connection,
    document_id: int,
    chunk_id: int | None = None,
    limit: int | None = None,
    retry_failed: bool = False,
    force: bool = False,
    all_roles: bool = False,
) -> list[ChunkRecord]:
    status_rows = list_structure_chunk_status(conn, document_id)
    selected = []
    for row in status_rows:
        if chunk_id is not None and row["chunk_id"] != chunk_id:
            continue
        if not all_roles and not _is_study_content_role(row["content_role"]):
            continue
        if force:
            selected.append(row)
        elif retry_failed:
            if row["latest_status"] is not None and row["latest_status"] != "valid":
                selected.append(row)
        elif row["has_valid_output"]:
            continue
        elif row["latest_status"] is None:
            selected.append(row)

    if limit is not None:
        selected = selected[:limit]
    return [_chunk_from_status_row(row) for row in selected]


def list_structure_chunk_status(
    conn: sqlite3.Connection, document_id: int
) -> list[dict[str, Any]]:
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
            c.content_role,
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
        row
        for row in rows
        if row["latest_status"] is not None and row["latest_status"] != "valid"
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
