"""Quiz importers for LMS and Canvas pasted text."""

from __future__ import annotations

import re
from typing import Any

from .quiz_core import (
    CANVAS_FLAG_RE,
    CANVAS_QUESTION_HEADER_RE,
    CHOICE_QUESTION_TYPES,
    EXTERNAL_MIXED_QUIZ_VERSION,
    EXTERNAL_QUIZ_VERSION,
    LABEL_ANSWER_RE,
    POSITION_HEADER_RE,
    normalize_options,
    normalize_question_type,
    normalize_quiz,
    _normalize_option,
    _normalize_points,
)


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
        if item[
            "question_type"
        ] == "matching" and "incomplete_matching_item" in item.get("warnings", []):
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
    raw_entries = [
        line.strip() for line in answer_key_text.splitlines() if line.strip()
    ]
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
                raise ValueError(
                    f"Answer key for question {index} uses invalid option {label}"
                )
            question["correct"] = label
        return
    if len(positional_entries) != len(questions):
        raise ValueError(
            "Answer key text line count must match the imported question count"
        )
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


def _apply_choice_answer_key(
    questions: list[dict[str, Any]], answer_key_text: str
) -> None:
    raw_entries = [
        line.strip() for line in answer_key_text.splitlines() if line.strip()
    ]
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
