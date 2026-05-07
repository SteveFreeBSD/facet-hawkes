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
    connect,
    create_extraction_run,
    db_info,
    apply_section_preset,
    finish_extraction_run,
    get_document,
    init_db,
    list_chunks,
    list_documents,
    list_pages,
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
from .section_presets import PRESETS, get_section_preset


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

    search_parser = _command(subcommands, "search", "Search chunks with SQLite FTS5.", search)
    search_parser.add_argument("query")
    search_parser.add_argument("--limit", type=int, default=10)

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


def search(args: argparse.Namespace) -> int:
    _, conn = open_db(args)
    results = search_chunks(conn, args.query, args.limit)
    for result in results:
        print(f"[{result['source_citation']}]")
        print(result["snippet"])
        print()
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


def _write_or_print(text: str, output: Path | None) -> None:
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    raise SystemExit(main())
