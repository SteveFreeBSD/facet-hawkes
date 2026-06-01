"""Shared text normalization helpers."""

from __future__ import annotations


CORE_STOPWORDS = frozenset(
    {
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
)

QUESTION_STOPWORDS = CORE_STOPWORDS | frozenset(
    {
        "about",
        "are",
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
        "from",
        "give",
        "handle",
        "how",
        "idea",
        "ideas",
        "is",
        "it",
        "main",
        "matches",
        "mean",
        "means",
        "me",
        "on",
        "say",
        "text",
        "that",
        "they",
        "this",
        "those",
        "tell",
        "used",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)

ANSWER_TOKEN_STOPWORDS = frozenset(
    {
        "and",
        "are",
        "because",
        "that",
        "the",
        "their",
        "this",
        "with",
    }
)

GUIDANCE_STOPWORDS = frozenset(
    {
        "about",
        "above",
        "also",
        "being",
        "both",
        "from",
        "into",
        "that",
        "their",
        "there",
        "these",
        "this",
        "through",
        "under",
        "with",
    }
)


def compact_text(text: object, max_chars: int) -> str:
    """Collapse whitespace and truncate with an ellipsis when needed."""

    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    if max_chars <= 3:
        return "." * max(0, max_chars)
    return compact[: max_chars - 3].rstrip() + "..."
