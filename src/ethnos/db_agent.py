"""Persistence helpers for agent review runs."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .agent_models import AgentReviewItem, AgentReviewReport


def create_agent_run(
    conn: sqlite3.Connection,
    *,
    document_id: int,
    quiz_path: Path,
    model_name: str,
    model_profile: str,
    config: dict[str, Any],
    output_path: Path,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO agent_runs (
            document_id, quiz_path, model_name, model_profile,
            config_json, status, output_path
        )
        VALUES (?, ?, ?, ?, ?, 'running', ?)
        """,
        (
            document_id,
            str(quiz_path),
            model_name,
            model_profile,
            json.dumps(config, sort_keys=True),
            str(output_path),
        ),
    )
    conn.commit()
    return int(cursor.lastrowid)


def finish_agent_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    status: str,
    summary: dict[str, Any],
    error_message: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE agent_runs
        SET finished_at = CURRENT_TIMESTAMP,
            status = ?,
            summary_json = ?,
            error_message = ?
        WHERE id = ?
        """,
        (status, json.dumps(summary, sort_keys=True), error_message, run_id),
    )
    conn.commit()


def save_agent_findings(
    conn: sqlite3.Connection,
    run_id: int,
    items: list[AgentReviewItem],
) -> None:
    with conn:
        conn.execute("DELETE FROM agent_findings WHERE run_id = ?", (run_id,))
        for item in items:
            finding_type = _primary_finding_type(item)
            severity = _primary_severity(item)
            evidence_json = json.dumps(
                [citation.model_dump(mode="json") for citation in item.evidence],
                sort_keys=True,
            )
            result_json = json.dumps(item.model_dump(mode="json"), sort_keys=True)
            conn.execute(
                """
                INSERT INTO agent_findings (
                    run_id, quiz_item_id, verdict, severity, finding_type,
                    evidence_json, result_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    item.id,
                    item.verdict,
                    severity,
                    finding_type,
                    evidence_json,
                    result_json,
                ),
            )


def agent_report_summary(report: AgentReviewReport) -> dict[str, Any]:
    return {
        "document_id": report.document_id,
        "quiz": report.quiz,
        "model": report.model,
        "model_profile": report.model_profile,
        "item_count": report.item_count,
        "verdict_counts": report.verdict_counts,
        "quality_counts": report.quality_counts,
        "priority_counts": report.priority_counts,
        "model_finalized_count": getattr(report, "model_finalized_count", 0),
        "fallback_item_count": getattr(report, "fallback_item_count", 0),
    }


def _primary_finding_type(item: AgentReviewItem) -> str:
    if item.quality_findings:
        return item.quality_findings[0].finding_type
    return item.verdict


def _primary_severity(item: AgentReviewItem) -> str:
    if item.verdict == "key_conflict_candidate":
        return "high"
    if item.verdict in {"source_missing", "ambiguous_question"}:
        return "medium"
    if item.quality_findings:
        return item.quality_findings[0].severity
    return "info"
