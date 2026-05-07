"""Export helpers for JSON and Markdown output."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from .db import export_document


def export_json(conn: sqlite3.Connection, document_id: int) -> str:
    return json.dumps(export_document(conn, document_id), indent=2, sort_keys=True)


def export_markdown(conn: sqlite3.Connection, document_id: int) -> str:
    data = export_document(conn, document_id)
    document = data["document"]
    lines = [
        f"# {document.get('title') or document['filename']}",
        "",
        f"- Source: `{document['source_path']}`",
        f"- Pages: {document['page_count']}",
        f"- SHA256: `{document['sha256']}`",
        "",
        "## Chunks",
        "",
    ]

    for chunk in data["chunks"]:
        heading = chunk.get("heading") or f"Chunk {chunk['chunk_index']}"
        lines.extend(
            [
                f"### {heading}",
                "",
                f"Source: {chunk['source_citation']}",
                "",
                chunk["text"],
                "",
            ]
        )

    _append_records(lines, "Topics", data["topics"], _topic_line)
    _append_records(lines, "Key Terms", data["key_terms"], _key_term_line)
    _append_records(lines, "Examples", data["examples"], _example_line)
    _append_records(lines, "Study Questions", data["questions"], _question_line)
    return "\n".join(lines).rstrip() + "\n"


def _append_records(
    lines: list[str],
    title: str,
    records: list[dict[str, Any]],
    formatter: Any,
) -> None:
    if not records:
        return
    lines.extend(["", f"## {title}", ""])
    for record in records:
        lines.append(formatter(record))
        lines.append("")


def _topic_line(record: dict[str, Any]) -> str:
    return f"- **{record['name']}**: {record['summary']}"


def _key_term_line(record: dict[str, Any]) -> str:
    return f"- **{record['term']}**: {record['definition']}"


def _example_line(record: dict[str, Any]) -> str:
    return f"- **{record['title']}**: {record['body']}"


def _question_line(record: dict[str, Any]) -> str:
    return f"- **Q:** {record['question']}\n  **A:** {record['answer']}"

