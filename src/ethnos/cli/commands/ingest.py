"""PDF ingestion, extraction, and chunking commands."""

from __future__ import annotations

from pathlib import Path
import time
from collections import Counter

from ..shared import add_command, open_db, structure_num_predict, ollama_num_ctx, _ollama_done_reason
from ..formatting import format_elapsed, _print_ollama_debug

from ...chunking import build_chunks
from ...db import (
    create_extraction_run,
    finish_extraction_run,
    get_document,
    list_pages,
    save_chunks,
    save_document_pages,
    save_extraction_result,
    save_model_output,
    select_chunks_for_structure,
)
from ...ollama_client import extract_chunk
from ...pdf_extract import extract_pdf


def register(subcommands):
    add_command(subcommands, "ingest-pdf", "Extract and store PDF pages.", ingest_pdf).add_argument(
        "path", type=Path
    )
    add_command(subcommands, "extract", "Rerun extraction for a stored document.", extract).add_argument(
        "document_id", type=int
    )

    chunk_parser = add_command(subcommands, "chunk", "Create page-aware chunks.", chunk_document)
    chunk_parser.add_argument("document_id", type=int)
    chunk_parser.add_argument("--target-chars", type=int, default=3000)
    chunk_parser.add_argument("--max-chars", type=int, default=4000)
    chunk_parser.add_argument("--overlap-chars", type=int, default=250)

    structure_parser = add_command(
        subcommands, "structure", "Run Ollama structured extraction.", structure
    )
    structure_parser.add_argument("document_id", type=int)
    structure_parser.add_argument("--model", help="Ollama model name.")
    structure_parser.add_argument(
        "--num-predict", type=int, help="Ollama output token budget for structured JSON.",
    )
    structure_parser.add_argument(
        "--num-ctx", type=int, help="Ollama context window token budget.",
    )
    selection = structure_parser.add_mutually_exclusive_group()
    selection.add_argument("--chunk-id", type=int, help="Process one stored chunk id.")
    selection.add_argument(
        "--limit", type=int,
        help="Process the first N chunks without a valid stored model output.",
    )
    structure_parser.add_argument(
        "--debug-ollama", action="store_true",
        help="Print compact Ollama request/response diagnostics.",
    )
    structure_parser.add_argument(
        "--retry-failed", action="store_true",
        help="Process chunks whose latest model output failed.",
    )
    structure_parser.add_argument(
        "--force", action="store_true",
        help="Reprocess selected chunks even if they already have valid output.",
    )
    structure_parser.add_argument(
        "--all-roles", action="store_true",
        help="Include admin/support chunks instead of the default core-only structure run.",
    )


def ingest_pdf(args) -> int:
    _, conn = open_db(args)
    document, pages = extract_pdf(args.path)
    document_id = save_document_pages(conn, document, pages)
    print(f"Ingested document {document_id}: {document.filename} ({len(pages)} pages)")
    return 0


def extract(args) -> int:
    _, conn = open_db(args)
    document = get_document(conn, args.document_id)
    extracted_document, pages = extract_pdf(Path(document.source_path))
    document_id = save_document_pages(conn, extracted_document, pages)
    print(f"Re-extracted document {document_id}: {extracted_document.filename} ({len(pages)} pages)")
    return 0


def chunk_document(args) -> int:
    _, conn = open_db(args)
    if args.target_chars < 1:
        raise SystemExit("--target-chars must be 1 or greater.")
    if args.max_chars < 1:
        raise SystemExit("--max-chars must be 1 or greater.")
    if args.overlap_chars < 0:
        raise SystemExit("--overlap-chars must be 0 or greater.")
    if args.overlap_chars >= args.max_chars:
        raise SystemExit("--overlap-chars must be less than --max-chars.")
    if args.target_chars > args.max_chars:
        raise SystemExit("--target-chars must be less than or equal to --max-chars.")
    document = get_document(conn, args.document_id)
    pages = list_pages(conn, args.document_id)
    chunks = build_chunks(
        document, pages,
        target_chars=args.target_chars,
        max_chars=args.max_chars,
        overlap_chars=args.overlap_chars,
    )
    save_chunks(conn, args.document_id, chunks)
    print(f"Stored {len(chunks)} chunks for document {args.document_id}")
    return 0


def structure(args) -> int:
    settings, conn = open_db(args)
    model_name = args.model or settings.ollama_model
    num_predict = structure_num_predict(args, settings)
    num_ctx = ollama_num_ctx(args, settings)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if num_ctx < 1:
        raise SystemExit("--num-ctx must be 1 or greater.")
    if args.force and args.retry_failed:
        raise SystemExit("Use either --force or --retry-failed, not both.")

    chunks = select_chunks_for_structure(
        conn,
        document_id=args.document_id,
        chunk_id=args.chunk_id,
        limit=args.limit,
        retry_failed=args.retry_failed,
        force=args.force,
        all_roles=args.all_roles,
    )
    if not chunks:
        print("No chunks selected.")
        print("Default structure runs process never-attempted core/unlabeled chunks only.")
        print("Use --all-roles to include admin/support chunks.")
        print("Use --retry-failed for chunks whose latest output failed, or --force to reprocess.")
        return 0

    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    print("Structure run preview:", flush=True)
    print(f"  document id: {args.document_id}", flush=True)
    print(f"  model: {model_name}", flush=True)
    print(f"  num_predict: {num_predict}", flush=True)
    print(f"  num_ctx: {num_ctx}", flush=True)
    print(f"  roles: {'all' if args.all_roles else 'core/unlabeled'}", flush=True)
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

    # Late import to support monkeypatching via "ethnos.cli.create_client"
    from .. import create_client as _create_client
    ollama_client = _create_client(settings.ollama_host, settings.ollama_timeout)
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
            num_ctx=num_ctx,
            debug_ollama=args.debug_ollama,
            think=settings.ollama_think,
            client=ollama_client,
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
