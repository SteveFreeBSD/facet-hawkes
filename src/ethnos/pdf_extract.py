"""PDF extraction using PyMuPDF."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .clean_text import clean_page_text
from .models import DocumentRecord, PageRecord


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract_pdf(path: Path) -> tuple[DocumentRecord, list[PageRecord]]:
    """Extract raw and cleaned text from every PDF page."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required. Install dependencies with `uv sync`.") from exc

    path = path.expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Expected a PDF file, got: {path}")

    sha256 = file_sha256(path)

    with fitz.open(path) as pdf:
        page_count = pdf.page_count
        metadata = dict(pdf.metadata or {})
        title = metadata.get("title") or path.stem
        document = DocumentRecord(
            source_path=str(path),
            filename=path.name,
            sha256=sha256,
            title=title,
            page_count=page_count,
            metadata=metadata,
        )
        pages = []
        for index, page in enumerate(pdf, start=1):
            raw_text = page.get_text(sort=True)
            cleaned_text = clean_page_text(raw_text)
            pages.append(
                PageRecord(
                    document_id=0,
                    page_number=index,
                    raw_text=raw_text,
                    cleaned_text=cleaned_text,
                    char_count=len(cleaned_text),
                )
            )

    return document, pages

