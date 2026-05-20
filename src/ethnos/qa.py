"""Question-answering prompt helpers for retrieved PDF context."""

from __future__ import annotations

import json
from pathlib import Path
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any


DEFAULT_ANSWER_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "answer.md"
QUESTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "best",
    "book",
    "can",
    "define",
    "definition",
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
    "it",
    "main",
    "matches",
    "mean",
    "means",
    "me",
    "of",
    "on",
    "say",
    "the",
    "that",
    "text",
    "they",
    "this",
    "those",
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
class SubqueryRetrievalResult:
    subquery: str
    queries_tried: list[str]
    selected_query: str | None
    rows: list[dict[str, Any]]
    stopped_reason: str


@dataclass(frozen=True)
class RetrievalResult:
    original_question: str
    queries_tried: list[str]
    selected_query: str | None
    rows: list[dict[str, Any]]
    stopped_reason: str
    comparison_detected: bool = False
    comparison_subqueries: list[str] = field(default_factory=list)
    subquery_results: list[SubqueryRetrievalResult] = field(default_factory=list)


@dataclass(frozen=True)
class AnswerEvaluation:
    status: str
    missing_expected_terms: list[str]
    forbidden_terms_found: list[str]
    citation_hit: bool | None
    expected_citations: list[str]


@dataclass(frozen=True)
class FollowUpResolution:
    detected: bool
    previous_question: str | None
    previous_topic: str | None
    rewritten_question: str | None


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
    template = _prompt_template(prompt_path)
    context = build_answer_context(context_rows, max_chars)
    return template.format(question=question, context=context)


@lru_cache(maxsize=16)
def _prompt_template(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8")


def normalize_answer_role(role: str) -> str | None:
    return None if role == "all" else role


def question_to_fts_query(question: str) -> str:
    return answer_query_candidates(question)[0]


def detect_comparison_question(question: str) -> bool:
    return bool(extract_comparison_subqueries(question))


def extract_comparison_subqueries(question: str) -> list[str]:
    normalized = _normalize_question_text(question)
    patterns = [
        r"^compare\s+(.+?)\s+(?:and|with)\s+(.+)$",
        r"^compare\s+(.+?)\s+to\s+(.+)$",
        r"^what\s+is\s+the\s+difference\s+between\s+(.+?)\s+and\s+(.+)$",
        r"^difference\s+between\s+(.+?)\s+and\s+(.+)$",
        r"^how\s+is\s+(.+?)\s+different\s+from\s+(.+)$",
        r"^how\s+does\s+(.+?)\s+differ\s+from\s+(.+)$",
        r"^how\s+do\s+(.+?)\s+differ\s+from\s+(.+)$",
        r"^how\s+are\s+(.+?)\s+and\s+(.+?)\s+different$",
        r"^how\s+does\s+(.+?)\s+compare\s+to\s+(.+)$",
        r"^how\s+do\s+(.+?)\s+compare\s+to\s+(.+)$",
        r"^(.+?)\s+vs\.?\s+(.+)$",
        r"^(.+?)\s+versus\s+(.+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, normalized)
        if match:
            return _clean_comparison_parts(match.group(1), match.group(2))
    return []


def detect_chat_followup(question: str) -> bool:
    normalized = _normalize_question_text(question)
    return bool(
        re.search(r"\b(that|this|it|they|those)\b", normalized)
        or "the first one" in normalized
        or "the second one" in normalized
    )


def resolve_chat_followup(
    question: str,
    *,
    previous_question: str | None,
    previous_retrieval: RetrievalResult | None,
) -> FollowUpResolution:
    detected = detect_chat_followup(question)
    if not detected:
        return FollowUpResolution(
            detected=False,
            previous_question=previous_question,
            previous_topic=None,
            rewritten_question=None,
        )
    previous_topic = _previous_topic_for_followup(question, previous_retrieval)
    if previous_topic is None:
        return FollowUpResolution(
            detected=True,
            previous_question=previous_question,
            previous_topic=None,
            rewritten_question=None,
        )
    rewritten = _rewrite_followup_question(question, previous_topic)
    return FollowUpResolution(
        detected=True,
        previous_question=previous_question,
        previous_topic=previous_topic,
        rewritten_question=rewritten if rewritten != question else None,
    )


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
    _add_focused_token_candidates(candidates, tokens)

    if not candidates:
        candidates.append(question)
    return candidates[:12]


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
    expected_any_groups = _normalize_expected_any_terms(item)
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
        missing_expected = list(item.get("expected_answer_terms", []))
        missing_expected.extend(
            _format_any_group(group) for group in expected_any_groups
        )
        return AnswerEvaluation(
            status="no_context_unexpected",
            missing_expected_terms=missing_expected,
            forbidden_terms_found=[],
            citation_hit=False,
            expected_citations=[],
        )

    answer_lower = answer_text.lower()
    expected_terms = list(item.get("expected_answer_terms", []))
    missing_terms = [term for term in expected_terms if term.lower() not in answer_lower]
    missing_any_groups = [
        group
        for group in expected_any_groups
        if not any(term.lower() in answer_lower for term in group)
    ]
    missing_expected_terms = missing_terms + [
        _format_any_group(group) for group in missing_any_groups
    ]
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
        checks = len(expected_terms) + len(expected_any_groups) + (
            1 if citation_hit is not None else 0
        )
        passed = (
            (len(expected_terms) - len(missing_terms))
            + (len(expected_any_groups) - len(missing_any_groups))
            + int(citation_hit is True)
        )
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
        missing_expected_terms=missing_expected_terms,
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


def _normalize_expected_any_terms(item: dict[str, Any]) -> list[list[str]]:
    groups = []
    for group in item.get("expected_any_terms", []):
        if isinstance(group, (list, tuple, set)):
            terms = [str(term).strip() for term in group if str(term).strip()]
        else:
            term = str(group).strip()
            terms = [term] if term else []
        if terms:
            groups.append(terms)
    return groups


def _format_any_group(group: list[str]) -> str:
    return "any of: " + " | ".join(group)


def summarize_answer_items(items: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "answer_pass": 0,
        "answer_partial": 0,
        "answer_fail": 0,
        "no_context_expected": 0,
        "no_context_unexpected": 0,
        "model_error": 0,
    }
    answer_times = []
    answer_lengths = []
    retrieval_hits = 0
    retrieval_misses = 0
    no_context_cases = 0
    for item in items:
        retrieval_hits += int(item.get("hit") is True)
        retrieval_misses += int(item.get("hit") is False)
        no_context_cases += int(not item.get("selected_chunks"))
        evaluation = item.get("answer_evaluation") or {}
        status = evaluation.get("status")
        if status == "pass":
            counts["answer_pass"] += 1
        elif status == "partial":
            counts["answer_partial"] += 1
        elif status == "fail":
            counts["answer_fail"] += 1
        elif status == "no_context_expected":
            counts["no_context_expected"] += 1
        elif status == "no_context_unexpected":
            counts["no_context_unexpected"] += 1
        elif status == "model_error":
            counts["model_error"] += 1
        answer_seconds = (item.get("timings") or {}).get("answer_seconds")
        if answer_seconds is not None:
            answer_times.append(float(answer_seconds))
        answer_text = item.get("answer_text")
        if answer_text:
            answer_lengths.append(len(answer_text))
    return {
        "total": len(items),
        "retrieval_hits": retrieval_hits,
        "retrieval_misses": retrieval_misses,
        "no_context_cases": no_context_cases,
        **counts,
        "average_answer_seconds": (
            sum(answer_times) / len(answer_times) if answer_times else None
        ),
        "average_answer_length": (
            sum(answer_lengths) / len(answer_lengths) if answer_lengths else None
        ),
    }


def rank_model_summaries(model_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [summary for summary in model_summaries if summary.get("model_error", 0) == 0]
    if not model_summaries:
        return {"best_pass_count": [], "lowest_fail_count": [], "fastest_no_fail": None}
    best_pass = max(summary.get("answer_pass", 0) for summary in model_summaries)
    lowest_fail = min(summary.get("answer_fail", 0) for summary in model_summaries)
    no_failure = [
        summary
        for summary in usable
        if summary.get("answer_fail", 0) == 0
        and summary.get("no_context_unexpected", 0) == 0
    ]
    fastest = None
    if no_failure:
        fastest = min(no_failure, key=lambda summary: summary.get("total_elapsed_seconds", 0))
    return {
        "best_pass_count": [
            summary["model"]
            for summary in model_summaries
            if summary.get("answer_pass", 0) == best_pass
        ],
        "lowest_fail_count": [
            summary["model"]
            for summary in model_summaries
            if summary.get("answer_fail", 0) == lowest_fail
        ],
        "fastest_no_fail": fastest["model"] if fastest else None,
    }


def _expects_no_context(item: dict[str, Any]) -> bool:
    return item.get("expected_source_chunks") == [] or item.get("expected_source_pages") == []


def _content_tokens(question: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[A-Za-z0-9]+", question.lower())
        if len(token) > 1 and token not in QUESTION_STOPWORDS
    ]


def _normalize_question_text(question: str) -> str:
    normalized = question.lower().strip()
    normalized = re.sub(r"[?!.]+$", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _clean_comparison_parts(left: str, right: str) -> list[str]:
    cleaned = []
    for part in (left, right):
        part = re.sub(r"^(?:the|a|an)\s+", "", part.strip())
        part = re.sub(r"\s+", " ", part)
        tokens = _content_tokens(part)
        if not tokens:
            continue
        query_tokens = _strong_domain_tokens(tokens) or tokens
        query = " ".join(query_tokens)
        if query and query not in cleaned:
            cleaned.append(query)
    return cleaned if len(cleaned) >= 2 else []


def _previous_topic_for_followup(
    question: str, previous_retrieval: RetrievalResult | None
) -> str | None:
    if previous_retrieval is None:
        return None
    normalized = _normalize_question_text(question)
    if "the first one" in normalized and previous_retrieval.comparison_subqueries:
        return previous_retrieval.comparison_subqueries[0]
    if (
        "the second one" in normalized
        and len(previous_retrieval.comparison_subqueries) >= 2
    ):
        return previous_retrieval.comparison_subqueries[1]
    if previous_retrieval.comparison_subqueries:
        return " and ".join(previous_retrieval.comparison_subqueries)
    if previous_retrieval.selected_query:
        return previous_retrieval.selected_query.split(" | ", 1)[0]
    if previous_retrieval.queries_tried:
        return previous_retrieval.queries_tried[0]
    return None


def _rewrite_followup_question(question: str, previous_topic: str) -> str:
    rewritten = re.sub(
        r"\bthe first one\b",
        previous_topic,
        question,
        count=1,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"\bthe second one\b",
        previous_topic,
        rewritten,
        count=1,
        flags=re.IGNORECASE,
    )
    rewritten = re.sub(
        r"\b(that|this|it|they|those)\b",
        previous_topic,
        rewritten,
        count=1,
        flags=re.IGNORECASE,
    )
    return rewritten


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


def _add_focused_token_candidates(candidates: list[str], tokens: list[str]) -> None:
    strong_tokens = _strong_domain_tokens(tokens)
    if len(strong_tokens) < 3:
        return
    for size in (2, 3):
        for index in range(0, len(strong_tokens) - size + 1):
            _add_candidate(candidates, strong_tokens[index : index + size])


def retrieve_with_fallbacks(
    *,
    search_func,
    document_id: int,
    question: str,
    limit: int,
    role: str | None,
    section: str | None,
) -> RetrievalResult:
    comparison_subqueries = extract_comparison_subqueries(question)
    if comparison_subqueries:
        return _retrieve_comparison_with_fallbacks(
            search_func=search_func,
            document_id=document_id,
            question=question,
            subqueries=comparison_subqueries,
            limit=limit,
            role=role,
            section=section,
        )

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


def _retrieve_comparison_with_fallbacks(
    *,
    search_func,
    document_id: int,
    question: str,
    subqueries: list[str],
    limit: int,
    role: str | None,
    section: str | None,
) -> RetrievalResult:
    subquery_results = []
    merged_rows = []
    seen_chunk_ids = set()
    all_queries_tried = []
    selected_queries = []

    for subquery in subqueries:
        result = _retrieve_single_with_fallbacks(
            search_func=search_func,
            document_id=document_id,
            question=subquery,
            limit=limit,
            role=role,
            section=section,
        )
        subquery_results.append(
            SubqueryRetrievalResult(
                subquery=subquery,
                queries_tried=result.queries_tried,
                selected_query=result.selected_query,
                rows=result.rows,
                stopped_reason=result.stopped_reason,
            )
        )
        all_queries_tried.extend(result.queries_tried)
        if result.selected_query:
            selected_queries.append(result.selected_query)
        for row in result.rows:
            chunk_id = row["id"]
            if chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk_id)
            merged_rows.append(row)

    return RetrievalResult(
        original_question=question,
        queries_tried=all_queries_tried,
        selected_query=" | ".join(selected_queries) if selected_queries else None,
        rows=merged_rows,
        stopped_reason="context_found" if merged_rows else "no_context",
        comparison_detected=True,
        comparison_subqueries=subqueries,
        subquery_results=subquery_results,
    )


def _retrieve_single_with_fallbacks(
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
