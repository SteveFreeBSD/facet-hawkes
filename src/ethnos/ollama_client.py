"""Ollama structured extraction wrapper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .models import ChunkRecord, ExtractionResult


@dataclass(frozen=True)
class StructuredCallResult:
    raw_prompt: str
    raw_response: str
    result: ExtractionResult | None
    parsed_json: dict | None
    validation_status: str
    validation_error: str | None


def load_prompt(prompt_path: Path, chunk: ChunkRecord) -> str:
    template = prompt_path.read_text(encoding="utf-8")
    return template.format(source_citation=chunk.source_citation, chunk_text=chunk.text)


def extract_chunk(
    chunk: ChunkRecord,
    prompt_path: Path,
    model_name: str,
    host: str,
    timeout: float,
    retries: int = 1,
) -> StructuredCallResult:
    prompt = load_prompt(prompt_path, chunk)
    schema = ExtractionResult.model_json_schema()
    last: StructuredCallResult | None = None

    for attempt in range(retries + 1):
        attempt_prompt = prompt if attempt == 0 else _repair_prompt(prompt)
        try:
            raw_response = _chat(
                prompt=attempt_prompt,
                schema=schema,
                model_name=model_name,
                host=host,
                timeout=timeout,
            )
        except Exception as exc:  # Ollama/httpx exceptions vary by version.
            last = StructuredCallResult(
                raw_prompt=attempt_prompt,
                raw_response="",
                result=None,
                parsed_json=None,
                validation_status="request_failed",
                validation_error=str(exc),
            )
            continue

        result = _validate_response(attempt_prompt, raw_response)
        if result.result is not None:
            return result
        last = result

    if last is None:
        raise RuntimeError("Ollama extraction failed before producing a result")
    return last


def _chat(
    prompt: str,
    schema: dict,
    model_name: str,
    host: str,
    timeout: float,
) -> str:
    try:
        from ollama import Client
    except ImportError as exc:
        raise RuntimeError("The ollama Python package is required. Install with `uv sync`.") from exc

    client = Client(host=host, timeout=timeout)
    response = client.chat(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": "You extract structured study data and return only schema-valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        format=schema,
        options={"temperature": 0},
    )
    message = response.get("message", {})
    content = message.get("content", "")
    if not isinstance(content, str):
        raise RuntimeError("Ollama response did not include string message content")
    return content


def _validate_response(prompt: str, raw_response: str) -> StructuredCallResult:
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return StructuredCallResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            result=None,
            parsed_json=None,
            validation_status="invalid_json",
            validation_error=str(exc),
        )

    try:
        result = ExtractionResult.model_validate(parsed)
    except ValidationError as exc:
        return StructuredCallResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            result=None,
            parsed_json=parsed,
            validation_status="validation_error",
            validation_error=str(exc),
        )

    return StructuredCallResult(
        raw_prompt=prompt,
        raw_response=raw_response,
        result=result,
        parsed_json=parsed,
        validation_status="valid",
        validation_error=None,
    )


def _repair_prompt(original_prompt: str) -> str:
    return (
        "The previous response was not valid JSON for the required schema. "
        "Return only valid JSON, with no Markdown fences or commentary.\n\n"
        + original_prompt
    )

