"""QA benchmark commands."""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from ..shared import (
    ASK_ROLES,
    add_command,
    answer_num_predict,
    limit_benchmark_items,
    ollama_num_ctx,
    open_db,
    parse_models_arg,
    progress_line,
)
from ..formatting import format_elapsed, preview_text, _print_model_summary
from ..retrieval import retrieve_answer_context

from ...qa import (
    benchmark_hit,
    build_answer_prompt,
    evaluate_answer_quality,
    load_qa_benchmark,
    normalize_answer_role,
    rank_model_summaries,
    summarize_answer_items,
)
from ...section_presets import SECTION_LABELS
from ...config import PROJECT_ROOT, load_settings
from ...hawkes_coverage import format_report, load_cases, summarize, sweep
from ...precalc_benchmark import (
    load_precalculus_benchmark,
    run_precalculus_benchmark,
    write_precalculus_report,
)


def hawkes_coverage_cmd(args) -> int:
    """Report which Hawkes question types the exact path can answer.

    No browser and no model: the fallback that hides a coverage gap costs about
    seventy seconds live, and everything needed to find the gap is offline.
    """
    results = sweep(load_cases(Path(args.corpus)))
    print(format_report(results))
    counts = summarize(results)
    # A wrong exact answer fails the sweep. A gap does not: gaps are the
    # backlog this command exists to print, and failing on them would mean the
    # sweep could never be run in CI while any remained.
    if counts["wrong"]:
        return 1
    if args.strict and (counts["no-verb"] or counts["solver-declined"]):
        return 1
    return 0


def register(subcommands):
    coverage_parser = add_command(
        subcommands,
        "hawkes-coverage",
        "Report which Hawkes question types the exact solver answers.",
        hawkes_coverage_cmd,
    )
    coverage_parser.add_argument(
        "--corpus",
        default=str(PROJECT_ROOT / "benchmarks" / "hawkes_lesson_coverage.json"),
        help="Coverage corpus to sweep.",
    )
    coverage_parser.add_argument(
        "--strict",
        action="store_true",
        help="Also fail when any question type is uncovered, not only when one is wrong.",
    )

    bench_parser = add_command(
        subcommands,
        "qa-bench",
        "Run a retrieval benchmark for local PDF QA.",
        qa_bench_cmd,
    )
    bench_parser.add_argument("document_id", type=int)
    bench_parser.add_argument("--benchmark", type=Path, required=True)
    bench_parser.add_argument(
        "--ask", action="store_true", help="Also call Ollama for answer previews."
    )
    bench_parser.add_argument(
        "--no-ask",
        action="store_true",
        help="Retrieval-only mode. This is the default.",
    )
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
        help="Comma-separated Ollama model names for comparison, e.g. gemma-python,other-model.",
    )
    bench_parser.add_argument(
        "--num-predict", type=int, help="Ollama output token budget for --ask answers."
    )
    bench_parser.add_argument(
        "--num-ctx",
        type=int,
        help="Ollama context window token budget for --ask answers.",
    )
    bench_parser.add_argument("--output", type=Path)

    precalc_parser = add_command(
        subcommands,
        "precalc-bench",
        "Benchmark an Ollama model on structured pre-calculus problems.",
        precalc_bench_cmd,
    )
    precalc_parser.add_argument(
        "--benchmark",
        type=Path,
        default=PROJECT_ROOT / "benchmarks" / "precalculus_model_benchmark.json",
    )
    precalc_parser.add_argument("--model", default="precalc-local")
    precalc_parser.add_argument("--num-predict", type=int, default=512)
    precalc_parser.add_argument("--num-ctx", type=int, default=4096)
    precalc_parser.add_argument("--max-questions", type=int)
    precalc_parser.add_argument("--output", type=Path)


def precalc_bench_cmd(args) -> int:
    if args.num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if args.num_ctx < 1:
        raise SystemExit("--num-ctx must be 1 or greater.")
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")

    settings = load_settings()
    benchmark = load_precalculus_benchmark(args.benchmark)
    from .. import create_client as _create_client

    print("Pre-calculus model benchmark", flush=True)
    print(f"  model: {args.model}", flush=True)
    print(f"  benchmark: {args.benchmark}", flush=True)
    report = run_precalculus_benchmark(
        benchmark=benchmark,
        client=_create_client(settings.ollama_host, settings.ollama_timeout),
        model_name=args.model,
        num_predict=args.num_predict,
        num_ctx=args.num_ctx,
        max_questions=args.max_questions,
    )
    for item in report["items"]:
        status = "pass" if item["is_correct"] else item["validation_status"]
        print(
            f"  {item['id']}: {status} "
            f"(expected {item['expected_option']}, got {item['selected_option']})"
        )
    print("Summary:")
    print(f"  correct: {report['correct']}/{report['total']}")
    print(f"  invalid: {report['invalid']}")
    print(f"  elapsed: {format_elapsed(report['elapsed_seconds'])}")
    if args.output:
        write_precalculus_report(report, args.output)
        print(f"  wrote report: {args.output}")
    return 0 if report["correct"] == report["total"] else 1


def qa_bench_cmd(args) -> int:
    settings, conn = open_db(args)
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.ask and args.no_ask:
        raise SystemExit("Use either --ask or --no-ask, not both.")
    if args.models and not args.ask:
        raise SystemExit("--models requires --ask.")
    num_predict = answer_num_predict(args, settings)
    num_ctx = ollama_num_ctx(args, settings)
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if num_ctx < 1:
        raise SystemExit("--num-ctx must be 1 or greater.")
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
            num_ctx=num_ctx,
            models=models,
        )
    started_at = time.monotonic()
    report_items = []
    hits = misses = no_context = 0
    answer_counts = Counter()
    run_answers = bool(args.ask)
    # Late import to support monkeypatching via "ethnos.cli.create_client"
    from .. import create_client as _create_client

    run_client = (
        _create_client(settings.ollama_host, settings.ollama_timeout)
        if run_answers
        else None
    )

    for item in items:
        item_started_at = time.monotonic()
        item_number = len(report_items) + 1
        retrieval = retrieve_answer_context(
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
            print(
                progress_line(
                    args.model or settings.ollama_model,
                    item_number,
                    len(items),
                    item["id"],
                ),
                flush=True,
            )
        print(
            f"  derived query: {retrieval.queries_tried[0] if retrieval.queries_tried else ''}"
        )
        print(f"  fallback queries tried: {', '.join(retrieval.queries_tried)}")
        print(
            f"  selected chunks: {', '.join(str(chunk) for chunk in selected_chunks) or 'none'}"
        )
        print(f"  selected source citations: {', '.join(selected_citations) or 'none'}")
        print(
            f"  expected chunks: {item.get('expected_source_chunks', 'not specified')}"
        )
        print(f"  expected pages: {item.get('expected_source_pages', 'not specified')}")
        print(f"  status: {'hit' if hit else 'miss'}")

        answer_text = None
        answer_preview = None
        answer_evaluation = None
        answer_elapsed = None
        if run_answers and retrieval.rows:
            # Late import to support monkeypatching via "ethnos.cli.answer_question"
            from .. import answer_question as _answer_question

            prompt = build_answer_prompt(
                item["question"], retrieval.rows, max_chars=1200
            )
            answer_started_at = time.monotonic()
            print("  answer generation: start", flush=True)
            result = _answer_question(
                prompt=prompt,
                model_name=args.model or settings.ollama_model,
                host=settings.ollama_host,
                timeout=settings.ollama_timeout,
                num_predict=num_predict,
                num_ctx=num_ctx,
                think=settings.ollama_think,
                client=run_client,
            )
            answer_elapsed = time.monotonic() - answer_started_at
            print(
                f"  answer generation elapsed: {format_elapsed(answer_elapsed)}",
                flush=True,
            )
            answer_text = result.raw_response.strip()
            answer_preview = preview_text(result.raw_response, 400)
        if run_answers:
            answer_evaluation = evaluate_answer_quality(
                item, answer_text or "", retrieval.rows
            )
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
                "derived_query": retrieval.queries_tried[0]
                if retrieval.queries_tried
                else "",
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
            "no_context_expected": answer_counts["no_context_expected"]
            if run_answers
            else None,
            "no_context_unexpected": answer_counts["no_context_unexpected"]
            if run_answers
            else None,
            "elapsed_seconds": elapsed,
            "items": report_items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"  wrote report: {args.output}")
    return 0


def qa_bench_compare_models(
    *,
    args,
    settings,
    conn,
    items,
    selected_role,
    num_predict,
    num_ctx,
    models,
) -> int:
    started_at = time.monotonic()
    retrieval_entries = []
    retrieval_hits = retrieval_misses = no_context = 0
    for item in items:
        retrieval = retrieve_answer_context(
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
                "selected_citations": [
                    row["source_citation"] for row in retrieval.rows
                ],
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
    # Late imports to support monkeypatching via "ethnos.cli.*"
    from .. import answer_question as _answer_question
    from .. import create_client as _create_client

    for model_name in models:
        print(f"Model: {model_name}", flush=True)
        ollama_client = _create_client(settings.ollama_host, settings.ollama_timeout)
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
            print(
                progress_line(model_name, index, len(retrieval_entries), item["id"]),
                flush=True,
            )
            if retrieval.rows:
                prompt = build_answer_prompt(
                    item["question"], retrieval.rows, max_chars=1200
                )
                answer_started_at = time.monotonic()
                print("  answer generation: start", flush=True)
                try:
                    result = _answer_question(
                        prompt=prompt,
                        model_name=model_name,
                        host=settings.ollama_host,
                        timeout=settings.ollama_timeout,
                        num_predict=num_predict,
                        num_ctx=num_ctx,
                        think=settings.ollama_think,
                        client=ollama_client,
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
                except Exception as exc:
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
                    "derived_query": retrieval.queries_tried[0]
                    if retrieval.queries_tried
                    else "",
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
                    "timings": {"answer_seconds": answer_elapsed},
                    "model_error": model_error,
                }
            )
        model_elapsed = time.monotonic() - model_started_at
        summary = summarize_answer_items(model_items)
        summary["model"] = model_name
        summary["total_elapsed_seconds"] = model_elapsed
        model_reports.append(
            {"model": model_name, "summary": summary, "items": model_items}
        )
        model_summaries.append(summary)
        _print_model_summary(summary)
        print()

    ranking = rank_model_summaries(model_summaries)
    elapsed = time.monotonic() - started_at
    print("Model comparison ranked summary:")
    print(f"  best pass count: {', '.join(ranking['best_pass_count']) or 'none'}")
    print(f"  lowest fail count: {', '.join(ranking['lowest_fail_count']) or 'none'}")
    print(
        f"  fastest among models with no failures: {ranking['fastest_no_fail'] or 'none'}"
    )
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
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"  wrote report: {args.output}")
    return 0
