from __future__ import annotations

import pytest
from pydantic import ValidationError

from ethnos.chunking import build_chunks
from ethnos.cli import main
from ethnos.db import (
    connect,
    init_db,
    list_documents,
    save_chunks,
    save_document_pages,
    save_model_output,
    create_extraction_run,
    search_chunks,
    select_chunks_for_structure,
)
from ethnos.models import ChunkRecord, DocumentRecord, ExtractionResult, PageRecord


def test_tiny_text_to_sqlite_and_fts(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)

    document = DocumentRecord(
        source_path="/tmp/tiny.pdf",
        filename="tiny.pdf",
        sha256="abc123",
        title="Tiny",
        page_count=1,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="Ecology\nFood webs describe energy transfer.",
            cleaned_text="Ecology\nFood webs describe energy transfer.",
            char_count=43,
        )
    ]

    document_id = save_document_pages(conn, document, pages)
    stored_document = document.model_copy(update={"id": document_id})
    chunks = build_chunks(stored_document, pages)
    save_chunks(conn, document_id, chunks)

    results = search_chunks(conn, "energy", limit=5)

    assert len(results) == 1
    assert results[0]["source_citation"] == "tiny.pdf p. 1, chunk 1"


def test_list_documents_returns_beginner_visible_fields(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/tiny.pdf",
        filename="tiny.pdf",
        sha256="abcdef1234567890",
        title="Tiny",
        page_count=3,
    )

    save_document_pages(conn, document, [])

    documents = list_documents(conn)

    assert documents == [
        {
            "id": 1,
            "filename": "tiny.pdf",
            "page_count": 3,
            "source_path": "/tmp/tiny.pdf",
            "sha256": "abcdef1234567890",
            "created_at": documents[0]["created_at"],
        }
    ]
    assert documents[0]["created_at"]


def test_documents_cli_lists_stored_documents(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="1234567890abcdef",
        title="Course",
        page_count=12,
    )
    save_document_pages(conn, document, [])

    exit_code = main(["--db", str(db_path), "documents"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "id" in output
    assert "filename" in output
    assert "pages" in output
    assert "course.pdf" in output
    assert "12" in output
    assert "1234567890ab" in output
    assert "/tmp/course.pdf" in output


def test_select_chunks_for_structure_supports_limit_and_skips_valid_outputs(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="structurelimit",
        title="Course",
        page_count=2,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="First chunk text.",
            cleaned_text="First chunk text.",
            char_count=17,
        ),
        PageRecord(
            document_id=0,
            page_number=2,
            raw_text="Second chunk text.",
            cleaned_text="Second chunk text.",
            char_count=18,
        ),
    ]
    document_id = save_document_pages(conn, document, pages)
    stored_document = document.model_copy(update={"id": document_id})
    chunks = build_chunks(stored_document, pages, target_chars=1, max_chars=1000)
    save_chunks(conn, document_id, chunks)

    selected = select_chunks_for_structure(conn, document_id, limit=1)
    assert [chunk.chunk_index for chunk in selected] == [1]

    run_id = create_extraction_run(conn, document_id, "test-model", "test-prompt")
    assert selected[0].id is not None
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=selected[0].id,
        raw_prompt="prompt",
        raw_response='{"chunk_summary": "ok"}',
        parsed_json={"chunk_summary": "ok"},
        validation_status="valid",
        validation_error=None,
    )

    selected = select_chunks_for_structure(conn, document_id, limit=1)
    assert [chunk.chunk_index for chunk in selected] == [2]


def test_select_chunks_for_structure_requires_matching_document_for_chunk_id(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="chunkid",
        title="Course",
        page_count=1,
    )
    document_id = save_document_pages(conn, document, [])
    chunk = build_chunks(
        document.model_copy(update={"id": document_id}),
        [
            PageRecord(
                document_id=document_id,
                page_number=1,
                raw_text="Only chunk text.",
                cleaned_text="Only chunk text.",
                char_count=16,
            )
        ],
    )
    save_chunks(conn, document_id, chunk)
    stored_chunk = select_chunks_for_structure(conn, document_id)[0]

    assert stored_chunk.id is not None
    assert select_chunks_for_structure(conn, document_id, chunk_id=stored_chunk.id)[0].id == stored_chunk.id
    assert select_chunks_for_structure(conn, document_id + 1, chunk_id=stored_chunk.id) == []


def test_save_extraction_result_falls_back_to_chunk_page_range(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=1, page_end=7)
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "A broad ethics overview.",
            "topics": [
                {
                    "name": "Ethics",
                    "summary": "The chunk introduces ethics.",
                    "confidence": 0.8,
                    "source_pages": [],
                }
            ],
            "key_terms": [
                {
                    "term": "Ethics",
                    "definition": "The study of moral questions.",
                    "context": "Introductory course material.",
                    "source_pages": [],
                }
            ],
            "examples": [
                {
                    "title": "Moral dilemma",
                    "body": "A sample ethical choice.",
                    "source_pages": [],
                }
            ],
            "questions": [
                {
                    "question": "What is ethics?",
                    "answer": "The study of moral questions.",
                    "difficulty": "easy",
                    "source_pages": [],
                }
            ],
        }
    )

    from ethnos.db import save_extraction_result

    save_extraction_result(conn, chunk_id, result)

    expected = "[1, 2, 3, 4, 5, 6, 7]"
    assert conn.execute("SELECT source_pages FROM topics").fetchone()["source_pages"] == expected
    assert conn.execute("SELECT source_pages FROM key_terms").fetchone()["source_pages"] == expected
    assert conn.execute("SELECT source_pages FROM examples").fetchone()["source_pages"] == expected
    assert conn.execute("SELECT source_pages FROM questions").fetchone()["source_pages"] == expected


def test_save_extraction_result_falls_back_to_single_page_chunk(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=12, page_end=12)
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "A single-page chunk.",
            "topics": [
                {
                    "name": "Virtue Ethics",
                    "summary": "The chunk discusses virtue ethics.",
                    "confidence": 0.7,
                    "source_pages": [],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [],
        }
    )

    from ethnos.db import save_extraction_result

    save_extraction_result(conn, chunk_id, result)

    assert conn.execute("SELECT source_pages FROM topics").fetchone()["source_pages"] == "[12]"


def test_save_extraction_result_preserves_valid_model_source_pages(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=1, page_end=7)
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "A chunk with model citations.",
            "topics": [
                {
                    "name": "Kantian Ethics",
                    "summary": "The model cited a specific page.",
                    "confidence": 0.9,
                    "source_pages": [3],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [],
        }
    )

    from ethnos.db import save_extraction_result

    save_extraction_result(conn, chunk_id, result)

    assert conn.execute("SELECT source_pages FROM topics").fetchone()["source_pages"] == "[3]"


def test_valid_extraction_rerun_replaces_normalized_rows_for_chunk(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=20, page_end=20)

    from ethnos.db import save_extraction_result

    first = ExtractionResult.model_validate(
        {
            "chunk_summary": "First result.",
            "topics": [
                {
                    "name": "Old Topic",
                    "summary": "Old summary.",
                    "confidence": 0.6,
                    "source_pages": [],
                }
            ],
            "key_terms": [
                {
                    "term": "Old Term",
                    "definition": "Old definition.",
                    "context": "",
                    "source_pages": [],
                }
            ],
            "examples": [],
            "questions": [
                {
                    "question": "Old question?",
                    "answer": "Old answer.",
                    "difficulty": "easy",
                    "source_pages": [],
                }
            ],
        }
    )
    second = ExtractionResult.model_validate(
        {
            "chunk_summary": "Second result.",
            "topics": [
                {
                    "name": "New Topic",
                    "summary": "New summary.",
                    "confidence": 0.9,
                    "source_pages": [],
                }
            ],
            "key_terms": [],
            "examples": [
                {
                    "title": "New Example",
                    "body": "New example body.",
                    "source_pages": [],
                }
            ],
            "questions": [
                {
                    "question": "New question?",
                    "answer": "New answer.",
                    "difficulty": "medium",
                    "source_pages": [],
                }
            ],
        }
    )

    save_extraction_result(conn, chunk_id, first)
    save_extraction_result(conn, chunk_id, second)

    assert conn.execute("SELECT name FROM topics").fetchall()[0]["name"] == "New Topic"
    assert conn.execute("SELECT COUNT(*) AS count FROM key_terms").fetchone()["count"] == 0
    assert conn.execute("SELECT title FROM examples").fetchone()["title"] == "New Example"
    assert conn.execute("SELECT question FROM questions").fetchone()["question"] == "New question?"


def test_failed_validation_does_not_clear_existing_normalized_rows(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=30, page_end=30)

    from ethnos.db import save_extraction_result

    valid = ExtractionResult.model_validate(
        {
            "chunk_summary": "Valid result.",
            "topics": [
                {
                    "name": "Existing Topic",
                    "summary": "Existing summary.",
                    "confidence": 0.8,
                    "source_pages": [],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [
                {
                    "question": "Existing question?",
                    "answer": "Existing answer.",
                    "difficulty": "easy",
                    "source_pages": [],
                }
            ],
        }
    )
    save_extraction_result(conn, chunk_id, valid)

    with pytest.raises(ValidationError):
        ExtractionResult.model_validate(
            {
                "chunk_summary": "Invalid result.",
                "topics": [],
                "key_terms": [],
                "examples": [],
                "questions": [
                    {
                        "question": "Bad question?",
                        "answer": "",
                        "difficulty": "easy",
                        "source_pages": [],
                    }
                ],
            }
        )

    assert conn.execute("SELECT name FROM topics").fetchone()["name"] == "Existing Topic"
    assert conn.execute("SELECT question FROM questions").fetchone()["question"] == "Existing question?"


def test_model_outputs_history_is_preserved_across_normalized_replacement(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=40, page_end=40)
    document_id = conn.execute("SELECT document_id FROM chunks WHERE id = ?", (chunk_id,)).fetchone()[
        "document_id"
    ]
    first_run_id = create_extraction_run(conn, document_id, "test-model", "prompt")
    second_run_id = create_extraction_run(conn, document_id, "test-model", "prompt")
    save_model_output(
        conn,
        run_id=first_run_id,
        chunk_id=chunk_id,
        raw_prompt="first prompt",
        raw_response="first raw response",
        parsed_json={"chunk_summary": "first"},
        validation_status="valid",
        validation_error=None,
    )
    save_model_output(
        conn,
        run_id=second_run_id,
        chunk_id=chunk_id,
        raw_prompt="second prompt",
        raw_response="second raw response",
        parsed_json={"chunk_summary": "second"},
        validation_status="valid",
        validation_error=None,
    )

    from ethnos.db import save_extraction_result

    first = ExtractionResult.model_validate(
        {
            "chunk_summary": "First result.",
            "topics": [
                {
                    "name": "First Topic",
                    "summary": "First summary.",
                    "confidence": 0.7,
                    "source_pages": [],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [],
        }
    )
    second = ExtractionResult.model_validate(
        {
            "chunk_summary": "Second result.",
            "topics": [
                {
                    "name": "Second Topic",
                    "summary": "Second summary.",
                    "confidence": 0.8,
                    "source_pages": [],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [],
        }
    )

    save_extraction_result(conn, chunk_id, first)
    save_extraction_result(conn, chunk_id, second)

    outputs = conn.execute(
        "SELECT raw_response FROM model_outputs WHERE chunk_id = ? ORDER BY id", (chunk_id,)
    ).fetchall()
    assert [row["raw_response"] for row in outputs] == ["first raw response", "second raw response"]
    assert conn.execute("SELECT COUNT(*) AS count FROM extraction_runs").fetchone()["count"] == 2
    assert conn.execute("SELECT name FROM topics").fetchone()["name"] == "Second Topic"


def test_empty_response_is_stored_as_empty_response_and_preserves_rows(tmp_path):
    from ethnos.db import save_extraction_result
    from ethnos.ollama_client import _validate_response

    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=50, page_end=50)
    document_id = conn.execute("SELECT document_id FROM chunks WHERE id = ?", (chunk_id,)).fetchone()[
        "document_id"
    ]
    existing = ExtractionResult.model_validate(
        {
            "chunk_summary": "Existing result.",
            "topics": [
                {
                    "name": "Existing Topic",
                    "summary": "Existing summary.",
                    "confidence": 0.8,
                    "source_pages": [],
                }
            ],
            "key_terms": [],
            "examples": [],
            "questions": [],
        }
    )
    save_extraction_result(conn, chunk_id, existing)

    result = _validate_response("prompt", "")
    run_id = create_extraction_run(conn, document_id, "test-model", "prompt")
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunk_id,
        raw_prompt=result.raw_prompt,
        raw_response=result.raw_response,
        parsed_json=result.parsed_json,
        validation_status=result.validation_status,
        validation_error=result.validation_error,
    )

    output = conn.execute("SELECT * FROM model_outputs").fetchone()
    assert output["validation_status"] == "empty_response"
    assert output["validation_error"] == "Ollama returned an empty response body/content"
    assert output["raw_response"] == ""
    assert conn.execute("SELECT name FROM topics").fetchone()["name"] == "Existing Topic"


def test_whitespace_response_is_empty_response_but_raw_output_is_preserved(tmp_path):
    from ethnos.ollama_client import _validate_response

    result = _validate_response("prompt", "  \n\t  ")

    assert result.validation_status == "empty_response"
    assert result.validation_error == "Ollama returned an empty response body/content"
    assert result.raw_response == "  \n\t  "
    assert result.result is None


def test_non_empty_invalid_json_stays_invalid_json():
    from ethnos.ollama_client import _validate_response

    result = _validate_response("prompt", "not json")

    assert result.validation_status == "invalid_json"
    assert "Expecting value" in result.validation_error
    assert result.raw_response == "not json"
    assert result.result is None


def _stored_chunk(conn, page_start: int, page_end: int) -> int:
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256=f"chunk-{page_start}-{page_end}",
        title="Course",
        page_count=page_end,
    )
    document_id = save_document_pages(conn, document, [])
    save_chunks(
        conn,
        document_id,
        [
            ChunkRecord(
                document_id=document_id,
                page_start=page_start,
                page_end=page_end,
                chunk_index=1,
                text="Chunk text.",
                char_count=11,
                source_citation=f"course.pdf pp. {page_start}-{page_end}, chunk 1",
            )
        ],
    )
    stored_chunk = select_chunks_for_structure(conn, document_id)[0]
    assert stored_chunk.id is not None
    return stored_chunk.id
