"""Shared text normalization helpers."""

from __future__ import annotations

import re
import unicodedata


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


def normalized_match_variants(text: object) -> tuple[str, ...]:
    """Return Unicode-folded variants for PDF text and ordinary hyphenation."""
    normalized = unicodedata.normalize("NFKD", str(text)).casefold()
    normalized = "".join(
        "-"
        if unicodedata.category(char) == "Pd"
        else ""
        if unicodedata.category(char) in {"Cf", "Mn"}
        else char
        for char in normalized
    )
    joined_wraps = re.sub(r"(?<=\w)-\s+(?=\w)", "", normalized)
    spaced_wraps = re.sub(r"(?<=\w)-\s+(?=\w)", " ", normalized)
    variants = []
    for candidate in (joined_wraps, spaced_wraps):
        for hyphen_replacement in (" ", ""):
            comparable = candidate.replace("-", hyphen_replacement)
            comparable = " ".join(
                re.sub(r"[^\w]+", " ", comparable).replace("_", " ").split()
            )
            if comparable and comparable not in variants:
                variants.append(comparable)
    return tuple(variants)


def normalize_match_text(text: object) -> str:
    variants = normalized_match_variants(text)
    return variants[0] if variants else ""


def normalized_phrase_found(phrase: object, text: object) -> bool:
    phrase_variants = normalized_match_variants(phrase)
    text_variants = normalized_match_variants(text)
    return any(
        f" {needle} " in f" {haystack} "
        for needle in phrase_variants
        for haystack in text_variants
    )


def normalized_phrase_index(text: object, phrase: object) -> int:
    """Return an approximate original-text index for a normalized phrase."""
    original = str(text)
    if not original or not normalize_match_text(phrase):
        return -1
    best: tuple[float, int] | None = None
    for needle in normalized_match_variants(phrase):
        pattern = re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)")
        for haystack in normalized_match_variants(original):
            match = pattern.search(haystack)
            if match is None:
                continue
            ratio = match.start() / max(len(haystack), 1)
            candidate = (ratio, round(ratio * len(original)))
            if best is None or candidate < best:
                best = candidate
    return best[1] if best is not None else -1


def compact_text(text: object, max_chars: int) -> str:
    """Collapse whitespace and truncate with an ellipsis when needed."""

    compact = " ".join(str(text).split())
    if len(compact) <= max_chars:
        return compact
    if max_chars <= 3:
        return "." * max(0, max_chars)
    return compact[: max_chars - 3].rstrip() + "..."
