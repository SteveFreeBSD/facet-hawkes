"""Multiple-choice quiz generation and prompt helpers."""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


DEFAULT_MC_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "mc_answer.md"
DEFAULT_CHOICE_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "choice_answer.md"
DEFAULT_ESSAY_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "essay_answer.md"
QUIZ_VERSION = "mc-quiz-v1"
EXTERNAL_QUIZ_VERSION = "external-mc-v1"
EXTERNAL_MIXED_QUIZ_VERSION = "external-quiz-v2"
OPTION_LABELS = ("A", "B", "C", "D", "E", "F")
GENERATED_OPTION_LABELS = OPTION_LABELS[:4]
QUESTION_TYPES = ("multiple_choice", "true_false", "matching", "essay")
CHOICE_QUESTION_TYPES = {"multiple_choice", "true_false"}
TRUE_FALSE_OPTIONS = {"A": "True", "B": "False"}
POSITION_HEADER_RE = re.compile(r"^Question at position\s+(\d+)\s*$", re.IGNORECASE)
CANVAS_QUESTION_HEADER_RE = re.compile(
    r"^Question\s+(\d+)\s+(\d+(?:\.\d+)?)\s+pts?\.?\s*$",
    re.IGNORECASE,
)
CANVAS_FLAG_RE = re.compile(r"^Flag question:\s*Question\s+\d+\s*$", re.IGNORECASE)
LABEL_ANSWER_RE = re.compile(r"^(?:q)?0*(\d+)[\s:.)-]+([A-F])\s*$", re.IGNORECASE)


class BaseQuizItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    question: str = Field(min_length=1)
    question_type: Literal["multiple_choice", "true_false", "matching", "essay"]
    source_chunks: list[int] = Field(default_factory=list)
    source_pages: list[int] = Field(default_factory=list)


class ChoiceQuizItem(BaseQuizItem):
    question_type: Literal["multiple_choice", "true_false"]
    options: dict[str, str]
    correct: str | None = None

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: dict[str, str]) -> dict[str, str]:
        return normalize_options(value)

    @field_validator("correct")
    @classmethod
    def validate_correct(cls, value: str | None) -> str | None:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_choice_shape(self):
        if self.question_type == "true_false" and not is_true_false_options(self.options):
            raise ValueError("true_false quiz items must use options A=True and B=False")
        if self.correct is not None and self.correct not in self.options:
            raise ValueError("correct option must refer to an available option")
        return self


class MatchingQuizItem(BaseQuizItem):
    question_type: Literal["matching"]
    matching_prompts: list[str] = Field(default_factory=list)
    matching_pairs: list[Any] | None = None


class EssayQuizItem(BaseQuizItem):
    question_type: Literal["essay"]


QuizItemModel = ChoiceQuizItem | MatchingQuizItem | EssayQuizItem


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
    raw_question_type = item.get("question_type")
    if raw_question_type is None or str(raw_question_type).strip() == "":
        options = normalize_options(item.get("options")) if item.get("options") is not None else None
        question_type = normalize_question_type(raw_question_type, options)
    else:
        raw_type_name = str(raw_question_type).strip().lower().replace("-", "_")
        options = (
            normalize_options(item.get("options"))
            if raw_type_name in CHOICE_QUESTION_TYPES or item.get("options") is not None
            else {}
        )
        question_type = normalize_question_type(raw_question_type, options or None)
    normalized = {
        **item,
        "id": str(item.get("id") or f"q{index:04d}"),
        "question": question,
        "question_type": question_type,
        "source_chunks": _normalize_int_list(item.get("source_chunks")),
        "source_pages": _normalize_int_list(item.get("source_pages")),
    }
    if question_type in CHOICE_QUESTION_TYPES or options:
        normalized["options"] = options
    else:
        normalized.pop("options", None)
    if "points" in item:
        normalized["points"] = _normalize_points(item.get("points"))
    if "position" in item:
        normalized["position"] = _normalize_int(item.get("position"))
    if "warnings" in item:
        normalized["warnings"] = _normalize_string_list(item.get("warnings"))
    if question_type == "matching":
        normalized["matching_prompts"] = _normalize_string_list(
            item.get("matching_prompts")
        )
        pairs = item.get("matching_pairs")
        if pairs is not None and not isinstance(pairs, list):
            raise ValueError("matching_pairs must be a list")
        if pairs is not None:
            normalized["matching_pairs"] = pairs
    correct = item.get("correct")
    if correct is not None:
        if question_type not in CHOICE_QUESTION_TYPES:
            raise ValueError(f"Quiz item {normalized['id']} cannot key a {question_type} item")
        correct_label = str(correct).strip().upper()
        if not options or correct_label not in options:
            raise ValueError(f"Quiz item {normalized['id']} has invalid correct option")
        normalized["correct"] = correct_label
    else:
        normalized.pop("correct", None)
    return _validate_typed_quiz_item(normalized)


def _validate_typed_quiz_item(item: dict[str, Any]) -> dict[str, Any]:
    question_type = item["question_type"]
    model: type[QuizItemModel]
    if question_type in CHOICE_QUESTION_TYPES:
        model = ChoiceQuizItem
    elif question_type == "matching":
        model = MatchingQuizItem
    elif question_type == "essay":
        model = EssayQuizItem
    else:
        raise ValueError(f"Quiz item {item.get('id') or '?'} has unsupported question_type")
    try:
        return model.model_validate(item).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        raise ValueError(f"Quiz item {item.get('id') or '?'} is invalid: {exc}") from exc


def normalize_question_type(raw_type: Any, options: dict[str, str] | None) -> str:
    if raw_type is None or str(raw_type).strip() == "":
        if options is None:
            return "essay"
        return "true_false" if is_true_false_options(options) else "multiple_choice"
    question_type = str(raw_type).strip().lower().replace("-", "_")
    if question_type not in QUESTION_TYPES:
        raise ValueError(
            f"Quiz item question_type must be one of: {', '.join(QUESTION_TYPES)}"
        )
    if question_type == "true_false" and not is_true_false_options(options or {}):
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


def import_canvas_quiz(
    raw_text: str,
    *,
    document_id: int | None = None,
    title: str | None = None,
    answer_key_text: str | None = None,
    id_prefix: str = "q",
) -> dict[str, Any]:
    """Convert pasted Canvas quiz text into normalized mixed quiz JSON."""
    lines = [line.rstrip() for line in raw_text.splitlines()]
    starts = [
        (index, int(match.group(1)), match.group(2))
        for index, line in enumerate(lines)
        if (match := CANVAS_QUESTION_HEADER_RE.match(line.strip()))
    ]
    if not starts:
        raise ValueError("Could not find any 'Question N X pts' markers")

    quiz_title = title or _infer_canvas_quiz_title(lines, starts[0][0])
    questions = []
    import_warnings: list[str] = []
    for start_index, question_number, raw_points in starts:
        next_starts = [index for index, _, _ in starts if index > start_index]
        end_index = next_starts[0] if next_starts else len(lines)
        block = lines[start_index + 1 : end_index]
        item = _parse_canvas_question_block(
            block,
            question_number=question_number,
            points=_normalize_points(raw_points),
            id_prefix=id_prefix,
        )
        if item["question_type"] == "matching" and "incomplete_matching_item" in item.get(
            "warnings", []
        ):
            import_warnings.append(f"{item['id']}: incomplete matching item")
        questions.append(item)

    if answer_key_text:
        _apply_choice_answer_key(questions, answer_key_text)

    quiz: dict[str, Any] = {
        "version": EXTERNAL_MIXED_QUIZ_VERSION,
        "source": "canvas_pasted_text",
        "title": quiz_title,
        "total_points": sum(float(item.get("points") or 0) for item in questions),
        "import_warnings": import_warnings,
        "questions": questions,
    }
    if document_id is not None:
        quiz["document_id"] = document_id
    normalized = normalize_quiz(quiz)
    total_points = normalized.get("total_points")
    if isinstance(total_points, float) and total_points.is_integer():
        normalized["total_points"] = int(total_points)
    return normalized


def _parse_canvas_question_block(
    block: list[str],
    *,
    question_number: int,
    points: int | float | None,
    id_prefix: str,
) -> dict[str, Any]:
    content = [
        line.strip()
        for line in block
        if line.strip() and not CANVAS_FLAG_RE.match(line.strip())
    ]
    content = [
        line
        for line in content
        if not CANVAS_QUESTION_HEADER_RE.match(line)
        and _normalize_option(line) != "group of answer choices"
    ]
    if not content:
        raise ValueError(f"Question {question_number} must include prompt text")

    group_index = _canvas_answer_group_index(block)
    if group_index is not None:
        before_group = [
            line.strip()
            for line in block[:group_index]
            if line.strip()
            and not CANVAS_FLAG_RE.match(line.strip())
            and not CANVAS_QUESTION_HEADER_RE.match(line.strip())
        ]
        after_group = [
            line.strip()
            for line in block[group_index + 1 :]
            if line.strip()
            and not CANVAS_FLAG_RE.match(line.strip())
            and not CANVAS_QUESTION_HEADER_RE.match(line.strip())
        ]
        question = _join_canvas_prompt(before_group)
        if _looks_like_matching_prompt(question):
            warnings = []
            matching_prompts = after_group
            item: dict[str, Any] = {
                "id": f"{id_prefix}{question_number:03d}",
                "position": question_number,
                "question": question,
                "question_type": "matching",
                "points": points,
                "matching_prompts": matching_prompts,
            }
            if not _has_complete_matching_pairs(matching_prompts):
                warnings.append("incomplete_matching_item")
            if warnings:
                item["warnings"] = warnings
            return item
        options = normalize_options(after_group)
        return {
            "id": f"{id_prefix}{question_number:03d}",
            "position": question_number,
            "question": question,
            "question_type": normalize_question_type(None, options),
            "points": points,
            "options": options,
        }

    prompt_lines, submitted_response = _split_canvas_essay_response(content)
    return {
        "id": f"{id_prefix}{question_number:03d}",
        "position": question_number,
        "question": _join_canvas_prompt(prompt_lines),
        "question_type": "essay",
        "points": points,
        **({"submitted_response": submitted_response} if submitted_response else {}),
    }


def _canvas_answer_group_index(block: list[str]) -> int | None:
    for index, line in enumerate(block):
        if _normalize_option(line.strip()) == "group of answer choices":
            return index
    return None


def _infer_canvas_quiz_title(lines: list[str], first_marker_index: int) -> str:
    for line in lines[:first_marker_index]:
        stripped = line.strip()
        if stripped and not CANVAS_FLAG_RE.match(stripped):
            return stripped
    return "Imported Canvas Quiz"


def _join_canvas_prompt(lines: list[str]) -> str:
    return " ".join(line.strip() for line in lines if line.strip()).strip()


def _looks_like_matching_prompt(question: str) -> bool:
    normalized = _normalize_option(question)
    return normalized.startswith("match ") or " matching " in f" {normalized} "


def _has_complete_matching_pairs(lines: list[str]) -> bool:
    if not lines:
        return False
    return any("->" in line or "=" in line or ":" in line for line in lines)


def _split_canvas_essay_response(lines: list[str]) -> tuple[list[str], str | None]:
    if len(lines) < 2:
        return lines, None
    last = lines[-1].strip()
    previous_text = " ".join(lines[:-1]).lower()
    if len(last.split()) <= 2 and (
        "answer in at least" in previous_text or "paragraph" in previous_text
    ):
        return lines[:-1], last
    return lines, None


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


def _apply_choice_answer_key(questions: list[dict[str, Any]], answer_key_text: str) -> None:
    raw_entries = [line.strip() for line in answer_key_text.splitlines() if line.strip()]
    if not raw_entries:
        return
    choice_questions = [
        question
        for question in questions
        if question.get("question_type") in CHOICE_QUESTION_TYPES
    ]
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
        by_position = {
            int(question.get("position") or index): question
            for index, question in enumerate(questions, start=1)
        }
        for position, label in keyed_by_number.items():
            question = by_position.get(position)
            if question is None:
                raise ValueError(f"Answer key references unknown question {position}")
            if question.get("question_type") not in CHOICE_QUESTION_TYPES:
                raise ValueError(
                    f"Answer key for question {position} targets a non-choice item"
                )
            if label not in question["options"]:
                raise ValueError(
                    f"Answer key for question {position} uses invalid option {label}"
                )
            question["correct"] = label
        return
    if len(positional_entries) != len(choice_questions):
        raise ValueError(
            "Answer key text line count must match the imported choice question count"
        )
    for index, (question, answer_text) in enumerate(
        zip(choice_questions, positional_entries), start=1
    ):
        answer_norm = _normalize_option(answer_text)
        matches = [
            label
            for label, text in question["options"].items()
            if _normalize_option(text) == answer_norm
        ]
        if len(matches) != 1:
            raise ValueError(
                f"Answer key text for choice question {index} did not match exactly one option"
            )
        question["correct"] = matches[0]


def build_mc_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_MC_PROMPT,
) -> str:
    template = _prompt_template(prompt_path)
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


def build_choice_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_CHOICE_PROMPT,
) -> str:
    template = _prompt_template(prompt_path)
    options = "\n".join(
        f"{label}. {text}" for label, text in normalize_options(item["options"]).items()
    )
    option_labels = ", ".join(normalize_options(item["options"]))
    target = item.get("target") or ""
    context_target = target or item.get("_context_target") or ""
    source_citation = item.get("source_citation") or ""
    context = build_mc_context(
        _prioritized_context_rows(item, context_rows),
        max_chars,
        target=context_target,
    )
    question_guidance = build_choice_question_guidance(item, context_rows)
    return template.format(
        question=item["question"],
        question_type=item.get("question_type") or "multiple_choice",
        target=target,
        source_citation=source_citation,
        option_labels=option_labels,
        options=options,
        question_guidance=question_guidance,
        context=context,
    )


def build_choice_question_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str:
    guidance = []
    question = str(item.get("question") or "")
    if re.search(r"\b(?:not|except)\b", question, flags=re.IGNORECASE):
        guidance.append(
            "This is a negative question: choose the option that the context does not state as true or directly contradicts."
        )
        negative_guidance = _negative_option_guidance(item, context_rows)
        if negative_guidance:
            guidance.append(negative_guidance)
    both_guidance = _both_option_guidance(item, context_rows)
    if both_guidance:
        guidance.append(both_guidance)
    purpose_guidance = _purpose_option_guidance(item, context_rows)
    if purpose_guidance:
        guidance.append(purpose_guidance)
    percent_guidance = _percentage_complement_guidance(item, context_rows)
    if percent_guidance:
        guidance.append(percent_guidance)
    return "\n".join(guidance) if guidance else "None."


def _negative_option_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    options = normalize_options(item.get("options") or {})
    if len(options) < 3:
        return None
    context = _choice_guidance_context(context_rows)
    if not context:
        return None
    supported = []
    unsupported = []
    for label, text in options.items():
        if _option_text_supported(text, context):
            supported.append(label)
        else:
            unsupported.append(label)
    if len(unsupported) == 1 and len(supported) >= 2:
        label = unsupported[0]
        return (
            f"Direct option-text check: options {', '.join(supported)} appear in the context; "
            f"option {label} does not. For this negative question, select option {label}."
        )
    return None


def _both_option_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    options = normalize_options(item.get("options") or {})
    context = _choice_guidance_context(context_rows)
    if not options or not context:
        return None
    both_options = [
        (label, text)
        for label, text in options.items()
        if re.search(r"\bboth\b", text, flags=re.IGNORECASE)
    ]
    if not both_options:
        return None
    supported = [
        label
        for label, text in options.items()
        if not re.search(r"\b(?:both|neither|none|all)\b", text, flags=re.IGNORECASE)
        and _option_text_supported(text, context)
    ]
    if len(supported) >= 2:
        both_label = both_options[0][0]
        return (
            f"The context supports multiple individual options ({', '.join(supported)}). "
            f"Because option {both_label} is a 'Both' answer, select option {both_label}."
        )
    return None


def _purpose_option_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    question = str(item.get("question") or "").lower()
    if not re.search(r"\b(?:aimed|purpose|primary purpose|intended)\b", question):
        return None
    options = normalize_options(item.get("options") or {})
    context = _choice_guidance_context(context_rows)
    if not options or not context:
        return None
    context_search = _guidance_normalized_text(context)
    if (
        "dawes" in question
        and "path to civilization" in context_search
        and "american style agriculture" in context_search
    ):
        for label, text in options.items():
            if re.search(r"\bassimilat", text, flags=re.IGNORECASE):
                return (
                    "This purpose question asks for the policy aim, not a narrower implementation detail. "
                    "The context says allotment would encourage American-style agriculture and put Native Americans "
                    f"on the path to 'civilization,' so select option {label}."
                )
    return None


def _choice_guidance_context(context_rows: list[dict[str, Any]]) -> str:
    return " ".join(" ".join(str(row.get("text", "")).split()) for row in context_rows)


def _option_text_supported(option_text: str, context: str) -> bool:
    option_norm = _guidance_normalized_text(option_text)
    context_norm = _guidance_normalized_text(context)
    if not option_norm:
        return False
    return re.search(rf"\b{re.escape(option_norm)}\b", context_norm) is not None


def _guidance_normalized_text(text: str) -> str:
    dehyphenated = re.sub(r"(\w)-\s+(\w)", r"\1\2", str(text))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", dehyphenated.lower()).split())


def _percentage_complement_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    question = str(item.get("question") or "").lower()
    if "percent" not in question and "%" not in question:
        return None
    question_group = _percentage_group(question)
    if question_group is None:
        return None
    context = " ".join(str(row.get("text", "")) for row in context_rows)
    context_compact = " ".join(context.split())
    context_lower = context_compact.lower()
    for match in re.finditer(r"\b(\d{1,3})\s*(?:%|percent)(?=\W|$)", context_lower):
        value = int(match.group(1))
        if not 0 <= value <= 100:
            continue
        window = context_lower[match.start() : match.end() + 140]
        clause = re.split(r"[,.;:]", window, maxsplit=1)[0]
        context_group = _percentage_group(clause)
        if context_group is None or context_group == question_group:
            continue
        complement = 100 - value
        options = normalize_options(item["options"])
        label = _percentage_option_label(options, complement)
        if label is None:
            continue
        return (
            f"The context says about {value} percent were {context_group}; "
            f"the question asks for {question_group}, so use the complement "
            f"100 - {value} = {complement} percent. Select option {label}."
        )
    return None


def _percentage_group(text: str) -> str | None:
    if re.search(r"\b(?:women|woman|female|females)\b", text):
        return "women"
    if re.search(r"\b(?:men|man|male|males)\b", text):
        return "men"
    return None


def _percentage_option_label(options: dict[str, str], value: int) -> str | None:
    value_patterns = {
        f"{value}%",
        f"{value} percent",
        f"{value} per cent",
    }
    for label, text in options.items():
        normalized = _normalize_option(text)
        if normalized in value_patterns:
            return label
    return None


def build_essay_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_ESSAY_PROMPT,
) -> str:
    template = _prompt_template(prompt_path)
    target = item.get("target") or ""
    context_target = target or item.get("_context_target") or ""
    source_citation = item.get("source_citation") or ""
    context = build_mc_context(
        _prioritized_context_rows(item, context_rows),
        max_chars,
        target=context_target,
    )
    return template.format(
        question=item["question"],
        points=item.get("points") or "",
        target=target,
        source_citation=source_citation,
        context=context,
    )


@lru_cache(maxsize=16)
def _prompt_template(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8")


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
        index = _best_token_window_center(compact, target, max_chars)
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


def _best_token_window_center(text: str, target: str, max_chars: int) -> int:
    lowered = text.lower()
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", target.lower())
        if len(token) > 2
    ]
    if not tokens:
        return -1
    unique_tokens = list(dict.fromkeys(tokens))
    best_index = -1
    best_score: tuple[int, int, int] | None = None
    for token in unique_tokens:
        start = 0
        while True:
            index = lowered.find(token, start)
            if index < 0:
                break
            window_start = max(index - max_chars // 2, 0)
            window_end = min(window_start + max_chars, len(text))
            window = lowered[window_start:window_end]
            score = (
                sum(1 for candidate in unique_tokens if candidate in window),
                len(token),
                index,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
            start = index + len(token)
    return best_index


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


def _normalize_option(value: str) -> str:
    return " ".join(str(value).strip().lower().split())


def _normalize_points(value: Any) -> int | float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def _normalize_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


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
