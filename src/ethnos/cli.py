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
    list_pages,
    save_chunks,
    save_document_pages,
    save_extraction_result,
    save_model_output,
    search_chunks,
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
    chunks = list_chunks(conn, args.document_id)
    if not chunks:
        raise SystemExit("No chunks found. Run `ethnos chunk DOC_ID` first.")

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
        )
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
            continue
        save_extraction_result(conn, chunk.id, result.result)
        valid_count += 1

    status = "completed" if failed_count == 0 else "completed_with_errors"
    finish_extraction_run(conn, run_id, status=status, error_message=last_error)
    print(f"Structured {valid_count} chunks; {failed_count} failed. Run id: {run_id}")
    return 0 if failed_count == 0 else 1


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


def _write_or_print(text: str, output: Path | None) -> None:
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote {output}")


if __name__ == "__main__":
    raise SystemExit(main())
