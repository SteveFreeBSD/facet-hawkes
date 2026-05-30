"""Shared retrieval helpers for CLI answer commands."""

from __future__ import annotations

import sqlite3

from ..db import add_continuation_context_chunks, context_chunks
from ..qa import retrieve_with_fallbacks


def retrieve_answer_context(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    question: str,
    limit: int,
    role: str | None,
    section: str | None,
):
    return retrieve_with_fallbacks(
        search_func=lambda doc_id, query, limit, role, section: (
            add_continuation_context_chunks(
                conn,
                doc_id,
                context_chunks(
                    conn, doc_id, query, limit=limit, role=role, section=section
                ),
                role=role,
                section=section,
            )
        ),
        document_id=document_id,
        question=question,
        limit=limit,
        role=role,
        section=section,
    )
