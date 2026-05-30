"""Deterministic tool layer used by the agent review loop."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .agent_models import AgentToolResult
from .db import (
    add_continuation_context_chunks,
    chunk_records,
    context_chunks,
    get_document,
    inspect_chunk,
    inspect_page,
    search_chunks,
)
from .qa import RetrievalResult, answer_query_candidates, normalize_answer_role
from .quiz_validation import validate_quiz_item as _validate_quiz_item


COMMON_ANSWER_SPELLING_FIXES = {
    "temperence": "Temperance",
}


class AgentTool(Protocol):
    def __call__(self, arguments: dict[str, Any]) -> AgentToolResult: ...


@dataclass(frozen=True)
class AgentToolContext:
    conn: object
    document_id: int
    quiz_items: dict[str, dict[str, Any]]
    output_dir: Path
    allow_web: bool
    vision_pages: str
    model_name: str
    num_predict: int
    num_ctx: int
    client: object | None = None


def build_agent_tool_registry(context: AgentToolContext) -> dict[str, AgentTool]:
    return {
        "search_pdf": lambda args: _tool_result(
            "search_pdf", _search_pdf(context, args)
        ),
        "inspect_chunk": lambda args: _tool_result(
            "inspect_chunk", _inspect_chunk(context, args)
        ),
        "inspect_page": lambda args: _tool_result(
            "inspect_page", _inspect_page(context, args)
        ),
        "ground_quiz_item": lambda args: _tool_result(
            "ground_quiz_item", _ground_quiz_item(context, args)
        ),
        "compare_options": lambda args: _tool_result(
            "compare_options", _compare_options(context, args)
        ),
        "render_page_image": lambda args: _tool_result(
            "render_page_image", _render_page_image(context, args)
        ),
        "vision_inspect_page": lambda args: _tool_result(
            "vision_inspect_page", _vision_inspect_page(context, args)
        ),
        "web_search": lambda args: _tool_result(
            "web_search", _web_search(context, args)
        ),
        "web_fetch": lambda args: _tool_result("web_fetch", _web_fetch(context, args)),
    }


def call_agent_tool(
    registry: dict[str, AgentTool],
    tool_name: str,
    arguments: dict[str, Any],
) -> AgentToolResult:
    tool = registry.get(tool_name)
    if tool is None:
        return AgentToolResult(
            tool=tool_name,
            ok=False,
            error=f"Unknown agent tool: {tool_name}",
        )
    try:
        return tool(arguments)
    except Exception as exc:
        return AgentToolResult(tool=tool_name, ok=False, error=str(exc))


def _tool_result(tool: str, result: dict[str, Any]) -> AgentToolResult:
    return AgentToolResult(tool=tool, ok=True, result=result)


def _search_pdf(context: AgentToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    query = _required_str(arguments, "query")
    limit = _positive_int(arguments.get("limit"), default=5)
    rows = search_chunks(
        context.conn,
        query,
        limit,
        document_id=context.document_id,
        role=arguments.get("role") or "core",
        section=arguments.get("section"),
        include_text=True,
    )
    return {
        "query": query,
        "rows": [_compact_chunk_row(row, text_chars=900) for row in rows],
    }


def _inspect_chunk(
    context: AgentToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    chunk_id = _required_int(arguments, "chunk_id")
    inspected = inspect_chunk(context.conn, context.document_id, chunk_id)
    records = chunk_records(context.conn, chunk_id)
    chunk = dict(inspected["chunk"])
    chunk["text"] = _clip(str(chunk.get("text") or ""), 1800)
    return {"chunk": chunk, "counts": inspected["counts"], "records": records}


def _inspect_page(
    context: AgentToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    page_number = _required_int(arguments, "page_number")
    page = inspect_page(context.conn, context.document_id, page_number)
    page["raw_text"] = _clip(str(page.get("raw_text") or ""), 1800)
    page["cleaned_text"] = _clip(str(page.get("cleaned_text") or ""), 1800)
    return {"page": page}


def _ground_quiz_item(
    context: AgentToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    item = _quiz_item(context, arguments)
    role = normalize_answer_role(str(arguments.get("role") or "core"))
    section = arguments.get("section")
    limit = _positive_int(arguments.get("limit"), default=5)
    retrieval = _retrieve_quiz_item_context(
        context,
        item,
        limit=limit,
        role=role,
        section=section,
    )
    retrieval_questions = _quiz_item_retrieval_queries(item)
    record = _build_source_grounding_record(
        context.conn,
        document_id=context.document_id,
        item=item,
        context_rows=retrieval.rows,
        retrieval=retrieval,
        retrieval_questions=retrieval_questions,
        chars=_positive_int(arguments.get("chars"), default=500),
    )
    return {
        "grounding": record,
        "context_rows": [
            _compact_chunk_row(row, text_chars=900) for row in retrieval.rows[:limit]
        ],
    }


def _retrieve_quiz_item_context(
    context: AgentToolContext,
    item: dict[str, Any],
    *,
    limit: int,
    role: str | None,
    section: str | None,
) -> RetrievalResult:
    queries = _quiz_item_retrieval_queries(item)
    rows_by_id: dict[int, dict[str, Any]] = {}
    row_queries: dict[int, list[str]] = {}
    tried: list[str] = []
    for query in queries:
        for candidate in answer_query_candidates(query):
            if candidate in tried:
                continue
            tried.append(candidate)
            rows = add_continuation_context_chunks(
                context.conn,
                context.document_id,
                context_chunks(
                    context.conn,
                    context.document_id,
                    candidate,
                    limit=limit,
                    role=role,
                    section=section,
                ),
                role=role,
                section=section,
            )
            for row in rows:
                chunk_id = int(row["id"])
                if chunk_id not in rows_by_id:
                    rows_by_id[chunk_id] = row
                row_queries.setdefault(chunk_id, []).append(candidate)
    ranked_rows = _rank_quiz_context_rows(item, list(rows_by_id.values()), row_queries)
    selected_query = None
    if ranked_rows:
        selected_query = ", ".join(row_queries.get(int(ranked_rows[0]["id"]), [])[:3])
    return RetrievalResult(
        original_question=str(item.get("question") or ""),
        queries_tried=tried,
        selected_query=selected_query,
        rows=ranked_rows[:limit],
        stopped_reason="context_found" if ranked_rows else "no_context",
    )


def _quiz_item_retrieval_queries(item: dict[str, Any]) -> list[str]:
    question = str(item.get("question") or "").strip()
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    keyed_text = options.get(correct) if isinstance(correct, str) else None
    queries: list[str] = []
    _add_query(queries, question)
    if keyed_text:
        _add_query(queries, f"{question} {keyed_text}")
        _add_query(queries, keyed_text)
        for canonical in _canonical_answer_queries(str(keyed_text)):
            _add_query(queries, f"{question} {canonical}")
            _add_query(queries, canonical)
    target = str(item.get("target") or "").strip()
    if target:
        _add_query(queries, f"{question} {target}")
        _add_query(queries, target)
    for value in item.get("retrieval_questions", []):
        _add_query(queries, str(value))
    for label, option_text in options.items():
        if isinstance(correct, str) and label == correct:
            continue
        _add_query(queries, f"{question} {option_text}")
        _add_query(queries, str(option_text))
    return queries


def _rank_quiz_context_rows(
    item: dict[str, Any],
    rows: list[dict[str, Any]],
    row_queries: dict[int, list[str]],
) -> list[dict[str, Any]]:
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    keyed_text = options.get(correct) if isinstance(correct, str) else None
    keyed_terms = _significant_terms(str(keyed_text or ""))
    target_terms = _significant_terms(str(item.get("target") or ""))
    question_terms = _significant_terms(str(item.get("question") or ""))

    def score(row: dict[str, Any]) -> tuple[int, int, int]:
        text = _normalized_search_text(str(row.get("text") or row.get("snippet") or ""))
        keyed_hits = _term_hit_count(keyed_terms, text)
        target_hits = _term_hit_count(target_terms, text)
        question_hits = _term_hit_count(question_terms, text)
        term_hits = keyed_hits * 8 + target_hits * 3 + question_hits
        query_hits = len(row_queries.get(int(row["id"]), []))
        chapter_role = int(str(row.get("content_role") or "") == "core")
        return (term_hits, query_hits, chapter_role)

    return sorted(rows, key=score, reverse=True)


def _add_query(queries: list[str], query: str) -> None:
    compact = " ".join(query.split())
    if compact and compact not in queries:
        queries.append(compact)


def _build_source_grounding_record(
    conn,
    *,
    document_id: int,
    item: dict[str, object],
    context_rows: list[dict[str, object]],
    retrieval,
    retrieval_questions: list[str],
    chars: int,
) -> dict[str, object]:
    warnings = item.get("warnings", [])
    if not isinstance(warnings, list):
        warnings = []
    validation_errors = _validate_quiz_item(
        conn,
        document_id,
        item,
        require_anchors=False,
        strict_complete=False,
        require_key=False,
    )
    source_status = _source_status_for_item(
        item,
        warnings=warnings,
        validation_errors=validation_errors,
        context_rows=context_rows,
    )
    keyed_option = item.get("correct")
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    keyed_option_text = (
        options.get(keyed_option) if isinstance(keyed_option, str) else None
    )
    source_chunks = [row["id"] for row in context_rows]
    source_citations = [str(row["source_citation"]) for row in context_rows]
    return {
        "id": item.get("id"),
        "question": item.get("question"),
        "question_type": item.get("question_type") or "multiple_choice",
        "source_status": source_status,
        "target": item.get("target"),
        "source_chunks": source_chunks,
        "source_pages": item.get("source_pages", []),
        "source_citation": item.get("source_citation"),
        "source_citations": source_citations,
        "selected_query": retrieval.selected_query or "",
        "retrieval_questions": retrieval_questions,
        "queries_tried": retrieval.queries_tried,
        "evidence_summary": _grounding_evidence_summary(
            context_rows,
            str(
                item.get("target")
                or retrieval.selected_query
                or item.get("question")
                or ""
            ),
            chars,
        ),
        "validation_errors": validation_errors,
        "warnings": warnings,
        "keyed_option": keyed_option,
        "keyed_option_text": keyed_option_text,
        "keyed_answer_supported": answer_text_supported_by_rows(
            str(keyed_option_text or ""),
            context_rows,
        ),
        "source_missing_note": item.get("source_missing_note")
        or item.get("external_source_note"),
    }


def _source_status_for_item(
    item: dict[str, object],
    *,
    warnings: list[object],
    validation_errors: list[str],
    context_rows: list[dict[str, object]],
) -> str:
    if "external_source_item" in warnings:
        return "source_missing_in_local_pdf"
    if "incomplete_matching_item" in warnings:
        return "incomplete"
    if validation_errors:
        return "invalid_anchor"
    if item.get("source_chunks") and item.get("source_citation") and context_rows:
        return "pdf_grounded"
    if context_rows:
        return "retrieved_candidate"
    return "ungrounded"


def _grounding_evidence_summary(
    context_rows: list[dict[str, object]],
    target: str,
    chars: int,
) -> str | None:
    if not context_rows:
        return None
    text = " ".join(str(row.get("text") or "") for row in context_rows)
    compact = " ".join(text.split())
    if len(compact) <= chars:
        return compact
    index = compact.lower().find(target.strip().lower()) if target.strip() else -1
    if index < 0:
        return compact[: chars - 3].rstrip() + "..."
    start = max(index - chars // 2, 0)
    end = min(len(compact), start + chars)
    return compact[start:end].strip()


def answer_text_supported_by_rows(text: str, rows: list[dict[str, object]]) -> bool:
    terms = _significant_terms(text)
    if not terms:
        return False
    for row in rows:
        evidence = _normalized_search_text(
            str(row.get("text") or row.get("snippet") or "")
        )
        hits = _term_hit_count(terms, evidence)
        if _term_supports_answer(len(terms), hits):
            return True
    return False


def _canonical_answer_queries(text: str) -> list[str]:
    canonical_terms = _significant_terms(text)
    compact = " ".join(canonical_terms)
    original = " ".join(_tokenize_terms(text))
    if compact and compact != original:
        return [compact]
    return []


def _term_supports_answer(term_count: int, hits: int) -> bool:
    if term_count <= 1:
        return hits == 1
    if term_count <= 3:
        return hits >= term_count - 1
    return hits >= max(3, term_count // 3)


def _compare_options(
    context: AgentToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    item = _quiz_item(context, arguments)
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    return {
        "id": item.get("id"),
        "question": item.get("question"),
        "options": options,
        "keyed_option": correct,
        "keyed_option_text": options.get(correct) if isinstance(correct, str) else None,
        "question_type": item.get("question_type"),
    }


def _render_page_image(
    context: AgentToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    page_number = _required_int(arguments, "page_number")
    document = get_document(context.conn, context.document_id)
    source_path = Path(document.source_path)
    if not source_path.exists():
        return {
            "status": "source_pdf_missing",
            "source_path": str(source_path),
            "page_number": page_number,
        }
    import fitz

    pages_dir = context.output_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    image_path = pages_dir / f"document_{context.document_id}_page_{page_number}.png"
    with fitz.open(source_path) as pdf:
        if page_number < 1 or page_number > pdf.page_count:
            raise ValueError(f"page_number must be between 1 and {pdf.page_count}")
        page = pdf.load_page(page_number - 1)
        pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        pixmap.save(image_path)
    return {
        "status": "rendered",
        "page_number": page_number,
        "image_path": str(image_path),
    }


def _vision_inspect_page(
    context: AgentToolContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    if context.vision_pages == "off":
        return {"status": "blocked", "reason": "vision page inspection is disabled"}
    image_path = arguments.get("image_path")
    if not image_path:
        rendered = _render_page_image(context, arguments)
        image_path = rendered.get("image_path")
    if not image_path:
        return {"status": "unavailable", "reason": "no rendered page image available"}
    if context.client is None:
        return {"status": "unavailable", "reason": "no Ollama client available"}
    from .ollama_client import structured_chat_json

    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "visible_text": {"type": "string"},
            "relevance": {"type": "string"},
        },
        "required": ["summary", "visible_text", "relevance"],
        "additionalProperties": False,
    }
    response = structured_chat_json(
        client=context.client,
        model_name=context.model_name,
        messages=[
            {
                "role": "user",
                "content": str(
                    arguments.get("prompt") or "Inspect this PDF page image."
                ),
            }
        ],
        schema=schema,
        num_predict=context.num_predict,
        num_ctx=context.num_ctx,
        images=[str(image_path)],
    )
    return {
        "status": response.validation_status,
        "image_path": str(image_path),
        "vision": response.parsed_json or {},
        "error": response.validation_error,
    }


def _web_search(context: AgentToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if not context.allow_web:
        return {"status": "blocked", "reason": "web search requires --allow-web"}
    from ollama import web_search

    return _plain_tool_payload(web_search(**arguments))


def _web_fetch(context: AgentToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    if not context.allow_web:
        return {"status": "blocked", "reason": "web fetch requires --allow-web"}
    from ollama import web_fetch

    return _plain_tool_payload(web_fetch(**arguments))


def _quiz_item(context: AgentToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    item_id = _required_str(arguments, "item_id")
    try:
        return context.quiz_items[item_id]
    except KeyError as exc:
        raise ValueError(f"Unknown quiz item id: {item_id}") from exc


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _required_int(arguments: dict[str, Any], key: str) -> int:
    value = arguments.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


def _positive_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _compact_chunk_row(row: dict[str, Any], *, text_chars: int) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "document_id": row.get("document_id"),
        "chunk_index": row.get("chunk_index"),
        "page_start": row.get("page_start"),
        "page_end": row.get("page_end"),
        "source_citation": row.get("source_citation"),
        "section_label": row.get("section_label"),
        "content_role": row.get("content_role"),
        "snippet": row.get("snippet"),
        "text": _clip(str(row.get("text") or ""), text_chars),
    }


def _clip(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _significant_terms(text: str) -> list[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "as",
        "by",
        "could",
        "for",
        "in",
        "into",
        "of",
        "or",
        "the",
        "to",
        "was",
        "were",
        "with",
    }
    terms = []
    for term in _tokenize_terms(text):
        for canonical in _canonical_term_variants(term):
            if (
                len(canonical) >= 4
                and canonical not in stopwords
                and canonical not in terms
            ):
                terms.append(canonical)
    return terms


def _tokenize_terms(text: str) -> list[str]:
    normalized = _normalized_search_text(text)
    terms = []
    for raw in normalized.split():
        term = "".join(ch for ch in raw if ch.isalnum())
        if term and term not in terms:
            terms.append(term)
    return terms


def _canonical_term_variants(term: str) -> list[str]:
    canonical = COMMON_ANSWER_SPELLING_FIXES.get(term, term).lower()
    variants = [canonical]
    if canonical.endswith("ies") and len(canonical) > 5:
        variants.append(canonical[:-3] + "y")
    if canonical.endswith("s") and len(canonical) > 4:
        variants.append(canonical[:-1])
    return variants


def _normalized_search_text(text: str) -> str:
    return (
        text.lower()
        .replace("-\n", "")
        .replace("- ", "")
        .replace("&", " ")
        .replace("/", " ")
    )


def _term_hit_count(terms: list[str], text: str) -> int:
    return sum(1 for term in terms if term in text)


def _plain_tool_payload(value: object) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        if isinstance(dumped, dict):
            return dumped
    if isinstance(value, dict):
        return value
    try:
        return json.loads(json.dumps(value))
    except (TypeError, ValueError):
        return {"value": str(value)}
