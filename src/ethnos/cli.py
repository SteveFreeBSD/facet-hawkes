"""Command-line interface for ethnos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from .chunking import build_chunks
from .config import load_settings
from .db import (
    connect,
    create_extraction_run,
    db_info,
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
    select_chunks_for_structure,
)
from .export import export_json, export_markdown
from .ollama_client import extract_chunk
from .pdf_extract import extract_pdf


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

    _command(subcommands, "db-info", "Show local database counts.", db_info_cmd)
    _command(subcommands, "documents", "List stored documents.", documents_cmd)
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
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")

    chunks = select_chunks_for_structure(
        conn,
        document_id=args.document_id,
        chunk_id=args.chunk_id,
        limit=args.limit,
    )
    if not chunks:
        raise SystemExit(
            "No matching chunks found. Run `ethnos chunk DOC_ID` first or check the chunk id."
        )

    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    print("Structure run preview:")
    print(f"  document id: {args.document_id}")
    print(f"  model: {model_name}")
    print(f"  chunks selected: {len(chunks)}")
    print(f"  chunk ids: {', '.join(str(chunk_id) for chunk_id in chunk_ids)}")
    if args.chunk_id is None and args.limit is None:
        print("  selection: full document")

    run_id = create_extraction_run(
        conn,
        document_id=args.document_id,
        model_name=model_name,
        prompt_name=settings.prompt_path.name,
    )
    valid_count = 0
    failed_count = 0
    last_error = None

    for chunk in chunks:
        if chunk.id is None:
            raise RuntimeError("Stored chunks must have database ids")
        result = extract_chunk(
            chunk=chunk,
            prompt_path=settings.prompt_path,
            model_name=model_name,
            host=settings.ollama_host,
            timeout=settings.ollama_timeout,
            debug_ollama=args.debug_ollama,
        )
        if args.debug_ollama:
            _print_ollama_debug(chunk.id, result.debug_info)
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
            if result.validation_status == "empty_response":
                print(
                    f"Warning: chunk {chunk.id} produced an empty Ollama response; "
                    "raw output was preserved."
                )
            continue
        save_extraction_result(conn, chunk.id, result.result)
        valid_count += 1

    status = "completed" if failed_count == 0 else "completed_with_errors"
    finish_extraction_run(conn, run_id, status=status, error_message=last_error)
    print(f"Structured {valid_count} chunks; {failed_count} failed. Run id: {run_id}")
    return 0 if failed_count == 0 else 1


def _print_ollama_debug(chunk_id: int | None, debug_info) -> None:
    if debug_info is None:
        print(f"Ollama debug for chunk {chunk_id}: unavailable")
        return
    print(f"Ollama debug for chunk {chunk_id}:")
    print(f"  prompt chars: {debug_info.prompt_char_length}")
    print(f"  schema top-level keys: {', '.join(debug_info.schema_top_level_keys)}")
    print(f"  format: {debug_info.format_kind}")
    if debug_info.response_summary is None:
        print("  response envelope: unavailable")
        return
    print("  response envelope:")
    for key, value in debug_info.response_summary.items():
        print(f"    {key}: {value}")


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


def _write_or_print(text: str, output: Path | None) -> None:
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    raise SystemExit(main())
