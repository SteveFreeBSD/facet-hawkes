"""Shared SQLite aggregate helpers."""

from __future__ import annotations

import sqlite3


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
