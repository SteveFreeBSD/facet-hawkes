"""Ollama structured extraction wrapper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from .models import ChunkRecord, ExtractionResult


@dataclass(frozen=True)
class OllamaDebugInfo:
    prompt_char_length: int
    schema_top_level_keys: list[str]
    format_kind: str
    think: bool
    response_summary: dict | None = None


@dataclass(frozen=True)
class OllamaChatResult:
    content: str
    response_summary: dict


@dataclass(frozen=True)
class StructuredCallResult:
    raw_prompt: str
    raw_response: str
    result: ExtractionResult | None
    parsed_json: dict | None
    validation_status: str
    validation_error: str | None
    debug_info: OllamaDebugInfo | None = None


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
    debug_ollama: bool = False,
) -> StructuredCallResult:
    prompt = load_prompt(prompt_path, chunk)
    schema = ExtractionResult.model_json_schema()
    last: StructuredCallResult | None = None

    for attempt in range(retries + 1):
        attempt_prompt = prompt if attempt == 0 else _repair_prompt(prompt)
        debug_info = _debug_info(attempt_prompt, schema) if debug_ollama else None
        try:
            chat_result = _chat(
                prompt=attempt_prompt,
                schema=schema,
                model_name=model_name,
                host=host,
                timeout=timeout,
            )
            raw_response = chat_result.content
        except Exception as exc:  # Ollama/httpx exceptions vary by version.
            last = StructuredCallResult(
                raw_prompt=attempt_prompt,
                raw_response="",
                result=None,
                parsed_json=None,
                validation_status="request_failed",
                validation_error=str(exc),
                debug_info=debug_info,
            )
            continue

        result = _validate_response(attempt_prompt, raw_response)
        if debug_info is not None:
            result = _with_debug_info(
                result,
                OllamaDebugInfo(
                    prompt_char_length=debug_info.prompt_char_length,
                    schema_top_level_keys=debug_info.schema_top_level_keys,
                    format_kind=debug_info.format_kind,
                    think=debug_info.think,
                    response_summary=chat_result.response_summary,
                ),
            )
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
) -> OllamaChatResult:
    try:
        from ollama import Client
    except ImportError as exc:
        raise RuntimeError("The ollama Python package is required. Install with `uv sync`.") from exc

    client = Client(host=host, timeout=timeout)
    response = client.chat(
        **_chat_request_kwargs(model_name, prompt, schema),
    )
    message = response.get("message", {})
    content = message.get("content", "")
    if not isinstance(content, str):
        raise RuntimeError("Ollama response did not include string message content")
    return OllamaChatResult(
        content=content,
        response_summary=_response_summary(response),
    )


def _chat_request_kwargs(model_name: str, prompt: str, schema: dict) -> dict:
    return {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "You extract structured study data and return only schema-valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        "format": schema,
        "options": {"temperature": 0},
        "think": False,
    }


def _validate_response(prompt: str, raw_response: str) -> StructuredCallResult:
    if not raw_response.strip():
        return StructuredCallResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            result=None,
            parsed_json=None,
            validation_status="empty_response",
            validation_error="Ollama returned an empty response body/content",
        )

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


def _debug_info(prompt: str, schema: dict) -> OllamaDebugInfo:
    return OllamaDebugInfo(
        prompt_char_length=len(prompt),
        schema_top_level_keys=sorted(schema.keys()),
        format_kind="json_schema",
        think=False,
    )


def _with_debug_info(
    result: StructuredCallResult, debug_info: OllamaDebugInfo
) -> StructuredCallResult:
    return StructuredCallResult(
        raw_prompt=result.raw_prompt,
        raw_response=result.raw_response,
        result=result.result,
        parsed_json=result.parsed_json,
        validation_status=result.validation_status,
        validation_error=result.validation_error,
        debug_info=debug_info,
    )


def _response_summary(response: object) -> dict:
    envelope = _plain_response(response)
    message = _plain_message(envelope.get("message") or {})
    content = message.get("content", "")
    if not isinstance(content, str):
        content = ""
    return {
        "done": envelope.get("done"),
        "done_reason": envelope.get("done_reason"),
        "message_content_length": len(content),
        "message_thinking_exists": "thinking" in message,
        "error": envelope.get("error"),
        "total_duration": envelope.get("total_duration"),
        "top_level_keys": sorted(envelope.keys()),
    }


def _plain_response(response: object) -> dict:
    if hasattr(response, "model_dump"):
        dumped = response.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    try:
        return dict(response)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {"response_type": type(response).__name__}


def _plain_message(message: object) -> dict:
    if isinstance(message, dict):
        return message
    if hasattr(message, "model_dump"):
        dumped = message.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    try:
        return dict(message)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return {}
