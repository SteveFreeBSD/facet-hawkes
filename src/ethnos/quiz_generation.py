"""Quiz generation and distractor selection."""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .quiz_core import (
    GENERATED_OPTION_LABELS,
    QUIZ_VERSION,
    limit_option_text,
    parse_source_pages,
    _normalize_option,
)


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


@dataclass
class QuizGenerationDiagnostics:
    skipped_insufficient_distractors: int = 0
    skipped_display_collision: int = 0
    used_distractor_records: set[tuple[str, int]] = field(default_factory=set)
    option_lengths: list[int] = field(default_factory=list)


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
    diagnostics = QuizGenerationDiagnostics()

    for record in selected_records:
        pool = records_by_type[record.source_record_type]
        item = build_quiz_item(
            record,
            pool,
            topics_by_chunk=topics_by_chunk,
            rng=rng,
            max_option_chars=max_option_chars,
            difficulty=difficulty,
            diagnostics=diagnostics,
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
        "quality_stats": _generation_quality_stats(
            records_by_type,
            questions,
            topics_by_chunk,
            diagnostics,
        ),
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
    diagnostics: QuizGenerationDiagnostics | None = None,
) -> dict[str, Any] | None:
    distractors = _ranked_distractors(record, pool, topics_by_chunk, rng, difficulty)
    options = [
        {
            "text": record.correct_answer,
            "source": _option_source_metadata(record, role="correct"),
        }
    ]
    selected_distractors = []
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
        options.append(
            {
                "text": distractor.correct_answer,
                "source": _option_source_metadata(distractor, role="distractor"),
            }
        )
        selected_distractors.append(distractor)
        seen_display.add(display_norm)
        if len(options) == len(GENERATED_OPTION_LABELS):
            break
    if len(options) < len(GENERATED_OPTION_LABELS):
        if diagnostics is not None:
            if (
                unique_raw_distractors >= len(GENERATED_OPTION_LABELS) - 1
                and display_collisions
            ):
                diagnostics.skipped_display_collision += 1
            else:
                diagnostics.skipped_insufficient_distractors += 1
        return None

    labeled_options = [
        {
            "label": label,
            "text": limit_option_text(option["text"], max_option_chars),
            "source": option["source"],
        }
        for label, option in zip(GENERATED_OPTION_LABELS, options)
    ]
    if diagnostics is not None:
        diagnostics.option_lengths.extend(
            len(option["text"]) for option in labeled_options
        )
        diagnostics.used_distractor_records.update(
            _record_key(distractor) for distractor in selected_distractors
        )
    correct_label = GENERATED_OPTION_LABELS[0]
    rng.shuffle(labeled_options)
    relabeled_options = {}
    option_sources = {}
    new_correct = None
    for label, option in zip(GENERATED_OPTION_LABELS, labeled_options):
        relabeled_options[label] = option["text"]
        option_sources[label] = option["source"]
        if option["label"] == correct_label:
            new_correct = label
    if new_correct is None:
        raise RuntimeError("Could not locate correct option after shuffling")

    item = {
        "question": record.question,
        "question_type": "multiple_choice",
        "options": relabeled_options,
        "option_sources": option_sources,
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
        if difficulty in {"easy", "medium"}:
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
        raw_target_tokens = _raw_target_tokens(record.target or "")
        target_tokens = _target_tokens(record.target or "")
        has_specific_sibling = any(
            other.source_record_id != record.source_record_id
            and other.chunk_id == record.chunk_id
            and _is_more_specific_term(
                raw_target_tokens,
                target_tokens,
                _target_tokens(other.target or ""),
            )
            for other in records
        )
        if has_specific_sibling:
            continue
        filtered.append(record)
    return filtered


def _is_more_specific_term(
    raw_target_tokens: set[str],
    target_tokens: set[str],
    sibling_tokens: set[str],
) -> bool:
    return (
        len(raw_target_tokens) == 1
        and len(sibling_tokens) > 1
        and bool(target_tokens & sibling_tokens)
    )


def _raw_target_tokens(value: str) -> set[str]:
    return {
        token
        for token in _normalize_option(value).replace("-", " ").split()
        if len(token) > 2
    }


def _target_tokens(value: str) -> set[str]:
    tokens = set(_raw_target_tokens(value))
    for token in _normalize_option(value).replace("-", " ").split():
        if len(token) <= 2:
            continue
        if token.endswith("ity") and len(token) > 5:
            tokens.add(token[:-3])
        if token.endswith("s") and len(token) > 4:
            tokens.add(token[:-1])
        if token.endswith("al") and len(token) > 5:
            tokens.add(token[:-2])
    return tokens


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
        1 if same_chunk else 0,
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


def _generation_quality_stats(
    records_by_type: dict[str, list[QuizSourceRecord]],
    questions: list[dict[str, Any]],
    topics_by_chunk: dict[int, set[str]],
    diagnostics: QuizGenerationDiagnostics,
) -> dict[str, Any]:
    available_records = [
        record for records in records_by_type.values() for record in records
    ]
    available_record_keys = {_record_key(record) for record in available_records}
    generated_record_keys = {
        (str(item["source_record_type"]), int(item["source_record_id"]))
        for item in questions
        if item.get("source_record_type") is not None
        and item.get("source_record_id") is not None
    }
    available_chunks = {record.chunk_id for record in available_records}
    represented_chunks = {
        record.chunk_id
        for record in available_records
        if _record_key(record) in generated_record_keys
    }
    available_sections = {
        record.section_label for record in available_records if record.section_label
    }
    represented_sections = {
        record.section_label
        for record in available_records
        if _record_key(record) in generated_record_keys and record.section_label
    }
    available_topics = _topics_for_chunks(available_chunks, topics_by_chunk)
    represented_topics = _topics_for_chunks(represented_chunks, topics_by_chunk)
    return {
        "skipped_insufficient_distractors": diagnostics.skipped_insufficient_distractors,
        "skipped_display_collision": diagnostics.skipped_display_collision,
        "distractor_pool": _coverage_stats(
            len(diagnostics.used_distractor_records),
            len(available_record_keys),
        ),
        "option_lengths": _option_length_stats(diagnostics.option_lengths),
        "topic_coverage": _named_coverage_stats(represented_topics, available_topics),
        "section_coverage": _named_coverage_stats(
            represented_sections,
            available_sections,
        ),
        "chunk_coverage": _coverage_stats(
            len(represented_chunks),
            len(available_chunks),
        ),
    }


def _record_key(record: QuizSourceRecord) -> tuple[str, int]:
    return (record.source_record_type, record.source_record_id)


def _option_source_metadata(record: QuizSourceRecord, *, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "source_record_type": record.source_record_type,
        "source_record_id": record.source_record_id,
        "target": record.target,
        "source_chunks": [record.chunk_id],
        "source_pages": record.source_pages,
        "source_citation": record.source_citation,
    }


def _topics_for_chunks(
    chunk_ids: set[int], topics_by_chunk: dict[int, set[str]]
) -> set[str]:
    return {
        topic
        for chunk_id in chunk_ids
        for topic in topics_by_chunk.get(chunk_id, set())
    }


def _coverage_stats(count: int, total: int) -> dict[str, Any]:
    return {
        "count": count,
        "total": total,
        "coverage": count / total if total else None,
    }


def _named_coverage_stats(represented: set[str], available: set[str]) -> dict[str, Any]:
    stats = _coverage_stats(len(represented), len(available))
    stats["represented"] = sorted(represented)
    stats["available"] = sorted(available)
    return stats


def _option_length_stats(lengths: list[int]) -> dict[str, float | int | None]:
    return {
        "average": round(sum(lengths) / len(lengths), 2) if lengths else None,
        "max": max(lengths) if lengths else 0,
    }
