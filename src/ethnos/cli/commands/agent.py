"""Agentic source review commands."""

from __future__ import annotations

import json
from pathlib import Path
import sys

from ..shared import add_command, open_db

from ...agent_loop import run_agent_review
from ...agent_models import MODEL_PROFILES, resolve_model_profile
from ...db import (
    agent_report_summary,
    create_agent_run,
    finish_agent_run,
    get_document,
    save_agent_findings,
)
from ...quiz import load_quiz


def register(subcommands):
    parser = add_command(
        subcommands,
        "agent-review",
        "Run a source-grounded agent review over a quiz fixture.",
        agent_review_cmd,
    )
    parser.add_argument("document_id", type=int)
    parser.add_argument("--quiz", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", help="Ollama model name for the agent.")
    parser.add_argument(
        "--profile",
        "--model-profile",
        dest="model_profile",
        choices=sorted([*MODEL_PROFILES, "cto"]),
        help="Agent model profile. 'cto' is an alias for review-local.",
    )
    parser.add_argument(
        "--allow-web",
        action="store_true",
        help="Permit Ollama web search/fetch tools during review.",
    )
    parser.add_argument(
        "--vision-pages",
        choices=["auto", "off", "on"],
        help="Allow rendered PDF page image inspection with a vision model.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=8,
        help=(
            "Maximum model tool-loop steps per item; 0 runs deterministic "
            "preflight/fallback only."
        ),
    )
    parser.add_argument(
        "--item-timeout",
        type=float,
        default=0,
        help="Maximum seconds for one quiz item before deterministic fallback; 0 disables.",
    )
    parser.add_argument("--debug-agent", action="store_true")


def agent_review_cmd(args) -> int:
    if args.max_steps < 0:
        raise SystemExit("--max-steps must be 0 or greater.")
    if args.item_timeout < 0:
        raise SystemExit("--item-timeout must be 0 or greater.")
    settings, conn = open_db(args)
    get_document(conn, args.document_id)
    explicit_model = args.model or settings.agent_model
    requested_profile = args.model_profile or settings.agent_model_profile
    if requested_profile == "cto":
        requested_profile = "review-local"
    profile = resolve_model_profile(
        requested_profile,
        explicit_model,
    )
    allow_web = bool(
        args.allow_web or settings.agent_allow_web or profile.allow_web_default
    )
    vision_pages = (
        args.vision_pages or settings.agent_vision_pages or profile.vision_pages_default
    )
    if vision_pages not in {"auto", "off", "on"}:
        raise SystemExit("agent vision pages must be one of auto, off, or on.")
    model_name = explicit_model or profile.recommended_model
    quiz = load_quiz(args.quiz)
    config = {
        "allow_web": allow_web,
        "vision_pages": vision_pages,
        "max_steps": args.max_steps,
        "item_timeout": args.item_timeout,
        "debug_agent": args.debug_agent,
        "model_profile": profile.name,
    }
    run_id = create_agent_run(
        conn,
        document_id=args.document_id,
        quiz_path=args.quiz,
        model_name=model_name,
        model_profile=profile.name,
        config=config,
        output_path=args.output,
    )
    try:
        from .. import create_client as _create_client

        client = (
            None
            if args.max_steps == 0
            else _create_client(settings.ollama_host, settings.ollama_timeout)
        )
        report = run_agent_review(
            conn=conn,
            document_id=args.document_id,
            quiz=quiz,
            quiz_path=args.quiz,
            output_dir=args.output,
            model_name=model_name,
            model_profile=profile,
            allow_web=allow_web,
            vision_pages=vision_pages,
            max_steps=args.max_steps,
            item_timeout=args.item_timeout or None,
            debug_agent=args.debug_agent,
            client=client,
            progress=_agent_review_progress,
        )
        save_agent_findings(conn, run_id, report.items)
        summary = agent_report_summary(report)
        finish_agent_run(conn, run_id, status="succeeded", summary=summary)
    except Exception as exc:
        finish_agent_run(
            conn,
            run_id,
            status="failed",
            summary={"error": str(exc)},
            error_message=str(exc),
        )
        raise
    print("Agent review")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  output: {args.output}")
    print(f"  model: {model_name}")
    print(f"  profile: {profile.name}")
    print(f"  items: {report.item_count}")
    print(f"  verdicts: {json.dumps(report.verdict_counts, sort_keys=True)}")
    print(f"  quality findings: {json.dumps(report.quality_counts, sort_keys=True)}")
    print(f"  model finalized: {getattr(report, 'model_finalized_count', 0)}")
    print(f"  deterministic fallback: {getattr(report, 'fallback_item_count', 0)}")
    return 0


def _agent_review_progress(index: int, total: int, item: dict[str, object]) -> None:
    item_id = item.get("id") or index
    print(f"agent-review item {index}/{total}: {item_id}", file=sys.stderr, flush=True)
