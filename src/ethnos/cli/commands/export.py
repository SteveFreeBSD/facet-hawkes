"""Export commands for JSON, Markdown, and study guides."""

from __future__ import annotations

from pathlib import Path

from ..shared import add_command, open_db
from ..formatting import _write_or_print

from ...export import export_json, export_markdown, export_study


def register(subcommands):
    json_parser = add_command(
        subcommands, "export-json", "Export document data as JSON.", export_json_cmd
    )
    json_parser.add_argument("document_id", type=int)
    json_parser.add_argument("--output", type=Path)

    markdown_parser = add_command(
        subcommands,
        "export-markdown",
        "Export document data as Markdown.",
        export_markdown_cmd,
    )
    markdown_parser.add_argument("document_id", type=int)
    markdown_parser.add_argument("--output", type=Path)

    study_parser = add_command(
        subcommands,
        "export-study",
        "Export a structured Markdown study guide.",
        export_study_cmd,
    )
    study_parser.add_argument("document_id", type=int)
    study_parser.add_argument("--output", type=Path, required=True)


def export_json_cmd(args) -> int:
    _, conn = open_db(args)
    text = export_json(conn, args.document_id)
    _write_or_print(text, args.output)
    return 0


def export_markdown_cmd(args) -> int:
    _, conn = open_db(args)
    text = export_markdown(conn, args.document_id)
    _write_or_print(text, args.output)
    return 0


def export_study_cmd(args) -> int:
    _, conn = open_db(args)
    guide = export_study(conn, args.document_id)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(guide.markdown, encoding="utf-8")
    print(f"Wrote study guide: {args.output}")
    print(f"  document: {guide.filename}")
    print(f"  chunks: {guide.chunk_count}")
    print(f"  key terms: {guide.key_term_count}")
    print(f"  questions: {guide.question_count}")
    return 0
