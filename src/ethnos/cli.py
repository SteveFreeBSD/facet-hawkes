"""Command-line interface for ethnos."""

from __future__ import annotations

import argparse
import time
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Callable

from .chunking import build_chunks
from .config import load_settings
from .db import (
    chunk_records,
    connect,
    context_chunks,
    create_extraction_run,
    db_info,
    add_continuation_context_chunks,
    apply_section_preset,
    finish_extraction_run,
    get_document,
    inspect_chunk,
    inspect_page,
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
from .ollama_client import answer_question, extract_chunk
from .pdf_extract import extract_pdf
from .qa import (
    benchmark_hit,
    build_answer_prompt,
    resolve_chat_followup,
    evaluate_answer_quality,
    load_qa_benchmark,
    normalize_answer_role,
    question_to_fts_query,
    rank_model_summaries,
    retrieve_with_fallbacks,
    summarize_answer_items,
)
from .section_presets import CONTENT_ROLES, PRESETS, SECTION_LABELS, get_section_preset


ASK_ROLES = sorted([*CONTENT_ROLES, "all"])


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

    page_parser = _command(
        subcommands, "inspect-page", "Inspect one stored source page.", inspect_page_cmd
    )
    page_parser.add_argument("document_id", type=int)
    page_parser.add_argument("page_number", type=int)
    page_parser.add_argument("--raw", action="store_true")
    page_parser.add_argument("--limit", type=int, default=2000)

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
        choices=["all", "chunk_summaries", "key_terms", "questions", "topics", "examples"],
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

    ask_parser = _command(
        subcommands, "ask", "Answer a question using retrieved local PDF context.", ask_cmd
    )
    ask_parser.add_argument("document_id", type=int)
    ask_parser.add_argument("question")
    ask_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    ask_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    ask_parser.add_argument("--limit", type=int, default=5)
    ask_parser.add_argument("--chars", type=int, default=1200)
    ask_parser.add_argument("--model", help="Ollama model name.")
    ask_parser.add_argument(
        "--num-predict",
        type=int,
        help="Ollama output token budget for the answer.",
    )
    ask_parser.add_argument(
        "--debug-ollama",
        action="store_true",
        help="Print compact Ollama request/response diagnostics.",
    )
    ask_parser.add_argument(
        "--debug-retrieval",
        action="store_true",
        help="Print answer retrieval query attempts.",
    )
    ask_parser.add_argument(
        "--trace-dir",
        type=Path,
        help="Write one local JSON trace file for this answered question.",
    )

    chat_parser = _command(
        subcommands, "chat", "Ask repeated grounded questions in a local terminal loop.", chat_cmd
    )
    chat_parser.add_argument("document_id", type=int)
    chat_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    chat_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    chat_parser.add_argument("--limit", type=int, default=5)
    chat_parser.add_argument("--chars", type=int, default=1200)
    chat_parser.add_argument("--model", help="Ollama model name.")
    chat_parser.add_argument(
        "--num-predict",
        type=int,
        help="Ollama output token budget for each answer.",
    )
    chat_parser.add_argument(
        "--debug-ollama",
        action="store_true",
        help="Print compact Ollama request/response diagnostics.",
    )
    chat_parser.add_argument(
        "--debug-retrieval",
        action="store_true",
        help="Print answer retrieval query attempts.",
    )
    chat_parser.add_argument(
        "--trace-dir",
        type=Path,
        help="Write one local JSON trace file per answered question.",
    )

    bench_parser = _command(
        subcommands, "qa-bench", "Run a retrieval benchmark for local PDF QA.", qa_bench_cmd
    )
    bench_parser.add_argument("document_id", type=int)
    bench_parser.add_argument("--benchmark", type=Path, required=True)
    bench_parser.add_argument("--ask", action="store_true", help="Also call Ollama for answer previews.")
    bench_parser.add_argument("--no-ask", action="store_true", help="Retrieval-only mode. This is the default.")
    bench_parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Retrieved context chunks per benchmark question.",
    )
    bench_parser.add_argument(
        "--max-questions",
        type=int,
        help="Maximum benchmark questions to run; useful for smoke tests.",
    )
    bench_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    bench_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    bench_parser.add_argument("--model", help="Ollama model name for --ask runs.")
    bench_parser.add_argument(
        "--models",
        help="Comma-separated Ollama model names for comparison, e.g. gemma-python,gemma-fast.",
    )
    bench_parser.add_argument(
        "--num-predict",
        type=int,
        help="Ollama output token budget for --ask answers.",
    )
    bench_parser.add_argument("--output", type=Path)

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


def inspect_page_cmd(args: argparse.Namespace) -> int:
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


def ask_cmd(args: argparse.Namespace) -> int:
    settings, conn = open_db(args)
    _validate_answer_options(args, settings)
    _answer_once(
        settings=settings,
        conn=conn,
        document_id=args.document_id,
        question=args.question,
        role=args.role,
        section=args.section,
        limit=args.limit,
        chars=args.chars,
        model_name=args.model or settings.ollama_model,
        num_predict=structure_num_predict(args, settings),
        debug_retrieval=args.debug_retrieval,
        debug_ollama=args.debug_ollama,
        trace_dir=args.trace_dir,
        mode="ask",
    )
    return 0


def chat_cmd(args: argparse.Namespace) -> int:
    settings, conn = open_db(args)
    _validate_answer_options(args, settings)
    model_name = args.model or settings.ollama_model
    num_predict = structure_num_predict(args, settings)

    print(f"ethnos chat for document {args.document_id}")
    print(f"model: {model_name}")
    print("Type quit, exit, or :q to leave.")
    previous_question = None
    previous_retrieval = None

    try:
        while True:
            try:
                question = input("ethnos> ").strip()
            except EOFError:
                print()
                break
            if not question:
                continue
            if question.lower() in {"quit", "exit", ":q"}:
                break
            followup = resolve_chat_followup(
                question,
                previous_question=previous_question,
                previous_retrieval=previous_retrieval,
            )
            print()
            previous_retrieval = _answer_once(
                settings=settings,
                conn=conn,
                document_id=args.document_id,
                question=question,
                retrieval_question=followup.rewritten_question or question,
                role=args.role,
                section=args.section,
                limit=args.limit,
                chars=args.chars,
                model_name=model_name,
                num_predict=num_predict,
                debug_retrieval=args.debug_retrieval,
                debug_ollama=args.debug_ollama,
                trace_dir=args.trace_dir,
                mode="chat",
                followup=followup,
            )
            previous_question = question
            print()
    except KeyboardInterrupt:
        print("\nExiting.")
    return 0


def _validate_answer_options(args: argparse.Namespace, settings) -> None:
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    num_predict = structure_num_predict(args, settings)
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")


def _answer_once(
    *,
    settings,
    conn,
    document_id: int,
    question: str,
    retrieval_question: str | None = None,
    role: str,
    section: str | None,
    limit: int,
    chars: int,
    model_name: str,
    num_predict: int,
    debug_retrieval: bool,
    debug_ollama: bool,
    trace_dir: Path | None,
    mode: str,
    followup=None,
):
    started_at = time.monotonic()
    retrieval_question = retrieval_question or question
    selected_role = normalize_answer_role(role)
    retrieval = _retrieve_answer_context(
        conn,
        document_id=document_id,
        question=retrieval_question,
        limit=limit,
        role=selected_role,
        section=section,
    )
    print(f"Question: {question}")
    if debug_retrieval or debug_ollama:
        if followup is not None:
            _print_followup_debug(followup)
        if retrieval_question != question:
            print(f"Retrieval question: {retrieval_question}")
        _print_retrieval_debug(retrieval)
    print()
    if not retrieval.rows:
        answer_text = "The document context did not contain enough information to answer this question."
        elapsed = time.monotonic() - started_at
        print("Selected context chunks: none")
        print()
        print("Answer:")
        print(answer_text)
        _maybe_write_answer_trace(
            trace_dir=trace_dir,
            document_id=document_id,
            question=question,
            retrieval=retrieval,
            model_name=model_name,
            num_predict=num_predict,
            answer_text=answer_text,
            elapsed_seconds=elapsed,
            context_found=False,
            mode=mode,
            followup=followup,
            rewritten_retrieval_question=(
                retrieval_question if retrieval_question != question else None
            ),
        )
        return retrieval

    print("Selected context chunks:")
    _print_context_sources(retrieval.rows)
    prompt_question = question
    if followup is not None and followup.detected and retrieval_question != question:
        prompt_question = (
            f"{question}\n"
            f"Resolved follow-up for retrieval: {retrieval_question}"
        )
    prompt = build_answer_prompt(prompt_question, retrieval.rows, max_chars=chars)
    result = answer_question(
        prompt=prompt,
        model_name=model_name,
        host=settings.ollama_host,
        timeout=settings.ollama_timeout,
        num_predict=num_predict,
        debug_ollama=debug_ollama,
    )
    elapsed = time.monotonic() - started_at
    if debug_ollama:
        _print_ollama_debug(None, result.debug_info)
    answer_text = result.raw_response.strip() or "The document context did not contain enough information."
    print()
    print("Answer:")
    print(answer_text)
    print()
    print("Sources:")
    _print_context_sources(retrieval.rows)
    _maybe_write_answer_trace(
        trace_dir=trace_dir,
        document_id=document_id,
        question=question,
        retrieval=retrieval,
        model_name=model_name,
        num_predict=num_predict,
        answer_text=answer_text,
        elapsed_seconds=elapsed,
        context_found=True,
        mode=mode,
        followup=followup,
        rewritten_retrieval_question=(
            retrieval_question if retrieval_question != question else None
        ),
    )
    return retrieval


def qa_bench_cmd(args: argparse.Namespace) -> int:
    settings, conn = open_db(args)
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.ask and args.no_ask:
        raise SystemExit("Use either --ask or --no-ask, not both.")
    if args.models and not args.ask:
        raise SystemExit("--models requires --ask.")
    num_predict = structure_num_predict(args, settings)
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    selected_role = normalize_answer_role(args.role)
    items = load_qa_benchmark(args.benchmark)
    items = limit_benchmark_items(items, args.max_questions)
    if args.models:
        models = parse_models_arg(args.models)
        if not models:
            raise SystemExit("--models did not include any model names.")
        return qa_bench_compare_models(
            args=args,
            settings=settings,
            conn=conn,
            items=items,
            selected_role=selected_role,
            num_predict=num_predict,
            models=models,
        )
    started_at = time.monotonic()
    report_items = []
    hits = misses = no_context = 0
    answer_counts = Counter()
    run_answers = bool(args.ask)

    for item in items:
        item_started_at = time.monotonic()
        item_number = len(report_items) + 1
        retrieval = _retrieve_answer_context(
            conn,
            document_id=args.document_id,
            question=item["question"],
            limit=args.limit,
            role=selected_role,
            section=args.section,
        )
        hit = benchmark_hit(item, retrieval.rows)
        hits += int(hit)
        misses += int(not hit)
        no_context += int(not retrieval.rows)
        selected_chunks = [row["id"] for row in retrieval.rows]
        selected_citations = [row["source_citation"] for row in retrieval.rows]

        print(f"{item['id']}: {item['question']}")
        if run_answers:
            print(progress_line(args.model or settings.ollama_model, item_number, len(items), item["id"]), flush=True)
        print(f"  derived query: {retrieval.queries_tried[0] if retrieval.queries_tried else ''}")
        print(f"  fallback queries tried: {', '.join(retrieval.queries_tried)}")
        print(f"  selected chunks: {', '.join(str(chunk) for chunk in selected_chunks) or 'none'}")
        print(f"  selected source citations: {', '.join(selected_citations) or 'none'}")
        print(f"  expected chunks: {item.get('expected_source_chunks', 'not specified')}")
        print(f"  expected pages: {item.get('expected_source_pages', 'not specified')}")
        print(f"  status: {'hit' if hit else 'miss'}")

        answer_text = None
        answer_preview = None
        answer_evaluation = None
        answer_elapsed = None
        if run_answers and retrieval.rows:
            prompt = build_answer_prompt(item["question"], retrieval.rows, max_chars=1200)
            answer_started_at = time.monotonic()
            print("  answer generation: start", flush=True)
            result = answer_question(
                prompt=prompt,
                model_name=args.model or settings.ollama_model,
                host=settings.ollama_host,
                timeout=settings.ollama_timeout,
                num_predict=num_predict,
            )
            answer_elapsed = time.monotonic() - answer_started_at
            print(f"  answer generation elapsed: {format_elapsed(answer_elapsed)}", flush=True)
            answer_text = result.raw_response.strip()
            answer_preview = preview_text(result.raw_response, 400)
        if run_answers:
            answer_evaluation = evaluate_answer_quality(item, answer_text or "", retrieval.rows)
            answer_counts[answer_evaluation.status] += 1
            print(f"  answer status: {answer_evaluation.status}")
            if answer_evaluation.missing_expected_terms:
                print(
                    "  missing expected terms: "
                    + ", ".join(answer_evaluation.missing_expected_terms)
                )
            if answer_evaluation.forbidden_terms_found:
                print(
                    "  forbidden terms found: "
                    + ", ".join(answer_evaluation.forbidden_terms_found)
                )
            if answer_evaluation.citation_hit is not None:
                print(f"  citation hit: {answer_evaluation.citation_hit}")
            if answer_preview:
                print(f"  answer preview: {answer_preview}")
        print()

        item_elapsed = time.monotonic() - item_started_at
        report_items.append(
            {
                "id": item["id"],
                "question": item["question"],
                "derived_query": retrieval.queries_tried[0] if retrieval.queries_tried else "",
                "queries_tried": retrieval.queries_tried,
                "selected_query": retrieval.selected_query,
                "selected_chunks": selected_chunks,
                "selected_source_citations": selected_citations,
                "expected_source_chunks": item.get("expected_source_chunks"),
                "expected_source_pages": item.get("expected_source_pages"),
                "hit": hit,
                "stopped_reason": retrieval.stopped_reason,
                "answer_text": answer_text,
                "answer_preview": answer_preview,
                "answer_evaluation": (
                    {
                        "status": answer_evaluation.status,
                        "missing_expected_terms": answer_evaluation.missing_expected_terms,
                        "forbidden_terms_found": answer_evaluation.forbidden_terms_found,
                        "citation_hit": answer_evaluation.citation_hit,
                        "expected_citations": answer_evaluation.expected_citations,
                    }
                    if answer_evaluation is not None
                    else None
                ),
                "timings": {
                    "item_seconds": item_elapsed,
                    "answer_seconds": answer_elapsed,
                },
            }
        )

    elapsed = time.monotonic() - started_at
    print("QA benchmark summary:")
    print(f"  total: {len(items)}")
    print(f"  hits: {hits}")
    print(f"  misses: {misses}")
    print(f"  no-context cases: {no_context}")
    if run_answers:
        print(f"  answer pass: {answer_counts['pass']}")
        print(f"  answer partial: {answer_counts['partial']}")
        print(f"  answer fail: {answer_counts['fail']}")
        print(f"  no-context expected: {answer_counts['no_context_expected']}")
        print(f"  no-context unexpected: {answer_counts['no_context_unexpected']}")
    print(f"  elapsed: {format_elapsed(elapsed)}")

    if args.output:
        report = {
            "document_id": args.document_id,
            "benchmark": str(args.benchmark),
            "total": len(items),
            "hits": hits,
            "misses": misses,
            "no_context_cases": no_context,
            "answer_pass": answer_counts["pass"] if run_answers else None,
            "answer_partial": answer_counts["partial"] if run_answers else None,
            "answer_fail": answer_counts["fail"] if run_answers else None,
            "no_context_expected": answer_counts["no_context_expected"] if run_answers else None,
            "no_context_unexpected": (
                answer_counts["no_context_unexpected"] if run_answers else None
            ),
            "elapsed_seconds": elapsed,
            "items": report_items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote report: {args.output}")
    return 0


def qa_bench_compare_models(
    *,
    args: argparse.Namespace,
    settings,
    conn,
    items: list[dict],
    selected_role: str | None,
    num_predict: int,
    models: list[str],
) -> int:
    started_at = time.monotonic()
    retrieval_entries = []
    retrieval_hits = retrieval_misses = no_context = 0
    for item in items:
        retrieval = _retrieve_answer_context(
            conn,
            document_id=args.document_id,
            question=item["question"],
            limit=args.limit,
            role=selected_role,
            section=args.section,
        )
        hit = benchmark_hit(item, retrieval.rows)
        retrieval_hits += int(hit)
        retrieval_misses += int(not hit)
        no_context += int(not retrieval.rows)
        retrieval_entries.append(
            {
                "item": item,
                "retrieval": retrieval,
                "hit": hit,
                "selected_chunks": [row["id"] for row in retrieval.rows],
                "selected_citations": [row["source_citation"] for row in retrieval.rows],
            }
        )

    print("QA model comparison")
    print(f"  benchmark: {args.benchmark}")
    print(f"  models: {', '.join(models)}")
    print(f"  retrieval hits: {retrieval_hits}")
    print(f"  retrieval misses: {retrieval_misses}")
    print(f"  no-context cases: {no_context}")
    print()

    model_reports = []
    model_summaries = []
    for model_name in models:
        print(f"Model: {model_name}", flush=True)
        model_started_at = time.monotonic()
        model_items = []
        for index, entry in enumerate(retrieval_entries, start=1):
            item = entry["item"]
            retrieval = entry["retrieval"]
            answer_text = None
            answer_preview = None
            answer_evaluation = None
            answer_elapsed = None
            model_error = None
            print(progress_line(model_name, index, len(retrieval_entries), item["id"]), flush=True)
            if retrieval.rows:
                prompt = build_answer_prompt(item["question"], retrieval.rows, max_chars=1200)
                answer_started_at = time.monotonic()
                print("  answer generation: start", flush=True)
                try:
                    result = answer_question(
                        prompt=prompt,
                        model_name=model_name,
                        host=settings.ollama_host,
                        timeout=settings.ollama_timeout,
                        num_predict=num_predict,
                    )
                    answer_elapsed = time.monotonic() - answer_started_at
                    print(
                        f"  answer generation elapsed: {format_elapsed(answer_elapsed)}",
                        flush=True,
                    )
                    answer_text = result.raw_response.strip()
                    answer_preview = preview_text(result.raw_response, 240)
                    answer_evaluation = evaluate_answer_quality(
                        item, answer_text, retrieval.rows
                    )
                except Exception as exc:  # Ollama error types vary by version.
                    answer_elapsed = time.monotonic() - answer_started_at
                    print(
                        f"  answer generation elapsed: {format_elapsed(answer_elapsed)}",
                        flush=True,
                    )
                    model_error = str(exc)
                    answer_evaluation = {
                        "status": "model_error",
                        "error": model_error,
                        "missing_expected_terms": [],
                        "forbidden_terms_found": [],
                        "citation_hit": None,
                        "expected_citations": [],
                    }
            else:
                evaluation = evaluate_answer_quality(item, "", retrieval.rows)
                answer_evaluation = {
                    "status": evaluation.status,
                    "missing_expected_terms": evaluation.missing_expected_terms,
                    "forbidden_terms_found": evaluation.forbidden_terms_found,
                    "citation_hit": evaluation.citation_hit,
                    "expected_citations": evaluation.expected_citations,
                }

            if hasattr(answer_evaluation, "status"):
                evaluation_dict = {
                    "status": answer_evaluation.status,
                    "missing_expected_terms": answer_evaluation.missing_expected_terms,
                    "forbidden_terms_found": answer_evaluation.forbidden_terms_found,
                    "citation_hit": answer_evaluation.citation_hit,
                    "expected_citations": answer_evaluation.expected_citations,
                }
            else:
                evaluation_dict = answer_evaluation

            print(
                f"  {item['id']}: retrieval={'hit' if entry['hit'] else 'miss'}, "
                f"answer={evaluation_dict['status']}"
            )
            if model_error:
                print(f"    model error: {model_error}")
            elif answer_preview:
                print(f"    preview: {answer_preview}")

            model_items.append(
                {
                    "id": item["id"],
                    "question": item["question"],
                    "model": model_name,
                    "derived_query": (
                        retrieval.queries_tried[0] if retrieval.queries_tried else ""
                    ),
                    "queries_tried": retrieval.queries_tried,
                    "selected_query": retrieval.selected_query,
                    "selected_chunks": entry["selected_chunks"],
                    "selected_source_citations": entry["selected_citations"],
                    "expected_source_chunks": item.get("expected_source_chunks"),
                    "expected_source_pages": item.get("expected_source_pages"),
                    "hit": entry["hit"],
                    "stopped_reason": retrieval.stopped_reason,
                    "answer_text": answer_text,
                    "answer_preview": answer_preview,
                    "answer_evaluation": evaluation_dict,
                    "timings": {
                        "answer_seconds": answer_elapsed,
                    },
                    "model_error": model_error,
                }
            )
        model_elapsed = time.monotonic() - model_started_at
        summary = summarize_answer_items(model_items)
        summary["model"] = model_name
        summary["total_elapsed_seconds"] = model_elapsed
        model_reports.append({"model": model_name, "summary": summary, "items": model_items})
        model_summaries.append(summary)
        _print_model_summary(summary)
        print()

    ranking = rank_model_summaries(model_summaries)
    elapsed = time.monotonic() - started_at
    print("Model comparison ranked summary:")
    print(f"  best pass count: {', '.join(ranking['best_pass_count']) or 'none'}")
    print(f"  lowest fail count: {', '.join(ranking['lowest_fail_count']) or 'none'}")
    print(f"  fastest among models with no failures: {ranking['fastest_no_fail'] or 'none'}")
    print(f"  elapsed total: {format_elapsed(elapsed)}")

    if args.output:
        report = {
            "document_id": args.document_id,
            "benchmark": str(args.benchmark),
            "mode": "model_compare",
            "models": models,
            "retrieval_summary": {
                "total": len(items),
                "hits": retrieval_hits,
                "misses": retrieval_misses,
                "no_context_cases": no_context,
            },
            "ranking": ranking,
            "model_summaries": model_summaries,
            "models_report": model_reports,
            "elapsed_seconds": elapsed,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote report: {args.output}")
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
    for section in ["chunk_summaries", "key_terms", "questions", "topics", "examples"]:
        print(f"{section}:")
        if not records[section]:
            print("  none")
            continue
        for row in records[section]:
            _print_record({"record_type": section, **row})


def _print_record(row: dict) -> None:
    record_type = row["record_type"]
    source_pages = format_source_pages(row.get("source_pages"))
    if record_type == "chunk_summaries":
        print(f"[chunk_summary] chunk {row['chunk_id']}")
        print(f"  summary: {row['summary']}")
    elif record_type == "key_terms":
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


def parse_models_arg(value: str) -> list[str]:
    models = []
    for part in value.split(","):
        model = part.strip()
        if model and model not in models:
            models.append(model)
    return models


def limit_benchmark_items(items: list[dict], max_questions: int | None) -> list[dict]:
    if max_questions is None:
        return items
    return items[:max_questions]


def progress_line(model_name: str, question_number: int, total_questions: int, question_id: str) -> str:
    return f"[{model_name}] question {question_number}/{total_questions}: {question_id}"


def _print_model_summary(summary: dict) -> None:
    print("  summary:")
    print(f"    total questions: {summary['total']}")
    print(f"    retrieval hits: {summary['retrieval_hits']}")
    print(f"    retrieval misses: {summary['retrieval_misses']}")
    print(f"    answer pass: {summary['answer_pass']}")
    print(f"    answer partial: {summary['answer_partial']}")
    print(f"    answer fail: {summary['answer_fail']}")
    print(f"    no-context expected: {summary['no_context_expected']}")
    print(f"    no-context unexpected: {summary['no_context_unexpected']}")
    print(f"    model errors: {summary['model_error']}")
    print(f"    total elapsed: {format_elapsed(summary['total_elapsed_seconds'])}")
    average_seconds = summary.get("average_answer_seconds")
    average_length = summary.get("average_answer_length")
    print(
        f"    average answer time: "
        f"{average_seconds:.1f}s" if average_seconds is not None else "    average answer time: n/a"
    )
    print(
        f"    average answer length: "
        f"{average_length:.0f} chars" if average_length is not None else "    average answer length: n/a"
    )


def _retrieve_answer_context(
    conn,
    *,
    document_id: int,
    question: str,
    limit: int,
    role: str | None,
    section: str | None,
):
    return retrieve_with_fallbacks(
        search_func=lambda doc_id, query, limit, role, section: add_continuation_context_chunks(
            conn,
            doc_id,
            context_chunks(
                conn,
                doc_id,
                query,
                limit=limit,
                role=role,
                section=section,
            ),
            role=role,
            section=section,
        ),
        document_id=document_id,
        question=question,
        limit=limit,
        role=role,
        section=section,
    )


def _print_followup_debug(followup) -> None:
    print("Follow-up debug:")
    print(f"  follow-up detected: {followup.detected}")
    print(f"  previous question: {followup.previous_question or 'none'}")
    print(f"  previous topic/query: {followup.previous_topic or 'none'}")
    print(f"  rewritten retrieval question: {followup.rewritten_question or 'none'}")


def _print_retrieval_debug(retrieval) -> None:
    print("Retrieval debug:")
    print(f"  original question: {retrieval.original_question}")
    print(f"  comparison detected: {retrieval.comparison_detected}")
    if retrieval.comparison_detected:
        print(f"  subqueries: {', '.join(retrieval.comparison_subqueries)}")
        for result in retrieval.subquery_results:
            print(f"  subquery: {result.subquery}")
            print(f"    fallback queries tried: {', '.join(result.queries_tried)}")
            print(
                "    selected chunks: "
                + (
                    ", ".join(str(row["id"]) for row in result.rows)
                    if result.rows
                    else "none"
                )
            )
        print(
            "  merged selected chunks: "
            + (
                ", ".join(str(row["id"]) for row in retrieval.rows)
                if retrieval.rows
                else "none"
            )
        )
    print(f"  derived query: {retrieval.queries_tried[0] if retrieval.queries_tried else ''}")
    print(f"  fallback queries tried: {', '.join(retrieval.queries_tried)}")
    print(f"  selected query: {retrieval.selected_query or 'none'}")
    print(
        "  selected chunks: "
        + (", ".join(str(row["id"]) for row in retrieval.rows) if retrieval.rows else "none")
    )
    print(f"  stopped reason: {retrieval.stopped_reason}")


def _print_context_sources(rows: list[dict]) -> None:
    for row in rows:
        print(
            f"  chunk {row['id']}: {row['source_citation']} "
            f"({row['section_label'] or 'unlabeled'} / {row['content_role'] or 'unlabeled'})"
        )


def _maybe_write_answer_trace(
    *,
    trace_dir: Path | None,
    document_id: int,
    question: str,
    retrieval,
    model_name: str,
    num_predict: int,
    answer_text: str,
    elapsed_seconds: float,
    context_found: bool,
    mode: str,
    followup=None,
    rewritten_retrieval_question: str | None = None,
) -> Path | None:
    if trace_dir is None:
        return None
    timestamp = datetime.now(timezone.utc)
    trace_dir.mkdir(parents=True, exist_ok=True)
    path = trace_dir / _answer_trace_filename(timestamp, mode, question)
    trace = {
        "timestamp": timestamp.isoformat(),
        "document_id": document_id,
        "question": question,
        "derived_query": retrieval.queries_tried[0] if retrieval.queries_tried else "",
        "fallback_queries_tried": retrieval.queries_tried[1:],
        "selected_query": retrieval.selected_query,
        "comparison_detected": retrieval.comparison_detected,
        "comparison_subqueries": retrieval.comparison_subqueries,
        "comparison_subquery_results": [
            {
                "subquery": result.subquery,
                "queries_tried": result.queries_tried,
                "selected_query": result.selected_query,
                "selected_chunks": [_trace_chunk(row) for row in result.rows],
                "stopped_reason": result.stopped_reason,
            }
            for result in retrieval.subquery_results
        ],
        "selected_chunks": [_trace_chunk(row) for row in retrieval.rows],
        "model": model_name,
        "num_predict": num_predict,
        "answer_text": answer_text,
        "elapsed_seconds": elapsed_seconds,
        "context_found": context_found,
        "command_mode": mode,
        "follow_up_detected": bool(followup.detected) if followup is not None else False,
        "previous_question": (
            followup.previous_question if followup is not None else None
        ),
        "previous_topic": followup.previous_topic if followup is not None else None,
        "rewritten_retrieval_question": rewritten_retrieval_question,
    }
    path.write_text(json.dumps(trace, indent=2, sort_keys=True), encoding="utf-8")
    print()
    print(f"Trace: {path}")
    return path


def _answer_trace_filename(timestamp: datetime, mode: str, question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:48]
    if not slug:
        slug = "question"
    return f"{timestamp.strftime('%Y%m%dT%H%M%S%fZ')}-{mode}-{slug}.json"


def _trace_chunk(row: dict) -> dict:
    return {
        "chunk_id": row["id"],
        "chunk_index": row["chunk_index"],
        "source_citation": row["source_citation"],
        "section_label": row["section_label"],
        "content_role": row["content_role"],
        "page_start": row["page_start"],
        "page_end": row["page_end"],
    }


def preview_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def limit_display_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... [truncated]"


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
