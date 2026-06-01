"""Agentic local-PDF Q&A loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .agent_models import AgentToolResult
from .agent_tools import (
    AgentTool,
    AgentToolContext,
    build_agent_tool_registry,
    call_agent_tool,
)
from .ollama_client import OllamaClientProtocol, OllamaDebugInfo, structured_chat_json
from .qa import RetrievalResult, normalize_answer_role


QAAgentToolName = Literal[
    "search_pdf", "inspect_chunk", "inspect_page", "finalize_answer"
]
QASourceStatus = Literal["source_supported", "partial_context", "source_missing"]
StructuredChat = Callable[..., object]

QA_ALLOWED_TOOLS = frozenset({"search_pdf", "inspect_chunk", "inspect_page"})


class QAAgentAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: list[str] = Field(default_factory=list)
    evidence_chunk_ids: list[int] = Field(default_factory=list)
    evidence_pages: list[int] = Field(default_factory=list)
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    source_status: QASourceStatus = "partial_context"


class QAAgentAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool: QAAgentToolName
    arguments: dict[str, Any] = Field(default_factory=dict)
    final_answer: QAAgentAnswer | None = None

    @field_validator("final_answer")
    @classmethod
    def require_answer_for_finalize(
        _cls, value: QAAgentAnswer | None, info
    ) -> QAAgentAnswer | None:
        if info.data.get("tool") == "finalize_answer" and value is None:
            raise ValueError("finalize_answer requires final_answer")
        return value


@dataclass(frozen=True)
class QAAgentResult:
    finalized: bool
    answer_text: str
    retrieval: RetrievalResult
    trace: dict[str, Any]
    fallback_reason: str | None = None
    debug_info: OllamaDebugInfo | None = None


def run_agentic_qa(
    *,
    conn,
    document_id: int,
    question: str,
    output_dir: Path,
    model_name: str,
    num_predict: int,
    num_ctx: int,
    think,
    role: str,
    section: str | None,
    limit: int,
    chars: int,
    max_steps: int,
    client: OllamaClientProtocol | None,
    structured_chat: StructuredChat = structured_chat_json,
) -> QAAgentResult:
    role_filter = normalize_answer_role(role)
    trace: dict[str, Any] = {
        "enabled": True,
        "engine": "structured_json",
        "max_steps": max_steps,
        "allowed_tools": sorted(QA_ALLOWED_TOOLS),
        "actions": [],
        "tool_results": [],
        "fallback_reason": None,
        "source_status": None,
    }
    if client is None:
        return _agent_fallback_result(question, trace, "no_client")

    context = AgentToolContext(
        conn=conn,
        document_id=document_id,
        quiz_items={},
        output_dir=output_dir,
        allow_web=False,
        vision_pages="off",
        model_name=model_name,
        num_predict=num_predict,
        num_ctx=num_ctx,
        client=client,
    )
    registry = build_agent_tool_registry(context)
    messages = _initial_messages(
        question=question,
        role=role_filter,
        section=section,
        limit=limit,
        chars=chars,
    )
    observations: list[dict[str, Any]] = []
    last_debug_info: OllamaDebugInfo | None = None

    for _step in range(max_steps):
        response = structured_chat(
            client=client,
            model_name=model_name,
            messages=messages,
            schema=QAAgentAction.model_json_schema(),
            num_predict=num_predict,
            num_ctx=num_ctx,
            think=think,
        )
        last_debug_info = _debug_info_from_response(
            response,
            schema=QAAgentAction.model_json_schema(),
            num_predict=num_predict,
            num_ctx=num_ctx,
        )
        parsed_json = getattr(response, "parsed_json", None)
        if not parsed_json:
            return _agent_fallback_result(
                question, trace, "empty_or_invalid_model_action", last_debug_info
            )
        try:
            action = QAAgentAction.model_validate(parsed_json)
        except ValidationError as exc:
            trace["fallback_reason"] = "invalid_model_action"
            trace["validation_error"] = str(exc)
            return _agent_fallback_result(
                question, trace, "invalid_model_action", last_debug_info
            )
        trace["actions"].append(action.model_dump(mode="json"))
        messages.append(
            {"role": "assistant", "content": json.dumps(parsed_json, sort_keys=True)}
        )

        if action.tool == "finalize_answer":
            final = action.final_answer
            if final is None:
                return _agent_fallback_result(
                    question, trace, "missing_final_answer", last_debug_info
                )
            retrieval = _retrieval_from_observations(
                question, observations, final.evidence_chunk_ids
            )
            trace["source_status"] = final.source_status
            return QAAgentResult(
                finalized=True,
                answer_text=final.answer.strip()
                or "The document context did not contain enough information.",
                retrieval=retrieval,
                trace=trace,
                fallback_reason=None,
                debug_info=last_debug_info,
            )

        result = call_qa_agent_tool(registry, action.tool, action.arguments)
        result_dump = result.model_dump(mode="json")
        observations.append(result_dump)
        trace["tool_results"].append(result_dump)
        messages.append(
            {
                "role": "user",
                "content": "Tool result:\n" + json.dumps(result_dump, sort_keys=True),
            }
        )

    return _agent_fallback_result(
        question, trace, "max_steps_exhausted", last_debug_info
    )


def call_qa_agent_tool(
    registry: dict[str, AgentTool],
    tool_name: str,
    arguments: dict[str, Any],
) -> AgentToolResult:
    if tool_name not in QA_ALLOWED_TOOLS:
        return AgentToolResult(
            tool=tool_name,
            ok=False,
            error=f"Tool {tool_name!r} is not allowed for agentic Q&A v1.",
        )
    return call_agent_tool(registry, tool_name, arguments)


def _initial_messages(
    *,
    question: str,
    role: str | None,
    section: str | None,
    limit: int,
    chars: int,
) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a local-PDF research assistant. Use only the provided "
                "tools and the local PDF evidence they return. Choose one tool "
                "call at a time. Search first, inspect promising chunks or pages "
                "when needed, then finalize with a concise answer and citations. "
                "If evidence is insufficient, finalize with source_status "
                "source_missing and say the document context is insufficient."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question: {question}\n"
                f"Default search role: {role or 'all'}\n"
                f"Section filter: {section or 'none'}\n"
                f"Default result limit: {limit}\n"
                f"Context character budget: {chars}\n"
                "Available tools: search_pdf(query, limit, role, section), "
                "inspect_chunk(chunk_id), inspect_page(page_number), "
                "finalize_answer(final_answer)."
            ),
        },
    ]


def _agent_fallback_result(
    question: str,
    trace: dict[str, Any],
    reason: str,
    debug_info: OllamaDebugInfo | None = None,
) -> QAAgentResult:
    trace["fallback_reason"] = reason
    return QAAgentResult(
        finalized=False,
        answer_text="",
        retrieval=RetrievalResult(
            original_question=question,
            queries_tried=[],
            selected_query=None,
            rows=[],
            stopped_reason="agentic_fallback",
        ),
        trace=trace,
        fallback_reason=reason,
        debug_info=debug_info,
    )


def _retrieval_from_observations(
    question: str,
    observations: list[dict[str, Any]],
    evidence_chunk_ids: list[int],
) -> RetrievalResult:
    rows_by_id = _rows_by_id(observations)
    if evidence_chunk_ids:
        rows = [
            rows_by_id[chunk_id]
            for chunk_id in evidence_chunk_ids
            if chunk_id in rows_by_id
        ]
    else:
        rows = list(rows_by_id.values())
    queries = _queries_from_observations(observations)
    return RetrievalResult(
        original_question=question,
        queries_tried=queries,
        selected_query=queries[0] if queries else None,
        rows=rows,
        stopped_reason="agentic_finalized" if rows else "agentic_no_context",
    )


def _rows_by_id(observations: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for observation in observations:
        if not observation.get("ok"):
            continue
        result = observation.get("result")
        if not isinstance(result, dict):
            continue
        for row in result.get("rows") or []:
            if isinstance(row, dict) and row.get("id") is not None:
                rows[int(row["id"])] = row
        chunk = result.get("chunk")
        if isinstance(chunk, dict) and chunk.get("id") is not None:
            rows[int(chunk["id"])] = chunk
    return rows


def _queries_from_observations(observations: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for observation in observations:
        result = observation.get("result")
        if not isinstance(result, dict):
            continue
        query = str(result.get("query") or "").strip()
        if query and query not in queries:
            queries.append(query)
    return queries


def _debug_info_from_response(
    response: object,
    *,
    schema: dict[str, Any],
    num_predict: int,
    num_ctx: int,
) -> OllamaDebugInfo | None:
    summary = getattr(response, "response_summary", None)
    if not isinstance(summary, dict):
        return None
    return OllamaDebugInfo(
        prompt_char_length=0,
        schema_top_level_keys=sorted(str(key) for key in schema.keys()),
        format_kind="json_schema",
        num_predict=num_predict,
        num_ctx=num_ctx,
        response_summary=summary,
    )
