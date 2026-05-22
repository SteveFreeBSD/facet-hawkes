"""Structured model-output persistence and normalization."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .models import ExtractionResult
from .db_core import _is_study_content_role


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
    persist_study_records = _should_persist_study_records(conn, chunk_id)
    with conn:
        _delete_normalized_chunk_records(conn, chunk_id)
        conn.execute(
            """
            INSERT INTO chunk_summaries (chunk_id, summary)
            VALUES (?, ?)
            """,
            (chunk_id, result.chunk_summary),
        )
        if not persist_study_records:
            return
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


def refresh_normalized_records(conn: sqlite3.Connection, document_id: int) -> dict[str, Any]:
    rows = conn.execute(
        """
        WITH latest_valid_outputs AS (
            SELECT c.id AS chunk_id, MAX(mo.id) AS model_output_id
            FROM chunks c
            JOIN model_outputs mo ON mo.chunk_id = c.id
            WHERE c.document_id = ?
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
        "refreshed": 0,
        "skipped_invalid": 0,
        "refreshed_chunks": [],
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
        report["refreshed"] += 1
        report["refreshed_chunks"].append(row["chunk_id"])
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


def _should_persist_study_records(conn: sqlite3.Connection, chunk_id: int) -> bool:
    row = conn.execute("SELECT content_role FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
    if row is None:
        raise ValueError(f"No chunk found with id {chunk_id}")
    return _is_study_content_role(row["content_role"])
