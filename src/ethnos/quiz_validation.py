"""Validation helpers for imported and generated quiz items."""

from __future__ import annotations

import re
import sqlite3
from typing import Any


CHOICE_TYPES = {"multiple_choice", "true_false"}
QUIZ_TYPES = {"multiple_choice", "true_false", "matching", "essay"}
INCOMPLETE_ITEM_WARNINGS = {"incomplete_item", "incomplete_matching_item"}


def is_incomplete_item(item: dict[str, object]) -> bool:
    warnings = item.get("warnings")
    return isinstance(warnings, list) and bool(
        INCOMPLETE_ITEM_WARNINGS.intersection(warnings)
    )


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
    return " ".join(value.lower().replace("-", " ").split())


def target_text_found(target: str, source_text: str) -> bool:
    normalized_target = normalize_review_text(target)
    normalized_source = normalize_review_text(source_text)
    if not normalized_target:
        return True
    if normalized_target in normalized_source:
        return True
    if "/" not in target:
        return False
    parts = [
        normalize_review_text(part)
        for part in target.split("/")
        if normalize_review_text(part)
    ]
    return bool(parts) and all(part in normalized_source for part in parts)


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
    warnings = item.get("warnings")
    anchor_exempt = isinstance(warnings, list) and bool(
        {"external_source_item", *INCOMPLETE_ITEM_WARNINGS}.intersection(warnings)
    )
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
        row = conn.execute(
            """
            SELECT id, source_citation, text
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

    target = str(item.get("target") or "").strip()
    if target and chunk_rows:
        source_text = normalize_review_text(" ".join(row["text"] for row in chunk_rows))
        if not target_text_found(target, source_text):
            errors.append("target phrase not found in source_chunks text")
    source_citation = str(item.get("source_citation") or "").strip()
    if source_citation and chunk_rows:
        citations = {str(row["source_citation"]) for row in chunk_rows}
        if source_citation not in citations:
            errors.append("source_citation does not match any source_chunks citation")
    return errors
