from __future__ import annotations

import pytest

from ethnos.pdf_extract import extract_pdf


fitz = pytest.importorskip("fitz")


def test_extract_pdf_preserves_pages_and_text(tmp_path):
    pdf_path = tmp_path / "tiny.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Biology 101\nCells convert energy.")
    doc.save(pdf_path)
    doc.close()

    document, pages = extract_pdf(pdf_path)

    assert document.filename == "tiny.pdf"
    assert document.page_count == 1
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Cells convert energy" in pages[0].cleaned_text
