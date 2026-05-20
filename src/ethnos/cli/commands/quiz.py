"""Quiz generation, import, review, validation, and benchmark commands."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ..shared import (
    ASK_ROLES,
    add_command,
    limit_benchmark_items,
    ollama_num_ctx,
    open_db,
    progress_line,
)
from ..formatting import (
    _format_accuracy,
    _format_accuracy_delta,
    _format_optional_percent,
    _print_mc_compare_section,
    _print_mc_key_preview,
    _print_ollama_debug,
    _print_quiz_preview,
    _print_retrieval_debug,
    format_elapsed,
)

from ...db import context_chunks, get_document
from ...qa import normalize_answer_role, retrieve_with_fallbacks
from ...quiz import (
    build_choice_prompt,
    build_essay_prompt,
    build_mc_prompt,
    compact_question_with_options,
    generate_quiz,
    import_canvas_quiz,
    import_lms_mc_quiz,
    load_quiz,
)
from ...quiz_compare import compare_mc_bench_reports, load_mc_bench_report
from ...quiz_validation import (
    normalize_review_text as _normalize_review_text,
    validate_mc_quiz_item as _validate_mc_quiz_item,
    validate_quiz_item as _validate_quiz_item,
)
from ...section_presets import SECTION_LABELS


def register(subcommands):
    generate_quiz_parser = add_command(
        subcommands, "generate-quiz",
        "Generate a local multiple-choice quiz from structured records.",
        generate_quiz_cmd,
    )
    generate_quiz_parser.add_argument("document_id", type=int)
    generate_quiz_parser.add_argument("--output", type=Path, required=True)
    generate_quiz_parser.add_argument("--source", choices=["terms", "questions", "both"], default="terms")
    generate_quiz_parser.add_argument("--limit", type=int)
    generate_quiz_parser.add_argument("--seed", type=int)
    generate_quiz_parser.add_argument("--max-option-chars", type=int, default=120)
    generate_quiz_parser.add_argument(
        "--difficulty", choices=["easy", "medium", "hard"], default="medium",
        help="Distractor difficulty: easy uses farther distractors, hard uses closer/shared-topic distractors.",
    )
    generate_quiz_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    generate_quiz_parser.add_argument("--section", choices=sorted(SECTION_LABELS))

    mc_bench_parser = add_command(
        subcommands, "mc-bench",
        "Run a multiple-choice benchmark using retrieved local PDF context.",
        mc_bench_cmd,
    )
    mc_bench_parser.add_argument("document_id", type=int)
    mc_bench_parser.add_argument("--quiz", type=Path, required=True)
    mc_bench_parser.add_argument("--max-questions", type=int)
    mc_bench_parser.add_argument("--limit", type=int, default=3, help="Retrieved context chunks per quiz question.")
    mc_bench_parser.add_argument("--chars", type=int, default=300)
    mc_bench_parser.add_argument("--output", type=Path)
    mc_bench_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    mc_bench_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    mc_bench_parser.add_argument("--options-retrieval", action="store_true")
    mc_bench_parser.add_argument("--debug-ollama", action="store_true")
    mc_bench_parser.add_argument("--debug-retrieval", action="store_true")
    mc_bench_parser.add_argument("--model", help="Ollama model name.")
    mc_bench_parser.add_argument("--num-predict", type=int, help="Ollama output token budget for the MC JSON answer.")
    mc_bench_parser.add_argument("--num-ctx", type=int, help="Ollama context window token budget.")

    mc_compare_parser = add_command(
        subcommands, "mc-compare",
        "Compare two multiple-choice benchmark JSON reports.",
        mc_compare_cmd,
    )
    mc_compare_parser.add_argument("baseline", type=Path)
    mc_compare_parser.add_argument("candidate", type=Path)
    mc_compare_parser.add_argument("--output", type=Path)

    import_mc_parser = add_command(
        subcommands, "import-mc-quiz",
        "Convert copied LMS quiz text into external multiple-choice quiz JSON.",
        import_mc_quiz_cmd,
    )
    import_mc_parser.add_argument("input", type=Path)
    import_mc_parser.add_argument("--output", type=Path, required=True)
    import_mc_parser.add_argument("--document-id", type=int)
    import_mc_parser.add_argument("--title")
    import_mc_parser.add_argument("--answer-key", type=Path)
    import_mc_parser.add_argument("--id-prefix", default="q", help="Question id prefix before the zero-padded number, e.g. ch1-q.")
    import_mc_parser.add_argument("--with-key-preview", action="store_true", help="Print each keyed answer after writing the imported quiz.")

    import_canvas_parser = add_command(
        subcommands, "import-canvas-quiz",
        "Convert pasted Canvas quiz text into external mixed quiz JSON.",
        import_canvas_quiz_cmd,
    )
    import_canvas_parser.add_argument("input", type=Path)
    import_canvas_parser.add_argument("--output", type=Path, required=True)
    import_canvas_parser.add_argument("--document-id", type=int)
    import_canvas_parser.add_argument("--title")
    import_canvas_parser.add_argument("--answer-key", type=Path)
    import_canvas_parser.add_argument("--id-prefix", default="q", help="Question id prefix before the zero-padded number, e.g. ch1-q.")
    import_canvas_parser.add_argument("--with-key-preview", action="store_true", help="Print each keyed choice answer after writing the imported quiz.")

    review_mc_parser = add_command(
        subcommands, "review-mc-quiz",
        "Print a multiple-choice quiz with keyed answers marked for review.",
        review_mc_quiz_cmd,
    )
    review_mc_parser.add_argument("quiz", type=Path)
    review_mc_parser.add_argument("--max-questions", type=int)

    validate_mc_parser = add_command(
        subcommands, "validate-mc-quiz",
        "Validate multiple-choice quiz keys and source anchors without calling Ollama.",
        validate_mc_quiz_cmd,
    )
    validate_mc_parser.add_argument("document_id", type=int)
    validate_mc_parser.add_argument("--quiz", type=Path, required=True)
    validate_mc_parser.add_argument("--max-questions", type=int)
    validate_mc_parser.add_argument("--require-anchors", action="store_true", help="Require target, source_chunks, source_pages, and source_citation on every item.")

    suggest_mc_parser = add_command(
        subcommands, "suggest-mc-anchors",
        "Suggest source chunks for anchoring a multiple-choice quiz without calling Ollama.",
        suggest_mc_anchors_cmd,
    )
    suggest_mc_parser.add_argument("document_id", type=int)
    suggest_mc_parser.add_argument("--quiz", type=Path, required=True)
    suggest_mc_parser.add_argument("--max-questions", type=int)
    suggest_mc_parser.add_argument("--limit", type=int, default=3)
    suggest_mc_parser.add_argument("--chars", type=int, default=360)
    suggest_mc_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    suggest_mc_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    suggest_mc_parser.add_argument("--output", type=Path)

    review_quiz_parser = add_command(
        subcommands, "review-quiz",
        "Print a mixed quiz with keyed answers and warnings marked for review.",
        review_quiz_cmd,
    )
    review_quiz_parser.add_argument("quiz", type=Path)
    review_quiz_parser.add_argument("--max-questions", type=int)

    validate_quiz_parser = add_command(
        subcommands, "validate-quiz",
        "Validate mixed quiz keys, completion, and source anchors without Ollama.",
        validate_quiz_cmd,
    )
    validate_quiz_parser.add_argument("document_id", type=int)
    validate_quiz_parser.add_argument("--quiz", type=Path, required=True)
    validate_quiz_parser.add_argument("--max-questions", type=int)
    validate_quiz_parser.add_argument("--require-anchors", action="store_true", help="Require target, source_chunks, source_pages, and source_citation on every item.")
    validate_quiz_parser.add_argument("--strict-complete", action="store_true", help="Treat incomplete matching items and other import warnings as errors.")

    quiz_bench_parser = add_command(
        subcommands, "quiz-bench",
        "Run a mixed quiz benchmark using retrieved local PDF context.",
        quiz_bench_cmd,
    )
    quiz_bench_parser.add_argument("document_id", type=int)
    quiz_bench_parser.add_argument("--quiz", type=Path, required=True)
    quiz_bench_parser.add_argument("--max-questions", type=int)
    quiz_bench_parser.add_argument("--limit", type=int, default=3)
    quiz_bench_parser.add_argument("--chars", type=int, default=900)
    quiz_bench_parser.add_argument("--output", type=Path)
    quiz_bench_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    quiz_bench_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    quiz_bench_parser.add_argument("--options-retrieval", action="store_true")
    quiz_bench_parser.add_argument("--debug-ollama", action="store_true")
    quiz_bench_parser.add_argument("--debug-retrieval", action="store_true")
    quiz_bench_parser.add_argument("--model", help="Ollama model name.")
    quiz_bench_parser.add_argument("--num-predict", type=int)
    quiz_bench_parser.add_argument("--num-ctx", type=int)


def generate_quiz_cmd(args) -> int:
    _, conn = open_db(args)
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.max_option_chars < 4:
        raise SystemExit("--max-option-chars must be 4 or greater.")
    selected_role = normalize_answer_role(args.role)
    quiz = generate_quiz(
        conn,
        args.document_id,
        source=args.source,
        limit=args.limit,
        seed=args.seed,
        max_option_chars=args.max_option_chars,
        role=selected_role,
        section=args.section,
        difficulty=args.difficulty,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(quiz, indent=2, sort_keys=True), encoding="utf-8")
    counts = quiz["record_counts"]
    print(f"Generated quiz for document {args.document_id}: {args.output}")
    print(f"  source: {args.source}")
    print(f"  difficulty: {args.difficulty}")
    print(f"  role: {args.role}")
    print(f"  section: {args.section or 'all'}")
    print(f"  generated: {quiz['generated_count']}")
    print(f"  available terms: {counts['available_terms']}")
    print(f"  available questions: {counts['available_questions']}")
    print(f"  generated terms: {counts['generated_terms']}")
    print(f"  generated questions: {counts['generated_questions']}")
    quality = quiz["quality_stats"]
    distractor_pool = quality["distractor_pool"]
    option_lengths = quality["option_lengths"]
    topic_coverage = quality["topic_coverage"]
    section_coverage = quality["section_coverage"]
    chunk_coverage = quality["chunk_coverage"]
    print(
        "  skipped insufficient distractors: "
        f"{quality['skipped_insufficient_distractors']}"
    )
    print(f"  skipped display collisions: {quality['skipped_display_collision']}")
    print(
        "  distractor pool: "
        f"{distractor_pool['count']}/{distractor_pool['total']} "
        f"({_format_optional_percent(distractor_pool['coverage'])})"
    )
    print(
        "  option length avg/max: "
        f"{option_lengths['average'] or 'n/a'}/{option_lengths['max']}"
    )
    print(
        "  topic coverage: "
        f"{topic_coverage['count']}/{topic_coverage['total']} "
        f"({_format_optional_percent(topic_coverage['coverage'])})"
    )
    print(
        "  section coverage: "
        f"{section_coverage['count']}/{section_coverage['total']} "
        f"({_format_optional_percent(section_coverage['coverage'])})"
    )
    print(
        "  chunk coverage: "
        f"{chunk_coverage['count']}/{chunk_coverage['total']} "
        f"({_format_optional_percent(chunk_coverage['coverage'])})"
    )
    return 0

def import_mc_quiz_cmd(args) -> int:
    raw_text = args.input.read_text(encoding="utf-8")
    answer_key_text = (
        args.answer_key.read_text(encoding="utf-8") if args.answer_key is not None else None
    )
    try:
        quiz = import_lms_mc_quiz(
            raw_text,
            document_id=args.document_id,
            title=args.title,
            answer_key_text=answer_key_text,
            id_prefix=args.id_prefix,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(quiz, indent=2, sort_keys=True), encoding="utf-8")
    keyed_count = sum(1 for item in quiz["questions"] if "correct" in item)
    print(f"Imported MC quiz: {args.output}")
    print(f"  source: {args.input}")
    print(f"  title: {quiz.get('title') or 'Imported MC Quiz'}")
    print(f"  questions: {len(quiz['questions'])}")
    print(f"  keyed: {keyed_count}")
    if args.with_key_preview:
        print()
        _print_mc_key_preview(quiz["questions"])
    return 0

def import_canvas_quiz_cmd(args) -> int:
    raw_text = args.input.read_text(encoding="utf-8")
    answer_key_text = (
        args.answer_key.read_text(encoding="utf-8") if args.answer_key is not None else None
    )
    try:
        quiz = import_canvas_quiz(
            raw_text,
            document_id=args.document_id,
            title=args.title,
            answer_key_text=answer_key_text,
            id_prefix=args.id_prefix,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(quiz, indent=2, sort_keys=True), encoding="utf-8")
    keyed_count = sum(1 for item in quiz["questions"] if "correct" in item)
    warning_count = sum(len(item.get("warnings", [])) for item in quiz["questions"])
    print(f"Imported Canvas quiz: {args.output}")
    print(f"  source: {args.input}")
    print(f"  title: {quiz.get('title') or 'Imported Canvas Quiz'}")
    print(f"  questions: {len(quiz['questions'])}")
    print(f"  total points: {quiz.get('total_points') or 0}")
    print(f"  keyed choices: {keyed_count}")
    print(f"  warnings: {warning_count}")
    if args.with_key_preview:
        print()
        _print_quiz_preview(quiz["questions"], include_options=False)
    return 0

def review_mc_quiz_cmd(args) -> int:
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    quiz = load_quiz(args.quiz)
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    keyed_count = sum(1 for item in items if "correct" in item)
    print("MC quiz review")
    print(f"  quiz: {args.quiz}")
    print(f"  title: {quiz.get('title') or 'n/a'}")
    print(f"  questions: {len(items)}")
    print(f"  keyed: {keyed_count}")
    print()
    _print_mc_key_preview(items, include_options=True)
    return 0

def review_quiz_cmd(args) -> int:
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    quiz = load_quiz(args.quiz)
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    keyed_count = sum(1 for item in items if "correct" in item)
    warning_count = sum(len(item.get("warnings", [])) for item in items)
    print("Quiz review")
    print(f"  quiz: {args.quiz}")
    print(f"  title: {quiz.get('title') or 'n/a'}")
    print(f"  questions: {len(items)}")
    print(f"  keyed choices: {keyed_count}")
    print(f"  warnings: {warning_count}")
    print()
    _print_quiz_preview(items, include_options=True)
    return 0

def validate_mc_quiz_cmd(args) -> int:
    _, conn = open_db(args)
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    get_document(conn, args.document_id)
    try:
        quiz = load_quiz(args.quiz)
    except ValueError as exc:
        print("MC quiz validation")
        print(f"  document id: {args.document_id}")
        print(f"  quiz: {args.quiz}")
        print()
        print("Validation failed")
        print("  errors: 1")
        print(f"  - {exc}")
        return 1
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    error_count = 0

    print("MC quiz validation")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  questions: {len(items)}")
    print(f"  require anchors: {'yes' if args.require_anchors else 'no'}")
    print()

    for item in items:
        item_errors = _validate_mc_quiz_item(
            conn,
            args.document_id,
            item,
            require_anchors=args.require_anchors,
        )
        if item_errors:
            error_count += len(item_errors)
            print(f"{item['id']}: error")
            for error in item_errors:
                print(f"  - {error}")
        else:
            print(f"{item['id']}: ok")

    print()
    print(f"Validation {'failed' if error_count else 'passed'}")
    print(f"  errors: {error_count}")
    return 1 if error_count else 0

def validate_quiz_cmd(args) -> int:
    _, conn = open_db(args)
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    get_document(conn, args.document_id)
    try:
        quiz = load_quiz(args.quiz)
    except ValueError as exc:
        print("Quiz validation")
        print(f"  document id: {args.document_id}")
        print(f"  quiz: {args.quiz}")
        print()
        print("Validation failed")
        print("  errors: 1")
        print(f"  - {exc}")
        return 1
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    error_count = 0

    print("Quiz validation")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  questions: {len(items)}")
    print(f"  require anchors: {'yes' if args.require_anchors else 'no'}")
    print(f"  strict complete: {'yes' if args.strict_complete else 'no'}")
    print()

    for item in items:
        item_errors = _validate_quiz_item(
            conn,
            args.document_id,
            item,
            require_anchors=args.require_anchors,
            strict_complete=args.strict_complete,
            require_key=False,
        )
        if item_errors:
            error_count += len(item_errors)
            print(f"{item['id']}: error")
            for error in item_errors:
                print(f"  - {error}")
        else:
            print(f"{item['id']}: ok")

    print()
    print(f"Validation {'failed' if error_count else 'passed'}")
    print(f"  errors: {error_count}")
    return 1 if error_count else 0

def suggest_mc_anchors_cmd(args) -> int:
    _, conn = open_db(args)
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    quiz = load_quiz(args.quiz)
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    selected_role = normalize_answer_role(args.role)

    report_items = []
    print("MC anchor suggestions")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  questions: {len(items)}")
    print(f"  candidate chunks per query: {args.limit}")
    print()

    for item in items:
        suggestions = _mc_anchor_suggestions_for_item(
            conn,
            args.document_id,
            item,
            limit=args.limit,
            chars=args.chars,
            role=selected_role,
            section=args.section,
        )
        report_items.append(suggestions)
        print(f"{item['id']}: {item['question']}")
        print(f"  type: {item.get('question_type') or 'multiple_choice'}")
        print(f"  current target: {item.get('target') or 'none'}")
        print(
            "  current source chunks: "
            + (
                ", ".join(str(chunk_id) for chunk_id in item.get("source_chunks", []))
                or "none"
            )
        )
        for query_entry in suggestions["queries"]:
            print(f"  query: {query_entry['query']}")
            if not query_entry["candidates"]:
                print("    no candidates")
                continue
            for candidate in query_entry["candidates"]:
                print(f"    chunk {candidate['chunk_id']}: {candidate['source_citation']}")
                print(f"      {candidate['snippet']}")
        print()

    if args.output:
        report = {
            "document_id": args.document_id,
            "quiz": str(args.quiz),
            "limit": args.limit,
            "chars": args.chars,
            "items": report_items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"wrote suggestions: {args.output}")
    return 0

def _mc_anchor_suggestions_for_item(
    conn,
    document_id: int,
    item: dict[str, object],
    *,
    limit: int,
    chars: int,
    role: str | None,
    section: str | None,
) -> dict[str, object]:
    query_entries = []
    for query in _mc_anchor_query_candidates(item):
        retrieval = _retrieve_mc_context(
            conn,
            document_id=document_id,
            question=query,
            limit=limit,
            role=role,
            section=section,
        )
        candidates = []
        for row in retrieval.rows:
            candidates.append(
                {
                    "chunk_id": row["id"],
                    "chunk_index": row["chunk_index"],
                    "source_citation": row["source_citation"],
                    "section_label": row.get("section_label"),
                    "content_role": row.get("content_role"),
                    "selected_query": retrieval.selected_query,
                    "queries_tried": retrieval.queries_tried,
                    "snippet": _anchor_snippet(
                        str(row.get("text", "")),
                        str(item.get("target") or retrieval.selected_query or query),
                        chars,
                    ),
                }
            )
        query_entries.append({"query": query, "candidates": candidates})
    return {
        "id": item["id"],
        "question": item["question"],
        "question_type": item.get("question_type") or "multiple_choice",
        "current_target": item.get("target"),
        "current_source_chunks": item.get("source_chunks", []),
        "queries": query_entries,
    }

def _mc_anchor_query_candidates(item: dict[str, object]) -> list[str]:
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = str(item.get("correct") or "")
    correct_option_text = str(options.get(correct) or "") if isinstance(options, dict) else ""
    candidates = [
        str(item.get("target") or ""),
        *[str(query) for query in _mc_retrieval_query_hints(item)],
        str(item["question"]),
        correct_option_text,
        compact_question_with_options(item),
    ]
    queries = []
    seen = set()
    for candidate in candidates:
        query = " ".join(candidate.split())
        key = _normalize_review_text(query)
        if query and key not in seen:
            seen.add(key)
            queries.append(query)
    return queries


def _mc_retrieval_query_hints(item: dict[str, object]) -> list[object]:
    queries = item.get("retrieval_queries", [])
    questions = item.get("retrieval_questions", [])
    hints = []
    if isinstance(queries, list):
        hints.extend(queries)
    if isinstance(questions, list):
        hints.extend(questions)
    return hints

def _anchor_snippet(text: str, target: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    target = target.strip()
    index = compact.lower().find(target.lower()) if target else -1
    if index < 0:
        return compact[: max_chars - 3].rstrip() + "..."
    half_window = max((max_chars - len(target)) // 2, 0)
    start = max(index - half_window, 0)
    end = min(start + max_chars, len(compact))
    start = max(end - max_chars, 0)
    snippet = compact[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(compact):
        snippet = snippet.rstrip() + "..."
    return snippet


def _add_selected_option_provenance(
    report_item: dict[str, object],
    item: dict[str, object],
    selected_option: str | None,
) -> None:
    option_sources = item.get("option_sources")
    if not selected_option or not isinstance(option_sources, dict):
        return
    source = option_sources.get(selected_option)
    if not isinstance(source, dict):
        return
    report_item["selected_option_source"] = source
    report_item["selected_option_source_record_type"] = source.get("source_record_type")
    report_item["selected_option_source_record_id"] = source.get("source_record_id")
    report_item["selected_option_source_target"] = source.get("target")
    if selected_option == item.get("correct") or source.get("role") != "distractor":
        return
    report_item["selected_distractor_source"] = source
    report_item["selected_distractor_source_record_type"] = source.get(
        "source_record_type"
    )
    report_item["selected_distractor_source_record_id"] = source.get(
        "source_record_id"
    )
    report_item["selected_distractor_target"] = source.get("target")
    report_item["selected_distractor_source_citation"] = source.get("source_citation")

def quiz_bench_cmd(args) -> int:
    settings, conn = open_db(args)
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    num_predict = (
        args.num_predict
        if args.num_predict is not None
        else settings.ollama_answer_num_predict
    )
    num_ctx = ollama_num_ctx(args, settings)
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if num_ctx < 1:
        raise SystemExit("--num-ctx must be 1 or greater.")

    quiz = load_quiz(args.quiz)
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    selected_role = normalize_answer_role(args.role)
    model_name = args.model or settings.ollama_model
    started_at = time.monotonic()
    ollama_client = None
    report_items = []
    keyed_total = correct_count = scored_total = no_context_count = invalid_count = 0
    answered_unscored_count = drafted_count = skipped_incomplete_count = 0

    print("Quiz benchmark")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  model: {model_name}")
    print(f"  questions: {len(items)}")
    print()

    for index, item in enumerate(items, start=1):
        item_started_at = time.monotonic()
        question_type = str(item.get("question_type") or "multiple_choice")
        keyed = question_type in {"multiple_choice", "true_false"} and "correct" in item
        keyed_total += int(keyed)
        selected_option = None
        validation_status = None
        validation_error = None
        raw_response = ""
        answer_elapsed = None
        answer_payload: dict[str, object] = {}
        retrieval, retrieval_questions = _retrieve_quiz_context_for_item(
            conn,
            document_id=args.document_id,
            item=item,
            limit=args.limit,
            role=selected_role,
            section=args.section,
        )
        if (
            not retrieval.rows
            and args.options_retrieval
            and question_type in {"multiple_choice", "true_false"}
        ):
            option_query = compact_question_with_options(item)
            retrieval_questions.append(option_query)
            retrieval = _retrieve_mc_context(
                conn,
                document_id=args.document_id,
                question=option_query,
                limit=args.limit,
                role=selected_role,
                section=args.section,
            )
        context_rows = _add_quiz_source_context(
            conn,
            args.document_id,
            retrieval.rows,
            item,
            role=selected_role,
            section=args.section,
        )
        selected_chunks = [row["id"] for row in context_rows]
        selected_citations = [row["source_citation"] for row in context_rows]

        print(f"{item['id']}: {item['question']}")
        print(f"  type: {question_type}")
        if args.debug_retrieval:
            _print_retrieval_debug(retrieval)
        print(f"  selected chunks: {', '.join(str(chunk) for chunk in selected_chunks) or 'none'}")

        if question_type == "matching" and "incomplete_matching_item" in item.get(
            "warnings", []
        ):
            status = "skipped_incomplete"
            skipped_incomplete_count += 1
            print("  status: skipped_incomplete")
        elif question_type == "matching":
            status = "skipped_matching"
            print("  status: skipped_matching")
        elif not context_rows:
            status = "no_context"
            no_context_count += 1
            print("  status: no_context")
        elif question_type in {"multiple_choice", "true_false"}:
            prompt_item = {
                **item,
                "_context_target": retrieval.selected_query or "",
            }
            prompt = build_choice_prompt(prompt_item, context_rows, max_chars=args.chars)
            answer_started_at = time.monotonic()
            print(progress_line(model_name, index, len(items), item["id"]), flush=True)
            if ollama_client is None:
                # Late import to support monkeypatching via "ethnos.cli.*"
                from .. import create_client as _create_client
                ollama_client = _create_client(settings.ollama_host, settings.ollama_timeout)
            # Late import to support monkeypatching
            from .. import answer_choice_question as _answer_choice
            result = _answer_choice(
                prompt=prompt,
                model_name=model_name,
                host=settings.ollama_host,
                timeout=settings.ollama_timeout,
                num_predict=num_predict,
                num_ctx=num_ctx,
                allowed_options=tuple(item["options"].keys()),
                client=ollama_client,
            )
            answer_elapsed = time.monotonic() - answer_started_at
            selected_option = result.selected_option
            validation_status = result.validation_status
            validation_error = result.validation_error
            raw_response = result.raw_response
            answer_payload = {
                "evidence": result.evidence,
                "source_citations": result.source_citations,
            }
            if args.debug_ollama:
                _print_ollama_debug(None, result.debug_info)
            if result.validation_status != "valid":
                status = "invalid_response"
                invalid_count += 1
            elif keyed:
                scored_total += 1
                is_correct = result.selected_option == item["correct"]
                correct_count += int(is_correct)
                status = "correct" if is_correct else "incorrect"
            else:
                status = "answered_unscored"
                answered_unscored_count += 1
            print(f"  selected option: {selected_option or 'none'}")
            if keyed:
                print(f"  correct option: {item['correct']}")
            print(f"  validation: {validation_status}")
            print(f"  status: {status}")
        elif question_type == "essay":
            prompt_item = {
                **item,
                "_context_target": retrieval.selected_query or "",
            }
            prompt = build_essay_prompt(prompt_item, context_rows, max_chars=args.chars)
            answer_started_at = time.monotonic()
            print(progress_line(model_name, index, len(items), item["id"]), flush=True)
            if ollama_client is None:
                from .. import create_client as _create_client
                ollama_client = _create_client(settings.ollama_host, settings.ollama_timeout)
            from .. import answer_essay_question as _answer_essay
            result = _answer_essay(
                prompt=prompt,
                model_name=model_name,
                host=settings.ollama_host,
                timeout=settings.ollama_timeout,
                num_predict=num_predict,
                num_ctx=num_ctx,
                client=ollama_client,
            )
            answer_elapsed = time.monotonic() - answer_started_at
            validation_status = result.validation_status
            validation_error = result.validation_error
            raw_response = result.raw_response
            answer_payload = {
                "answer": result.answer,
                "key_points": result.key_points,
                "rubric": result.rubric,
                "source_citations": result.source_citations,
                "limitations": result.limitations,
            }
            if args.debug_ollama:
                _print_ollama_debug(None, result.debug_info)
            if result.validation_status == "valid":
                status = "drafted"
                drafted_count += 1
            else:
                status = "invalid_response"
                invalid_count += 1
            print(f"  validation: {validation_status}")
            print(f"  status: {status}")
        else:
            status = "unsupported"
            print("  status: unsupported")
        print()

        item_elapsed = time.monotonic() - item_started_at
        options = item.get("options") if isinstance(item.get("options"), dict) else {}
        report_item = {
            "id": item["id"],
            "position": item.get("position"),
            "question": item["question"],
            "question_type": question_type,
            "points": item.get("points"),
            "options": options,
            "warnings": item.get("warnings", []),
            "target": item.get("target"),
            "selected_option": selected_option,
            "selected_option_text": options.get(selected_option) if selected_option else None,
            "validation_status": validation_status,
            "validation_error": validation_error,
            "selected_chunks": selected_chunks,
            "selected_source_citations": selected_citations,
            "queries_tried": retrieval.queries_tried,
            "retrieval_questions": retrieval_questions,
            "raw_response": raw_response,
            "answer": answer_payload,
            "timings": {
                "item_seconds": item_elapsed,
                "answer_seconds": answer_elapsed,
            },
            "status": status,
        }
        if keyed:
            report_item["correct"] = item["correct"]
            report_item["correct_option_text"] = options.get(item["correct"])
            report_item["is_correct"] = status == "correct"
            _add_selected_option_provenance(report_item, item, selected_option)
        if question_type == "matching":
            report_item["matching_prompts"] = item.get("matching_prompts", [])
            report_item["matching_pairs"] = item.get("matching_pairs", [])
        report_items.append(report_item)

    elapsed = time.monotonic() - started_at
    accuracy = correct_count / scored_total if scored_total else None
    print("Quiz benchmark summary:")
    print(f"  total: {len(items)}")
    print(f"  keyed total: {keyed_total}")
    print(f"  scored total: {scored_total}")
    print(f"  correct: {correct_count}")
    print(f"  accuracy: {accuracy:.1%}" if accuracy is not None else "  accuracy: n/a")
    print(f"  answered unscored: {answered_unscored_count}")
    print(f"  essays drafted: {drafted_count}")
    print(f"  skipped incomplete: {skipped_incomplete_count}")
    print(f"  no-context cases: {no_context_count}")
    print(f"  invalid responses: {invalid_count}")
    print(f"  elapsed: {format_elapsed(elapsed)}")

    if args.output:
        report = {
            "document_id": args.document_id,
            "quiz": str(args.quiz),
            "model": model_name,
            "total": len(items),
            "keyed_total": keyed_total,
            "scored_total": scored_total,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "answered_unscored_count": answered_unscored_count,
            "drafted_count": drafted_count,
            "skipped_incomplete_count": skipped_incomplete_count,
            "no_context_count": no_context_count,
            "invalid_response_count": invalid_count,
            "elapsed_seconds": elapsed,
            "items": report_items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote report: {args.output}")
    return 0

def mc_bench_cmd(args) -> int:
    settings, conn = open_db(args)
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    num_predict = args.num_predict if args.num_predict is not None else 32
    num_ctx = ollama_num_ctx(args, settings)
    if num_predict < 1:
        raise SystemExit("--num-predict must be 1 or greater.")
    if num_ctx < 1:
        raise SystemExit("--num-ctx must be 1 or greater.")

    quiz = load_quiz(args.quiz)
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    selected_role = normalize_answer_role(args.role)
    model_name = args.model or settings.ollama_model
    started_at = time.monotonic()
    ollama_client = None
    report_items = []
    keyed_total = correct_count = scored_total = no_context_count = invalid_count = 0

    print("MC benchmark")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  model: {model_name}")
    print(f"  questions: {len(items)}")
    print()

    for index, item in enumerate(items, start=1):
        item_started_at = time.monotonic()
        keyed = "correct" in item
        keyed_total += int(keyed)
        retrieval, retrieval_questions = _retrieve_quiz_context_for_item(
            conn,
            document_id=args.document_id,
            item=item,
            limit=args.limit,
            role=selected_role,
            section=args.section,
        )
        if not retrieval.rows and args.options_retrieval:
            option_query = compact_question_with_options(item)
            retrieval_questions.append(option_query)
            retrieval = _retrieve_mc_context(
                conn,
                document_id=args.document_id,
                question=option_query,
                limit=args.limit,
                role=selected_role,
                section=args.section,
            )
        context_rows = _add_quiz_source_context(
            conn,
            args.document_id,
            retrieval.rows,
            item,
            role=selected_role,
            section=args.section,
        )

        selected_chunks = [row["id"] for row in context_rows]
        selected_citations = [row["source_citation"] for row in context_rows]
        selected_option = None
        validation_status = None
        validation_error = None
        raw_response = ""
        answer_elapsed = None

        print(f"{item['id']}: {item['question']}")
        if args.debug_retrieval:
            _print_retrieval_debug(retrieval)
        print(f"  selected chunks: {', '.join(str(chunk) for chunk in selected_chunks) or 'none'}")

        if not context_rows:
            status = "no_context"
            no_context_count += 1
            print("  status: no_context")
        else:
            prompt = build_mc_prompt(item, context_rows, max_chars=args.chars)
            answer_started_at = time.monotonic()
            print(progress_line(model_name, index, len(items), item["id"]), flush=True)
            if ollama_client is None:
                from .. import create_client as _create_client
                ollama_client = _create_client(settings.ollama_host, settings.ollama_timeout)
            from .. import answer_mc_question as _answer_mc
            result = _answer_mc(
                prompt=prompt,
                model_name=model_name,
                host=settings.ollama_host,
                timeout=settings.ollama_timeout,
                num_predict=num_predict,
                num_ctx=num_ctx,
                allowed_options=tuple(item["options"].keys()),
                client=ollama_client,
            )
            answer_elapsed = time.monotonic() - answer_started_at
            selected_option = result.selected_option
            validation_status = result.validation_status
            validation_error = result.validation_error
            raw_response = result.raw_response
            if args.debug_ollama:
                _print_ollama_debug(None, result.debug_info)
            if result.validation_status != "valid":
                status = "invalid_response"
                invalid_count += 1
            elif keyed:
                scored_total += 1
                is_correct = result.selected_option == item["correct"]
                correct_count += int(is_correct)
                status = "correct" if is_correct else "incorrect"
            else:
                status = "unkeyed"
            print(f"  selected option: {selected_option or 'none'}")
            if keyed:
                print(f"  correct option: {item['correct']}")
            print(f"  validation: {validation_status}")
            print(f"  status: {status}")
        print()

        item_elapsed = time.monotonic() - item_started_at
        report_item = {
            "id": item["id"],
            "question": item["question"],
            "question_type": item.get("question_type") or "multiple_choice",
            "options": item["options"],
            "option_sources": item.get("option_sources", {}),
            "source_record_type": item.get("source_record_type"),
            "source_record_id": item.get("source_record_id"),
            "target": item.get("target"),
            "selected_option": selected_option,
            "selected_option_text": (
                item["options"].get(selected_option) if selected_option else None
            ),
            "validation_status": validation_status,
            "validation_error": validation_error,
            "selected_chunks": selected_chunks,
            "selected_source_citations": selected_citations,
            "queries_tried": retrieval.queries_tried,
            "retrieval_questions": retrieval_questions,
            "raw_response": raw_response,
            "timings": {
                "item_seconds": item_elapsed,
                "answer_seconds": answer_elapsed,
            },
            "status": status,
        }
        if keyed:
            report_item["correct"] = item["correct"]
            report_item["correct_option_text"] = item["options"].get(item["correct"])
            report_item["is_correct"] = status == "correct"
            _add_selected_option_provenance(report_item, item, selected_option)
        report_items.append(report_item)

    elapsed = time.monotonic() - started_at
    accuracy = correct_count / scored_total if scored_total else None
    print("MC benchmark summary:")
    print(f"  total: {len(items)}")
    print(f"  keyed total: {keyed_total}")
    print(f"  scored total: {scored_total}")
    print(f"  correct: {correct_count}")
    print(f"  accuracy: {accuracy:.1%}" if accuracy is not None else "  accuracy: n/a")
    print(f"  no-context cases: {no_context_count}")
    print(f"  invalid responses: {invalid_count}")
    print(f"  elapsed: {format_elapsed(elapsed)}")

    if args.output:
        report = {
            "document_id": args.document_id,
            "quiz": str(args.quiz),
            "model": model_name,
            "total": len(items),
            "keyed_total": keyed_total,
            "scored_total": scored_total,
            "correct_count": correct_count,
            "accuracy": accuracy,
            "no_context_count": no_context_count,
            "invalid_response_count": invalid_count,
            "elapsed_seconds": elapsed,
            "items": report_items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        print(f"  wrote report: {args.output}")
    return 0

def mc_compare_cmd(args) -> int:
    try:
        baseline = load_mc_bench_report(args.baseline, "baseline")
        candidate = load_mc_bench_report(args.candidate, "candidate")
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    comparison = compare_mc_bench_reports(baseline, candidate)

    print("MC benchmark comparison")
    print(f"  baseline: {args.baseline}")
    print(f"  candidate: {args.candidate}")
    print(f"  baseline model: {baseline.get('model') or 'n/a'}")
    print(f"  candidate model: {candidate.get('model') or 'n/a'}")
    print(f"  baseline accuracy: {_format_accuracy(comparison['baseline_accuracy'])}")
    print(f"  candidate accuracy: {_format_accuracy(comparison['candidate_accuracy'])}")
    print(f"  accuracy delta: {_format_accuracy_delta(comparison['accuracy_delta'])}")
    print(f"  common questions: {comparison['common_count']}")
    print(f"  added questions: {len(comparison['added_item_ids'])}")
    print(f"  removed questions: {len(comparison['removed_item_ids'])}")
    print(f"  correct -> incorrect: {len(comparison['correct_to_incorrect'])}")
    print(f"  incorrect -> correct: {len(comparison['incorrect_to_correct'])}")
    print(f"  answer changes: {len(comparison['answer_changes'])}")
    print(f"  retrieval changes: {len(comparison['retrieval_changes'])}")

    _print_mc_compare_section("correct -> incorrect", comparison["correct_to_incorrect"])
    _print_mc_compare_section("incorrect -> correct", comparison["incorrect_to_correct"])
    _print_mc_compare_section("answer changes", comparison["answer_changes"])
    _print_mc_compare_section("retrieval changes", comparison["retrieval_changes"])

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(comparison, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"  wrote comparison: {args.output}")
    return 0

def _retrieve_mc_context(
    conn,
    *,
    document_id: int,
    question: str,
    limit: int,
    role: str | None,
    section: str | None,
):
    return retrieve_with_fallbacks(
        search_func=lambda doc_id, query, limit, role, section: context_chunks(
            conn,
            doc_id,
            query,
            limit=limit,
            role=role,
            section=section,
        ),
        document_id=document_id,
        question=question,
        limit=limit,
        role=role,
        section=section,
    )

def _retrieve_quiz_context_for_item(
    conn,
    *,
    document_id: int,
    item: dict[str, object],
    limit: int,
    role: str | None,
    section: str | None,
):
    retrieval = None
    retrieval_questions = _quiz_retrieval_report_questions(item)
    for query in _quiz_retrieval_query_order(item):
        retrieval = _retrieve_mc_context(
            conn,
            document_id=document_id,
            question=query,
            limit=limit,
            role=role,
            section=section,
        )
        if retrieval.rows:
            return retrieval, retrieval_questions
    if retrieval is None:
        retrieval = _retrieve_mc_context(
            conn,
            document_id=document_id,
            question=str(item["question"]),
            limit=limit,
            role=role,
            section=section,
        )
    return retrieval, retrieval_questions


def _quiz_retrieval_report_questions(item: dict[str, object]) -> list[str]:
    return _dedupe_quiz_queries(
        [
            str(item["question"]),
            *[str(query) for query in _mc_retrieval_query_hints(item)],
        ]
    )


def _quiz_retrieval_query_order(item: dict[str, object]) -> list[str]:
    candidates = [*list(_mc_retrieval_query_hints(item)), str(item["question"])]
    return _dedupe_quiz_queries(candidates)


def _dedupe_quiz_queries(candidates: list[object]) -> list[str]:
    queries = []
    seen = set()
    for candidate in candidates:
        query = " ".join(candidate.split())
        key = _normalize_review_text(query)
        if query and key not in seen:
            seen.add(key)
            queries.append(query)
    return queries

def _add_quiz_source_context(
    conn,
    document_id: int,
    rows: list[dict],
    item: dict,
    *,
    role: str | None,
    section: str | None,
) -> list[dict]:
    source_chunks = []
    for chunk_id in item.get("source_chunks", []):
        try:
            source_chunks.append(int(chunk_id))
        except (TypeError, ValueError):
            continue
    if not source_chunks:
        return rows
    filters = ["id IN (" + ", ".join("?" for _ in source_chunks) + ")", "document_id = ?"]
    params: list[object] = [*source_chunks, document_id]
    source_rows = conn.execute(
        f"""
        SELECT
            id,
            document_id,
            chunk_index,
            page_start,
            page_end,
            source_citation,
            section_label,
            content_role,
            '' AS snippet,
            0.0 AS score,
            text
        FROM chunks
        WHERE {" AND ".join(filters)}
        """,
        params,
    ).fetchall()
    by_id = {int(row["id"]): dict(row) for row in source_rows}
    anchored = [by_id[chunk_id] for chunk_id in source_chunks if chunk_id in by_id]
    seen = {int(row["id"]) for row in anchored}
    return anchored + [row for row in rows if int(row["id"]) not in seen]
