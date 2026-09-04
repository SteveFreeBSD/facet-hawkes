"""Quiz schemas, normalization, and shared constants."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .text_utils import compact_text


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
    def validate_options(_cls, value: dict[str, str]) -> dict[str, str]:
        return normalize_options(value)

    @field_validator("correct")
    @classmethod
    def validate_correct(_cls, value: str | None) -> str | None:
        return value.strip().upper() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_choice_shape(self):
        if self.question_type == "true_false" and not is_true_false_options(
            self.options
        ):
            raise ValueError(
                "true_false quiz items must use options A=True and B=False"
            )
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
        options = (
            normalize_options(item.get("options"))
            if item.get("options") is not None
            else None
        )
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
        # Chunk order is meaningful: anchored retrieval and evidence presentation
        # follow the order declared by the quiz author.
        "source_chunks": _normalize_ordered_int_list(item.get("source_chunks")),
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
            raise ValueError(
                f"Quiz item {normalized['id']} cannot key a {question_type} item"
            )
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
        raise ValueError(
            f"Quiz item {item.get('id') or '?'} has unsupported question_type"
        )
    try:
        return model.model_validate(item).model_dump(mode="json", exclude_none=True)
    except ValidationError as exc:
        raise ValueError(
            f"Quiz item {item.get('id') or '?'} is invalid: {exc}"
        ) from exc


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
        and _normalize_option(options["A"])
        == _normalize_option(TRUE_FALSE_OPTIONS["A"])
        and _normalize_option(options["B"])
        == _normalize_option(TRUE_FALSE_OPTIONS["B"])
    )


def normalize_options(options: Any) -> dict[str, str]:
    if isinstance(options, dict):
        normalized = {
            str(key).upper(): str(value).strip() for key, value in options.items()
        }
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
    return compact_text(text, max_chars)


def parse_source_pages(raw_pages: Any) -> list[int]:
    if raw_pages is None:
        return []
    if isinstance(raw_pages, str):
        try:
            raw_pages = json.loads(raw_pages)
        except json.JSONDecodeError:
            return []
    return _normalize_int_list(raw_pages)


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


def _normalize_ordered_int_list(value: Any) -> list[int]:
    if value is None or not isinstance(value, list):
        return []
    normalized: list[int] = []
    for item in value:
        try:
            parsed = int(item)
        except (TypeError, ValueError):
            continue
        if parsed not in normalized:
            normalized.append(parsed)
    return normalized
