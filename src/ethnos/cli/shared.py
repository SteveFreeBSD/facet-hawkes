"""Shared CLI utilities used across command modules."""

from __future__ import annotations

import argparse
from typing import Callable

from ..config import load_settings
from ..db import connect, init_db
from ..section_presets import CONTENT_ROLES


ASK_ROLES = sorted([*CONTENT_ROLES, "all"])


def open_db(args: argparse.Namespace):
    settings = load_settings()
    db_path = args.db or settings.db_path
    conn = connect(db_path)
    init_db(conn)
    return settings, conn


def structure_num_predict(args: argparse.Namespace, settings) -> int:
    return (
        args.num_predict
        if args.num_predict is not None
        else settings.ollama_structure_num_predict
    )


def answer_num_predict(args: argparse.Namespace, settings) -> int:
    return (
        args.num_predict
        if args.num_predict is not None
        else settings.ollama_answer_num_predict
    )


def ollama_num_ctx(args: argparse.Namespace, settings) -> int:
    return (
        args.num_ctx
        if getattr(args, "num_ctx", None) is not None
        else settings.ollama_num_ctx
    )


def _ollama_done_reason(result) -> str | None:
    if result.debug_info is None or result.debug_info.response_summary is None:
        return None
    done_reason = result.debug_info.response_summary.get("done_reason")
    return done_reason if isinstance(done_reason, str) else None


def _validate_answer_options(args: argparse.Namespace, settings) -> None:
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    num_predict = answer_num_predict(args, settings)
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if ollama_num_ctx(args, settings) < 1:
        raise SystemExit("--num-ctx must be 1 or greater.")


def limit_benchmark_items(items: list[dict], max_questions: int | None) -> list[dict]:
    if max_questions is None:
        return items
    return items[:max_questions]


def parse_models_arg(value: str) -> list[str]:
    models = []
    for part in value.split(","):
        model = part.strip()
        if model and model not in models:
            models.append(model)
    return models


def progress_line(
    model_name: str, question_number: int, total_questions: int, question_id: str
) -> str:
    return f"[{model_name}] question {question_number}/{total_questions}: {question_id}"


def add_command(
    subcommands: argparse._SubParsersAction,
    name: str,
    help_text: str,
    handler: Callable[[argparse.Namespace], int],
) -> argparse.ArgumentParser:
    command = subcommands.add_parser(name, help=help_text)
    command.set_defaults(handler=handler)
    return command
