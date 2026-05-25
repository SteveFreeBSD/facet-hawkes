"""Section-label persistence and reporting."""

from __future__ import annotations

import sqlite3
from typing import Any

from .db_core import quote_identifier
from .section_presets import SectionPreset


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
    table_sql = quote_identifier(table)
    number_column_sql = quote_identifier(number_column)
    counts: dict[tuple[str, str], int] = {}
    for section_range in ranges:
        count = conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table_sql}
            WHERE document_id = ? AND {number_column_sql} BETWEEN ? AND ?
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
    table_sql = quote_identifier(table)
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(section_label, 'unlabeled') AS section_label,
            COALESCE(content_role, 'unlabeled') AS content_role,
            COUNT(*) AS count
        FROM {table_sql}
        WHERE document_id = ?
        GROUP BY section_label, content_role
        ORDER BY section_label, content_role
        """,
        (document_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def _unlabeled_count(conn: sqlite3.Connection, table: str, document_id: int) -> int:
    table_sql = quote_identifier(table)
    return int(
        conn.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM {table_sql}
            WHERE document_id = ? AND (section_label IS NULL OR content_role IS NULL)
            """,
            (document_id,),
        ).fetchone()["count"]
    )
