"""Standalone structured-output benchmark for pre-calculus model candidates."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .ollama_client import OllamaClientProtocol, structured_chat_json


class PrecalculusBenchmarkItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    question: str
    choices: dict[str, str]
    answer: Literal["A", "B", "C", "D"]

    @model_validator(mode="after")
    def answer_must_be_available(self):
        if set(self.choices) != {"A", "B", "C", "D"}:
            raise ValueError("choices must contain exactly A, B, C, and D")
        if self.answer not in self.choices:
            raise ValueError("answer must name an available choice")
        return self


class PrecalculusBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["precalculus-model-benchmark-v1"]
    items: list[PrecalculusBenchmarkItem] = Field(min_length=1)


class PrecalculusModelAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Field order matters for autoregressive models: make the model derive the
    # result before it commits to a multiple-choice option.
    work: str = Field(min_length=20, max_length=500)
    selected_option: Literal["A", "B", "C", "D"]
    final_answer: str = Field(min_length=1, max_length=120)


def load_precalculus_benchmark(path: Path) -> PrecalculusBenchmark:
    return PrecalculusBenchmark.model_validate_json(path.read_text(encoding="utf-8"))


def build_precalculus_prompt(item: PrecalculusBenchmarkItem) -> str:
    choices = "\n".join(f"{label}. {text}" for label, text in item.choices.items())
    return (
        "Solve this pre-calculus multiple-choice problem carefully. Independently "
        "derive and verify the result in the work field before selecting a choice. "
        "Keep work to 2-4 concise calculation steps; do not merely restate the "
        "question. Return only the requested JSON object, with work first.\n\n"
        f"Question: {item.question}\n\nChoices:\n{choices}"
    )


def run_precalculus_benchmark(
    *,
    benchmark: PrecalculusBenchmark,
    client: OllamaClientProtocol,
    model_name: str,
    num_predict: int,
    num_ctx: int,
    max_questions: int | None = None,
    structured_chat: Callable = structured_chat_json,
) -> dict:
    items = (
        benchmark.items[:max_questions]
        if max_questions is not None
        else benchmark.items
    )
    report_items = []
    correct = invalid = 0
    started_at = time.monotonic()

    for index, item in enumerate(items, start=1):
        item_started_at = time.monotonic()
        result = structured_chat(
            client=client,
            model_name=model_name,
            messages=[{"role": "user", "content": build_precalculus_prompt(item)}],
            schema=PrecalculusModelAnswer.model_json_schema(),
            num_predict=num_predict,
            num_ctx=num_ctx,
            think=False,
        )
        parsed = result.parsed_json
        validation_status = result.validation_status
        validation_error = result.validation_error
        selected_option = None
        if validation_status == "valid" and parsed is not None:
            try:
                answer = PrecalculusModelAnswer.model_validate(parsed)
            except ValidationError as exc:
                validation_status = "validation_error"
                validation_error = str(exc)
            else:
                selected_option = answer.selected_option
        is_valid = validation_status == "valid" and selected_option is not None
        is_correct = is_valid and selected_option == item.answer
        correct += int(is_correct)
        invalid += int(not is_valid)
        report_items.append(
            {
                "id": item.id,
                "category": item.category,
                "question": item.question,
                "expected_option": item.answer,
                "selected_option": selected_option,
                "is_correct": is_correct,
                "validation_status": validation_status,
                "validation_error": validation_error,
                "response": parsed,
                "raw_response": result.raw_response,
                "response_summary": result.response_summary,
                "elapsed_seconds": time.monotonic() - item_started_at,
            }
        )

    total = len(items)
    return {
        "schema_version": "precalculus-model-benchmark-report-v1",
        "model": model_name,
        "num_ctx": num_ctx,
        "num_predict": num_predict,
        "total": total,
        "correct": correct,
        "incorrect": total - correct - invalid,
        "invalid": invalid,
        "accuracy": correct / total if total else 0.0,
        "elapsed_seconds": time.monotonic() - started_at,
        "items": report_items,
    }


def write_precalculus_report(report: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
