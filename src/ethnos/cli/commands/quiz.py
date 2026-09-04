"""Quiz generation, import, review, validation, and benchmark commands."""

from __future__ import annotations

import argparse
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
from ..quiz_audit import (
    anchor_snippet as _anchor_snippet,
    build_source_grounding_record,
    load_quiz_bench_report,
    source_grounding_counts,
    verify_answer_key_report,
)
from ..quiz_manifest import (
    _keyed_choice_count,
    _quiz_warning_count,
    apply_chapter_quiz_item_overrides as _apply_chapter_quiz_item_overrides,
    chapter_quiz_file_stem as _chapter_quiz_file_stem,
    chapter_quiz_manifest_entry as _chapter_quiz_manifest_entry,
    chapter_quiz_unresolved_notes as _chapter_quiz_unresolved_notes,
    load_chapter_quiz_manifest as _load_chapter_quiz_manifest,
    validate_chapter_quiz_contract as _validate_chapter_quiz_contract,
    validate_imported_chapter_quiz_shape as _validate_imported_chapter_quiz_shape,
)

from ...db import context_chunks, get_document
from ...agent_tools import answer_support_details
from ...ollama_client import ChoiceAnswerResult
from ...qa import RetrievalResult, normalize_answer_role, retrieve_with_fallbacks
from ...quiz import (
    build_choice_prompt,
    build_essay_prompt,
    build_mc_prompt,
    compact_question_with_options,
    generate_quiz,
    import_canvas_quiz,
    import_lms_mc_quiz,
    load_quiz,
    recommended_choice_from_guidance,
)
from ...quiz_compare import compare_mc_bench_reports, load_mc_bench_report
from ...quiz_validation import (
    anchored_source_context_rows,
    is_incomplete_item,
    normalize_review_text as _normalize_review_text,
    source_retrieval_exclusion_reason,
    validate_mc_quiz_item as _validate_mc_quiz_item,
    validate_quiz_item as _validate_quiz_item,
)
from ...section_presets import SECTION_LABELS


def register(subcommands):
    generate_quiz_parser = add_command(
        subcommands,
        "generate-quiz",
        "Generate a local multiple-choice quiz from structured records.",
        generate_quiz_cmd,
    )
    generate_quiz_parser.add_argument("document_id", type=int)
    generate_quiz_parser.add_argument("--output", type=Path, required=True)
    generate_quiz_parser.add_argument(
        "--source", choices=["terms", "questions", "both"], default="terms"
    )
    generate_quiz_parser.add_argument("--limit", type=int)
    generate_quiz_parser.add_argument("--seed", type=int)
    generate_quiz_parser.add_argument("--max-option-chars", type=int, default=120)
    generate_quiz_parser.add_argument(
        "--difficulty",
        choices=["easy", "medium", "hard"],
        default="medium",
        help="Distractor difficulty: easy uses farther distractors, hard uses closer/shared-topic distractors.",
    )
    generate_quiz_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    generate_quiz_parser.add_argument("--section", choices=sorted(SECTION_LABELS))

    mc_bench_parser = add_command(
        subcommands,
        "mc-bench",
        "Run a multiple-choice benchmark using retrieved local PDF context.",
        mc_bench_cmd,
    )
    mc_bench_parser.add_argument("document_id", type=int)
    mc_bench_parser.add_argument("--quiz", type=Path, required=True)
    mc_bench_parser.add_argument("--max-questions", type=int)
    mc_bench_parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Retrieved context chunks per quiz question.",
    )
    mc_bench_parser.add_argument("--chars", type=int, default=300)
    mc_bench_parser.add_argument("--output", type=Path)
    mc_bench_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    mc_bench_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    mc_bench_parser.add_argument("--options-retrieval", action="store_true")
    mc_bench_parser.add_argument("--debug-ollama", action="store_true")
    mc_bench_parser.add_argument("--debug-retrieval", action="store_true")
    mc_bench_parser.add_argument("--model", help="Ollama model name.")
    mc_bench_parser.add_argument(
        "--num-predict",
        type=int,
        help="Ollama output token budget for the MC JSON answer.",
    )
    mc_bench_parser.add_argument(
        "--num-ctx", type=int, help="Ollama context window token budget."
    )

    mc_compare_parser = add_command(
        subcommands,
        "mc-compare",
        "Compare two multiple-choice benchmark JSON reports.",
        mc_compare_cmd,
    )
    mc_compare_parser.add_argument("baseline", type=Path)
    mc_compare_parser.add_argument("candidate", type=Path)
    mc_compare_parser.add_argument("--output", type=Path)

    verify_key_parser = add_command(
        subcommands,
        "verify-answer-key",
        "Audit keyed quiz answers from a quiz-bench report.",
        verify_answer_key_cmd,
    )
    verify_key_parser.add_argument("report", type=Path)
    verify_key_parser.add_argument("--output", type=Path)

    ground_quiz_parser = add_command(
        subcommands,
        "ground-quiz",
        "Build source-grounding records for every quiz item without model calls.",
        ground_quiz_cmd,
    )
    ground_quiz_parser.add_argument("document_id", type=int)
    ground_quiz_parser.add_argument("--quiz", type=Path, required=True)
    ground_quiz_parser.add_argument("--output", type=Path)
    ground_quiz_parser.add_argument("--max-questions", type=int)
    ground_quiz_parser.add_argument("--limit", type=int, default=3)
    ground_quiz_parser.add_argument("--chars", type=int, default=360)
    ground_quiz_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    ground_quiz_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    ground_quiz_parser.add_argument("--options-retrieval", action="store_true")
    ground_quiz_parser.add_argument(
        "--fail-unresolved",
        action="store_true",
        help="Exit nonzero when any item is ungrounded, invalidly anchored, or incomplete.",
    )

    import_mc_parser = add_command(
        subcommands,
        "import-mc-quiz",
        "Convert copied LMS quiz text into external multiple-choice quiz JSON.",
        import_mc_quiz_cmd,
    )
    import_mc_parser.add_argument("input", type=Path)
    import_mc_parser.add_argument("--output", type=Path, required=True)
    import_mc_parser.add_argument("--document-id", type=int)
    import_mc_parser.add_argument("--title")
    import_mc_parser.add_argument("--answer-key", type=Path)
    import_mc_parser.add_argument(
        "--id-prefix",
        default="q",
        help="Question id prefix before the zero-padded number, e.g. ch1-q.",
    )
    import_mc_parser.add_argument(
        "--with-key-preview",
        action="store_true",
        help="Print each keyed answer after writing the imported quiz.",
    )

    import_canvas_parser = add_command(
        subcommands,
        "import-canvas-quiz",
        "Convert pasted Canvas quiz text into external mixed quiz JSON.",
        import_canvas_quiz_cmd,
    )
    import_canvas_parser.add_argument("input", type=Path)
    import_canvas_parser.add_argument("--output", type=Path, required=True)
    import_canvas_parser.add_argument("--document-id", type=int)
    import_canvas_parser.add_argument("--title")
    import_canvas_parser.add_argument("--answer-key", type=Path)
    import_canvas_parser.add_argument(
        "--id-prefix",
        default="q",
        help="Question id prefix before the zero-padded number, e.g. ch1-q.",
    )
    import_canvas_parser.add_argument(
        "--with-key-preview",
        action="store_true",
        help="Print each keyed choice answer after writing the imported quiz.",
    )

    review_mc_parser = add_command(
        subcommands,
        "review-mc-quiz",
        "Print a multiple-choice quiz with keyed answers marked for review.",
        review_mc_quiz_cmd,
    )
    review_mc_parser.add_argument("quiz", type=Path)
    review_mc_parser.add_argument("--max-questions", type=int)

    validate_mc_parser = add_command(
        subcommands,
        "validate-mc-quiz",
        "Validate multiple-choice quiz keys and source anchors without calling Ollama.",
        validate_mc_quiz_cmd,
    )
    validate_mc_parser.add_argument("document_id", type=int)
    validate_mc_parser.add_argument("--quiz", type=Path, required=True)
    validate_mc_parser.add_argument("--max-questions", type=int)
    validate_mc_parser.add_argument(
        "--require-anchors",
        action="store_true",
        help="Require anchor fields unless an item is declared external-source.",
    )

    suggest_mc_parser = add_command(
        subcommands,
        "suggest-mc-anchors",
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
        subcommands,
        "review-quiz",
        "Print a mixed quiz with keyed answers and warnings marked for review.",
        review_quiz_cmd,
    )
    review_quiz_parser.add_argument("quiz", type=Path)
    review_quiz_parser.add_argument("--max-questions", type=int)

    validate_quiz_parser = add_command(
        subcommands,
        "validate-quiz",
        "Validate mixed quiz keys, completion, and source anchors without Ollama.",
        validate_quiz_cmd,
    )
    validate_quiz_parser.add_argument("document_id", type=int)
    validate_quiz_parser.add_argument("--quiz", type=Path, required=True)
    validate_quiz_parser.add_argument("--max-questions", type=int)
    validate_quiz_parser.add_argument(
        "--require-anchors",
        action="store_true",
        help="Require anchor fields unless an item is declared external-source.",
    )
    validate_quiz_parser.add_argument(
        "--strict-complete",
        action="store_true",
        help="Treat incomplete items and other import warnings as errors.",
    )

    quiz_bench_parser = add_command(
        subcommands,
        "quiz-bench",
        "Run a mixed quiz benchmark using retrieved local PDF context.",
        quiz_bench_cmd,
    )
    quiz_bench_parser.add_argument("document_id", type=int)
    quiz_bench_parser.add_argument("--quiz", type=Path, required=True)
    quiz_bench_parser.add_argument("--max-questions", type=int)
    quiz_bench_parser.add_argument(
        "--item-id",
        dest="item_ids",
        action="append",
        default=[],
        metavar="ID",
        help="Benchmark only this quiz item ID; repeat for multiple items.",
    )
    quiz_bench_parser.add_argument("--limit", type=int, default=3)
    quiz_bench_parser.add_argument("--chars", type=int, default=900)
    quiz_bench_parser.add_argument("--output", type=Path)
    quiz_bench_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an incomplete checkpoint from --output.",
    )
    quiz_bench_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    quiz_bench_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    quiz_bench_parser.add_argument("--options-retrieval", action="store_true")
    quiz_bench_parser.add_argument("--debug-ollama", action="store_true")
    quiz_bench_parser.add_argument("--debug-retrieval", action="store_true")
    quiz_bench_parser.add_argument("--model", help="Ollama model name.")
    quiz_bench_parser.add_argument("--num-predict", type=int)
    quiz_bench_parser.add_argument("--num-ctx", type=int)
    quiz_bench_parser.add_argument(
        "--answer-retries",
        type=int,
        default=1,
        help="Retry a choice response that is invalid or inconsistent with its evidence.",
    )

    quiz_pipeline_parser = add_command(
        subcommands,
        "quiz-pipeline",
        "Run quiz validation, grounding, optional benchmark, and key audit.",
        quiz_pipeline_cmd,
    )
    quiz_pipeline_parser.add_argument("document_id", type=int)
    quiz_pipeline_parser.add_argument("--quiz", type=Path, required=True)
    quiz_pipeline_parser.add_argument("--max-questions", type=int)
    quiz_pipeline_parser.add_argument("--limit", type=int, default=3)
    quiz_pipeline_parser.add_argument("--chars", type=int, default=900)
    quiz_pipeline_parser.add_argument("--role", choices=ASK_ROLES, default="core")
    quiz_pipeline_parser.add_argument("--section", choices=sorted(SECTION_LABELS))
    quiz_pipeline_parser.add_argument("--options-retrieval", action="store_true")
    quiz_pipeline_parser.add_argument(
        "--require-anchors",
        action="store_true",
        help="Require anchor fields unless an item is declared external-source.",
    )
    quiz_pipeline_parser.add_argument(
        "--strict-complete",
        action="store_true",
        help="Treat incomplete items and other import warnings as errors.",
    )
    quiz_pipeline_parser.add_argument(
        "--grounding-output",
        type=Path,
        help="Write the source-grounding report.",
    )
    quiz_pipeline_parser.add_argument(
        "--fail-unresolved",
        action="store_true",
        help="Exit nonzero when grounding finds unresolved local PDF source status.",
    )
    quiz_pipeline_parser.add_argument(
        "--bench-output",
        type=Path,
        help="Run quiz-bench and write this benchmark report.",
    )
    quiz_pipeline_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an incomplete quiz-bench checkpoint from --bench-output.",
    )
    quiz_pipeline_parser.add_argument("--model", help="Ollama model name.")
    quiz_pipeline_parser.add_argument("--num-predict", type=int)
    quiz_pipeline_parser.add_argument("--num-ctx", type=int)
    quiz_pipeline_parser.add_argument(
        "--answer-retries",
        type=int,
        default=1,
        help="Retry a choice response that is invalid or inconsistent with its evidence.",
    )
    quiz_pipeline_parser.add_argument(
        "--key-audit-output",
        type=Path,
        help="Write the answer-key audit after a successful benchmark.",
    )
    quiz_pipeline_parser.add_argument(
        "--skip-key-audit",
        action="store_true",
        help="Skip verify-answer-key after quiz-bench.",
    )

    import_chapter_parser = add_command(
        subcommands,
        "import-chapter-quiz",
        "Import, validate, and contract-check one chapter Canvas quiz fixture.",
        import_chapter_quiz_cmd,
    )
    import_chapter_parser.add_argument(
        "course", help="Course fixture prefix, e.g. ethics."
    )
    import_chapter_parser.add_argument(
        "chapter", type=int, help="Chapter number to import."
    )
    import_chapter_parser.add_argument(
        "--manifest",
        type=Path,
        help="Chapter quiz manifest. Defaults to benchmarks/<course>_chapter_quizzes.json.",
    )
    import_chapter_parser.add_argument(
        "--base-dir",
        type=Path,
        default=Path("benchmarks"),
        help="Directory containing raw, key, and imported chapter quiz files.",
    )
    import_chapter_parser.add_argument(
        "--strict-complete",
        action="store_true",
        help="Treat incomplete items and other import warnings as errors.",
    )
    import_chapter_parser.add_argument(
        "--review",
        action="store_true",
        help="Print the full keyed/unkeyed quiz review after the summary.",
    )


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


def verify_answer_key_cmd(args) -> int:
    try:
        report = load_quiz_bench_report(args.report)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if report.get("complete") is False:
        raise SystemExit(
            "Cannot verify an incomplete quiz benchmark "
            f"({report.get('processed_total', 0)}/{report.get('total', '?')} items). "
            "Resume quiz-bench first."
        )
    audit = verify_answer_key_report(report, report_path=args.report)

    print("Answer key verification")
    print(f"  report: {args.report}")
    print(f"  quiz: {audit.get('quiz') or 'n/a'}")
    print(f"  model: {audit.get('model') or 'n/a'}")
    print(f"  keyed items: {audit['keyed_item_count']}")
    print(f"  supported: {audit['key_supported_count']}")
    print(f"  conflict candidates: {audit['key_conflict_candidate_count']}")
    print(f"  no PDF context: {audit['no_pdf_context_count']}")
    print(f"  source missing in local PDF: {audit['source_missing_count']}")
    print(f"  incomplete: {audit['incomplete_count']}")
    print(f"  invalid anchors: {audit['invalid_anchor_count']}")
    print(f"  invalid responses: {audit['invalid_response_count']}")
    print(f"  disputed keys: {audit['disputed_key_count']}")
    print()

    findings = [
        item for item in audit["items"] if item["audit_status"] != "key_supported"
    ]
    if findings:
        print("Findings:")
        for item in findings:
            print(f"{item['id']}: {item['audit_status']}")
            print(f"  question: {item['question']}")
            if item.get("keyed_option"):
                print(
                    f"  keyed: {item['keyed_option']} - "
                    f"{item.get('keyed_option_text') or 'n/a'}"
                )
            if item.get("selected_option"):
                print(
                    f"  selected: {item['selected_option']} - "
                    f"{item.get('selected_option_text') or 'n/a'}"
                )
            if item.get("evidence"):
                print(f"  evidence: {item['evidence']}")
            citations = item.get("source_citations") or []
            if citations:
                print(
                    f"  citations: {', '.join(str(citation) for citation in citations)}"
                )
    else:
        print("Findings: none")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(audit, indent=2, sort_keys=True), encoding="utf-8"
        )
        print()
        print(f"wrote audit: {args.output}")
    return (
        1
        if audit["key_conflict_candidate_count"] or audit["invalid_anchor_count"]
        else 0
    )


def ground_quiz_cmd(args) -> int:
    _, conn = open_db(args)
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    get_document(conn, args.document_id)
    quiz = load_quiz(args.quiz)
    items = limit_benchmark_items(quiz["questions"], args.max_questions)
    selected_role = normalize_answer_role(args.role)
    records = []

    print("Quiz grounding")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  questions: {len(items)}")
    print(f"  candidate chunks per query: {args.limit}")
    print()

    for item in items:
        retrieval, retrieval_questions = _retrieve_quiz_context_for_item(
            conn,
            document_id=args.document_id,
            item=item,
            limit=args.limit,
            role=selected_role,
            section=args.section,
        )
        if args.options_retrieval and str(
            item.get("question_type") or "multiple_choice"
        ) in {"multiple_choice", "true_false"}:
            retrieval, retrieval_questions = _with_option_aware_retrieval(
                conn,
                document_id=args.document_id,
                item=item,
                retrieval=retrieval,
                retrieval_questions=retrieval_questions,
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
        record = build_source_grounding_record(
            conn,
            document_id=args.document_id,
            item=item,
            context_rows=context_rows,
            retrieval=retrieval,
            retrieval_questions=retrieval_questions,
            chars=args.chars,
        )
        records.append(record)
        print(f"{record['id']}: {record['source_status']}")
        print(f"  type: {record['question_type']}")
        print(
            "  source chunks: "
            + (
                ", ".join(str(chunk_id) for chunk_id in record["source_chunks"])
                or "none"
            )
        )
        if record["source_citations"]:
            print(f"  citations: {', '.join(record['source_citations'])}")
        if record["validation_errors"]:
            print(f"  validation errors: {', '.join(record['validation_errors'])}")
        print()

    counts = source_grounding_counts(records)
    unresolved_count = sum(
        count
        for status, count in counts.items()
        if status in {"ungrounded", "invalid_anchor", "incomplete"}
    )
    report = {
        "version": "quiz-grounding-v1",
        "document_id": args.document_id,
        "quiz": str(args.quiz),
        "total": len(records),
        "counts": counts,
        "unresolved_count": unresolved_count,
        "items": records,
    }

    print("Quiz grounding summary:")
    print(f"  total: {len(records)}")
    for status, count in counts.items():
        print(f"  {status}: {count}")
    print(f"  unresolved: {unresolved_count}")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"  wrote grounding: {args.output}")
    return 1 if args.fail_unresolved and unresolved_count else 0


def import_mc_quiz_cmd(args) -> int:
    raw_text = args.input.read_text(encoding="utf-8")
    answer_key_text = (
        args.answer_key.read_text(encoding="utf-8")
        if args.answer_key is not None
        else None
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
        args.answer_key.read_text(encoding="utf-8")
        if args.answer_key is not None
        else None
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


def import_chapter_quiz_cmd(args) -> int:
    _, conn = open_db(args)
    if args.chapter < 1:
        raise SystemExit("chapter must be 1 or greater.")
    manifest_path = (
        args.manifest or args.base_dir / f"{args.course}_chapter_quizzes.json"
    )
    try:
        manifest = _load_chapter_quiz_manifest(manifest_path)
        chapter = _chapter_quiz_manifest_entry(manifest, args.chapter)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    document_id = int(chapter.get("document_id") or manifest.get("document_id") or 0)
    if document_id < 1:
        raise SystemExit("Chapter quiz manifest must define document_id.")
    get_document(conn, document_id)

    stem = _chapter_quiz_file_stem(manifest, args.course, args.chapter)
    raw_path = args.base_dir / f"{stem}_raw.txt"
    answer_key_path = args.base_dir / f"{stem}_answer_key.txt"
    output_path = args.base_dir / f"{stem}.json"
    if not raw_path.exists():
        raise SystemExit(f"Raw Canvas quiz file not found: {raw_path}")
    answer_key_text = None
    if answer_key_path.exists():
        answer_key_text = answer_key_path.read_text(encoding="utf-8")
    elif int(chapter.get("expected_keyed_choices") or 0) > 0:
        raise SystemExit(
            f"Expected keyed choices but answer key file is missing: {answer_key_path}"
        )

    try:
        quiz = import_canvas_quiz(
            raw_path.read_text(encoding="utf-8"),
            document_id=document_id,
            title=str(chapter.get("title") or f"Quiz CH {args.chapter}"),
            answer_key_text=answer_key_text,
            id_prefix=f"ch{args.chapter}-q",
        )
        _apply_chapter_quiz_item_overrides(quiz, chapter)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    shape_errors = _validate_imported_chapter_quiz_shape(
        conn,
        document_id=document_id,
        quiz=quiz,
        strict_complete=args.strict_complete,
    )
    contract_errors = _validate_chapter_quiz_contract(
        quiz,
        chapter=chapter,
        chapter_number=args.chapter,
    )
    errors = [*shape_errors, *contract_errors]
    wrote_output = False
    if not errors:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(quiz, indent=2, sort_keys=True), encoding="utf-8"
        )
        wrote_output = True
    keyed_count = _keyed_choice_count(quiz["questions"])
    warning_count = _quiz_warning_count(quiz["questions"])

    print("Chapter quiz import")
    print(f"  course: {args.course}")
    print(f"  chapter: {args.chapter}")
    print(f"  manifest: {manifest_path}")
    print(f"  raw: {raw_path}")
    print(f"  answer key: {answer_key_path if answer_key_path.exists() else 'none'}")
    print(f"  output: {output_path}")
    print(f"  wrote output: {'yes' if wrote_output else 'no'}")
    print(f"  document id: {document_id}")
    print(f"  title: {quiz.get('title') or 'n/a'}")
    print(f"  questions: {len(quiz['questions'])}")
    print(f"  total points: {quiz.get('total_points') or 0}")
    print(f"  keyed choices: {keyed_count}")
    print(f"  warnings: {warning_count}")
    if errors:
        print()
        print("Validation failed")
        print(f"  errors: {len(errors)}")
        for error in errors:
            print(f"  - {error}")
    else:
        print()
        print("Validation passed")
    unresolved = _chapter_quiz_unresolved_notes(quiz)
    if unresolved:
        print()
        print("Unresolved")
        for note in unresolved:
            print(f"  - {note}")
    if args.review:
        print()
        _print_quiz_preview(quiz["questions"], include_options=True)
    return 1 if errors else 0


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
                print(
                    f"    chunk {candidate['chunk_id']}: {candidate['source_citation']}"
                )
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
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
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
    correct_option_text = (
        str(options.get(correct) or "") if isinstance(options, dict) else ""
    )
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
    report_item["selected_distractor_source_record_id"] = source.get("source_record_id")
    report_item["selected_distractor_target"] = source.get("target")
    report_item["selected_distractor_source_citation"] = source.get("source_citation")


def _select_quiz_benchmark_items(
    questions: list[dict[str, object]],
    *,
    max_questions: int | None,
    item_ids: list[str],
) -> list[dict[str, object]]:
    if not item_ids:
        return limit_benchmark_items(questions, max_questions)
    requested = list(dict.fromkeys(str(item_id) for item_id in item_ids))
    by_id = {str(item.get("id") or ""): item for item in questions}
    missing = [item_id for item_id in requested if item_id not in by_id]
    if missing:
        raise SystemExit("Unknown --item-id value(s): " + ", ".join(missing))
    return [item for item in questions if str(item.get("id") or "") in requested]


def _choice_response_retry_reason(
    result: ChoiceAnswerResult,
    *,
    item: dict[str, object],
    context_rows: list[dict[str, object]],
) -> str | None:
    if result.validation_status != "valid":
        return (
            f"response validation failed ({result.validation_status}): "
            f"{result.validation_error or 'unknown error'}"
        )
    recommended = recommended_choice_from_guidance(item, context_rows)
    if recommended and result.selected_option != recommended:
        return (
            f"selected option {result.selected_option} conflicts with "
            f"source-derived guidance to select option {recommended}"
        )
    options = item.get("options")
    if (
        not result.selected_option
        or not isinstance(options, dict)
        or result.selected_option not in options
    ):
        return None
    evidence = str(result.evidence or "").strip()
    selected_support = answer_support_details(
        str(options[result.selected_option]),
        [{"text": evidence}],
    )
    selected_confidence = float(selected_support["confidence_score"])
    if len(evidence.split()) < 6 and selected_confidence < 0.72:
        return "evidence is too short to justify the selected option"
    alternative_confidence = max(
        (
            float(
                answer_support_details(str(text), [{"text": evidence}])[
                    "confidence_score"
                ]
            )
            for label, text in options.items()
            if label != result.selected_option
        ),
        default=0.0,
    )
    if selected_confidence <= 0.35 and alternative_confidence >= 0.72:
        return "evidence does not support the selected option wording"
    if not result.source_citations:
        return "response did not include a source citation"
    return None


def _choice_retry_prompt(
    prompt: str,
    *,
    result: ChoiceAnswerResult,
    reason: str,
) -> str:
    prior_evidence = str(result.evidence or "").strip() or "(none)"
    return (
        f"{prompt}\n\nRETRY REQUIRED: {reason}. "
        f"The previous evidence was: {prior_evidence!r}. "
        "Re-evaluate every option from the supplied context. Ensure the selected "
        "letter matches the option described by your evidence, and return complete "
        "schema-valid JSON."
    )


def quiz_bench_cmd(args) -> int:
    settings, conn = open_db(args)
    if args.resume and args.output is None:
        raise SystemExit("--resume requires --output.")
    if args.limit < 1:
        raise SystemExit("--limit must be 1 or greater.")
    if args.chars < 1:
        raise SystemExit("--chars must be 1 or greater.")
    if args.max_questions is not None and args.max_questions < 1:
        raise SystemExit("--max-questions must be 1 or greater.")
    if args.max_questions is not None and args.item_ids:
        raise SystemExit("--max-questions cannot be combined with --item-id.")
    if args.answer_retries < 0:
        raise SystemExit("--answer-retries must be 0 or greater.")
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
    item_ids = list(dict.fromkeys(args.item_ids))
    items = _select_quiz_benchmark_items(
        quiz["questions"],
        max_questions=args.max_questions,
        item_ids=item_ids,
    )
    selected_role = normalize_answer_role(args.role)
    model_name = args.model or settings.ollama_model
    started_at = time.monotonic()
    ollama_client = None
    run_config = {
        "limit": args.limit,
        "chars": args.chars,
        "role": selected_role,
        "section": args.section,
        "options_retrieval": args.options_retrieval,
        "max_questions": args.max_questions,
        "item_ids": item_ids,
        "answer_retries": args.answer_retries,
        "num_predict": num_predict,
        "num_ctx": num_ctx,
    }
    report_items: list[dict[str, object]] = []
    previous_elapsed = 0.0
    if args.resume:
        if not args.output.exists():
            raise SystemExit(f"Resume checkpoint not found: {args.output}")
        try:
            checkpoint = load_quiz_bench_report(args.output)
            report_items, previous_elapsed = _validate_quiz_bench_resume(
                checkpoint,
                document_id=args.document_id,
                quiz_path=args.quiz,
                model_name=model_name,
                items=items,
                run_config=run_config,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc

    print("Quiz benchmark")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  model: {model_name}")
    print(f"  questions: {len(items)}")
    if item_ids:
        print(f"  selected item ids: {', '.join(item_ids)}")
    if report_items:
        print(f"  resumed: {len(report_items)}/{len(items)} items")
    print()

    if len(report_items) == len(items):
        print("Quiz benchmark already complete; nothing to resume.")
        return 0

    if args.output:
        _write_quiz_bench_report(
            args.output,
            document_id=args.document_id,
            quiz_path=args.quiz,
            model_name=model_name,
            items=items,
            report_items=report_items,
            run_config=run_config,
            elapsed_seconds=previous_elapsed,
        )

    for index, item in enumerate(
        items[len(report_items) :], start=len(report_items) + 1
    ):
        item_started_at = time.monotonic()
        question_type = str(item.get("question_type") or "multiple_choice")
        keyed = question_type in {"multiple_choice", "true_false"} and "correct" in item
        disputed_key = item.get("key_review_status") == "disputed"
        selected_option = None
        validation_status = None
        validation_error = None
        raw_response = ""
        answer_elapsed = None
        answer_payload: dict[str, object] = {}
        answer_attempts: list[dict[str, object]] = []
        answer_retry_reasons: list[str] = []
        retrieval, retrieval_questions = _retrieve_quiz_context_for_item(
            conn,
            document_id=args.document_id,
            item=item,
            limit=args.limit,
            role=selected_role,
            section=args.section,
        )
        if args.options_retrieval and question_type in {
            "multiple_choice",
            "true_false",
        }:
            retrieval, retrieval_questions = _with_option_aware_retrieval(
                conn,
                document_id=args.document_id,
                item=item,
                retrieval=retrieval,
                retrieval_questions=retrieval_questions,
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
        source_grounding = build_source_grounding_record(
            conn,
            document_id=args.document_id,
            item=item,
            context_rows=context_rows,
            retrieval=retrieval,
            retrieval_questions=retrieval_questions,
            chars=args.chars,
        )
        selected_chunks = [row["id"] for row in context_rows]
        selected_citations = [row["source_citation"] for row in context_rows]

        print(f"{item['id']}: {item['question']}")
        print(f"  type: {question_type}")
        if args.debug_retrieval:
            _print_retrieval_debug(retrieval)
        print(
            f"  selected chunks: {', '.join(str(chunk) for chunk in selected_chunks) or 'none'}"
        )

        if "external_source_item" in item.get("warnings", []):
            status = "skipped_source_missing"
            print("  status: skipped_source_missing")
        elif is_incomplete_item(item):
            status = "skipped_incomplete"
            print("  status: skipped_incomplete")
        elif source_grounding.get("source_status") == "invalid_anchor":
            status = "invalid_anchor"
            print("  status: invalid_anchor")
        elif question_type == "matching":
            status = "skipped_matching"
            print("  status: skipped_matching")
        elif not context_rows:
            status = "no_context"
            print("  status: no_context")
        elif question_type in {"multiple_choice", "true_false"}:
            prompt_item = {
                **item,
                "_context_target": retrieval.selected_query or "",
            }
            prompt = build_choice_prompt(
                prompt_item, context_rows, max_chars=args.chars
            )
            answer_started_at = time.monotonic()
            print(progress_line(model_name, index, len(items), item["id"]), flush=True)
            if ollama_client is None:
                # Late import to support monkeypatching via "ethnos.cli.*"
                from .. import create_client as _create_client

                ollama_client = _create_client(
                    settings.ollama_host, settings.ollama_timeout
                )
            # Late import to support monkeypatching
            from .. import answer_choice_question as _answer_choice

            attempt_prompt = prompt
            try:
                for attempt in range(args.answer_retries + 1):
                    result = _answer_choice(
                        prompt=attempt_prompt,
                        model_name=model_name,
                        host=settings.ollama_host,
                        timeout=settings.ollama_timeout,
                        num_predict=num_predict,
                        num_ctx=num_ctx,
                        allowed_options=tuple(item["options"].keys()),
                        client=ollama_client,
                        think=settings.ollama_think,
                    )
                    answer_attempts.append(
                        {
                            "attempt": attempt + 1,
                            "selected_option": result.selected_option,
                            "validation_status": result.validation_status,
                            "validation_error": result.validation_error,
                            "evidence": result.evidence,
                            "source_citations": result.source_citations,
                            "raw_response": result.raw_response,
                        }
                    )
                    retry_reason = _choice_response_retry_reason(
                        result,
                        item=item,
                        context_rows=context_rows,
                    )
                    if retry_reason is None or attempt == args.answer_retries:
                        break
                    answer_retry_reasons.append(retry_reason)
                    print(
                        f"  retrying answer ({attempt + 1}/{args.answer_retries}): "
                        f"{retry_reason}"
                    )
                    attempt_prompt = _choice_retry_prompt(
                        prompt,
                        result=result,
                        reason=retry_reason,
                    )
            except KeyboardInterrupt:
                print()
                print(
                    f"Quiz benchmark interrupted; checkpoint preserved at {args.output}"
                    if args.output
                    else "Quiz benchmark interrupted; no --output checkpoint was requested."
                )
                return 130
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
            elif keyed:
                is_correct = result.selected_option == item["correct"]
                status = "correct" if is_correct else "incorrect"
            else:
                status = "answered_unscored"
            print(f"  selected option: {selected_option or 'none'}")
            if keyed:
                print(f"  correct option: {item['correct']}")
                if disputed_key:
                    print("  scoring: excluded from grounded accuracy (disputed key)")
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

                ollama_client = _create_client(
                    settings.ollama_host, settings.ollama_timeout
                )
            from .. import answer_essay_question as _answer_essay

            try:
                result = _answer_essay(
                    prompt=prompt,
                    model_name=model_name,
                    host=settings.ollama_host,
                    timeout=settings.ollama_timeout,
                    num_predict=num_predict,
                    num_ctx=num_ctx,
                    client=ollama_client,
                    think=settings.ollama_think,
                )
            except KeyboardInterrupt:
                print()
                print(
                    f"Quiz benchmark interrupted; checkpoint preserved at {args.output}"
                    if args.output
                    else "Quiz benchmark interrupted; no --output checkpoint was requested."
                )
                return 130
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
            else:
                status = "invalid_response"
            print(f"  validation: {validation_status}")
            print(f"  status: {status}")
        else:
            status = "unsupported"
            print("  status: unsupported")
        print()

        item_elapsed = time.monotonic() - item_started_at
        options = item.get("options") if isinstance(item.get("options"), dict) else {}
        scoring_eligible = bool(
            keyed and not disputed_key and status in {"correct", "incorrect"}
        )
        report_item = {
            "id": item["id"],
            "position": item.get("position"),
            "question": item["question"],
            "question_type": question_type,
            "points": item.get("points"),
            "options": options,
            "warnings": item.get("warnings", []),
            "target": item.get("target"),
            "key_review_status": item.get("key_review_status"),
            "instructor_key_note": item.get("instructor_key_note"),
            "scoring_eligible": scoring_eligible,
            "selected_option": selected_option,
            "selected_option_text": options.get(selected_option)
            if selected_option
            else None,
            "validation_status": validation_status,
            "validation_error": validation_error,
            "selected_chunks": selected_chunks,
            "selected_source_citations": selected_citations,
            "queries_tried": retrieval.queries_tried,
            "retrieval_questions": retrieval_questions,
            "source_grounding": source_grounding,
            "raw_response": raw_response,
            "answer": answer_payload,
            "answer_attempt_count": len(answer_attempts),
            "answer_retry_reasons": answer_retry_reasons,
            "answer_attempts": answer_attempts,
            "timings": {
                "item_seconds": item_elapsed,
                "answer_seconds": answer_elapsed,
            },
            "status": status,
        }
        if keyed:
            report_item["correct"] = item["correct"]
            report_item["correct_option_text"] = options.get(item["correct"])
            report_item["is_correct"] = (
                status == "correct" if scoring_eligible else None
            )
            _add_selected_option_provenance(report_item, item, selected_option)
        if question_type == "matching":
            report_item["matching_prompts"] = item.get("matching_prompts", [])
            report_item["matching_pairs"] = item.get("matching_pairs", [])
        report_items.append(report_item)
        if args.output:
            _write_quiz_bench_report(
                args.output,
                document_id=args.document_id,
                quiz_path=args.quiz,
                model_name=model_name,
                items=items,
                report_items=report_items,
                run_config=run_config,
                elapsed_seconds=previous_elapsed + (time.monotonic() - started_at),
            )

    elapsed = time.monotonic() - started_at
    elapsed_total = previous_elapsed + elapsed
    counts = _quiz_bench_counts(report_items)
    keyed_total = counts["keyed_total"]
    scored_total = counts["scored_total"]
    correct_count = counts["correct_count"]
    accuracy = counts["accuracy"]
    instructor_key_agreement_total = counts["instructor_key_agreement_total"]
    instructor_key_agreement_count = counts["instructor_key_agreement_count"]
    instructor_key_agreement = counts["instructor_key_agreement"]
    disputed_key_count = counts["disputed_key_count"]
    source_covered_total = counts["source_covered_total"]
    source_coverage = counts["source_coverage"]
    answered_unscored_count = counts["answered_unscored_count"]
    drafted_count = counts["drafted_count"]
    skipped_incomplete_count = counts["skipped_incomplete_count"]
    skipped_source_missing_count = counts["skipped_source_missing_count"]
    no_context_count = counts["no_context_count"]
    invalid_anchor_count = counts["invalid_anchor_count"]
    invalid_count = counts["invalid_response_count"]
    retried_item_count = counts["retried_item_count"]
    answer_retry_count = counts["answer_retry_count"]
    print("Quiz benchmark summary:")
    print(f"  total: {len(items)}")
    print(f"  keyed total: {keyed_total}")
    print(f"  scored total: {scored_total}")
    print(f"  correct: {correct_count}")
    print(
        f"  grounded accuracy: {accuracy:.1%}"
        if accuracy is not None
        else "  grounded accuracy: n/a"
    )
    print(
        "  instructor-key agreement: "
        f"{instructor_key_agreement_count}/{instructor_key_agreement_total} "
        f"({instructor_key_agreement:.1%})"
        if instructor_key_agreement is not None
        else "  instructor-key agreement: n/a"
    )
    print(f"  disputed keys excluded from grounded accuracy: {disputed_key_count}")
    print(
        f"  source coverage: {source_covered_total}/{len(items)} ({source_coverage:.1%})"
        if source_coverage is not None
        else "  source coverage: n/a"
    )
    print(f"  answered unscored: {answered_unscored_count}")
    print(f"  essays drafted: {drafted_count}")
    print(f"  skipped incomplete: {skipped_incomplete_count}")
    print(f"  skipped source-missing: {skipped_source_missing_count}")
    print(f"  no-context cases: {no_context_count}")
    print(f"  invalid anchors: {invalid_anchor_count}")
    print(f"  invalid responses: {invalid_count}")
    print(f"  retried items: {retried_item_count}")
    print(f"  answer retries: {answer_retry_count}")
    print(f"  elapsed: {format_elapsed(elapsed_total)}")

    if args.output:
        _write_quiz_bench_report(
            args.output,
            document_id=args.document_id,
            quiz_path=args.quiz,
            model_name=model_name,
            items=items,
            report_items=report_items,
            run_config=run_config,
            elapsed_seconds=elapsed_total,
        )
        print(f"  wrote report: {args.output}")
    return 0


def quiz_pipeline_cmd(args) -> int:
    if args.resume and args.bench_output is None:
        raise SystemExit("--resume requires --bench-output.")
    if args.skip_key_audit and args.key_audit_output is not None:
        raise SystemExit("--skip-key-audit cannot be combined with --key-audit-output.")

    print("Quiz pipeline")
    print(f"  document id: {args.document_id}")
    print(f"  quiz: {args.quiz}")
    print(f"  benchmark: {'yes' if args.bench_output else 'no'}")
    print()

    validate_args = argparse.Namespace(
        db=args.db,
        document_id=args.document_id,
        quiz=args.quiz,
        max_questions=args.max_questions,
        require_anchors=args.require_anchors,
        strict_complete=args.strict_complete,
    )
    code = _run_quiz_pipeline_step("validate", validate_quiz_cmd, validate_args)
    if code:
        return code

    ground_args = argparse.Namespace(
        db=args.db,
        document_id=args.document_id,
        quiz=args.quiz,
        output=args.grounding_output,
        max_questions=args.max_questions,
        limit=args.limit,
        chars=args.chars,
        role=args.role,
        section=args.section,
        options_retrieval=args.options_retrieval,
        fail_unresolved=args.fail_unresolved,
    )
    code = _run_quiz_pipeline_step("ground", ground_quiz_cmd, ground_args)
    if code:
        return code

    if args.bench_output is None:
        print("Pipeline complete")
        print("  benchmark: skipped")
        return 0

    bench_args = argparse.Namespace(
        db=args.db,
        document_id=args.document_id,
        quiz=args.quiz,
        max_questions=args.max_questions,
        item_ids=[],
        limit=args.limit,
        chars=args.chars,
        output=args.bench_output,
        resume=args.resume,
        role=args.role,
        section=args.section,
        options_retrieval=args.options_retrieval,
        debug_ollama=False,
        debug_retrieval=False,
        model=args.model,
        num_predict=args.num_predict,
        num_ctx=args.num_ctx,
        answer_retries=args.answer_retries,
    )
    code = _run_quiz_pipeline_step("benchmark", quiz_bench_cmd, bench_args)
    if code:
        return code

    if args.skip_key_audit:
        print("Pipeline complete")
        print("  key audit: skipped")
        return 0

    audit_args = argparse.Namespace(
        report=args.bench_output,
        output=args.key_audit_output,
    )
    code = _run_quiz_pipeline_step("key audit", verify_answer_key_cmd, audit_args)
    if code:
        return code

    print("Pipeline complete")
    return 0


def _run_quiz_pipeline_step(
    name: str,
    handler,
    args: argparse.Namespace,
) -> int:
    print(f"== {name} ==")
    code = handler(args)
    print()
    if code:
        print(f"Pipeline stopped after {name}: exit {code}")
    return code


def _quiz_bench_counts(report_items: list[dict[str, object]]) -> dict[str, object]:
    statuses = [str(item.get("status") or "") for item in report_items]
    invalid_anchor_count = sum(
        _report_item_has_invalid_anchor(item) for item in report_items
    )
    key_comparisons = [
        item
        for item in report_items
        if str(item.get("status") or "") in {"correct", "incorrect"}
        and _report_item_non_scoring_source_status(item) is None
    ]
    scoring_eligible = [
        item for item in key_comparisons if item.get("scoring_eligible") is not False
    ]
    scored_total = len(scoring_eligible)
    correct_count = sum(item.get("status") == "correct" for item in scoring_eligible)
    instructor_key_agreement_total = len(key_comparisons)
    instructor_key_agreement_count = sum(
        item.get("status") == "correct" for item in key_comparisons
    )
    processed_total = len(report_items)
    skipped_source_missing_count = statuses.count("skipped_source_missing")
    source_covered_total = sum(
        isinstance(item.get("source_grounding"), dict)
        and item["source_grounding"].get("source_status")
        in {"pdf_grounded", "retrieved_candidate"}
        for item in report_items
    )
    return {
        "processed_total": processed_total,
        "keyed_total": sum("correct" in item for item in report_items),
        "scored_total": scored_total,
        "correct_count": correct_count,
        "accuracy": correct_count / scored_total if scored_total else None,
        "instructor_key_agreement_total": instructor_key_agreement_total,
        "instructor_key_agreement_count": instructor_key_agreement_count,
        "instructor_key_agreement": (
            instructor_key_agreement_count / instructor_key_agreement_total
            if instructor_key_agreement_total
            else None
        ),
        "disputed_key_count": sum(
            item.get("key_review_status") == "disputed" for item in report_items
        ),
        "source_covered_total": source_covered_total,
        "source_coverage": (
            source_covered_total / processed_total if processed_total else None
        ),
        "answered_unscored_count": statuses.count("answered_unscored"),
        "drafted_count": statuses.count("drafted"),
        "skipped_incomplete_count": statuses.count("skipped_incomplete"),
        "skipped_source_missing_count": skipped_source_missing_count,
        "no_context_count": statuses.count("no_context"),
        "invalid_anchor_count": invalid_anchor_count,
        "invalid_response_count": statuses.count("invalid_response"),
        "retried_item_count": sum(
            bool(item.get("answer_retry_reasons")) for item in report_items
        ),
        "answer_retry_count": sum(
            len(item.get("answer_retry_reasons", []))
            for item in report_items
            if isinstance(item.get("answer_retry_reasons"), list)
        ),
    }


def _write_quiz_bench_report(
    output_path: Path,
    *,
    document_id: int,
    quiz_path: Path,
    model_name: str,
    items: list[dict[str, object]],
    report_items: list[dict[str, object]],
    run_config: dict[str, object],
    elapsed_seconds: float,
) -> None:
    counts = _quiz_bench_counts(report_items)
    report = {
        "version": "quiz-bench-v1",
        "complete": len(report_items) == len(items),
        "document_id": document_id,
        "quiz": str(quiz_path),
        "model": model_name,
        "total": len(items),
        "processed_total": len(report_items),
        "expected_keyed_total": sum(
            str(item.get("question_type") or "multiple_choice")
            in {"multiple_choice", "true_false"}
            and "correct" in item
            for item in items
        ),
        **counts,
        "grounded_accuracy": counts["accuracy"],
        "skipped_external_source_count": counts["skipped_source_missing_count"],
        "elapsed_seconds": elapsed_seconds,
        "run_config": run_config,
        "items": report_items,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(output_path)


def _validate_quiz_bench_resume(
    checkpoint: dict[str, object],
    *,
    document_id: int,
    quiz_path: Path,
    model_name: str,
    items: list[dict[str, object]],
    run_config: dict[str, object],
) -> tuple[list[dict[str, object]], float]:
    if checkpoint.get("version") != "quiz-bench-v1":
        raise ValueError("Resume requires a quiz-bench-v1 checkpoint.")
    expected = {
        "document_id": document_id,
        "quiz": str(quiz_path),
        "model": model_name,
        "total": len(items),
        "run_config": run_config,
    }
    mismatches = [
        field for field, value in expected.items() if checkpoint.get(field) != value
    ]
    if mismatches:
        raise ValueError(
            "Resume checkpoint does not match this run: " + ", ".join(mismatches)
        )
    raw_report_items = checkpoint.get("items")
    if not isinstance(raw_report_items, list) or not all(
        isinstance(item, dict) for item in raw_report_items
    ):
        raise ValueError("Resume checkpoint items must be a list of objects.")
    report_items = [
        _normalize_checkpoint_report_item(dict(item)) for item in raw_report_items
    ]
    if checkpoint.get("processed_total") != len(report_items):
        raise ValueError("Resume checkpoint processed_total does not match its items.")
    if checkpoint.get("complete") is not (len(report_items) == len(items)):
        raise ValueError("Resume checkpoint complete flag is inconsistent.")
    expected_ids = [str(item["id"]) for item in items[: len(report_items)]]
    checkpoint_ids = [str(item.get("id") or "") for item in report_items]
    if checkpoint_ids != expected_ids:
        raise ValueError(
            "Resume checkpoint items are not a contiguous prefix of the quiz."
        )
    elapsed_seconds = checkpoint.get("elapsed_seconds")
    if not isinstance(elapsed_seconds, (int, float)) or elapsed_seconds < 0:
        raise ValueError("Resume checkpoint elapsed_seconds must be non-negative.")
    return report_items, float(elapsed_seconds)


def _report_item_has_invalid_anchor(item: dict[str, object]) -> bool:
    return _report_item_non_scoring_source_status(item) == "invalid_anchor"


def _report_item_non_scoring_source_status(
    item: dict[str, object],
) -> str | None:
    benchmark_status = str(item.get("status") or "")
    if benchmark_status == "invalid_anchor":
        return "invalid_anchor"
    source_grounding = item.get("source_grounding")
    if not isinstance(source_grounding, dict):
        return None
    source_status = str(source_grounding.get("source_status") or "")
    if source_status in {
        "invalid_anchor",
        "source_missing_in_local_pdf",
        "incomplete",
        "ungrounded",
    }:
        return source_status
    return None


def _normalize_checkpoint_report_item(
    item: dict[str, object],
) -> dict[str, object]:
    source_status = _report_item_non_scoring_source_status(item)
    if source_status is None:
        return item
    if str(item.get("status") or "") in {
        "correct",
        "incorrect",
        "answered_unscored",
        "drafted",
        "unkeyed",
    }:
        item["status"] = {
            "invalid_anchor": "invalid_anchor",
            "source_missing_in_local_pdf": "skipped_source_missing",
            "incomplete": "skipped_incomplete",
            "ungrounded": "no_context",
        }[source_status]
    item["scoring_eligible"] = False
    if "correct" in item:
        item["is_correct"] = None
    return item


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
    invalid_anchor_count = 0

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
        if args.options_retrieval:
            retrieval, retrieval_questions = _with_option_aware_retrieval(
                conn,
                document_id=args.document_id,
                item=item,
                retrieval=retrieval,
                retrieval_questions=retrieval_questions,
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
        source_grounding = build_source_grounding_record(
            conn,
            document_id=args.document_id,
            item=item,
            context_rows=context_rows,
            retrieval=retrieval,
            retrieval_questions=retrieval_questions,
            chars=args.chars,
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
        print(
            f"  selected chunks: {', '.join(str(chunk) for chunk in selected_chunks) or 'none'}"
        )

        if source_grounding.get("source_status") == "invalid_anchor":
            status = "invalid_anchor"
            invalid_anchor_count += 1
            print("  status: invalid_anchor")
        elif not context_rows:
            status = "no_context"
            no_context_count += 1
            print("  status: no_context")
        else:
            prompt = build_mc_prompt(item, context_rows, max_chars=args.chars)
            answer_started_at = time.monotonic()
            print(progress_line(model_name, index, len(items), item["id"]), flush=True)
            if ollama_client is None:
                from .. import create_client as _create_client

                ollama_client = _create_client(
                    settings.ollama_host, settings.ollama_timeout
                )
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
                think=settings.ollama_think,
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
            "source_grounding": source_grounding,
            "raw_response": raw_response,
            "timings": {
                "item_seconds": item_elapsed,
                "answer_seconds": answer_elapsed,
            },
            "status": status,
            "scoring_eligible": bool(keyed and status in {"correct", "incorrect"}),
        }
        if keyed:
            report_item["correct"] = item["correct"]
            report_item["correct_option_text"] = item["options"].get(item["correct"])
            report_item["is_correct"] = (
                status == "correct" if report_item["scoring_eligible"] else None
            )
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
    print(f"  invalid anchors: {invalid_anchor_count}")
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
            "invalid_anchor_count": invalid_anchor_count,
            "invalid_response_count": invalid_count,
            "elapsed_seconds": elapsed,
            "items": report_items,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
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

    _print_mc_compare_section(
        "correct -> incorrect", comparison["correct_to_incorrect"]
    )
    _print_mc_compare_section(
        "incorrect -> correct", comparison["incorrect_to_correct"]
    )
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
    exclusion_reason = source_retrieval_exclusion_reason(item)
    if exclusion_reason:
        return (
            RetrievalResult(
                original_question=str(item.get("question") or ""),
                queries_tried=[],
                selected_query=None,
                rows=[],
                stopped_reason=exclusion_reason,
            ),
            retrieval_questions,
        )
    if item.get("source_chunks"):
        rows = anchored_source_context_rows(conn, document_id, item)
        return (
            RetrievalResult(
                original_question=str(item.get("question") or ""),
                queries_tried=[],
                selected_query=None,
                rows=rows,
                stopped_reason="anchored_context" if rows else "invalid_anchor",
            ),
            retrieval_questions,
        )
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


def _with_option_aware_retrieval(
    conn,
    *,
    document_id: int,
    item: dict[str, object],
    retrieval: RetrievalResult,
    retrieval_questions: list[str],
    limit: int,
    role: str | None,
    section: str | None,
) -> tuple[RetrievalResult, list[str]]:
    if source_retrieval_exclusion_reason(item) or item.get("source_chunks"):
        return retrieval, retrieval_questions
    option_query = compact_question_with_options(item)
    retrieval_questions = _dedupe_quiz_queries([*retrieval_questions, option_query])
    option_retrieval = _retrieve_mc_context(
        conn,
        document_id=document_id,
        question=option_query,
        limit=limit,
        role=role,
        section=section,
    )
    return _merge_option_retrieval(retrieval, option_retrieval), retrieval_questions


def _merge_option_retrieval(
    retrieval: RetrievalResult, option_retrieval: RetrievalResult
) -> RetrievalResult:
    rows = []
    seen = set()
    for row in [*option_retrieval.rows, *retrieval.rows]:
        row_id = int(row["id"])
        if row_id in seen:
            continue
        seen.add(row_id)
        rows.append(row)

    selected_queries = _dedupe_quiz_queries(
        [option_retrieval.selected_query or "", retrieval.selected_query or ""]
    )
    queries_tried = _dedupe_quiz_queries(
        [*retrieval.queries_tried, *option_retrieval.queries_tried]
    )
    return RetrievalResult(
        original_question=retrieval.original_question,
        queries_tried=queries_tried,
        selected_query=" | ".join(selected_queries) if selected_queries else None,
        rows=rows,
        stopped_reason="context_found" if rows else "no_context",
    )


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
    if source_retrieval_exclusion_reason(item):
        return []
    if not item.get("source_chunks"):
        return rows
    return anchored_source_context_rows(conn, document_id, item)
