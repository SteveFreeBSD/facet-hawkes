"""Export helpers for JSON and Markdown output."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from .db import export_document


@dataclass(frozen=True)
class StudyGuide:
    markdown: str
    filename: str
    chunk_count: int
    key_term_count: int
    question_count: int


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


def export_study(conn: sqlite3.Connection, document_id: int) -> StudyGuide:
    data = export_document(conn, document_id)
    document = data["document"]
    key_terms = data["key_terms"]
    questions = data["questions"]
    lines = [
        f"# Study Guide: {document['filename']}",
        "",
        "## Document Summary",
        "",
        f"- Filename: `{document['filename']}`",
        f"- Page count: {document['page_count']}",
        f"- Chunk count: {len(data['chunks'])}",
        f"- Key term count: {len(key_terms)}",
        f"- Question count: {len(questions)}",
        "",
    ]

    if key_terms:
        lines.extend(["## Key Terms", ""])
        for source_label, records in _group_by_source_pages(key_terms).items():
            lines.extend([f"### {source_label}", ""])
            for record in records:
                source = _source_label(record)
                lines.extend(
                    [
                        f"- **{record['term']}**: {record['definition']}",
                        f"  Source pages: {source}",
                    ]
                )
                if record.get("context"):
                    lines.append(f"  Context: {record['context']}")
            lines.append("")

    if questions:
        lines.extend(["## Study Questions", ""])
        for source_label, records in _group_by_source_pages(questions).items():
            lines.extend([f"### {source_label}", ""])
            for record in records:
                lines.extend(
                    [
                        f"- **Q:** {record['question']}",
                        f"  **A:** {record['answer']}",
                        f"  Source pages: {_source_label(record)}",
                    ]
                )
            lines.append("")

    if key_terms:
        lines.extend(["## Review Checklist", ""])
        for term, source_label in _unique_terms_for_checklist(key_terms):
            lines.append(f"- [ ] Can I explain {term}? ({source_label})")
        lines.append("")

    return StudyGuide(
        markdown="\n".join(lines).rstrip() + "\n",
        filename=document["filename"],
        chunk_count=len(data["chunks"]),
        key_term_count=len(key_terms),
        question_count=len(questions),
    )


def _group_by_source_pages(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for record in sorted(records, key=_source_sort_key):
        groups.setdefault(_source_label(record), []).append(record)
    return groups


def _source_sort_key(record: dict[str, Any]) -> tuple[int, int, str]:
    pages = _source_pages(record)
    first_page = pages[0] if pages else 0
    last_page = pages[-1] if pages else 0
    label = record.get("term") or record.get("question") or ""
    return (first_page, last_page, label.lower())


def _source_label(record: dict[str, Any]) -> str:
    pages = _source_pages(record)
    if not pages:
        return "source pages unknown"
    if len(pages) == 1:
        return f"p. {pages[0]}"
    if pages == list(range(pages[0], pages[-1] + 1)):
        return f"pp. {pages[0]}-{pages[-1]}"
    return "pp. " + ", ".join(str(page) for page in pages)


def _source_pages(record: dict[str, Any]) -> list[int]:
    raw_pages = record.get("source_pages", "[]")
    if isinstance(raw_pages, str):
        try:
            pages = json.loads(raw_pages)
        except json.JSONDecodeError:
            return []
    else:
        pages = raw_pages
    if not isinstance(pages, list):
        return []
    return sorted(page for page in pages if isinstance(page, int))


def _unique_terms_for_checklist(records: list[dict[str, Any]]) -> list[tuple[str, str]]:
    seen = set()
    checklist = []
    for record in sorted(records, key=_source_sort_key):
        term = record["term"]
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        checklist.append((term, _source_label(record)))
    return checklist


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
