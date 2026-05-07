"""Question-answering prompt helpers for retrieved PDF context."""

from __future__ import annotations

from pathlib import Path
import re


DEFAULT_ANSWER_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "answer.md"
QUESTION_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "about",
    "can",
    "define",
    "describe",
    "does",
    "explain",
    "for",
    "from",
    "give",
    "how",
    "idea",
    "ideas",
    "in",
    "is",
    "main",
    "me",
    "of",
    "on",
    "the",
    "tell",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
}


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
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", question.lower())
        if len(token) > 1 and token not in QUESTION_STOPWORDS
    ]
    return " ".join(tokens) if tokens else question


def _preview_text(text: str, max_chars: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
