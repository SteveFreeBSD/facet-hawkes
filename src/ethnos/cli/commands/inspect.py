"""Inspection, search, status, and admin commands."""

from __future__ import annotations

import json

from ..shared import add_command, open_db
from ..formatting import (
    format_page_range,
    limit_display_text,
    preview_text,
    _print_chunk_records,
    _print_chunk_list,
    _print_non_core_records,
    _print_role_counts,
    _print_section_count_summary,
    _print_status_counts,
)

from ...db import (
    apply_section_preset,
    backfill_chunk_summaries,
    chunk_records,
    context_chunks,
    db_info,
    inspect_chunk,
    inspect_page,
    list_documents,
    list_structured_records,
    quality_report,
    refresh_normalized_records,
    search_chunks,
    section_label_status,
    structure_status,
)
from ...section_presets import CONTENT_ROLES, PRESETS, SECTION_LABELS, get_section_preset


def register(subcommands):
    inspect_parser = add_command(
        subcommands, "inspect-chunk", "Inspect one stored chunk and its extracted records.", inspect_chunk_cmd
    )
    inspect_parser.add_argument("document_id", type=int)
    inspect_parser.add_argument("chunk_id", type=int)
    inspect_parser.add_argument("--full-text", action="store_true")
    inspect_parser.add_argument("--records", action="store_true")

    page_parser = add_command(
        subcommands, "inspect-page", "Inspect one stored source page.", inspect_page_cmd
    )
    page_parser.add_argument("document_id", type=int)
    page_parser.add_argument("page_number", type=int)
    page_parser.add_argument("--raw", action="store_true")
    page_parser.add_argument("--limit", type=int, default=2000)

    search_parser = add_command(subcommands, "search", "Search chunks with SQLite FTS5.", search)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)
    search_parser.add_argument("--role", choices=sorted(CONTENT_ROLES))
    search_parser.add_argument("--section", choices=sorted(SECTION_LABELS))

    records_parser = add_command(
        subcommands, "records", "List normalized structured records.", records_cmd
    )
    records_parser.add_argument("document_id", type=int)
    records_parser.add_argument(
        "--type",
        choices=["all", "chunk_summaries", "key_terms", "questions", "topics", "examples"],
        default="all",
    )
    records_parser.add_argument("--role", choices=sorted(CONTENT_ROLES))
    records_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    records_parser.add_argument("--chunk-id", type=int)
    records_parser.add_argument("--limit", type=int, default=20)

    quality_parser = add_command(
        subcommands, "quality-report", "Summarize assimilation quality and scope.", quality_report_cmd
    )
    quality_parser.add_argument("document_id", type=int)

    backfill_parser = add_command(
        subcommands, "backfill-summaries",
        "Backfill normalized chunk summaries from valid model outputs.",
        backfill_summaries_cmd,
    )
    backfill_parser.add_argument("document_id", type=int)

    refresh_parser = add_command(
        subcommands, "refresh-records",
        "Refresh normalized records from latest valid model outputs.",
        refresh_records_cmd,
    )
    refresh_parser.add_argument("document_id", type=int)

    context_parser = add_command(
        subcommands, "context", "Show retrieval-ready context for a query.", context_cmd
    )
    context_parser.add_argument("document_id", type=int)
    context_parser.add_argument("query")
    context_parser.add_argument("--limit", type=int, default=5)
    context_parser.add_argument("--role", choices=sorted(CONTENT_ROLES), default="core")
    context_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    context_parser.add_argument("--chars", type=int, default=900)

    add_command(subcommands, "db-info", "Show local database counts.", db_info_cmd)
    add_command(subcommands, "documents", "List stored documents.", documents_cmd)

    status_parser = add_command(
        subcommands, "structure-status", "Show structured extraction status for a document.", structure_status_cmd
    )
    status_parser.add_argument("document_id", type=int)

    label_parser = add_command(
        subcommands, "label-sections", "Apply manual section labels to pages and chunks.", label_sections_cmd
    )
    label_parser.add_argument("document_id", type=int)
    label_parser.add_argument("--preset", required=True, choices=sorted(PRESETS))
    label_parser.add_argument("--dry-run", action="store_true")

    section_status_parser = add_command(
        subcommands, "section-status", "Show section-label status for a document.", section_status_cmd
    )
    section_status_parser.add_argument("document_id", type=int)


def inspect_chunk_cmd(args) -> int:
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
    print(f"  chunk_summaries: {counts['chunk_summaries']}")
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


def inspect_page_cmd(args) -> int:
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    _, conn = open_db(args)
    page = inspect_page(conn, args.document_id, args.page_number)
    text_key = "raw_text" if args.raw else "cleaned_text"
    text_label = "Raw text" if args.raw else "Cleaned text"
    print(f"Document: {page['filename']}")
    print(f"Page: {page['page_number']}")
    print(f"Page id: {page['id']}")
    print(f"Extraction method: {page['extraction_method']}")
    print(f"Chars: {page['char_count']}")
    print(f"Section: {page['section_label'] or 'unlabeled'}")
    print(f"Role: {page['content_role'] or 'unlabeled'}")
    print()
    print(f"{text_label}:")
    print(limit_display_text(page[text_key], args.limit))
    return 0


def search(args) -> int:
    _, conn = open_db(args)
    results = search_chunks(conn, args.query, args.limit, role=args.role, section=args.section)
    for result in results:
        print(f"[chunk {result['id']}] {result['source_citation']}")
        print(f"section: {result['section_label'] or 'unlabeled'} | role: {result['content_role'] or 'unlabeled'}")
        print(result["snippet"])
        print()
    return 0


def records_cmd(args) -> int:
    _, conn = open_db(args)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    rows = list_structured_records(
        conn, args.document_id,
        record_type=args.type, role=args.role, section=args.section,
        chunk_id=args.chunk_id, limit=args.limit,
    )
    if not rows:
        print("No records found.")
        return 0
    for row in rows:
        from ..formatting import _print_record
        _print_record(row)
    return 0


def quality_report_cmd(args) -> int:
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
        "Core chunks with no key_terms and no questions",
        report["chunks_with_no_terms_or_questions"],
    )
    _print_non_core_records(report["non_core_chunks_with_records"])
    print(f"Chunk summaries: {report['chunk_summaries']}")
    print(f"Topics: {report['topics']}")
    if report["topics"] < 10:
        print("  Warning: topics are sparse; do not treat topics as the main structure.")
    print(f"Examples: {report['examples']}")
    if report["examples"] == 0:
        print("  Warning: no examples were extracted.")
    return 0


def backfill_summaries_cmd(args) -> int:
    _, conn = open_db(args)
    report = backfill_chunk_summaries(conn, args.document_id)
    print(f"Backfilled chunk summaries for document {args.document_id}")
    print(f"  candidates: {report['candidates']}")
    print(f"  backfilled: {report['backfilled']}")
    print(f"  skipped_invalid: {report['skipped_invalid']}")
    if report["backfilled_chunks"]:
        print("  chunk ids: " + ", ".join(str(chunk_id) for chunk_id in report["backfilled_chunks"]))
    if report["errors"]:
        print("  validation errors:")
        for error in report["errors"][:10]:
            print(
                f"    chunk {error['chunk_id']} / model_output {error['model_output_id']}: "
                f"{preview_text(error['error'], 160)}"
            )
        if len(report["errors"]) > 10:
            print(f"    ... {len(report['errors']) - 10} more")
    return 0 if report["skipped_invalid"] == 0 else 1


def refresh_records_cmd(args) -> int:
    _, conn = open_db(args)
    report = refresh_normalized_records(conn, args.document_id)
    print(f"Refreshed normalized records for document {args.document_id}")
    print(f"  candidates: {report['candidates']}")
    print(f"  refreshed: {report['refreshed']}")
    print(f"  skipped_invalid: {report['skipped_invalid']}")
    if report["refreshed_chunks"]:
        print("  chunk ids: " + ", ".join(str(chunk_id) for chunk_id in report["refreshed_chunks"]))
    if report["errors"]:
        print("  validation errors:")
        for error in report["errors"][:10]:
            print(
                f"    chunk {error['chunk_id']} / model_output {error['model_output_id']}: "
                f"{preview_text(error['error'], 160)}"
            )
        if len(report["errors"]) > 10:
            print(f"    ... {len(report['errors']) - 10} more")
    return 0 if report["skipped_invalid"] == 0 else 1


def context_cmd(args) -> int:
    _, conn = open_db(args)
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    rows = context_chunks(
        conn, args.document_id, args.query,
        limit=args.limit, role=args.role, section=args.section,
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


def db_info_cmd(args) -> int:
    _, conn = open_db(args)
    print(json.dumps(db_info(conn), indent=2, sort_keys=True))
    return 0


def documents_cmd(args) -> int:
    _, conn = open_db(args)
    documents = list_documents(conn)
    if not documents:
        print("No documents stored.")
        return 0
    headers = ["id", "filename", "pages", "sha256", "created_at", "source_path"]
    rows = [
        [
            str(document["id"]), document["filename"], str(document["page_count"]),
            document["sha256"][:12], document["created_at"] or "", document["source_path"],
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


def structure_status_cmd(args) -> int:
    _, conn = open_db(args)
    status = structure_status(conn, args.document_id)
    print(f"Structure status for document {args.document_id}")
    print(f"  total chunks: {status['total_chunks']}")
    print(f"  chunks with valid output: {status['chunks_with_valid_output']}")
    print(f"  chunks latest failed: {status['chunks_latest_failed']}")
    print(f"  chunks never attempted: {status['chunks_never_attempted']}")
    print(f"  chunk_summaries: {status['chunk_summaries']}")
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


def label_sections_cmd(args) -> int:
    _, conn = open_db(args)
    preset = get_section_preset(args.preset)
    summary = apply_section_preset(conn, args.document_id, preset, dry_run=args.dry_run)
    action = "Section label dry run" if args.dry_run else "Applied section labels"
    print(f"{action} for document {args.document_id} using preset {args.preset}")
    _print_section_count_summary("Pages", summary["pages"])
    _print_section_count_summary("Chunks", summary["chunks"])
    return 0


def section_status_cmd(args) -> int:
    _, conn = open_db(args)
    status = section_label_status(conn, args.document_id)
    print(f"Section status for document {args.document_id}")
    _print_section_count_summary("Pages", status["pages"])
    print(f"  unlabeled pages: {status['unlabeled_pages']}")
    _print_section_count_summary("Chunks", status["chunks"])
    print(f"  unlabeled chunks: {status['unlabeled_chunks']}")
    return 0
