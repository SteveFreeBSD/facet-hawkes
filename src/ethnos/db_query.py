"""Inspection, full-text search, and retrieval context queries."""

from __future__ import annotations

import sqlite3
from typing import Any


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
    include_text: bool = False,
) -> list[dict[str, Any]]:
    try:
        return _search_chunks(
            conn,
            query,
            limit,
            document_id=document_id,
            role=role,
            section=section,
            include_text=include_text,
        )
    except sqlite3.OperationalError:
        quoted = '"' + query.replace('"', '""') + '"'
        return _search_chunks(
            conn,
            quoted,
            limit,
            document_id=document_id,
            role=role,
            section=section,
            include_text=include_text,
        )


def _search_chunks(
    conn: sqlite3.Connection,
    query: str,
    limit: int,
    *,
    document_id: int | None,
    role: str | None,
    section: str | None,
    include_text: bool,
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
    text_select = ",\n            c.text" if include_text else ""
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
            {text_select}
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
        include_text=True,
    )
    if not results:
        return []
    if all("text" in row for row in results):
        return results
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
