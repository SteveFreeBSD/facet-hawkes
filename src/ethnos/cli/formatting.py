"""Display and formatting helpers for CLI output."""

from __future__ import annotations

import json


def format_elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(seconds, 60)
    return f"{int(minutes)}m {remainder:.1f}s"


def preview_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def limit_display_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n... [truncated]"


def format_page_range(page_start: int, page_end: int) -> str:
    if page_start == page_end:
        return f"p. {page_start}"
    return f"pp. {page_start}-{page_end}"


def format_source_pages(raw_pages) -> str:
    if raw_pages is None:
        return "source pages: none"
    if isinstance(raw_pages, str):
        try:
            pages = json.loads(raw_pages)
        except json.JSONDecodeError:
            return f"source pages: {raw_pages}"
    else:
        pages = raw_pages
    if not pages:
        return "source pages: none"
    pages = sorted(set(int(page) for page in pages))
    ranges: list[str] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = page
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return "source pages: " + ", ".join(ranges)


def _format_accuracy(value: object) -> str:
    return f"{value:.1%}" if isinstance(value, float) else "n/a"


def _format_optional_percent(value: object) -> str:
    return f"{value:.1%}" if isinstance(value, int | float) else "n/a"


def _format_accuracy_delta(value: object) -> str:
    if not isinstance(value, float):
        return "n/a"
    return f"{value:+.1%}"


def _write_or_print(text: str, output) -> None:
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(f"Wrote {output}")


def _print_ollama_debug(chunk_id: int | None, debug_info) -> None:
    if debug_info is None:
        print(f"Ollama debug for chunk {chunk_id}: unavailable", flush=True)
        return
    print(f"Ollama debug for chunk {chunk_id}:", flush=True)
    print(f"  prompt chars: {debug_info.prompt_char_length}", flush=True)
    print(f"  schema top-level keys: {', '.join(debug_info.schema_top_level_keys)}", flush=True)
    print(f"  format: {debug_info.format_kind}", flush=True)
    print(f"  num_predict: {debug_info.num_predict}", flush=True)
    print(f"  num_ctx: {debug_info.num_ctx}", flush=True)
    if debug_info.response_summary is None:
        print("  response envelope: unavailable", flush=True)
        return
    print("  response envelope:", flush=True)
    for key, value in debug_info.response_summary.items():
        print(f"    {key}: {value}", flush=True)


def _print_section_count_summary(title: str, rows: list[dict]) -> None:
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['section_label']} / {row['content_role']}: {row['count']}")


def _print_chunk_records(records: dict[str, list[dict]]) -> None:
    print("Extracted records:")
    for section in ["chunk_summaries", "key_terms", "questions", "topics", "examples"]:
        print(f"{section}:")
        if not records[section]:
            print("  none")
            continue
        for row in records[section]:
            _print_record({"record_type": section, **row})


def _print_record(row: dict) -> None:
    record_type = row["record_type"]
    source_pages = format_source_pages(row.get("source_pages"))
    if record_type == "chunk_summaries":
        print(f"[chunk_summary] chunk {row['chunk_id']}")
        print(f"  summary: {row['summary']}")
    elif record_type == "key_terms":
        print(f"[key_term] chunk {row['chunk_id']} | {source_pages}")
        print(f"  term: {row['term']}")
        print(f"  definition: {row['definition']}")
    elif record_type == "questions":
        print(f"[question] chunk {row['chunk_id']} | {source_pages}")
        print(f"  question: {row['question']}")
        print(f"  answer: {row['answer']}")
    elif record_type == "topics":
        print(f"[topic] chunk {row['chunk_id']} | {source_pages}")
        print(f"  name: {row['name']}")
        print(f"  summary: {row['summary']}")
    elif record_type == "examples":
        print(f"[example] chunk {row['chunk_id']} | {source_pages}")
        print(f"  title: {row['title']}")
        print(f"  body: {row['body']}")
    print()


def _print_status_counts(title: str, rows: list[dict]) -> None:
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['validation_status']}: {row['count']}")


def _print_role_counts(title: str, rows: list[dict]) -> None:
    print(f"{title}:")
    if not rows:
        print("  none")
        return
    for row in rows:
        print(f"  {row['content_role']}: {row['count']}")


def _print_chunk_list(title: str, rows: list[dict], limit: int = 20) -> None:
    print(f"{title}: {len(rows)}")
    for row in rows[:limit]:
        print(
            f"  chunk {row['id']} ({row['section_label'] or 'unlabeled'} / "
            f"{row['content_role'] or 'unlabeled'}): {row['source_citation']}"
        )
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")


def _print_non_core_records(rows: list[dict], limit: int = 20) -> None:
    print(f"Non-core chunks with key_terms/questions: {len(rows)}")
    for row in rows[:limit]:
        print(
            f"  chunk {row['id']} ({row['section_label'] or 'unlabeled'} / "
            f"{row['content_role'] or 'unlabeled'}): "
            f"key_terms={row['key_terms']}, questions={row['questions']}"
        )
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")


def _print_mc_key_preview(
    items: list[dict[str, object]], *, include_options: bool = False
) -> None:
    for item in items:
        options = item["options"]
        if not isinstance(options, dict):
            options = {}
        correct = item.get("correct")
        correct_text = options.get(correct) if isinstance(correct, str) else None
        print(f"{item['id']}: {item['question']}")
        print(f"  type: {item.get('question_type') or 'multiple_choice'}")
        if correct:
            print(f"  keyed: {correct} - {correct_text or 'n/a'}")
        else:
            print("  keyed: unkeyed")
        if include_options:
            for label, text in options.items():
                marker = "  <-- keyed" if label == correct else ""
                print(f"  {label}. {text}{marker}")
        print()


def _print_quiz_preview(
    items: list[dict[str, object]], *, include_options: bool = False
) -> None:
    for item in items:
        question_type = str(item.get("question_type") or "multiple_choice")
        options = item.get("options") if isinstance(item.get("options"), dict) else {}
        correct = item.get("correct")
        correct_text = options.get(correct) if isinstance(correct, str) else None
        print(f"{item['id']}: {item['question']}")
        print(f"  type: {question_type}")
        if item.get("points") is not None:
            print(f"  points: {item['points']}")
        if item.get("warnings"):
            print(f"  warnings: {', '.join(str(w) for w in item['warnings'])}")
        if question_type in {"multiple_choice", "true_false"}:
            if correct:
                print(f"  keyed: {correct} - {correct_text or 'n/a'}")
            else:
                print("  keyed: unkeyed")
            if include_options:
                for label, text in options.items():
                    marker = "  <-- keyed" if label == correct else ""
                    print(f"  {label}. {text}{marker}")
        elif question_type == "matching":
            prompts = item.get("matching_prompts") or []
            print(f"  matching prompts: {len(prompts) if isinstance(prompts, list) else 0}")
            if include_options and isinstance(prompts, list):
                for prompt in prompts:
                    print(f"  - {prompt}")
        elif question_type == "essay":
            if item.get("submitted_response"):
                print("  submitted response: present")
        print()


def _print_mc_compare_section(title: str, changes: list[dict[str, object]]) -> None:
    if not changes:
        return
    print(f"  {title}:")
    for change in changes[:10]:
        before = change.get("before_selected_option") or "none"
        after = change.get("after_selected_option") or "none"
        print(f"    {change['id']}: {before} -> {after}")
    if len(changes) > 10:
        print(f"    ... {len(changes) - 10} more")


def _print_model_summary(summary: dict) -> None:
    print("  summary:")
    print(f"    total questions: {summary['total']}")
    print(f"    retrieval hits: {summary['retrieval_hits']}")
    print(f"    retrieval misses: {summary['retrieval_misses']}")
    print(f"    answer pass: {summary['answer_pass']}")
    print(f"    answer partial: {summary['answer_partial']}")
    print(f"    answer fail: {summary['answer_fail']}")
    print(f"    no-context expected: {summary['no_context_expected']}")
    print(f"    no-context unexpected: {summary['no_context_unexpected']}")
    print(f"    model errors: {summary['model_error']}")
    print(f"    total elapsed: {format_elapsed(summary['total_elapsed_seconds'])}")
    average_seconds = summary.get("average_answer_seconds")
    average_length = summary.get("average_answer_length")
    print(
        f"    average answer time: "
        f"{average_seconds:.1f}s" if average_seconds is not None else "    average answer time: n/a"
    )
    print(
        f"    average answer length: "
        f"{average_length:.0f} chars" if average_length is not None else "    average answer length: n/a"
    )


def _print_followup_debug(followup) -> None:
    print("Follow-up debug:")
    print(f"  follow-up detected: {followup.detected}")
    print(f"  previous question: {followup.previous_question or 'none'}")
    print(f"  previous topic/query: {followup.previous_topic or 'none'}")
    print(f"  rewritten retrieval question: {followup.rewritten_question or 'none'}")


def _print_retrieval_debug(retrieval) -> None:
    print("Retrieval debug:")
    print(f"  original question: {retrieval.original_question}")
    print(f"  comparison detected: {retrieval.comparison_detected}")
    if retrieval.comparison_detected:
        print(f"  subqueries: {', '.join(retrieval.comparison_subqueries)}")
        for result in retrieval.subquery_results:
            print(f"  subquery: {result.subquery}")
            print(f"    fallback queries tried: {', '.join(result.queries_tried)}")
            print(
                "    selected chunks: "
                + (
                    ", ".join(str(row["id"]) for row in result.rows)
                    if result.rows
                    else "none"
                )
            )
        print(
            "  merged selected chunks: "
            + (
                ", ".join(str(row["id"]) for row in retrieval.rows)
                if retrieval.rows
                else "none"
            )
        )
    print(f"  derived query: {retrieval.queries_tried[0] if retrieval.queries_tried else ''}")
    print(f"  fallback queries tried: {', '.join(retrieval.queries_tried)}")
    print(f"  selected query: {retrieval.selected_query or 'none'}")
    print(
        "  selected chunks: "
        + (", ".join(str(row["id"]) for row in retrieval.rows) if retrieval.rows else "none")
    )
    print(f"  stopped reason: {retrieval.stopped_reason}")


def _print_context_sources(rows: list[dict]) -> None:
    for row in rows:
        print(
            f"  chunk {row['id']}: {row['source_citation']} "
            f"({row['section_label'] or 'unlabeled'} / {row['content_role'] or 'unlabeled'})"
        )
