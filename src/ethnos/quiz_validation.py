"""Validation helpers for imported and generated quiz items."""

from __future__ import annotations

import re
import sqlite3
from typing import Any

from .text_utils import normalize_match_text, normalized_phrase_found


CHOICE_TYPES = {"multiple_choice", "true_false"}
QUIZ_TYPES = {"multiple_choice", "true_false", "matching", "essay"}
INCOMPLETE_ITEM_WARNINGS = {"incomplete_item", "incomplete_matching_item"}


def is_incomplete_item(item: dict[str, object]) -> bool:
    warnings = item.get("warnings")
    return isinstance(warnings, list) and bool(
        INCOMPLETE_ITEM_WARNINGS.intersection(warnings)
    )


def source_retrieval_exclusion_reason(item: dict[str, object]) -> str | None:
    warnings = item.get("warnings")
    if not isinstance(warnings, list):
        return None
    if "external_source_item" in warnings:
        return "declared_source_missing"
    if INCOMPLETE_ITEM_WARNINGS.intersection(str(warning) for warning in warnings):
        return "declared_incomplete"
    return None


def anchored_source_context_rows(
    conn: sqlite3.Connection,
    document_id: int,
    item: dict[str, object],
) -> list[dict[str, Any]]:
    raw_chunk_ids = item.get("source_chunks")
    if not isinstance(raw_chunk_ids, list):
        return []
    chunk_ids: list[int] = []
    for chunk_id in raw_chunk_ids:
        try:
            normalized = int(chunk_id)
        except (TypeError, ValueError):
            continue
        if normalized not in chunk_ids:
            chunk_ids.append(normalized)
    if not chunk_ids:
        return []
    rows = conn.execute(
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
        WHERE id IN ({", ".join("?" for _ in chunk_ids)})
          AND document_id = ?
        """,
        [*chunk_ids, document_id],
    ).fetchall()
    by_id = {int(row["id"]): dict(row) for row in rows}
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


def validate_mc_quiz_item(
    conn: sqlite3.Connection,
    document_id: int,
    item: dict[str, object],
    *,
    require_anchors: bool,
) -> list[str]:
    return validate_quiz_item(
        conn,
        document_id,
        item,
        require_anchors=require_anchors,
        strict_complete=False,
        require_key=True,
        allowed_types=CHOICE_TYPES,
    )


def validate_quiz_item(
    conn: sqlite3.Connection,
    document_id: int,
    item: dict[str, object],
    *,
    require_anchors: bool,
    strict_complete: bool,
    require_key: bool,
    allowed_types: set[str] | None = None,
) -> list[str]:
    errors = []
    if require_key and "correct" not in item:
        errors.append("missing correct answer")
    key_review_status = item.get("key_review_status")
    if key_review_status not in {None, "confirmed", "disputed"}:
        errors.append("key_review_status must be confirmed or disputed")
    if key_review_status == "disputed" and "correct" not in item:
        errors.append("disputed keys must include a correct answer")
    question_type = str(item.get("question_type") or "multiple_choice")
    allowed = allowed_types or QUIZ_TYPES
    if question_type not in allowed:
        errors.append("question_type must be " + " or ".join(sorted(allowed)))
    if question_type == "true_false" and not is_true_false_item_options(
        item.get("options")
    ):
        errors.append("true_false items must use exactly A=True and B=False")
    if question_type == "multiple_choice":
        options = item.get("options")
        if not isinstance(options, dict) or len(options) < 2:
            errors.append("multiple_choice items must include at least 2 options")
        if _looks_like_unsupported_multiple_response(str(item.get("question") or "")):
            errors.append(
                "multiple-response choice items are not supported; "
                "split the item or add explicit schema support"
            )
    if question_type == "matching":
        prompts = item.get("matching_prompts")
        if not isinstance(prompts, list) or not prompts:
            errors.append("matching items must include matching_prompts")
    if strict_complete and is_incomplete_item(item):
        errors.append(
            "incomplete matching item"
            if "incomplete_matching_item" in item.get("warnings", [])
            else "incomplete item"
        )
    if strict_complete:
        for warning in item.get("warnings", []):
            if warning not in INCOMPLETE_ITEM_WARNINGS:
                errors.append(f"import warning: {warning}")

    errors.extend(
        _anchor_errors(conn, document_id, item, require_anchors=require_anchors)
    )
    return errors


def _looks_like_unsupported_multiple_response(question: str) -> bool:
    return bool(
        re.search(
            r"\b(?:select|choose|pick)\s+(?:all(?:\s+that\s+apply)?|"
            r"(?:the\s+)?(?:two|three|2|3))\b",
            question,
            flags=re.IGNORECASE,
        )
    )


def normalize_review_text(value: str) -> str:
    return normalize_match_text(value)


def target_text_found(target: str, source_text: str) -> bool:
    if not normalize_review_text(target):
        return True
    if normalized_phrase_found(target, source_text):
        return True
    if "/" not in target:
        return False
    parts = [part for part in target.split("/") if part.strip()]
    return bool(parts) and all(target_text_found(part, source_text) for part in parts)


def is_true_false_item_options(options: object) -> bool:
    return (
        isinstance(options, dict)
        and tuple(options) == ("A", "B")
        and normalize_review_text(str(options["A"])) == "true"
        and normalize_review_text(str(options["B"])) == "false"
    )


def _anchor_errors(
    conn: sqlite3.Connection,
    document_id: int,
    item: dict[str, Any],
    *,
    require_anchors: bool,
) -> list[str]:
    errors: list[str] = []
    anchor_fields = ("target", "source_chunks", "source_pages", "source_citation")
    anchor_exempt = source_retrieval_exclusion_reason(item) is not None
    if require_anchors and not anchor_exempt:
        for field in anchor_fields:
            if not item.get(field):
                errors.append(f"missing {field}")

    chunk_ids = item.get("source_chunks") or []
    if not isinstance(chunk_ids, list):
        errors.append("source_chunks must be a list")
        chunk_ids = []
    chunk_rows = []
    for chunk_id in chunk_ids:
        if isinstance(chunk_id, bool) or not isinstance(chunk_id, int) or chunk_id < 1:
            if "source_chunks must contain positive integers" not in errors:
                errors.append("source_chunks must contain positive integers")
            continue
        row = conn.execute(
            """
            SELECT id, page_start, page_end, source_citation, text
            FROM chunks
            WHERE id = ? AND document_id = ?
            """,
            (chunk_id, document_id),
        ).fetchone()
        if row is None:
            errors.append(
                f"source chunk {chunk_id} not found for document {document_id}"
            )
        else:
            chunk_rows.append(row)

    source_pages = item.get("source_pages")
    normalized_pages: list[int] = []
    if source_pages is not None and not isinstance(source_pages, list):
        errors.append("source_pages must be a list")
    elif isinstance(source_pages, list):
        for page in source_pages:
            if isinstance(page, bool) or not isinstance(page, int) or page < 1:
                errors.append("source_pages must contain positive integers")
                break
            if page not in normalized_pages:
                normalized_pages.append(page)
    if normalized_pages and chunk_rows:
        covered_pages = {
            page
            for row in chunk_rows
            for page in range(int(row["page_start"]), int(row["page_end"]) + 1)
        }
        outside_pages = [page for page in normalized_pages if page not in covered_pages]
        if outside_pages:
            errors.append(
                "source_pages contains pages outside source_chunks: "
                + ", ".join(str(page) for page in outside_pages)
            )

    target = str(item.get("target") or "").strip()
    if target and chunk_rows:
        source_text = " ".join(row["text"] for row in chunk_rows)
        if not target_text_found(
            target, source_text
        ) and not _source_record_matches_anchor(
            conn,
            document_id,
            item,
            chunk_ids,
            target,
        ):
            errors.append("target phrase not found in source_chunks text")
    source_citation = str(item.get("source_citation") or "").strip()
    if source_citation and chunk_rows:
        citations = {str(row["source_citation"]) for row in chunk_rows}
        if source_citation not in citations:
            errors.append("source_citation does not match any source_chunks citation")
    return errors


def _source_record_matches_anchor(
    conn: sqlite3.Connection,
    document_id: int,
    item: dict[str, Any],
    chunk_ids: list[object],
    target: str,
) -> bool:
    source_record_type = str(item.get("source_record_type") or "").strip()
    if source_record_type != "key_terms":
        return False
    try:
        source_record_id = int(item.get("source_record_id"))
        normalized_chunk_ids = {int(chunk_id) for chunk_id in chunk_ids}
    except (TypeError, ValueError):
        return False
    if not normalized_chunk_ids:
        return False
    row = conn.execute(
        """
        SELECT kt.chunk_id, kt.term
        FROM key_terms kt
        JOIN chunks c ON c.id = kt.chunk_id
        WHERE kt.id = ? AND c.document_id = ?
        """,
        (source_record_id, document_id),
    ).fetchone()
    if row is None or int(row["chunk_id"]) not in normalized_chunk_ids:
        return False
    term = str(row["term"] or "")
    return normalize_review_text(target) == normalize_review_text(term)
