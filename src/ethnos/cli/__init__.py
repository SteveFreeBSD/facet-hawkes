"""Command-line interface package for ethnos."""

from __future__ import annotations

import argparse
from pathlib import Path

from .commands import agent as agent_commands
from .commands import ask as ask_commands
from .commands import bench as bench_commands
from .commands import export as export_commands
from .commands import ingest as ingest_commands
from .commands import inspect as inspect_commands
from .commands import quiz as quiz_commands
from .commands.quiz import _add_quiz_source_context
from .formatting import _print_ollama_debug
from .shared import (
    ASK_ROLES,
    answer_num_predict,
    limit_benchmark_items,
    ollama_num_ctx,
    parse_models_arg,
    progress_line,
    structure_num_predict,
    _ollama_done_reason,
)
from ..ollama_client import (
    answer_choice_question,
    answer_essay_question,
    answer_mc_question,
    answer_question,
    create_client,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ethnos",
        description="Local-first PDF-to-knowledge pipeline.",
    )
    parser.add_argument("--db", type=Path, help="SQLite database path.")
    subcommands = parser.add_subparsers(dest="command")
    agent_commands.register(subcommands)
    ingest_commands.register(subcommands)
    inspect_commands.register(subcommands)
    ask_commands.register(subcommands)
    bench_commands.register(subcommands)
    quiz_commands.register(subcommands)
    export_commands.register(subcommands)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 2
    return args.handler(args)


__all__ = [
    "ASK_ROLES",
    "answer_choice_question",
    "answer_essay_question",
    "answer_mc_question",
    "answer_num_predict",
    "answer_question",
    "build_parser",
    "create_client",
    "limit_benchmark_items",
    "main",
    "ollama_num_ctx",
    "parse_models_arg",
    "progress_line",
    "structure_num_predict",
    "_add_quiz_source_context",
    "_ollama_done_reason",
    "_print_ollama_debug",
]
