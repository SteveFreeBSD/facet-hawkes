"""Small, conservative text cleanup helpers."""

from __future__ import annotations

import re


_SPACES_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def clean_page_text(text: str) -> str:
    """Normalize text without trying to reinterpret the PDF layout."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join(line for line in lines)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned)
    return cleaned.strip()

