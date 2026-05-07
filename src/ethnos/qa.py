"""Question-answering prompt helpers for retrieved PDF context."""

from __future__ import annotations

import json
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_ANSWER_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "answer.md"
QUESTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "book",
    "can",
    "define",
    "describe",
    "did",
    "do",
    "does",
    "explain",
    "for",
    "from",
    "give",
    "handle",
    "how",
    "idea",
    "ideas",
    "in",
    "is",
    "main",
    "me",
    "of",
    "on",
    "say",
    "the",
    "tell",
    "to",
    "used",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
}
WEAKER_FALLBACK_TERMS = {
    "approach",
    "case",
    "cases",
    "concept",
    "concepts",
    "problem",
    "problems",
    "theory",
}


@dataclass(frozen=True)
class RetrievalResult:
    original_question: str
    queries_tried: list[str]
    selected_query: str | None
    rows: list[dict[str, Any]]
    stopped_reason: str


@dataclass(frozen=True)
class AnswerEvaluation:
    status: str
    missing_expected_terms: list[str]
    forbidden_terms_found: list[str]
    citation_hit: bool | None
    expected_citations: list[str]


def build_answer_context(rows: list[dict], max_chars: int) -> str:
    parts = []
    for row in rows:
        text = _preview_text(row["text"], max_chars)
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


def build_answer_prompt(
    question: str,
    context_rows: list[dict],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_ANSWER_PROMPT,
) -> str:
    template = prompt_path.read_text(encoding="utf-8")
    context = build_answer_context(context_rows, max_chars)
    return template.format(question=question, context=context)


def normalize_answer_role(role: str) -> str | None:
    return None if role == "all" else role


def question_to_fts_query(question: str) -> str:
    return answer_query_candidates(question)[0]


def answer_query_candidates(question: str) -> list[str]:
    tokens = _content_tokens(question)
    candidates: list[str] = []
    _add_candidate(candidates, tokens)

    expanded = _expand_domain_phrases(tokens)
    if expanded != tokens:
        _add_candidate(candidates, expanded)

    dropped_weaker = [token for token in tokens if token not in WEAKER_FALLBACK_TERMS]
    if dropped_weaker != tokens:
        _add_candidate(candidates, dropped_weaker)

    expanded_dropped_weaker = [
        token for token in expanded if token not in WEAKER_FALLBACK_TERMS
    ]
    if expanded_dropped_weaker != expanded:
        _add_candidate(candidates, expanded_dropped_weaker)

    _add_candidate(candidates, _strong_domain_tokens(tokens))

    if not candidates:
        candidates.append(question)
    return candidates[:5]


def load_qa_benchmark(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("QA benchmark must be a JSON list")
    for item in data:
        if not isinstance(item, dict) or "id" not in item or "question" not in item:
            raise ValueError("Each benchmark item must include id and question")
    return data


def benchmark_hit(item: dict[str, Any], rows: list[dict[str, Any]]) -> bool:
    expected_chunks = item.get("expected_source_chunks")
    expected_pages = item.get("expected_source_pages")
    if expected_chunks == [] or expected_pages == []:
        return not rows
    if expected_chunks:
        expected = {int(value) for value in expected_chunks}
        for row in rows:
            if int(row["id"]) in expected or int(row["chunk_index"]) in expected:
                return True
    if expected_pages:
        expected = {int(value) for value in expected_pages}
        for row in rows:
            pages = set(range(int(row["page_start"]), int(row["page_end"]) + 1))
            if pages & expected:
                return True
    return False


def evaluate_answer_quality(
    item: dict[str, Any], answer_text: str, rows: list[dict[str, Any]]
) -> AnswerEvaluation:
    if _expects_no_context(item):
        status = "no_context_expected" if not rows else "fail"
        return AnswerEvaluation(
            status=status,
            missing_expected_terms=[],
            forbidden_terms_found=[],
            citation_hit=None,
            expected_citations=[],
        )
    if not rows:
        return AnswerEvaluation(
            status="no_context_unexpected",
            missing_expected_terms=list(item.get("expected_answer_terms", [])),
            forbidden_terms_found=[],
            citation_hit=False,
            expected_citations=[],
        )

    answer_lower = answer_text.lower()
    expected_terms = list(item.get("expected_answer_terms", []))
    missing_terms = [term for term in expected_terms if term.lower() not in answer_lower]
    forbidden_terms = [
        term for term in item.get("forbidden_terms", []) if term.lower() in answer_lower
    ]
    expected_citations = expected_answer_citations(item)
    citation_hit = None
    if expected_citations:
        citation_hit = any(citation.lower() in answer_lower for citation in expected_citations)

    if forbidden_terms:
        status = "fail"
    else:
        checks = len(expected_terms) + (1 if citation_hit is not None else 0)
        passed = (len(expected_terms) - len(missing_terms)) + int(citation_hit is True)
        if checks == 0:
            status = "pass" if answer_text.strip() else "fail"
        elif passed == checks:
            status = "pass"
        elif passed > 0:
            status = "partial"
        else:
            status = "fail"

    return AnswerEvaluation(
        status=status,
        missing_expected_terms=missing_terms,
        forbidden_terms_found=forbidden_terms,
        citation_hit=citation_hit,
        expected_citations=expected_citations,
    )


def expected_answer_citations(item: dict[str, Any]) -> list[str]:
    citations = []
    for chunk in item.get("expected_citation_chunks", []):
        citations.append(f"chunk {int(chunk)}")
    for page in item.get("expected_citation_pages", []):
        page = int(page)
        citations.append(f"p. {page}")
        citations.append(f"pp. {page}")
    return citations


def _expects_no_context(item: dict[str, Any]) -> bool:
    return item.get("expected_source_chunks") == [] or item.get("expected_source_pages") == []


def _content_tokens(question: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9]+", question.lower())
        if len(token) > 1 and token not in QUESTION_STOPWORDS
    ]


def _expand_domain_phrases(tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    token_set = set(tokens)
    if "trolley" in token_set and "cases" in token_set and "problem" not in token_set:
        expanded = ["problem" if token == "cases" else token for token in expanded]
    return expanded


def _strong_domain_tokens(tokens: list[str]) -> list[str]:
    return [token for token in tokens if token not in WEAKER_FALLBACK_TERMS]


def _add_candidate(candidates: list[str], tokens: list[str]) -> None:
    if not tokens:
        return
    query = " ".join(tokens)
    if query and query not in candidates:
        candidates.append(query)


def retrieve_with_fallbacks(
    *,
    search_func,
    document_id: int,
    question: str,
    limit: int,
    role: str | None,
    section: str | None,
) -> RetrievalResult:
    queries = answer_query_candidates(question)
    tried: list[str] = []
    for query in queries:
        tried.append(query)
        rows = search_func(
            document_id,
            query,
            limit=limit,
            role=role,
            section=section,
        )
        if rows:
            return RetrievalResult(
                original_question=question,
                queries_tried=tried,
                selected_query=query,
                rows=rows,
                stopped_reason="context_found",
            )
    return RetrievalResult(
        original_question=question,
        queries_tried=tried,
        selected_query=None,
        rows=[],
        stopped_reason="no_context",
    )


def _preview_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
