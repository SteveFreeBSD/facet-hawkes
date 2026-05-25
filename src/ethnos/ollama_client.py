"""Ollama structured extraction wrapper."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from .config import OllamaThink
from .models import ChunkRecord, ExtractionResult


@dataclass(frozen=True)
class OllamaDebugInfo:
    prompt_char_length: int
    schema_top_level_keys: list[str]
    format_kind: str
    num_predict: int
    num_ctx: int
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


@dataclass(frozen=True)
class AnswerCallResult:
    raw_prompt: str
    raw_response: str
    debug_info: OllamaDebugInfo | None = None


@dataclass(frozen=True)
class MCAnswerResult:
    raw_prompt: str
    raw_response: str
    selected_option: str | None
    validation_status: str
    validation_error: str | None
    debug_info: OllamaDebugInfo | None = None


@dataclass(frozen=True)
class ChoiceAnswerResult:
    raw_prompt: str
    raw_response: str
    selected_option: str | None
    evidence: str | None
    source_citations: list[str]
    validation_status: str
    validation_error: str | None
    debug_info: OllamaDebugInfo | None = None


@dataclass(frozen=True)
class EssayAnswerResult:
    raw_prompt: str
    raw_response: str
    answer: str | None
    key_points: list[str]
    rubric: list[str]
    source_citations: list[str]
    limitations: list[str]
    validation_status: str
    validation_error: str | None
    debug_info: OllamaDebugInfo | None = None


class MCSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_option: Literal["A", "B", "C", "D"]


def load_prompt(prompt_path: Path, chunk: ChunkRecord) -> str:
    template = _prompt_template(prompt_path)
    return template.format(source_citation=chunk.source_citation, chunk_text=chunk.text)


@lru_cache(maxsize=16)
def _prompt_template(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8")


def extract_chunk(
    chunk: ChunkRecord,
    prompt_path: Path,
    model_name: str,
    host: str,
    timeout: float,
    num_predict: int,
    num_ctx: int,
    retries: int = 1,
    debug_ollama: bool = False,
    think: OllamaThink = False,
    client: object | None = None,
    retry_sleep: Callable[[float], None] = time.sleep,
) -> StructuredCallResult:
    prompt = load_prompt(prompt_path, chunk)
    schema = _extraction_schema()
    last: StructuredCallResult | None = None
    client = client if client is not None else create_client(host, timeout)

    for attempt in range(retries + 1):
        attempt_prompt = prompt if attempt == 0 else _repair_prompt(prompt)
        debug_info = _debug_info(attempt_prompt, schema, num_predict, num_ctx)
        try:
            chat_result = _chat(
                client=client,
                prompt=attempt_prompt,
                schema=schema,
                model_name=model_name,
                num_predict=num_predict,
                num_ctx=num_ctx,
                think=think,
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
                debug_info=debug_info if debug_ollama else None,
            )
            _sleep_before_retry(attempt, retries, retry_sleep)
            continue

        result = _validate_response(attempt_prompt, raw_response)
        result = _with_debug_info(
            result,
            OllamaDebugInfo(
                prompt_char_length=debug_info.prompt_char_length,
                schema_top_level_keys=debug_info.schema_top_level_keys,
                format_kind=debug_info.format_kind,
                num_predict=debug_info.num_predict,
                num_ctx=debug_info.num_ctx,
                response_summary=chat_result.response_summary,
            ),
        )
        if result.result is not None:
            return result
        last = result
        _sleep_before_retry(attempt, retries, retry_sleep)

    if last is None:
        raise RuntimeError("Ollama extraction failed before producing a result")
    return last


def _sleep_before_retry(
    attempt: int,
    retries: int,
    retry_sleep: Callable[[float], None],
) -> None:
    if attempt >= retries:
        return
    retry_sleep(_retry_delay_seconds(attempt))


def _retry_delay_seconds(attempt: int) -> float:
    return min(0.5 * (2**attempt), 4.0)


def answer_question(
    prompt: str,
    model_name: str,
    host: str,
    timeout: float,
    num_predict: int,
    num_ctx: int,
    think: OllamaThink = False,
    client: object | None = None,
) -> AnswerCallResult:
    client = client if client is not None else create_client(host, timeout)
    chat_result = _chat_plain(
        client=client,
        prompt=prompt,
        model_name=model_name,
        num_predict=num_predict,
        num_ctx=num_ctx,
        think=think,
    )
    debug_info = OllamaDebugInfo(
        prompt_char_length=len(prompt),
        schema_top_level_keys=[],
        format_kind="plain_text",
        num_predict=num_predict,
        num_ctx=num_ctx,
        response_summary=chat_result.response_summary,
    )
    return AnswerCallResult(
        raw_prompt=prompt,
        raw_response=chat_result.content,
        debug_info=debug_info,
    )


def answer_mc_question(
    prompt: str,
    model_name: str,
    host: str,
    timeout: float,
    num_predict: int,
    num_ctx: int,
    allowed_options: list[str] | tuple[str, ...] | None = None,
    client: object | None = None,
) -> MCAnswerResult:
    allowed_options = _normalize_allowed_options(allowed_options)
    schema = _mc_selection_schema(allowed_options)
    debug_info = _debug_info(prompt, schema, num_predict, num_ctx)
    client = client if client is not None else create_client(host, timeout)
    try:
        chat_result = _chat_mc(
            client=client,
            prompt=prompt,
            schema=schema,
            model_name=model_name,
            num_predict=num_predict,
            num_ctx=num_ctx,
        )
    except Exception as exc:  # Ollama/httpx exceptions vary by version.
        return MCAnswerResult(
            raw_prompt=prompt,
            raw_response="",
            selected_option=None,
            validation_status="request_failed",
            validation_error=str(exc),
            debug_info=debug_info,
        )
    debug_info = OllamaDebugInfo(
        prompt_char_length=debug_info.prompt_char_length,
        schema_top_level_keys=debug_info.schema_top_level_keys,
        format_kind=debug_info.format_kind,
        num_predict=debug_info.num_predict,
        num_ctx=debug_info.num_ctx,
        response_summary=chat_result.response_summary,
    )
    return _validate_mc_response(
        prompt, chat_result.content, debug_info, allowed_options=allowed_options
    )


def answer_choice_question(
    prompt: str,
    model_name: str,
    host: str,
    timeout: float,
    num_predict: int,
    num_ctx: int,
    allowed_options: list[str] | tuple[str, ...] | None = None,
    client: object | None = None,
) -> ChoiceAnswerResult:
    allowed_options = _normalize_allowed_options(allowed_options)
    schema = _choice_answer_schema(allowed_options)
    debug_info = _debug_info(prompt, schema, num_predict, num_ctx)
    client = client if client is not None else create_client(host, timeout)
    try:
        chat_result = _chat_mc(
            client=client,
            prompt=prompt,
            schema=schema,
            model_name=model_name,
            num_predict=num_predict,
            num_ctx=num_ctx,
        )
    except Exception as exc:
        return ChoiceAnswerResult(
            raw_prompt=prompt,
            raw_response="",
            selected_option=None,
            evidence=None,
            source_citations=[],
            validation_status="request_failed",
            validation_error=str(exc),
            debug_info=debug_info,
        )
    debug_info = OllamaDebugInfo(
        prompt_char_length=debug_info.prompt_char_length,
        schema_top_level_keys=debug_info.schema_top_level_keys,
        format_kind=debug_info.format_kind,
        num_predict=debug_info.num_predict,
        num_ctx=debug_info.num_ctx,
        response_summary=chat_result.response_summary,
    )
    return _validate_choice_response(
        prompt, chat_result.content, debug_info, allowed_options=allowed_options
    )


def answer_essay_question(
    prompt: str,
    model_name: str,
    host: str,
    timeout: float,
    num_predict: int,
    num_ctx: int,
    client: object | None = None,
) -> EssayAnswerResult:
    schema = _essay_answer_schema()
    debug_info = _debug_info(prompt, schema, num_predict, num_ctx)
    client = client if client is not None else create_client(host, timeout)
    try:
        chat_result = _chat_mc(
            client=client,
            prompt=prompt,
            schema=schema,
            model_name=model_name,
            num_predict=num_predict,
            num_ctx=num_ctx,
        )
    except Exception as exc:
        return EssayAnswerResult(
            raw_prompt=prompt,
            raw_response="",
            answer=None,
            key_points=[],
            rubric=[],
            source_citations=[],
            limitations=[],
            validation_status="request_failed",
            validation_error=str(exc),
            debug_info=debug_info,
        )
    debug_info = OllamaDebugInfo(
        prompt_char_length=debug_info.prompt_char_length,
        schema_top_level_keys=debug_info.schema_top_level_keys,
        format_kind=debug_info.format_kind,
        num_predict=debug_info.num_predict,
        num_ctx=debug_info.num_ctx,
        response_summary=chat_result.response_summary,
    )
    return _validate_essay_response(prompt, chat_result.content, debug_info)


def create_client(host: str, timeout: float) -> object:
    try:
        from ollama import Client
    except ImportError as exc:
        raise RuntimeError("The ollama Python package is required. Install with `uv sync`.") from exc

    return Client(host=host, timeout=timeout)


def _chat(
    client: object,
    prompt: str,
    schema: dict,
    model_name: str,
    num_predict: int,
    num_ctx: int,
    think: OllamaThink = False,
) -> OllamaChatResult:
    return _do_chat(
        client,
        _chat_request_kwargs(model_name, prompt, schema, num_predict, num_ctx, think),
    )


def _chat_plain(
    client: object,
    prompt: str,
    model_name: str,
    num_predict: int,
    num_ctx: int,
    think: OllamaThink = False,
) -> OllamaChatResult:
    return _do_chat(
        client,
        _answer_chat_request_kwargs(model_name, prompt, num_predict, num_ctx, think),
    )


def _chat_mc(
    client: object,
    prompt: str,
    schema: dict,
    model_name: str,
    num_predict: int,
    num_ctx: int,
) -> OllamaChatResult:
    return _do_chat(
        client,
        _mc_chat_request_kwargs(model_name, prompt, schema, num_predict, num_ctx),
    )


def _do_chat(client: object, request_kwargs: dict) -> OllamaChatResult:
    response = client.chat(**request_kwargs)
    envelope = _plain_response(response)
    message = _plain_message(envelope.get("message") or {})
    content = message.get("content", "")
    if not isinstance(content, str):
        raise RuntimeError("Ollama response did not include string message content")
    return OllamaChatResult(
        content=content,
        response_summary=_response_summary(response),
    )


def _chat_request_kwargs(
    model_name: str,
    prompt: str,
    schema: dict,
    num_predict: int,
    num_ctx: int,
    think: OllamaThink = False,
) -> dict:
    request = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": "You extract structured study data and return only schema-valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        "format": schema,
        "options": _ollama_options(num_predict, num_ctx),
    }
    _add_think_option(request, think)
    return request


def _ollama_schema(schema: dict) -> dict:
    return _compact_json_schema(schema)


@lru_cache(maxsize=1)
def _extraction_schema() -> dict:
    return _ollama_schema(ExtractionResult.model_json_schema())


def _compact_json_schema(value):
    if isinstance(value, dict):
        return {
            key: _compact_json_schema(child)
            for key, child in value.items()
            if key != "default"
        }
    if isinstance(value, list):
        return [_compact_json_schema(child) for child in value]
    return value


def _answer_chat_request_kwargs(
    model_name: str,
    prompt: str,
    num_predict: int,
    num_ctx: int,
    think: OllamaThink = False,
) -> dict:
    request = {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You answer questions from provided local PDF context. "
                    "Use only the supplied context and cite its chunk citations."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "options": _ollama_options(num_predict, num_ctx),
    }
    _add_think_option(request, think)
    return request


def _mc_chat_request_kwargs(
    model_name: str, prompt: str, schema: dict, num_predict: int, num_ctx: int
) -> dict:
    return {
        "model": model_name,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You answer multiple-choice and other quiz questions from provided local PDF context. "
                    "Use only the supplied context and return only schema-valid JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "format": schema,
        "options": _ollama_options(num_predict, num_ctx),
        "think": False,
    }


def _add_think_option(request: dict, think: OllamaThink) -> None:
    if think is not None:
        request["think"] = think


def _ollama_options(num_predict: int, num_ctx: int) -> dict[str, int]:
    options = {"temperature": 0, "num_predict": num_predict, "num_ctx": num_ctx}
    num_thread = _optional_positive_int_env("ETHNOS_OLLAMA_NUM_THREAD")
    if num_thread is not None:
        options["num_thread"] = num_thread
    return options


def _optional_positive_int_env(name: str) -> int | None:
    raw_value = os.getenv(name)
    if not raw_value:
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


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


def _validate_mc_response(
    prompt: str,
    raw_response: str,
    debug_info: OllamaDebugInfo | None = None,
    *,
    allowed_options: list[str] | tuple[str, ...] | None = None,
) -> MCAnswerResult:
    allowed_options = _normalize_allowed_options(allowed_options)
    if not raw_response.strip():
        return MCAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            validation_status="empty_response",
            validation_error="Ollama returned an empty response body/content",
            debug_info=debug_info,
        )

    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return MCAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            validation_status="invalid_json",
            validation_error=str(exc),
            debug_info=debug_info,
        )

    selected_option = parsed.get("selected_option") if isinstance(parsed, dict) else None
    if not isinstance(selected_option, str):
        return MCAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            validation_status="validation_error",
            validation_error="MC response must include string selected_option",
            debug_info=debug_info,
        )
    selected_option = selected_option.strip().upper()
    if selected_option not in allowed_options:
        validation_status = (
            "invalid_option"
            if selected_option
            else "validation_error"
        )
        return MCAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            validation_status=validation_status,
            validation_error=(
                f"selected_option must be one of {', '.join(allowed_options)}"
            ),
            debug_info=debug_info,
        )

    return MCAnswerResult(
        raw_prompt=prompt,
        raw_response=raw_response,
        selected_option=selected_option,
        validation_status="valid",
        validation_error=None,
        debug_info=debug_info,
    )


def _validate_choice_response(
    prompt: str,
    raw_response: str,
    debug_info: OllamaDebugInfo | None = None,
    *,
    allowed_options: list[str] | tuple[str, ...] | None = None,
) -> ChoiceAnswerResult:
    allowed_options = _normalize_allowed_options(allowed_options)
    base = _validate_json_object(raw_response)
    if isinstance(base, str):
        return ChoiceAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            evidence=None,
            source_citations=[],
            validation_status="empty_response" if not raw_response.strip() else "invalid_json",
            validation_error=base,
            debug_info=debug_info,
        )
    selected_option = base.get("selected_option")
    if not isinstance(selected_option, str):
        return ChoiceAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            evidence=None,
            source_citations=[],
            validation_status="validation_error",
            validation_error="Choice response must include string selected_option",
            debug_info=debug_info,
        )
    selected_option = selected_option.strip().upper()
    if selected_option not in allowed_options:
        return ChoiceAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            evidence=None,
            source_citations=[],
            validation_status="invalid_option",
            validation_error=f"selected_option must be one of {', '.join(allowed_options)}",
            debug_info=debug_info,
        )
    field_error = _required_field_error(
        base,
        required_types={
            "evidence": str,
            "source_citations": list,
        },
    )
    if field_error:
        return ChoiceAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            selected_option=None,
            evidence=None,
            source_citations=[],
            validation_status="validation_error",
            validation_error=field_error,
            debug_info=debug_info,
        )
    return ChoiceAnswerResult(
        raw_prompt=prompt,
        raw_response=raw_response,
        selected_option=selected_option,
        evidence=str(base.get("evidence") or "").strip() or None,
        source_citations=_string_list(base.get("source_citations")),
        validation_status="valid",
        validation_error=None,
        debug_info=debug_info,
    )


def _validate_essay_response(
    prompt: str,
    raw_response: str,
    debug_info: OllamaDebugInfo | None = None,
) -> EssayAnswerResult:
    base = _validate_json_object(raw_response)
    if isinstance(base, str):
        return EssayAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            answer=None,
            key_points=[],
            rubric=[],
            source_citations=[],
            limitations=[],
            validation_status="empty_response" if not raw_response.strip() else "invalid_json",
            validation_error=base,
            debug_info=debug_info,
        )
    answer = str(base.get("answer") or "").strip()
    field_error = _required_field_error(
        base,
        required_types={
            "answer": str,
            "key_points": list,
            "rubric": list,
            "source_citations": list,
            "limitations": list,
        },
    )
    if field_error:
        return EssayAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            answer=None,
            key_points=_string_list(base.get("key_points")),
            rubric=_string_list(base.get("rubric")),
            source_citations=_string_list(base.get("source_citations")),
            limitations=_string_list(base.get("limitations")),
            validation_status="validation_error",
            validation_error=field_error,
            debug_info=debug_info,
        )
    if not answer:
        return EssayAnswerResult(
            raw_prompt=prompt,
            raw_response=raw_response,
            answer=None,
            key_points=_string_list(base.get("key_points")),
            rubric=_string_list(base.get("rubric")),
            source_citations=_string_list(base.get("source_citations")),
            limitations=_string_list(base.get("limitations")),
            validation_status="validation_error",
            validation_error="Essay response must include non-empty answer",
            debug_info=debug_info,
        )
    return EssayAnswerResult(
        raw_prompt=prompt,
        raw_response=raw_response,
        answer=answer,
        key_points=_string_list(base.get("key_points")),
        rubric=_string_list(base.get("rubric")),
        source_citations=_string_list(base.get("source_citations")),
        limitations=_string_list(base.get("limitations")),
        validation_status="valid",
        validation_error=None,
        debug_info=debug_info,
    )


def _validate_json_object(raw_response: str) -> dict | str:
    if not raw_response.strip():
        return "Ollama returned an empty response body/content"
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        return str(exc)
    if not isinstance(parsed, dict):
        return "Response must be a JSON object"
    return parsed


def _required_field_error(base: dict, *, required_types: dict[str, type]) -> str | None:
    missing = [field for field in required_types if field not in base]
    if missing:
        return "Response missing required field(s): " + ", ".join(missing)
    wrong_type = [
        field
        for field, expected_type in required_types.items()
        if not isinstance(base.get(field), expected_type)
    ]
    if wrong_type:
        return "Response field(s) have invalid type: " + ", ".join(wrong_type)
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_allowed_options(
    allowed_options: list[str] | tuple[str, ...] | None,
) -> list[str]:
    if allowed_options is None:
        return ["A", "B", "C", "D"]
    normalized = []
    for option in allowed_options:
        label = str(option).strip().upper()
        if label and label not in normalized:
            normalized.append(label)
    if not normalized:
        raise ValueError("allowed_options must include at least one label")
    return normalized


def _mc_selection_schema(allowed_options: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "selected_option": {
                "type": "string",
                "enum": allowed_options,
            }
        },
        "required": ["selected_option"],
        "additionalProperties": False,
    }


def _choice_answer_schema(allowed_options: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "selected_option": {"type": "string", "enum": allowed_options},
            "evidence": {"type": "string"},
            "source_citations": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["selected_option", "evidence", "source_citations"],
        "additionalProperties": False,
    }


def _essay_answer_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "rubric": {"type": "array", "items": {"type": "string"}},
            "source_citations": {"type": "array", "items": {"type": "string"}},
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "answer",
            "key_points",
            "rubric",
            "source_citations",
            "limitations",
        ],
        "additionalProperties": False,
    }


def _repair_prompt(original_prompt: str) -> str:
    return (
        original_prompt
        + "\n\nIMPORTANT: Your previous response was not valid JSON. "
        "Return ONLY valid JSON matching the schema. No Markdown fences, no commentary."
    )


def _debug_info(prompt: str, schema: dict, num_predict: int, num_ctx: int) -> OllamaDebugInfo:
    return OllamaDebugInfo(
        prompt_char_length=len(prompt),
        schema_top_level_keys=sorted(schema.keys()),
        format_kind="json_schema",
        num_predict=num_predict,
        num_ctx=num_ctx,
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
    thinking = message.get("thinking", "")
    if not isinstance(thinking, str):
        thinking = ""
    return {
        "done": envelope.get("done"),
        "done_reason": envelope.get("done_reason"),
        "eval_count": envelope.get("eval_count"),
        "message_content_length": len(content),
        "message_thinking_length": len(thinking),
        "message_thinking_exists": bool(thinking),
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
