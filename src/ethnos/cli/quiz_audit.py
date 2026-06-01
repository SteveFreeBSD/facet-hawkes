"""Quiz grounding and answer-key audit helpers for CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from ..quiz_validation import validate_quiz_item as _validate_quiz_item
from ..text_utils import compact_text


def build_source_grounding_record(
    conn,
    *,
    document_id: int,
    item: dict[str, object],
    context_rows: list[dict[str, object]],
    retrieval,
    retrieval_questions: list[str],
    chars: int,
) -> dict[str, object]:
    warnings = item.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    validation_errors = _validate_quiz_item(
        conn,
        document_id,
        item,
        require_anchors=False,
        strict_complete=False,
        require_key=False,
    )
    source_chunks = [row["id"] for row in context_rows]
    source_citations = [str(row["source_citation"]) for row in context_rows]
    target = str(item.get("target") or "").strip()
    selected_query = retrieval.selected_query or ""
    source_status = source_status_for_item(
        item,
        warnings=warnings,
        validation_errors=validation_errors,
        context_rows=context_rows,
    )
    evidence_summary = grounding_evidence_summary(
        context_rows,
        target or selected_query or str(item.get("question") or ""),
        chars,
    )
    return {
        "id": item.get("id"),
        "question": item.get("question"),
        "question_type": item.get("question_type") or "multiple_choice",
        "source_status": source_status,
        "target": item.get("target"),
        "source_chunks": source_chunks,
        "source_pages": item.get("source_pages", []),
        "source_citation": item.get("source_citation"),
        "source_citations": source_citations,
        "selected_query": selected_query,
        "retrieval_questions": retrieval_questions,
        "queries_tried": retrieval.queries_tried,
        "evidence_summary": evidence_summary,
        "validation_errors": validation_errors,
        "warnings": warnings,
        "keyed_option": item.get("correct"),
        "source_missing_note": item.get("source_missing_note")
        or item.get("external_source_note"),
    }


def source_status_for_item(
    item: dict[str, object],
    *,
    warnings: list[object],
    validation_errors: list[str],
    context_rows: list[dict[str, object]],
) -> str:
    if "external_source_item" in warnings:
        return "source_missing_in_local_pdf"
    if "incomplete_matching_item" in warnings:
        return "incomplete"
    if validation_errors:
        return "invalid_anchor"
    if item.get("source_chunks") and item.get("source_citation") and context_rows:
        return "pdf_grounded"
    if context_rows:
        return "retrieved_candidate"
    return "ungrounded"


def grounding_evidence_summary(
    context_rows: list[dict[str, object]],
    target: str,
    chars: int,
) -> str | None:
    if not context_rows:
        return None
    text = " ".join(str(row.get("text") or "") for row in context_rows)
    return anchor_snippet(text, target, chars)


def source_grounding_counts(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("source_status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def load_quiz_bench_report(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ValueError(f"Quiz benchmark report not found: {path}")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Quiz benchmark report is invalid JSON: {path}") from exc
    if not isinstance(report, dict):
        raise ValueError("Quiz benchmark report must be a JSON object.")
    if not isinstance(report.get("items"), list):
        raise ValueError("Quiz benchmark report must include an items list.")
    return report


def verify_answer_key_report(
    report: dict[str, object],
    *,
    report_path: Path,
) -> dict[str, object]:
    audit_items = []
    for item in report["items"]:
        if not isinstance(item, dict) or "correct" not in item:
            continue
        question_type = str(item.get("question_type") or "multiple_choice")
        if question_type not in {"multiple_choice", "true_false"}:
            continue
        audit_items.append(audit_keyed_report_item(item))

    counts = {
        "key_supported_count": audit_status_count(audit_items, "key_supported"),
        "key_conflict_candidate_count": audit_status_count(
            audit_items, "key_conflict_candidate"
        ),
        "no_pdf_context_count": audit_status_count(audit_items, "no_pdf_context"),
        "source_missing_count": audit_status_count(
            audit_items, "source_missing_in_local_pdf"
        ),
        "external_source_count": audit_status_count(
            audit_items, "source_missing_in_local_pdf"
        ),
        "invalid_response_count": audit_status_count(audit_items, "invalid_response"),
    }
    return {
        "report": str(report_path),
        "quiz": report.get("quiz"),
        "model": report.get("model"),
        "keyed_item_count": len(audit_items),
        **counts,
        "items": audit_items,
    }


def audit_keyed_report_item(item: dict[str, object]) -> dict[str, object]:
    status = str(item.get("status") or "")
    source_grounding = (
        item.get("source_grounding")
        if isinstance(item.get("source_grounding"), dict)
        else {}
    )
    audit_status = {
        "correct": "key_supported",
        "incorrect": "key_conflict_candidate",
        "no_context": "no_pdf_context",
        "skipped_external_source": "source_missing_in_local_pdf",
        "skipped_source_missing": "source_missing_in_local_pdf",
        "invalid_response": "invalid_response",
    }.get(status, "unclassified")
    answer = item.get("answer") if isinstance(item.get("answer"), dict) else {}
    source_citations = []
    if isinstance(answer, dict) and isinstance(answer.get("source_citations"), list):
        source_citations = answer["source_citations"]
    if not source_citations and isinstance(item.get("selected_source_citations"), list):
        source_citations = item["selected_source_citations"]
    return {
        "id": item.get("id"),
        "question": item.get("question"),
        "question_type": item.get("question_type") or "multiple_choice",
        "audit_status": audit_status,
        "benchmark_status": status,
        "source_status": source_grounding.get("source_status"),
        "keyed_option": item.get("correct"),
        "keyed_option_text": item.get("correct_option_text"),
        "selected_option": item.get("selected_option"),
        "selected_option_text": item.get("selected_option_text"),
        "evidence": answer.get("evidence") if isinstance(answer, dict) else None,
        "source_citations": source_citations,
        "warnings": item.get("warnings", []),
    }


def audit_status_count(items: list[dict[str, object]], status: str) -> int:
    return sum(1 for item in items if item.get("audit_status") == status)


def anchor_snippet(text: str, target: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    target = target.strip()
    index = compact.lower().find(target.lower()) if target else -1
    if index < 0:
        return compact_text(compact, max_chars)
    half_window = max((max_chars - len(target)) // 2, 0)
    start = max(index - half_window, 0)
    end = min(len(compact), start + max_chars)
    start = max(end - max_chars, 0)
    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet = snippet.rstrip() + "..."
    return snippet
