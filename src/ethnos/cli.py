"""Command-line interface for ethnos."""

from __future__ import annotations

import argparse
import time
from collections import Counter
import json
from pathlib import Path
from typing import Callable

from .chunking import build_chunks
from .config import load_settings
from .db import (
    chunk_records,
    connect,
    context_chunks,
    create_extraction_run,
    db_info,
    apply_section_preset,
    finish_extraction_run,
    get_document,
    inspect_chunk,
    init_db,
    list_structured_records,
    list_chunks,
    list_documents,
    list_pages,
    quality_report,
    save_chunks,
    save_document_pages,
    save_extraction_result,
    save_model_output,
    search_chunks,
    section_label_status,
    select_chunks_for_structure,
    structure_status,
)
from .export import export_json, export_markdown, export_study
from .ollama_client import extract_chunk
from .pdf_extract import extract_pdf
from .section_presets import CONTENT_ROLES, PRESETS, SECTION_LABELS, get_section_preset


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    return args.handler(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ethnos",
        description="Local-first PDF-to-knowledge pipeline.",
    )
    parser.add_argument("--db", type=Path, help="SQLite database path.")
    subcommands = parser.add_subparsers(dest="command")

    _command(subcommands, "ingest-pdf", "Extract and store PDF pages.", ingest_pdf).add_argument(
        "path", type=Path
    )
    _command(subcommands, "extract", "Rerun extraction for a stored document.", extract).add_argument(
        "document_id", type=int
    )

    chunk_parser = _command(subcommands, "chunk", "Create page-aware chunks.", chunk_document)
    chunk_parser.add_argument("document_id", type=int)
    chunk_parser.add_argument("--target-chars", type=int, default=3000)
    chunk_parser.add_argument("--max-chars", type=int, default=4000)
    chunk_parser.add_argument("--overlap-chars", type=int, default=250)

    structure_parser = _command(
        subcommands, "structure", "Run Ollama structured extraction.", structure
    )
    structure_parser.add_argument("document_id", type=int)
    structure_parser.add_argument("--model", help="Ollama model name.")
    structure_parser.add_argument(
        "--num-predict",
        type=int,
        help="Ollama output token budget for structured JSON.",
    )
    selection = structure_parser.add_mutually_exclusive_group()
    selection.add_argument("--chunk-id", type=int, help="Process one stored chunk id.")
    selection.add_argument(
        "--limit",
        type=int,
        help="Process the first N chunks without a valid stored model output.",
    )
    structure_parser.add_argument(
        "--debug-ollama",
        action="store_true",
        help="Print compact Ollama request/response diagnostics.",
    )
    structure_parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Process chunks whose latest model output failed.",
    )
    structure_parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocess selected chunks even if they already have valid output.",
    )

    inspect_parser = _command(
        subcommands, "inspect-chunk", "Inspect one stored chunk and its extracted records.", inspect_chunk_cmd
    )
    inspect_parser.add_argument("document_id", type=int)
    inspect_parser.add_argument("chunk_id", type=int)
    inspect_parser.add_argument("--full-text", action="store_true")
    inspect_parser.add_argument("--records", action="store_true")

    search_parser = _command(subcommands, "search", "Search chunks with SQLite FTS5.", search)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--role", choices=sorted(CONTENT_ROLES))
    search_parser.add_argument("--section", choices=sorted(SECTION_LABELS))

    records_parser = _command(
        subcommands, "records", "List normalized structured records.", records_cmd
    )
    records_parser.add_argument("document_id", type=int)
    records_parser.add_argument(
        "--type",
        choices=["all", "key_terms", "questions", "topics", "examples"],
        default="all",
    )
    records_parser.add_argument("--role", choices=sorted(CONTENT_ROLES))
    records_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    records_parser.add_argument("--chunk-id", type=int)
    records_parser.add_argument("--limit", type=int, default=20)

    quality_parser = _command(
        subcommands, "quality-report", "Summarize assimilation quality and scope.", quality_report_cmd
    )
    quality_parser.add_argument("document_id", type=int)

    context_parser = _command(
        subcommands, "context", "Show retrieval-ready context for a query.", context_cmd
    )
    context_parser.add_argument("document_id", type=int)
    context_parser.add_argument("query")
    context_parser.add_argument("--limit", type=int, default=5)
    context_parser.add_argument("--role", choices=sorted(CONTENT_ROLES), default="core")
    context_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    context_parser.add_argument("--chars", type=int, default=900)

    json_parser = _command(subcommands, "export-json", "Export document data as JSON.", export_json_cmd)
    json_parser.add_argument("document_id", type=int)
    json_parser.add_argument("--output", type=Path)

    markdown_parser = _command(
        subcommands, "export-markdown", "Export document data as Markdown.", export_markdown_cmd
    )
    markdown_parser.add_argument("document_id", type=int)
    markdown_parser.add_argument("--output", type=Path)

    study_parser = _command(
        subcommands, "export-study", "Export a structured Markdown study guide.", export_study_cmd
    )
    study_parser.add_argument("document_id", type=int)
    study_parser.add_argument("--output", type=Path, required=True)

    _command(subcommands, "db-info", "Show local database counts.", db_info_cmd)
    _command(subcommands, "documents", "List stored documents.", documents_cmd)
    status_parser = _command(
        subcommands, "structure-status", "Show structured extraction status for a document.", structure_status_cmd
    )
    status_parser.add_argument("document_id", type=int)

    label_parser = _command(
        subcommands, "label-sections", "Apply manual section labels to pages and chunks.", label_sections_cmd
    )
    label_parser.add_argument("document_id", type=int)
    label_parser.add_argument("--preset", required=True, choices=sorted(PRESETS))
    label_parser.add_argument("--dry-run", action="store_true")

    section_status_parser = _command(
        subcommands, "section-status", "Show section-label status for a document.", section_status_cmd
    )
    section_status_parser.add_argument("document_id", type=int)
    return parser


def _command(
    subcommands: argparse._SubParsersAction,
    name: str,
    help_text: str,
    handler: Callable[[argparse.Namespace], int],
) -> argparse.ArgumentParser:
    command = subcommands.add_parser(name, help=help_text)
    command.set_defaults(handler=handler)
    return command


def open_db(args: argparse.Namespace):
    settings = load_settings()
    db_path = args.db or settings.db_path
    conn = connect(db_path)
    init_db(conn)
    return settings, conn


def ingest_pdf(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    document, pages = extract_pdf(args.path)
    document_id = save_document_pages(conn, document, pages)
    print(f"Ingested document {document_id}: {document.filename} ({len(pages)} pages)")
    return 0


def extract(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    document = get_document(conn, args.document_id)
    extracted_document, pages = extract_pdf(Path(document.source_path))
    document_id = save_document_pages(conn, extracted_document, pages)
    print(f"Re-extracted document {document_id}: {extracted_document.filename} ({len(pages)} pages)")
    return 0


def chunk_document(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    document = get_document(conn, args.document_id)
    pages = list_pages(conn, args.document_id)
    chunks = build_chunks(
        document,
        pages,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
    )
    save_chunks(conn, args.document_id, chunks)
    print(f"Stored {len(chunks)} chunks for document {args.document_id}")
    return 0


def structure(args: argparse.Namespace) -> int:
    settings, conn = open_db(args)
    model_name = args.model or settings.ollama_model
    num_predict = structure_num_predict(args, settings)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if args.force and args.retry_failed:
        raise SystemExit("Use either --force or --retry-failed, not both.")

    chunks = select_chunks_for_structure(
        conn,
        document_id=args.document_id,
        chunk_id=args.chunk_id,
        limit=args.limit,
        retry_failed=args.retry_failed,
        force=args.force,
    )
    if not chunks:
        print("No chunks selected.")
        print("Default structure runs process never-attempted chunks only.")
        print("Use --retry-failed for chunks whose latest output failed, or --force to reprocess.")
        return 0

    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    print("Structure run preview:", flush=True)
    print(f"  document id: {args.document_id}", flush=True)
    print(f"  model: {model_name}", flush=True)
    print(f"  num_predict: {num_predict}", flush=True)
    print(f"  chunks selected: {len(chunks)}", flush=True)
    print(f"  chunk ids: {', '.join(str(chunk_id) for chunk_id in chunk_ids)}", flush=True)
    if args.chunk_id is None and args.limit is None:
        print(
            "  selection: forced full document" if args.force else "  selection: never attempted",
            flush=True,
        )
    elif args.retry_failed:
        print("  selection: latest failed", flush=True)
    elif args.force:
        print("  selection: forced", flush=True)

    run_id = create_extraction_run(
        conn,
        document_id=args.document_id,
        model_name=model_name,
        prompt_name=settings.prompt_path.name,
    )
    valid_count = 0
    failed_count = 0
    last_error = None
    status_counts: Counter[str] = Counter()
    started_at = time.monotonic()

    for index, chunk in enumerate(chunks, start=1):
        if chunk.id is None:
            raise RuntimeError("Stored chunks must have database ids")
        chunk_started_at = time.monotonic()
        print(f"[{index}/{len(chunks)}] chunk {chunk.id}: {chunk.source_citation}", flush=True)
        result = extract_chunk(
            chunk=chunk,
            prompt_path=settings.prompt_path,
            model_name=model_name,
            host=settings.ollama_host,
            timeout=settings.ollama_timeout,
            num_predict=num_predict,
            debug_ollama=args.debug_ollama,
        )
        if args.debug_ollama:
            _print_ollama_debug(chunk.id, result.debug_info)
        elapsed = time.monotonic() - chunk_started_at
        status_counts[result.validation_status] += 1
        print(f"  status: {result.validation_status} ({format_elapsed(elapsed)})", flush=True)
        save_model_output(
            conn,
            run_id=run_id,
            chunk_id=chunk.id,
            raw_prompt=result.raw_prompt,
            raw_response=result.raw_response,
            parsed_json=result.parsed_json,
            validation_status=result.validation_status,
            validation_error=result.validation_error,
        )
        if result.result is None:
            failed_count += 1
            last_error = result.validation_error
            if _ollama_done_reason(result) == "length":
                print(
                    f"Warning: chunk {chunk.id} hit Ollama output length limit; "
                    "consider increasing --num-predict.",
                    flush=True,
                )
            if result.validation_status == "empty_response":
                print(
                    f"Warning: chunk {chunk.id} produced an empty Ollama response; "
                    "raw output was preserved.",
                    flush=True,
                )
            continue
        save_extraction_result(conn, chunk.id, result.result)
        valid_count += 1

    status = "completed" if failed_count == 0 else "completed_with_errors"
    finish_extraction_run(conn, run_id, status=status, error_message=last_error)
    total_elapsed = time.monotonic() - started_at
    print(flush=True)
    print("Structure run summary:", flush=True)
    print(f"  chunks selected: {len(chunks)}", flush=True)
    print(f"  chunks valid: {valid_count}", flush=True)
    print(f"  chunks failed: {failed_count}", flush=True)
    print(f"  empty_response: {status_counts['empty_response']}", flush=True)
    print(f"  invalid_json: {status_counts['invalid_json']}", flush=True)
    print(f"  validation_error: {status_counts['validation_error']}", flush=True)
    print(f"  elapsed total: {format_elapsed(total_elapsed)}", flush=True)
    print(f"  run id: {run_id}", flush=True)
    return 0 if failed_count == 0 else 1


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:.1f}s"


def structure_num_predict(args: argparse.Namespace, settings) -> int:
    return args.num_predict if args.num_predict is not None else settings.ollama_num_predict


def _ollama_done_reason(result) -> str | None:
    if result.debug_info is None or result.debug_info.response_summary is None:
        return None
    done_reason = result.debug_info.response_summary.get("done_reason")
    return done_reason if isinstance(done_reason, str) else None


def _print_ollama_debug(chunk_id: int | None, debug_info) -> None:
    if debug_info is None:
        print(f"Ollama debug for chunk {chunk_id}: unavailable", flush=True)
        return
    print(f"Ollama debug for chunk {chunk_id}:", flush=True)
    print(f"  prompt chars: {debug_info.prompt_char_length}", flush=True)
    print(f"  schema top-level keys: {', '.join(debug_info.schema_top_level_keys)}", flush=True)
    print(f"  format: {debug_info.format_kind}", flush=True)
    print(f"  think: {debug_info.think}", flush=True)
    print(f"  num_predict: {debug_info.num_predict}", flush=True)
    if debug_info.response_summary is None:
        print("  response envelope: unavailable", flush=True)
        return
    print("  response envelope:", flush=True)
    for key, value in debug_info.response_summary.items():
        print(f"    {key}: {value}", flush=True)


def inspect_chunk_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    inspection = inspect_chunk(conn, args.document_id, args.chunk_id)
    chunk = inspection["chunk"]
    counts = inspection["counts"]
    print(f"Document: {chunk['filename']}")
    print(f"Chunk id: {chunk['id']}")
    print(f"Chunk index: {chunk['chunk_index']}")
    print(f"Pages: {format_page_range(chunk['page_start'], chunk['page_end'])}")
    print(f"Source: {chunk['source_citation']}")
    print(f"Section: {chunk['section_label'] or 'unlabeled'}")
    print(f"Role: {chunk['content_role'] or 'unlabeled'}")
    print("Record counts:")
    print(f"  key_terms: {counts['key_terms']}")
    print(f"  questions: {counts['questions']}")
    print(f"  topics: {counts['topics']}")
    print(f"  examples: {counts['examples']}")
    print()
    print("Chunk text:")
    print(chunk["text"] if args.full_text else preview_text(chunk["text"], 1000))
    if args.records:
        print()
        _print_chunk_records(chunk_records(conn, args.chunk_id))
    return 0


def search(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    results = search_chunks(conn, args.query, args.limit, role=args.role, section=args.section)
    for result in results:
        print(f"[chunk {result['id']}] {result['source_citation']}")
        print(f"section: {result['section_label'] or 'unlabeled'} | role: {result['content_role'] or 'unlabeled'}")
        print(result["snippet"])
        print()
    return 0


def records_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    rows = list_structured_records(
        conn,
        args.document_id,
        record_type=args.type,
        role=args.role,
        section=args.section,
        chunk_id=args.chunk_id,
        limit=args.limit,
    )
    if not rows:
        print("No records found.")
        return 0
    for row in rows:
        _print_record(row)
    return 0


def quality_report_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    report = quality_report(conn, args.document_id)
    print(f"Quality report for document {args.document_id}")
    _print_section_count_summary("Pages by section/role", report["sections"]["pages"])
    print(f"  unlabeled pages: {report['sections']['unlabeled_pages']}")
    _print_section_count_summary("Chunks by section/role", report["sections"]["chunks"])
    print(f"  unlabeled chunks: {report['sections']['unlabeled_chunks']}")
    _print_status_counts("Total model output statuses", report["model_output_status_counts"])
    _print_status_counts("Latest output statuses", report["latest_output_status_counts"])
    _print_role_counts("Key terms by role", report["key_terms_by_role"])
    _print_role_counts("Questions by role", report["questions_by_role"])
    print("Top repeated key terms:")
    if report["top_repeated_key_terms"]:
        for row in report["top_repeated_key_terms"]:
            print(f"  {row['term']}: {row['count']}")
    else:
        print("  none")
    _print_chunk_list(
        "Chunks with no key_terms and no questions",
        report["chunks_with_no_terms_or_questions"],
    )
    _print_non_core_records(report["non_core_chunks_with_records"])
    print(f"Topics: {report['topics']}")
    if report["topics"] < 10:
        print("  Warning: topics are sparse; do not treat topics as the main structure.")
    print(f"Examples: {report['examples']}")
    if report["examples"] == 0:
        print("  Warning: no examples were extracted.")
    return 0


def context_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    rows = context_chunks(
        conn,
        args.document_id,
        args.query,
        limit=args.limit,
        role=args.role,
        section=args.section,
    )
    if not rows:
        print("No context chunks found.")
        return 0
    print(f"Context for document {args.document_id}: {args.query}")
    print(f"role: {args.role or 'all'} | section: {args.section or 'all'}")
    for row in rows:
        print()
        print(f"[chunk {row['id']}] {row['source_citation']}")
        print(f"section: {row['section_label'] or 'unlabeled'} | role: {row['content_role'] or 'unlabeled'}")
        print("Snippet:")
        print(row["snippet"])
        print("Context text:")
        print(preview_text(row["text"], args.chars))
    return 0


def export_json_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    text = export_json(conn, args.document_id)
    _write_or_print(text, args.output)
    return 0


def export_markdown_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    text = export_markdown(conn, args.document_id)
    _write_or_print(text, args.output)
    return 0


def export_study_cmd(args: argparse.Namespace) -> int:
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


def db_info_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    print(json.dumps(db_info(conn), indent=2, sort_keys=True))
    return 0


def documents_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    documents = list_documents(conn)
    if not documents:
        print("No documents stored.")
        return 0

    headers = ["id", "filename", "pages", "sha256", "created_at", "source_path"]
    rows = [
        [
            str(document["id"]),
            document["filename"],
            str(document["page_count"]),
            document["sha256"][:12],
            document["created_at"] or "",
            document["source_path"],
        ]
        for document in documents
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)))
    return 0


def structure_status_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    status = structure_status(conn, args.document_id)
    print(f"Structure status for document {args.document_id}")
    print(f"  total chunks: {status['total_chunks']}")
    print(f"  chunks with valid output: {status['chunks_with_valid_output']}")
    print(f"  chunks latest failed: {status['chunks_latest_failed']}")
    print(f"  chunks never attempted: {status['chunks_never_attempted']}")
    print(f"  topics: {status['topics']}")
    print(f"  key_terms: {status['key_terms']}")
    print(f"  examples: {status['examples']}")
    print(f"  questions: {status['questions']}")
    if status["latest_failed_chunks"]:
        print("  latest failed chunk ids:")
        print("    " + ", ".join(str(row["chunk_id"]) for row in status["latest_failed_chunks"][:30]))
        if len(status["latest_failed_chunks"]) > 30:
            print(f"    ... {len(status['latest_failed_chunks']) - 30} more")
    if status["never_attempted_chunks"]:
        print("  never attempted chunk ids:")
        print("    " + ", ".join(str(row["chunk_id"]) for row in status["never_attempted_chunks"][:30]))
        if len(status["never_attempted_chunks"]) > 30:
            print(f"    ... {len(status['never_attempted_chunks']) - 30} more")
    return 0


def label_sections_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    preset = get_section_preset(args.preset)
    summary = apply_section_preset(conn, args.document_id, preset, dry_run=args.dry_run)
    action = "Section label dry run" if args.dry_run else "Applied section labels"
    print(f"{action} for document {args.document_id} using preset {args.preset}")
    _print_section_count_summary("Pages", summary["pages"])
    _print_section_count_summary("Chunks", summary["chunks"])
    return 0


def section_status_cmd(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    status = section_label_status(conn, args.document_id)
    print(f"Section status for document {args.document_id}")
    _print_section_count_summary("Pages", status["pages"])
    print(f"  unlabeled pages: {status['unlabeled_pages']}")
    _print_section_count_summary("Chunks", status["chunks"])
    print(f"  unlabeled chunks: {status['unlabeled_chunks']}")
    return 0


def _print_section_count_summary(title: str, rows: list[dict]) -> None:
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['section_label']} / {row['content_role']}: {row['count']}")


def _print_chunk_records(records: dict[str, list[dict]]) -> None:
    print("Extracted records:")
    for section in ["key_terms", "questions", "topics", "examples"]:
        print(f"{section}:")
        if not records[section]:
            print("  none")
            continue
        for row in records[section]:
            _print_record({"record_type": section, **row})


def _print_record(row: dict) -> None:
    record_type = row["record_type"]
    source_pages = format_source_pages(row.get("source_pages"))
    if record_type == "key_terms":
        print(f"[key_term] chunk {row['chunk_id']} | {source_pages}")
        print(f"  term: {row['term']}")
        print(f"  definition: {row['definition']}")
    elif record_type == "questions":
        print(f"[question] chunk {row['chunk_id']} | {source_pages}")
        print(f"  question: {row['question']}")
        print(f"  answer: {row['answer']}")
    elif record_type == "topics":
        print(f"[topic] chunk {row['chunk_id']} | {source_pages}")
        print(f"  name: {row['name']}")
        print(f"  summary: {row['summary']}")
    elif record_type == "examples":
        print(f"[example] chunk {row['chunk_id']} | {source_pages}")
        print(f"  title: {row['title']}")
        print(f"  body: {row['body']}")
    print()


def _print_status_counts(title: str, rows: list[dict]) -> None:
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['validation_status']}: {row['count']}")


def _print_role_counts(title: str, rows: list[dict]) -> None:
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['content_role']}: {row['count']}")


def _print_chunk_list(title: str, rows: list[dict], limit: int = 20) -> None:
    print(f"{title}: {len(rows)}")
    for row in rows[:limit]:
        print(
            f"  chunk {row['id']} ({row['section_label'] or 'unlabeled'} / "
            f"{row['content_role'] or 'unlabeled'}): {row['source_citation']}"
        )
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")


def _print_non_core_records(rows: list[dict], limit: int = 20) -> None:
    print(f"Admin/support chunks with key_terms/questions: {len(rows)}")
    for row in rows[:limit]:
        print(
            f"  chunk {row['id']} ({row['section_label'] or 'unlabeled'} / "
            f"{row['content_role'] or 'unlabeled'}): "
            f"key_terms={row['key_terms']}, questions={row['questions']}"
        )
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")


def preview_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def format_page_range(page_start: int, page_end: int) -> str:
    if page_start == page_end:
        return f"p. {page_start}"
    return f"pp. {page_start}-{page_end}"


def format_source_pages(raw_pages) -> str:
    if raw_pages is None:
        return "source pages: none"
    if isinstance(raw_pages, str):
        try:
            pages = json.loads(raw_pages)
        except json.JSONDecodeError:
            return f"source pages: {raw_pages}"
    else:
        pages = raw_pages
    if not pages:
        return "source pages: none"
    pages = sorted(set(int(page) for page in pages))
    ranges: list[str] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return "source pages: " + ", ".join(ranges)


def _write_or_print(text: str, output: Path | None) -> None:
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    raise SystemExit(main())
