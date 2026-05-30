"""Shared SQLite aggregate helpers."""

from __future__ import annotations

import sqlite3

from .db_core import quote_identifier


def _normalized_record_counts(
    conn: sqlite3.Connection, document_id: int
) -> dict[str, int]:
    counts = {}
    for table in ["chunk_summaries", "topics", "key_terms", "examples", "questions"]:
        table_sql = quote_identifier(table)
        counts[table] = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table_sql} t
            JOIN chunks c ON c.id = t.chunk_id
            WHERE c.document_id = ?
            """,
            (document_id,),
        ).fetchone()["count"]
    return counts
