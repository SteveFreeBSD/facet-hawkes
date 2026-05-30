"""Ask and chat commands for grounded Q&A."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from ..shared import (
    ASK_ROLES,
    add_command,
    answer_num_predict,
    ollama_num_ctx,
    open_db,
    _ollama_done_reason,
    _validate_answer_options,
)
from ..formatting import (
    _print_context_sources,
    _print_followup_debug,
    _print_ollama_debug,
    _print_retrieval_debug,
)
from ..retrieval import retrieve_answer_context

from ...config import OllamaThink
from ...qa import (
    build_answer_prompt,
    normalize_answer_role,
    resolve_chat_followup,
)
from ...section_presets import SECTION_LABELS


def register(subcommands):
    ask_parser = add_command(
        subcommands,
        "ask",
        "Answer a question using retrieved local PDF context.",
        ask_cmd,
    )
    ask_parser.add_argument("document_id", type=int)
    ask_parser.add_argument("question")
    ask_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    ask_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    ask_parser.add_argument("--limit", type=int, default=5)
    ask_parser.add_argument("--chars", type=int, default=1200)
    ask_parser.add_argument("--model", help="Ollama model name.")
    ask_parser.add_argument(
        "--num-predict", type=int, help="Ollama output token budget for the answer."
    )
    ask_parser.add_argument(
        "--num-ctx", type=int, help="Ollama context window token budget."
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

    chat_parser = add_command(
        subcommands,
        "chat",
        "Ask repeated grounded questions in a local terminal loop.",
        chat_cmd,
    )
    chat_parser.add_argument("document_id", type=int)
    chat_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    chat_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    chat_parser.add_argument("--limit", type=int, default=5)
    chat_parser.add_argument("--chars", type=int, default=1200)
    chat_parser.add_argument("--model", help="Ollama model name.")
    chat_parser.add_argument(
        "--num-predict", type=int, help="Ollama output token budget for each answer."
    )
    chat_parser.add_argument(
        "--num-ctx", type=int, help="Ollama context window token budget."
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

    trace_parser = add_command(
        subcommands,
        "inspect-trace",
        "Summarize one local ask/chat JSON trace.",
        inspect_trace_cmd,
    )
    trace_parser.add_argument("trace_path", type=Path)
    trace_parser.add_argument(
        "--show-answer", action="store_true", help="Print the full stored answer text."
    )


def ask_cmd(args) -> int:
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
        num_predict=answer_num_predict(args, settings),
        num_ctx=ollama_num_ctx(args, settings),
        think=settings.ollama_think,
        debug_retrieval=args.debug_retrieval,
        debug_ollama=args.debug_ollama,
        trace_dir=args.trace_dir,
        mode="ask",
    )
    return 0


def chat_cmd(args) -> int:
    settings, conn = open_db(args)
    _validate_answer_options(args, settings)
    model_name = args.model or settings.ollama_model
    num_predict = answer_num_predict(args, settings)
    num_ctx = ollama_num_ctx(args, settings)

    # Late import to support monkeypatching via "ethnos.cli.create_client"
    from .. import create_client as _create_client

    ollama_client = _create_client(settings.ollama_host, settings.ollama_timeout)
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
                num_ctx=num_ctx,
                think=settings.ollama_think,
                debug_retrieval=args.debug_retrieval,
                debug_ollama=args.debug_ollama,
                trace_dir=args.trace_dir,
                mode="chat",
                followup=followup,
                client=ollama_client,
            )
            previous_question = question
            print()
    except KeyboardInterrupt:
        print("\nExiting.")
    return 0


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
    num_ctx: int,
    think: OllamaThink,
    debug_retrieval: bool,
    debug_ollama: bool,
    trace_dir: Path | None,
    mode: str,
    followup=None,
    client: object | None = None,
):
    # Late import to support monkeypatching via "ethnos.cli.answer_question"
    from .. import answer_question as _answer_question

    started_at = time.monotonic()
    retrieval_question = retrieval_question or question
    selected_role = normalize_answer_role(role)
    retrieval = retrieve_answer_context(
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
            num_ctx=num_ctx,
            answer_text=answer_text,
            elapsed_seconds=elapsed,
            context_found=False,
            mode=mode,
            followup=followup,
            ollama_debug_info=None,
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
            f"{question}\nResolved follow-up for retrieval: {retrieval_question}"
        )
    prompt = build_answer_prompt(prompt_question, retrieval.rows, max_chars=chars)
    result = _answer_question(
        prompt=prompt,
        model_name=model_name,
        host=settings.ollama_host,
        timeout=settings.ollama_timeout,
        num_predict=num_predict,
        num_ctx=num_ctx,
        think=think,
        client=client,
    )
    elapsed = time.monotonic() - started_at
    if debug_ollama:
        _print_ollama_debug(None, result.debug_info)
    if _ollama_done_reason(result) == "length":
        print(
            "Warning: answer hit Ollama output length limit; "
            "consider increasing --num-predict.",
            flush=True,
        )
    answer_text = (
        result.raw_response.strip()
        or "The document context did not contain enough information."
    )
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
        num_ctx=num_ctx,
        answer_text=answer_text,
        elapsed_seconds=elapsed,
        context_found=True,
        mode=mode,
        followup=followup,
        ollama_debug_info=result.debug_info,
        rewritten_retrieval_question=(
            retrieval_question if retrieval_question != question else None
        ),
    )
    return retrieval


def _maybe_write_answer_trace(
    *,
    trace_dir,
    document_id,
    question,
    retrieval,
    model_name,
    num_predict,
    num_ctx,
    answer_text,
    elapsed_seconds,
    context_found,
    mode,
    followup=None,
    ollama_debug_info=None,
    rewritten_retrieval_question=None,
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
        "num_ctx": num_ctx,
        "answer_text": answer_text,
        "elapsed_seconds": elapsed_seconds,
        "context_found": context_found,
        "command_mode": mode,
        "ollama": _trace_ollama_debug(ollama_debug_info),
        "follow_up_detected": bool(followup.detected)
        if followup is not None
        else False,
        "previous_question": followup.previous_question
        if followup is not None
        else None,
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


def _trace_ollama_debug(debug_info) -> dict | None:
    if debug_info is None:
        return None
    return {
        "prompt_char_length": debug_info.prompt_char_length,
        "format_kind": debug_info.format_kind,
        "num_predict": debug_info.num_predict,
        "num_ctx": debug_info.num_ctx,
        "response_summary": debug_info.response_summary,
    }


def inspect_trace_cmd(args) -> int:
    trace = json.loads(args.trace_path.read_text(encoding="utf-8"))
    print(f"Trace: {args.trace_path}")
    print(f"Mode: {trace.get('command_mode', 'unknown')}")
    print(f"Document: {trace.get('document_id')}")
    print(f"Question: {trace.get('question', '')}")
    rewritten = trace.get("rewritten_retrieval_question")
    if rewritten:
        print(f"Rewritten retrieval question: {rewritten}")
    print(f"Selected query: {trace.get('selected_query') or '(none)'}")
    fallback_queries = trace.get("fallback_queries_tried") or []
    if fallback_queries:
        print(f"Fallback queries tried: {', '.join(fallback_queries)}")
    print(f"Context found: {_yes_no(bool(trace.get('context_found')))}")
    print(f"Comparison detected: {_yes_no(bool(trace.get('comparison_detected')))}")
    if trace.get("follow_up_detected"):
        previous = trace.get("previous_question") or "(unknown)"
        print(f"Follow-up detected: yes, previous question: {previous}")
    chunks = trace.get("selected_chunks") or []
    print(f"Selected chunks: {len(chunks)}")
    for chunk in chunks:
        print(
            "  "
            f"chunk {chunk.get('chunk_id')} "
            f"(index {chunk.get('chunk_index')}): "
            f"{chunk.get('source_citation')} "
            f"[{chunk.get('section_label')} / {chunk.get('content_role')}]"
        )
    _print_trace_ollama_summary(trace.get("ollama"))
    answer = trace.get("answer_text") or ""
    if args.show_answer:
        print()
        print("Answer:")
        print(answer)
    else:
        print(f"Answer chars: {len(answer)}")
    return 0


def _print_trace_ollama_summary(ollama: dict | None) -> None:
    if not ollama:
        print("Ollama: not called")
        return
    print(
        "Ollama: "
        f"format={ollama.get('format_kind')}, "
        f"prompt_chars={ollama.get('prompt_char_length')}, "
        f"num_predict={ollama.get('num_predict')}, "
        f"num_ctx={ollama.get('num_ctx')}"
    )
    summary = ollama.get("response_summary") or {}
    print(
        "Ollama response: "
        f"done_reason={summary.get('done_reason')}, "
        f"eval_count={summary.get('eval_count')}, "
        f"content_chars={summary.get('message_content_length')}, "
        f"thinking_chars={summary.get('message_thinking_length')}, "
        f"error={summary.get('error')}"
    )


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
