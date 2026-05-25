"""Chapter quiz manifest helpers for CLI import commands."""

from __future__ import annotations

import json
from pathlib import Path

from ..quiz_validation import validate_quiz_item as _validate_quiz_item


def load_chapter_quiz_manifest(path: Path) -> dict[str, object]:
    if not path.exists():
        raise ValueError(f"Chapter quiz manifest not found: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Chapter quiz manifest is invalid JSON: {path}") from exc
    if not isinstance(manifest, dict):
        raise ValueError("Chapter quiz manifest must be a JSON object.")
    chapters = manifest.get("chapters")
    if not isinstance(chapters, dict):
        raise ValueError("Chapter quiz manifest must include a chapters object.")
    return manifest


def chapter_quiz_manifest_entry(
    manifest: dict[str, object],
    chapter_number: int,
) -> dict[str, object]:
    chapters = manifest.get("chapters")
    if not isinstance(chapters, dict):
        raise ValueError("Chapter quiz manifest must include a chapters object.")
    chapter = chapters.get(str(chapter_number))
    if not isinstance(chapter, dict):
        raise ValueError(f"Chapter {chapter_number} is not defined in the manifest.")
    return chapter


def chapter_quiz_file_stem(
    manifest: dict[str, object],
    course: str,
    chapter_number: int,
) -> str:
    template = str(manifest.get("file_template") or "{course}_ch{chapter}_canvas")
    try:
        return template.format(course=course, chapter=chapter_number)
    except KeyError as exc:
        raise SystemExit(f"Unsupported file_template placeholder: {exc}") from exc


def validate_imported_chapter_quiz_shape(
    conn,
    *,
    document_id: int,
    quiz: dict[str, object],
    strict_complete: bool,
) -> list[str]:
    errors = []
    if quiz.get("version") != "external-quiz-v2":
        errors.append("imported quiz must use version external-quiz-v2")
    questions = quiz.get("questions")
    if not isinstance(questions, list):
        return [*errors, "imported quiz must include a questions list"]
    for item in questions:
        if not isinstance(item, dict):
            errors.append("quiz questions must be objects")
            continue
        for error in _validate_quiz_item(
            conn,
            document_id,
            item,
            require_anchors=False,
            strict_complete=strict_complete,
            require_key=False,
        ):
            errors.append(f"{item.get('id') or '?'}: {error}")
    return errors


def validate_chapter_quiz_contract(
    quiz: dict[str, object],
    *,
    chapter: dict[str, object],
    chapter_number: int,
) -> list[str]:
    questions = quiz.get("questions")
    if not isinstance(questions, list):
        return []
    errors = []
    expected_questions = chapter.get("expected_questions")
    if expected_questions is not None and len(questions) != int(expected_questions):
        errors.append(
            f"expected {expected_questions} questions, imported {len(questions)}"
        )
    expected_points = chapter.get("expected_total_points")
    if expected_points is not None and quiz.get("total_points") != expected_points:
        errors.append(
            f"expected total_points {expected_points}, imported {quiz.get('total_points')}"
        )
    expected_keyed = chapter.get("expected_keyed_choices")
    if expected_keyed is not None:
        keyed_count = _keyed_choice_count(questions)
        if keyed_count != int(expected_keyed):
            errors.append(
                f"expected {expected_keyed} keyed choices, imported {keyed_count}"
            )
    expected_types = chapter.get("expected_question_types")
    if isinstance(expected_types, dict):
        actual_types = _question_type_counts(questions)
        expected_type_counts = {
            str(key): int(value) for key, value in expected_types.items()
        }
        if actual_types != expected_type_counts:
            errors.append(
                f"expected question types {expected_type_counts}, imported {actual_types}"
            )
    expected_prefix = f"ch{chapter_number}-q"
    for position, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            continue
        expected_id = f"{expected_prefix}{position:03d}"
        if item.get("id") != expected_id:
            errors.append(
                f"expected question {position} id {expected_id}, got {item.get('id')}"
            )
    allowed_warnings = {str(warning) for warning in chapter.get("allowed_warnings", [])}
    for item in questions:
        if not isinstance(item, dict):
            continue
        for warning in item.get("warnings", []):
            if str(warning) not in allowed_warnings:
                errors.append(f"{item.get('id')}: warning not allowed: {warning}")
    return errors


def apply_chapter_quiz_item_overrides(
    quiz: dict[str, object],
    chapter: dict[str, object],
) -> None:
    overrides = chapter.get("item_overrides")
    if not isinstance(overrides, dict):
        return
    questions = quiz.get("questions")
    if not isinstance(questions, list):
        return
    by_id = {
        str(item.get("id")): item
        for item in questions
        if isinstance(item, dict) and item.get("id")
    }
    for item_id, override in overrides.items():
        if not isinstance(override, dict):
            raise ValueError(f"item_overrides.{item_id} must be an object")
        item = by_id.get(str(item_id))
        if item is None:
            raise ValueError(f"item_overrides references unknown item {item_id}")
        for key, value in override.items():
            if key == "warnings":
                item[key] = _merged_warning_list(item.get("warnings"), value)
            else:
                item[key] = value


def _merged_warning_list(existing: object, override: object) -> list[str]:
    warnings: list[str] = []
    for values in (existing, override):
        if values is None:
            continue
        if not isinstance(values, list):
            raise ValueError("warning overrides must be lists")
        for value in values:
            warning = str(value)
            if warning not in warnings:
                warnings.append(warning)
    return warnings


def _keyed_choice_count(items: list[object]) -> int:
    return sum(
        1
        for item in items
        if isinstance(item, dict)
        and item.get("question_type") in {"multiple_choice", "true_false"}
        and "correct" in item
    )


def _quiz_warning_count(items: list[object]) -> int:
    return sum(
        len(item.get("warnings", []))
        for item in items
        if isinstance(item, dict) and isinstance(item.get("warnings", []), list)
    )


def _question_type_counts(items: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        question_type = str(item.get("question_type") or "multiple_choice")
        counts[question_type] = counts.get(question_type, 0) + 1
    return counts


def chapter_quiz_unresolved_notes(quiz: dict[str, object]) -> list[str]:
    questions = quiz.get("questions")
    if not isinstance(questions, list):
        return []
    unkeyed_choices = sum(
        1
        for item in questions
        if isinstance(item, dict)
        and item.get("question_type") in {"multiple_choice", "true_false"}
        and "correct" not in item
    )
    essays = sum(
        1
        for item in questions
        if isinstance(item, dict) and item.get("question_type") == "essay"
    )
    incomplete_matching = sum(
        1
        for item in questions
        if isinstance(item, dict)
        and "incomplete_matching_item" in item.get("warnings", [])
    )
    notes = []
    if unkeyed_choices:
        notes.append(f"{unkeyed_choices} choice item(s) are unkeyed.")
    if essays:
        notes.append(f"{essays} essay prompt(s) require rubric/model review.")
    if incomplete_matching:
        notes.append(f"{incomplete_matching} matching item(s) are incomplete.")
    return notes
