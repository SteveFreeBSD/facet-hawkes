"""Multiple-choice quiz generation and prompt helpers."""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MC_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "mc_answer.md"
QUIZ_VERSION = "mc-quiz-v1"
EXTERNAL_QUIZ_VERSION = "external-mc-v1"
OPTION_LABELS = ("A", "B", "C", "D", "E", "F")
GENERATED_OPTION_LABELS = OPTION_LABELS[:4]
QUESTION_TYPES = ("multiple_choice", "true_false")
TRUE_FALSE_OPTIONS = {"A": "True", "B": "False"}
POSITION_HEADER_RE = re.compile(r"^Question at position\s+(\d+)\s*$", re.IGNORECASE)
LABEL_ANSWER_RE = re.compile(r"^(?:q)?0*(\d+)[\s:.)-]+([A-F])\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class QuizSourceRecord:
    source_record_type: str
    source_record_id: int
    chunk_id: int
    chunk_index: int
    section_label: str | None
    content_role: str | None
    source_citation: str
    source_pages: list[int]
    question: str
    correct_answer: str
    target: str | None = None
    difficulty: str | None = None


def generate_quiz(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    source: str = "terms",
    limit: int | None = None,
    seed: int | None = None,
    max_option_chars: int = 120,
    role: str | None = "core",
    section: str | None = None,
    difficulty: str = "medium",
) -> dict[str, Any]:
    if source not in {"terms", "questions", "both"}:
        raise ValueError("source must be one of: terms, questions, both")
    if limit is not None and limit < 1:
        raise ValueError("limit must be 1 or greater")
    if max_option_chars < 4:
        raise ValueError("max_option_chars must be 4 or greater")
    if difficulty not in {"easy", "medium", "hard"}:
        raise ValueError("difficulty must be one of: easy, medium, hard")

    rng = random.Random(seed)
    topics_by_chunk = load_topic_names_by_chunk(conn, document_id)
    records_by_type = _load_records_by_type(
        conn,
        document_id,
        source=source,
        role=role,
        section=section,
        difficulty=difficulty,
    )
    selected_records = _selected_generation_records(records_by_type, source)
    questions = []
    skipped_counts = {
        "skipped_insufficient_distractors": 0,
        "skipped_display_collision": 0,
    }

    for record in selected_records:
        pool = records_by_type[record.source_record_type]
        item = build_quiz_item(
            record,
            pool,
            topics_by_chunk=topics_by_chunk,
            rng=rng,
            max_option_chars=max_option_chars,
            difficulty=difficulty,
            skipped_counts=skipped_counts,
        )
        if item is None:
            continue
        item["id"] = f"q{len(questions) + 1:04d}"
        questions.append(item)
        if limit is not None and len(questions) >= limit:
            break

    return {
        "version": QUIZ_VERSION,
        "document_id": document_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "source": source,
        "role": role or "all",
        "section": section,
        "max_option_chars": max_option_chars,
        "difficulty": difficulty,
        "record_counts": _record_counts(records_by_type, questions),
        "generated_count": len(questions),
        **skipped_counts,
        "questions": questions,
    }


def build_quiz_item(
    record: QuizSourceRecord,
    pool: list[QuizSourceRecord],
    *,
    topics_by_chunk: dict[int, set[str]],
    rng: random.Random,
    max_option_chars: int,
    difficulty: str = "medium",
    skipped_counts: dict[str, int] | None = None,
) -> dict[str, Any] | None:
    distractors = _ranked_distractors(record, pool, topics_by_chunk, rng, difficulty)
    options = [record.correct_answer]
    seen_raw = {_normalize_option(record.correct_answer)}
    seen_display = {
        _normalize_option(limit_option_text(record.correct_answer, max_option_chars))
    }
    unique_raw_distractors = 0
    display_collisions = 0
    for distractor in distractors:
        raw_norm = _normalize_option(distractor.correct_answer)
        if raw_norm in seen_raw:
            continue
        unique_raw_distractors += 1
        seen_raw.add(raw_norm)
        display = limit_option_text(distractor.correct_answer, max_option_chars)
        display_norm = _normalize_option(display)
        if display_norm in seen_display:
            display_collisions += 1
            continue
        options.append(distractor.correct_answer)
        seen_display.add(display_norm)
        if len(options) == len(GENERATED_OPTION_LABELS):
            break
    if len(options) < len(GENERATED_OPTION_LABELS):
        if skipped_counts is not None:
            if (
                unique_raw_distractors >= len(GENERATED_OPTION_LABELS) - 1
                and display_collisions
            ):
                skipped_counts["skipped_display_collision"] += 1
            else:
                skipped_counts["skipped_insufficient_distractors"] += 1
        return None

    labeled_options = [
        {"label": label, "text": limit_option_text(text, max_option_chars)}
        for label, text in zip(GENERATED_OPTION_LABELS, options)
    ]
    correct_label = GENERATED_OPTION_LABELS[0]
    rng.shuffle(labeled_options)
    relabeled_options = {}
    new_correct = None
    for label, option in zip(GENERATED_OPTION_LABELS, labeled_options):
        relabeled_options[label] = option["text"]
        if option["label"] == correct_label:
            new_correct = label
    if new_correct is None:
        raise RuntimeError("Could not locate correct option after shuffling")

    item = {
        "question": record.question,
        "question_type": "multiple_choice",
        "options": relabeled_options,
        "correct": new_correct,
        "source_record_type": record.source_record_type,
        "source_record_id": record.source_record_id,
        "target": record.target,
        "source_chunks": [record.chunk_id],
        "source_pages": record.source_pages,
        "source_citation": record.source_citation,
    }
    if record.difficulty:
        item["difficulty"] = record.difficulty
    return item


def load_quiz(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return normalize_quiz(data)


def normalize_quiz(data: Any) -> dict[str, Any]:
    if isinstance(data, list):
        root = {"version": "external-list", "questions": data}
    elif isinstance(data, dict):
        root = dict(data)
    else:
        raise ValueError("Quiz must be a JSON object or list")
    questions = root.get("questions")
    if not isinstance(questions, list):
        raise ValueError("Quiz must include a questions list")
    root["questions"] = [
        normalize_quiz_item(item, index + 1) for index, item in enumerate(questions)
    ]
    root["generated_count"] = len(root["questions"])
    return root


def normalize_quiz_item(item: Any, index: int) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("Each quiz item must be an object")
    question = str(item.get("question", "")).strip()
    if not question:
        raise ValueError("Each quiz item must include a non-empty question")
    options = normalize_options(item.get("options"))
    question_type = normalize_question_type(item.get("question_type"), options)
    normalized = {
        **item,
        "id": str(item.get("id") or f"q{index:04d}"),
        "question": question,
        "question_type": question_type,
        "options": options,
        "source_chunks": _normalize_int_list(item.get("source_chunks")),
        "source_pages": _normalize_int_list(item.get("source_pages")),
    }
    correct = item.get("correct")
    if correct is not None:
        correct_label = str(correct).strip().upper()
        if correct_label not in options:
            raise ValueError(f"Quiz item {normalized['id']} has invalid correct option")
        normalized["correct"] = correct_label
    else:
        normalized.pop("correct", None)
    return normalized


def normalize_question_type(raw_type: Any, options: dict[str, str]) -> str:
    if raw_type is None or str(raw_type).strip() == "":
        return "true_false" if is_true_false_options(options) else "multiple_choice"
    question_type = str(raw_type).strip().lower().replace("-", "_")
    if question_type not in QUESTION_TYPES:
        raise ValueError(
            f"Quiz item question_type must be one of: {', '.join(QUESTION_TYPES)}"
        )
    if question_type == "true_false" and not is_true_false_options(options):
        raise ValueError("true_false quiz items must use options A=True and B=False")
    return question_type


def is_true_false_options(options: dict[str, str]) -> bool:
    return (
        tuple(options) == tuple(TRUE_FALSE_OPTIONS)
        and _normalize_option(options["A"]) == _normalize_option(TRUE_FALSE_OPTIONS["A"])
        and _normalize_option(options["B"]) == _normalize_option(TRUE_FALSE_OPTIONS["B"])
    )


def normalize_options(options: Any) -> dict[str, str]:
    if isinstance(options, dict):
        normalized = {str(key).upper(): str(value).strip() for key, value in options.items()}
    elif isinstance(options, list):
        normalized = {}
        for index, value in enumerate(options):
            label = OPTION_LABELS[index] if index < len(OPTION_LABELS) else None
            if isinstance(value, dict):
                label = str(value.get("label") or label or "").upper()
                text = str(value.get("text", "")).strip()
            else:
                text = str(value).strip()
            if label:
                normalized[label] = text
    else:
        raise ValueError("Quiz item options must be an object or list")
    labels = tuple(normalized)
    if not 2 <= len(labels) <= len(OPTION_LABELS):
        raise ValueError("Quiz item options must include 2 to 6 options")
    expected_labels = OPTION_LABELS[: len(labels)]
    if labels != expected_labels:
        raise ValueError("Quiz item options must use contiguous labels starting at A")
    if any(not text for text in normalized.values()):
        raise ValueError("Quiz item options must be non-empty")
    return {label: normalized[label] for label in expected_labels}


def import_lms_mc_quiz(
    raw_text: str,
    *,
    document_id: int | None = None,
    title: str | None = None,
    answer_key_text: str | None = None,
    id_prefix: str = "q",
) -> dict[str, Any]:
    """Convert copied LMS multiple-choice quiz text into normalized quiz JSON."""
    lines = [line.strip() for line in raw_text.splitlines()]
    matches = [
        (index, int(match.group(1)))
        for index, line in enumerate(lines)
        if (match := POSITION_HEADER_RE.match(line))
    ]
    if not matches:
        raise ValueError("Could not find any 'Question at position N' markers")

    quiz_title = title or _infer_lms_quiz_title(lines, matches[0][0])
    questions = []
    group_index = 0
    while group_index < len(matches):
        question_number = matches[group_index][1]
        group_end = group_index + 1
        while group_end < len(matches) and matches[group_end][1] == question_number:
            group_end += 1
        start = matches[group_end - 1][0] + 1
        end = matches[group_end][0] if group_end < len(matches) else len(lines)
        content = [
            line
            for line in lines[start:end]
            if line and not _is_lms_quiz_boilerplate(line)
        ]
        if len(content) < 3:
            raise ValueError(
                f"Question {question_number} must include a question and at least 2 options"
            )
        question = content[0]
        options = normalize_options(content[1:])
        questions.append(
            {
                "id": f"{id_prefix}{question_number:03d}",
                "question": question,
                "question_type": normalize_question_type(None, options),
                "options": options,
            }
        )
        group_index = group_end

    if answer_key_text:
        _apply_answer_key(questions, answer_key_text)

    quiz: dict[str, Any] = {
        "version": EXTERNAL_QUIZ_VERSION,
        "source": "external",
        "title": quiz_title,
        "answer_key_notes": "Converted from copied quiz text.",
        "questions": questions,
    }
    if document_id is not None:
        quiz["document_id"] = document_id
    return normalize_quiz(quiz)


def _infer_lms_quiz_title(lines: list[str], first_marker_index: int) -> str:
    for line in lines[:first_marker_index]:
        if line and not _is_lms_quiz_boilerplate(line):
            return line
    return "Imported MC Quiz"


def _is_lms_quiz_boilerplate(line: str) -> bool:
    normalized = _normalize_option(line)
    if POSITION_HEADER_RE.match(line):
        return True
    if normalized in {
        "multiple choice",
        "true or false",
        "1 point",
    }:
        return True
    if re.fullmatch(r"\d+", normalized):
        return True
    return normalized.startswith("take the quiz.")


def _apply_answer_key(questions: list[dict[str, Any]], answer_key_text: str) -> None:
    raw_entries = [line.strip() for line in answer_key_text.splitlines() if line.strip()]
    if not raw_entries:
        return
    keyed_by_number: dict[int, str] = {}
    positional_entries = []
    for entry in raw_entries:
        if match := LABEL_ANSWER_RE.match(entry):
            keyed_by_number[int(match.group(1))] = match.group(2).upper()
        else:
            positional_entries.append(entry)
    if keyed_by_number and positional_entries:
        raise ValueError(
            "Answer key must use either numbered labels or one answer text per line"
        )
    if keyed_by_number:
        for index, question in enumerate(questions, start=1):
            label = keyed_by_number.get(index)
            if label is None:
                continue
            if label not in question["options"]:
                raise ValueError(f"Answer key for question {index} uses invalid option {label}")
            question["correct"] = label
        return
    if len(positional_entries) != len(questions):
        raise ValueError("Answer key text line count must match the imported question count")
    for index, (question, answer_text) in enumerate(
        zip(questions, positional_entries), start=1
    ):
        answer_norm = _normalize_option(answer_text)
        matches = [
            label
            for label, text in question["options"].items()
            if _normalize_option(text) == answer_norm
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Answer key text for question {index} did not match exactly one option"
            )
        question["correct"] = matches[0]


def build_mc_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_MC_PROMPT,
) -> str:
    template = prompt_path.read_text(encoding="utf-8")
    options = "\n".join(
        f"{label}. {text}" for label, text in normalize_options(item["options"]).items()
    )
    option_labels = ", ".join(normalize_options(item["options"]))
    target = item.get("target") or ""
    source_citation = item.get("source_citation") or ""
    context = build_mc_context(
        _prioritized_context_rows(item, context_rows),
        max_chars,
        target=target,
    )
    return template.format(
        question=item["question"],
        question_type=item.get("question_type") or "multiple_choice",
        target=target,
        source_citation=source_citation,
        option_labels=option_labels,
        options=options,
        context=context,
    )


def build_mc_context(
    rows: list[dict[str, Any]], max_chars: int, *, target: str | None = None
) -> str:
    parts = []
    for row in rows:
        text = _targeted_context_text(str(row.get("text", "")), max_chars, target)
        parts.append(
            "\n".join(
                [
                    f"[{row['source_citation']}]",
                    f"chunk_id: {row['id']}",
                    f"source_citation: {row['source_citation']}",
                    f"section_label: {row['section_label'] or 'unlabeled'}",
                    f"content_role: {row['content_role'] or 'unlabeled'}",
                    "text:",
                    text,
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _targeted_context_text(text: str, max_chars: int, target: str | None) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    target = (target or "").strip()
    if not target:
        return limit_option_text(compact, max_chars)
    index = compact.lower().find(target.lower())
    if index < 0:
        return limit_option_text(compact, max_chars)
    half_window = max((max_chars - len(target)) // 2, 0)
    start = max(index - half_window, 0)
    end = min(start + max_chars, len(compact))
    start = max(end - max_chars, 0)
    excerpt = compact[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(compact):
        excerpt = excerpt.rstrip() + "..."
    return excerpt


def _prioritized_context_rows(
    item: dict[str, Any], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source_chunks = {int(chunk_id) for chunk_id in item.get("source_chunks", [])}
    if not source_chunks:
        return rows
    return sorted(rows, key=lambda row: 0 if int(row["id"]) in source_chunks else 1)


def compact_question_with_options(item: dict[str, Any]) -> str:
    options = normalize_options(item["options"])
    option_texts = []
    seen = set()
    for text in options.values():
        key = _normalize_option(text)
        if key in seen:
            continue
        seen.add(key)
        option_texts.append(text)
    return item["question"] + " " + " ".join(option_texts)


def limit_option_text(text: str, max_chars: int) -> str:
    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def parse_source_pages(raw_pages: Any) -> list[int]:
    if raw_pages is None:
        return []
    if isinstance(raw_pages, str):
        try:
            raw_pages = json.loads(raw_pages)
        except json.JSONDecodeError:
            return []
    return _normalize_int_list(raw_pages)


def load_topic_names_by_chunk(
    conn: sqlite3.Connection, document_id: int
) -> dict[int, set[str]]:
    rows = conn.execute(
        """
        SELECT t.chunk_id, t.name
        FROM topics t
        JOIN chunks c ON c.id = t.chunk_id
        WHERE c.document_id = ?
        ORDER BY c.chunk_index, t.id
        """,
        (document_id,),
    ).fetchall()
    topics: dict[int, set[str]] = {}
    for row in rows:
        name = _normalize_option(row["name"])
        if not name:
            continue
        topics.setdefault(int(row["chunk_id"]), set()).add(name)
    return topics


def _load_records_by_type(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    source: str,
    role: str | None,
    section: str | None,
    difficulty: str,
) -> dict[str, list[QuizSourceRecord]]:
    records = {"key_terms": [], "questions": []}
    if source in {"terms", "both"}:
        records["key_terms"] = _load_term_records(
            conn, document_id, role=role, section=section
        )
        if difficulty == "easy":
            records["key_terms"] = _filter_ambiguous_broad_terms(records["key_terms"])
    if source in {"questions", "both"}:
        records["questions"] = _load_question_records(
            conn, document_id, role=role, section=section
        )
    return records


def _load_term_records(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    role: str | None,
    section: str | None,
) -> list[QuizSourceRecord]:
    filters = ["c.document_id = ?", "TRIM(kt.term) != ''", "TRIM(kt.definition) != ''"]
    params: list[Any] = [document_id]
    _append_chunk_filters(filters, params, role=role, section=section)
    rows = conn.execute(
        f"""
        SELECT
            kt.id,
            kt.chunk_id,
            kt.term,
            kt.definition,
            kt.source_pages,
            c.chunk_index,
            c.section_label,
            c.content_role,
            c.source_citation
        FROM key_terms kt
        JOIN chunks c ON c.id = kt.chunk_id
        WHERE {" AND ".join(filters)}
        ORDER BY c.chunk_index, kt.id
        """,
        params,
    ).fetchall()
    return [
        QuizSourceRecord(
            source_record_type="key_terms",
            source_record_id=int(row["id"]),
            chunk_id=int(row["chunk_id"]),
            chunk_index=int(row["chunk_index"]),
            section_label=row["section_label"],
            content_role=row["content_role"],
            source_citation=row["source_citation"],
            source_pages=parse_source_pages(row["source_pages"]),
            question=f"Which definition best matches {row['term'].strip()} in this text?",
            correct_answer=row["definition"],
            target=row["term"].strip(),
            difficulty="medium",
        )
        for row in rows
    ]


def _load_question_records(
    conn: sqlite3.Connection,
    document_id: int,
    *,
    role: str | None,
    section: str | None,
) -> list[QuizSourceRecord]:
    filters = ["c.document_id = ?", "TRIM(q.question) != ''", "TRIM(q.answer) != ''"]
    params: list[Any] = [document_id]
    _append_chunk_filters(filters, params, role=role, section=section)
    rows = conn.execute(
        f"""
        SELECT
            q.id,
            q.chunk_id,
            q.question,
            q.answer,
            q.difficulty,
            q.source_pages,
            c.chunk_index,
            c.section_label,
            c.content_role,
            c.source_citation
        FROM questions q
        JOIN chunks c ON c.id = q.chunk_id
        WHERE {" AND ".join(filters)}
        ORDER BY c.chunk_index, q.id
        """,
        params,
    ).fetchall()
    return [
        QuizSourceRecord(
            source_record_type="questions",
            source_record_id=int(row["id"]),
            chunk_id=int(row["chunk_id"]),
            chunk_index=int(row["chunk_index"]),
            section_label=row["section_label"],
            content_role=row["content_role"],
            source_citation=row["source_citation"],
            source_pages=parse_source_pages(row["source_pages"]),
            question=row["question"],
            correct_answer=row["answer"],
            target=None,
            difficulty=row["difficulty"],
        )
        for row in rows
    ]


def _append_chunk_filters(
    filters: list[str],
    params: list[Any],
    *,
    role: str | None,
    section: str | None,
) -> None:
    if role is not None:
        filters.append("c.content_role = ?")
        params.append(role)
    if section is not None:
        filters.append("c.section_label = ?")
        params.append(section)


def _selected_generation_records(
    records_by_type: dict[str, list[QuizSourceRecord]], source: str
) -> list[QuizSourceRecord]:
    if source == "terms":
        return records_by_type["key_terms"]
    if source == "questions":
        return records_by_type["questions"]
    records = records_by_type["key_terms"] + records_by_type["questions"]
    return sorted(
        records,
        key=lambda record: (
            record.chunk_index,
            0 if record.source_record_type == "key_terms" else 1,
            record.source_record_id,
        ),
    )


def _filter_ambiguous_broad_terms(
    records: list[QuizSourceRecord],
) -> list[QuizSourceRecord]:
    filtered = []
    for record in records:
        target_tokens = _target_tokens(record.target or "")
        has_specific_sibling = any(
            other.source_record_id != record.source_record_id
            and other.chunk_id == record.chunk_id
            and _is_more_specific_term(target_tokens, _target_tokens(other.target or ""))
            for other in records
        )
        if has_specific_sibling:
            continue
        filtered.append(record)
    return filtered


def _is_more_specific_term(target_tokens: set[str], sibling_tokens: set[str]) -> bool:
    return len(target_tokens) == 1 and len(sibling_tokens) > 1 and target_tokens < sibling_tokens


def _target_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize_option(value).replace("-", " ").split()
        if len(token) > 2
    }


def _ranked_distractors(
    record: QuizSourceRecord,
    pool: list[QuizSourceRecord],
    topics_by_chunk: dict[int, set[str]],
    rng: random.Random,
    difficulty: str,
) -> list[QuizSourceRecord]:
    correct_norm = _normalize_option(record.correct_answer)
    record_topics = topics_by_chunk.get(record.chunk_id, set())
    scored = []
    for candidate in pool:
        if candidate.source_record_id == record.source_record_id:
            continue
        if _normalize_option(candidate.correct_answer) == correct_norm:
            continue
        candidate_topics = topics_by_chunk.get(candidate.chunk_id, set())
        shared_topic_count = len(record_topics & candidate_topics)
        distance = abs(candidate.chunk_index - record.chunk_index)
        same_section = candidate.section_label == record.section_label
        answer_overlap = _answer_token_overlap(record.correct_answer, candidate.correct_answer)
        scored.append(
            (
                *_distractor_sort_key(
                    difficulty=difficulty,
                    same_chunk=candidate.chunk_id == record.chunk_id,
                    answer_overlap=answer_overlap,
                    shared_topic_count=shared_topic_count,
                    distance=distance,
                    same_section=same_section,
                ),
                rng.random(),
                candidate,
            )
        )
    scored.sort(key=lambda item: item[:-1])
    return [item[-1] for item in scored]


def _distractor_sort_key(
    *,
    difficulty: str,
    same_chunk: bool,
    answer_overlap: int,
    shared_topic_count: int,
    distance: int,
    same_section: bool,
) -> tuple[int, int, int, int, int]:
    if difficulty == "easy":
        return (
            1 if same_chunk else 0,
            answer_overlap,
            0 if shared_topic_count == 0 else 1,
            0 if not same_section else 1,
            -distance,
        )
    if difficulty == "hard":
        return (
            0 if shared_topic_count else 1,
            -shared_topic_count,
            distance,
            0 if same_section else 1,
            answer_overlap,
        )
    return (
        0 if same_section else 1,
        min(distance, 10),
        answer_overlap,
        0 if shared_topic_count else 1,
        -shared_topic_count,
    )


def _answer_token_overlap(left: str, right: str) -> int:
    return len(_answer_tokens(left) & _answer_tokens(right))


def _answer_tokens(value: str) -> set[str]:
    stopwords = {
        "and",
        "are",
        "because",
        "that",
        "the",
        "their",
        "this",
        "with",
    }
    return {
        token
        for token in _normalize_option(value).replace("-", " ").split()
        if len(token) > 4 and token not in stopwords
    }


def _record_counts(
    records_by_type: dict[str, list[QuizSourceRecord]], questions: list[dict[str, Any]]
) -> dict[str, int]:
    generated_terms = sum(1 for item in questions if item["source_record_type"] == "key_terms")
    generated_questions = sum(
        1 for item in questions if item["source_record_type"] == "questions"
    )
    return {
        "available_terms": len(records_by_type["key_terms"]),
        "available_questions": len(records_by_type["questions"]),
        "generated_terms": generated_terms,
        "generated_questions": generated_questions,
    }


def _normalize_option(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _normalize_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    normalized = []
    for item in value:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return sorted(set(normalized))
