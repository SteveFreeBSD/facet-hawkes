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
from ...ollama_client import OllamaClientProtocol
from ...qa import (
    build_answer_prompt,
    normalize_answer_role,
    resolve_chat_followup,
)
from ...qa_agent import run_agentic_qa
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
    ask_parser.add_argument(
        "--answer-image",
        type=Path,
        help="Render the answer and symbol key commands to a PNG image.",
    )
    image_source = ask_parser.add_mutually_exclusive_group()
    image_source.add_argument(
        "--question-image",
        type=Path,
        help="Read the question from a PNG, JPG, or WebP image before answering.",
    )
    image_source.add_argument(
        "--capture-question",
        action="store_true",
        help=(
            "Select a screen region, then transcribe, solve, trace, and render "
            "an answer-only PNG automatically."
        ),
    )
    ask_parser.add_argument(
        "--vision-model",
        help="Primary Ollama OCR model used to transcribe --question-image.",
    )
    ask_parser.add_argument(
        "--vision-verifier-model",
        help="Independent vision model used to verify the first transcription.",
    )
    ask_parser.add_argument(
        "--vision-num-predict",
        type=int,
        help="Output-token budget for each image transcription pass.",
    )
    ask_parser.add_argument(
        "--accept-image-uncertainty",
        action="store_true",
        help="Solve even when two vision passes disagree or report ambiguity.",
    )
    ask_parser.add_argument(
        "--no-question-image-cache",
        action="store_true",
        help="Reread the screenshot instead of reusing a compatible transcription.",
    )
    ask_parser.add_argument(
        "--agentic",
        action="store_true",
        help="Use opt-in agentic local-PDF search/inspect before answering.",
    )
    ask_parser.add_argument(
        "--agent-max-steps",
        type=int,
        default=4,
        help="Maximum agentic Q&A tool-loop steps when --agentic is used.",
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
    chat_parser.add_argument(
        "--agentic",
        action="store_true",
        help="Use opt-in agentic local-PDF search/inspect before answering.",
    )
    chat_parser.add_argument(
        "--agent-max-steps",
        type=int,
        default=4,
        help="Maximum agentic Q&A tool-loop steps when --agentic is used.",
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
    _validate_agentic_options(args)
    question = args.question
    question_image = args.question_image
    answer_image = args.answer_image
    trace_dir = args.trace_dir
    if getattr(args, "capture_question", False):
        from ...screen_capture import (
            capture_question_region,
            default_capture_answer_path,
            default_capture_trace_dir,
        )

        print("Select only the question panel in the screen overlay.")
        question_image = capture_question_region(settings.question_capture_dir)
        answer_image = answer_image or default_capture_answer_path(question_image)
        trace_dir = trace_dir or default_capture_trace_dir(question_image)
        print(f"Captured question: {question_image}")
    answer_image_question = None
    client = None
    question_image_trace = None
    answer_model_name = args.model or settings.ollama_model
    if question_image is not None:
        from .. import create_client as _create_client
        from ...question_image import build_solver_question, transcribe_question_image

        client = _create_client(settings.ollama_host, settings.ollama_timeout)
        vision_num_predict = (
            args.vision_num_predict
            if args.vision_num_predict is not None
            else settings.ollama_vision_num_predict
        )
        if vision_num_predict < 1:
            raise SystemExit("--vision-num-predict must be 1 or greater.")
        image_result = transcribe_question_image(
            image_path=question_image,
            instruction=args.question,
            model_name=args.vision_model or settings.ollama_vision_model,
            verifier_model_name=(
                args.vision_verifier_model or settings.ollama_vision_verifier_model
            ),
            client=client,
            num_predict=vision_num_predict,
            num_ctx=ollama_num_ctx(args, settings),
            cache_dir=(
                None
                if args.no_question_image_cache
                else settings.question_image_cache_dir
            ),
        )
        question = build_solver_question(args.question, image_result.transcription)
        if args.model is None:
            answer_model_name = settings.ollama_math_model
        answer_image_question = image_result.transcription.problem_text
        question_image_trace = {
            "image_path": str(image_result.image_path),
            "vision_model": image_result.vision_model,
            "verifier_model": image_result.verifier_model,
            "transcription": image_result.transcription.model_dump(),
            "initial_transcription": image_result.initial_transcription.model_dump(),
            "verification_issues": image_result.verification_issues,
            "response_summary": image_result.response_summary,
            "cache_hit": image_result.cache_hit,
        }
        _print_question_image_transcription(image_result)
        if image_result.verification_issues and not args.accept_image_uncertainty:
            print(
                "Refusing to solve an image transcription that did not pass "
                "two-pass verification. Crop or clarify the image, type the "
                "ambiguous expression, or use --accept-image-uncertainty."
            )
            return 1
    _answer_once(
        settings=settings,
        conn=conn,
        document_id=args.document_id,
        question=question,
        retrieval_question=answer_image_question,
        role=args.role,
        section=args.section,
        limit=args.limit,
        chars=args.chars,
        model_name=answer_model_name,
        num_predict=answer_num_predict(args, settings),
        num_ctx=ollama_num_ctx(args, settings),
        think=settings.ollama_think,
        debug_retrieval=args.debug_retrieval,
        debug_ollama=args.debug_ollama,
        trace_dir=trace_dir,
        answer_image=answer_image,
        mode="ask",
        client=client,
        question_image_trace=question_image_trace,
        answer_image_question=answer_image_question,
        agentic=args.agentic,
        agent_max_steps=args.agent_max_steps,
    )
    if getattr(args, "capture_question", False) and answer_image is not None:
        from ...screen_capture import open_answer_image

        if not open_answer_image(answer_image):
            print(f"Open the answer image at: {answer_image.expanduser().resolve()}")
    return 0


def _print_question_image_transcription(result) -> None:
    transcription = result.transcription
    print(f"Question image: {result.image_path}")
    print(f"Primary OCR model: {result.vision_model}")
    print(f"Verification model: {result.verifier_model}")
    print(f"Vision cache: {'hit' if result.cache_hit else 'miss'}")
    print()
    print("Recognized problem:")
    print(transcription.problem_text)
    if transcription.expressions:
        print("Recognized expressions:")
        for expression in transcription.expressions:
            print(f"  - {expression}")
    if transcription.answer_choices:
        print("Recognized answer choices:")
        for choice in transcription.answer_choices:
            print(f"  - {choice}")
    if transcription.diagram_description:
        print("Recognized graph/diagram:")
        print(transcription.diagram_description)
    print("Image-reading uncertainties:")
    if transcription.uncertainties:
        for uncertainty in transcription.uncertainties:
            print(f"  - {uncertainty}")
    else:
        print("  none")
    print("Two-pass verification:")
    if result.verification_issues:
        for issue in result.verification_issues:
            print(f"  - {issue}")
    else:
        print("  passed")
    print()


def chat_cmd(args) -> int:
    settings, conn = open_db(args)
    _validate_answer_options(args, settings)
    _validate_agentic_options(args)
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
                answer_image=None,
                mode="chat",
                question_image_trace=None,
                answer_image_question=None,
                followup=followup,
                client=ollama_client,
                agentic=args.agentic,
                agent_max_steps=args.agent_max_steps,
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
    answer_image: Path | None,
    mode: str,
    followup=None,
    client: OllamaClientProtocol | None = None,
    agentic: bool = False,
    agent_max_steps: int = 4,
    question_image_trace: dict | None = None,
    answer_image_question: str | None = None,
):
    # Late import to support monkeypatching via "ethnos.cli.answer_question"
    from .. import answer_question as _answer_question

    started_at = time.monotonic()
    retrieval_question = retrieval_question or question
    selected_role = normalize_answer_role(role)
    agentic_trace = None
    if agentic:
        prompt_question = question
        if (
            followup is not None
            and followup.detected
            and retrieval_question != question
        ):
            prompt_question = (
                f"{question}\nResolved follow-up for retrieval: {retrieval_question}"
            )
        if client is None:
            from .. import create_client as _create_client

            client = _create_client(settings.ollama_host, settings.ollama_timeout)
        agent_result = run_agentic_qa(
            conn=conn,
            document_id=document_id,
            question=prompt_question,
            output_dir=trace_dir or Path("."),
            model_name=model_name,
            num_predict=num_predict,
            num_ctx=num_ctx,
            think=think,
            role=role,
            section=section,
            limit=limit,
            chars=chars,
            max_steps=agent_max_steps,
            client=client,
        )
        agentic_trace = agent_result.trace
        if agent_result.finalized:
            elapsed = time.monotonic() - started_at
            print(f"Question: {question}")
            if debug_retrieval or debug_ollama:
                if followup is not None:
                    _print_followup_debug(followup)
                if retrieval_question != question:
                    print(f"Retrieval question: {retrieval_question}")
                print("Agentic Q&A: finalized")
            print()
            if agent_result.retrieval.rows:
                print("Selected context chunks:")
                _print_context_sources(agent_result.retrieval.rows)
            else:
                print("Selected context chunks: none")
            print()
            print("Answer:")
            print(agent_result.answer_text)
            print()
            print("Sources:")
            if agent_result.retrieval.rows:
                _print_context_sources(agent_result.retrieval.rows)
            else:
                print("none")
            _maybe_write_answer_trace(
                trace_dir=trace_dir,
                document_id=document_id,
                question=question,
                retrieval=agent_result.retrieval,
                model_name=model_name,
                num_predict=num_predict,
                num_ctx=num_ctx,
                answer_text=agent_result.answer_text,
                elapsed_seconds=elapsed,
                context_found=bool(agent_result.retrieval.rows),
                mode=mode,
                followup=followup,
                ollama_debug_info=agent_result.debug_info,
                rewritten_retrieval_question=(
                    retrieval_question if retrieval_question != question else None
                ),
                agentic_trace=agentic_trace,
                question_image=question_image_trace,
            )
            _maybe_write_answer_image(
                answer_image=answer_image,
                question=answer_image_question or question,
                answer_text=agent_result.answer_text,
                rows=agent_result.retrieval.rows,
                include_key_commands=question_image_trace is None,
            )
            return agent_result.retrieval

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
            agentic_trace=agentic_trace,
            question_image=question_image_trace,
        )
        _maybe_write_answer_image(
            answer_image=answer_image,
            question=answer_image_question or question,
            answer_text=answer_text,
            rows=[],
            include_key_commands=question_image_trace is None,
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
    if question_image_trace is not None:
        from ...polynomial_solver import answer_polynomial_product
        from ...question_image import answer_question_image
        from ...symbolic_solver import answer_symbolic_math

        transcription = question_image_trace["transcription"]
        result = answer_symbolic_math(
            problem_text=transcription["problem_text"],
            expressions=transcription.get("expressions") or [],
        )
        if result is None:
            result = answer_polynomial_product(question)
        if result is None:
            if client is None:
                from .. import create_client as _create_client

                client = _create_client(settings.ollama_host, settings.ollama_timeout)
            result = answer_question_image(
                question=question,
                context_rows=retrieval.rows,
                max_chars=chars,
                model_name=model_name,
                client=client,
                num_predict=num_predict,
                num_ctx=num_ctx,
            )
    else:
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
        agentic_trace=agentic_trace,
        question_image=question_image_trace,
    )
    _maybe_write_answer_image(
        answer_image=answer_image,
        question=answer_image_question or question,
        answer_text=answer_text,
        rows=retrieval.rows,
        include_key_commands=question_image_trace is None,
    )
    return retrieval


def _maybe_write_answer_image(
    *,
    answer_image: Path | None,
    question: str,
    answer_text: str,
    rows: list[dict],
    include_key_commands: bool = True,
):
    if answer_image is None:
        return None
    from ...answer_image import render_answer_image

    artifacts = render_answer_image(
        image_path=answer_image,
        question=question,
        answer_text=answer_text,
        sources=[row["source_citation"] for row in rows],
        include_key_commands=include_key_commands,
    )
    print()
    print(f"Answer image: {artifacts.image_path}")
    if artifacts.keys_path is not None:
        print(f"Symbol key commands: {artifacts.keys_path}")
    return artifacts


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
    agentic_trace=None,
    question_image=None,
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
    if agentic_trace is not None:
        trace["agentic"] = agentic_trace
    if question_image is not None:
        trace["question_image"] = question_image
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
    agentic = trace.get("agentic")
    if isinstance(agentic, dict):
        fallback = agentic.get("fallback_reason")
        status = agentic.get("source_status") or "fallback"
        print(
            "Agentic Q&A: "
            f"steps={len(agentic.get('actions') or [])}, "
            f"source_status={status}, "
            f"fallback={fallback or 'none'}"
        )
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


def _validate_agentic_options(args) -> None:
    if args.agent_max_steps < 1:
        raise SystemExit("--agent-max-steps must be 1 or greater.")
