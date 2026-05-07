from __future__ import annotations

import pytest
from pydantic import ValidationError

from ethnos.chunking import build_chunks
from ethnos.cli import main
from ethnos.db import (
    apply_section_preset,
    connect,
    init_db,
    list_documents,
    save_chunks,
    save_document_pages,
    save_extraction_result,
    save_model_output,
    create_extraction_run,
    chunk_records,
    context_chunks,
    inspect_chunk,
    list_structured_records,
    quality_report,
    search_chunks,
    section_label_status,
    select_chunks_for_structure,
    structure_status,
)
from ethnos.models import ChunkRecord, DocumentRecord, ExtractionResult, PageRecord
from ethnos.export import export_study
from ethnos.ollama_client import AnswerCallResult
from ethnos.qa import build_answer_prompt, normalize_answer_role, question_to_fts_query
from ethnos.section_presets import get_section_preset


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


def test_section_label_columns_exist_after_db_init(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)

    page_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pages)")}
    chunk_columns = {row["name"] for row in conn.execute("PRAGMA table_info(chunks)")}

    assert {"section_label", "content_role"}.issubset(page_columns)
    assert {"section_label", "content_role", "section_confidence"}.issubset(chunk_columns)


def test_section_label_dry_run_does_not_write_labels(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_three_page_document(conn)

    summary = apply_section_preset(conn, document_id, get_section_preset("ethics"), dry_run=True)

    assert summary["pages"] == [
        {"section_label": "front_matter", "content_role": "admin", "count": 3}
    ]
    assert summary["chunks"] == [
        {"section_label": "front_matter", "content_role": "admin", "count": 3}
    ]
    assert conn.execute("SELECT COUNT(*) AS count FROM pages WHERE section_label IS NOT NULL").fetchone()[
        "count"
    ] == 0
    assert conn.execute("SELECT COUNT(*) AS count FROM chunks WHERE section_label IS NOT NULL").fetchone()[
        "count"
    ] == 0


def test_label_sections_applies_expected_labels(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_three_page_document(conn)

    apply_section_preset(conn, document_id, get_section_preset("ethics"))

    page = conn.execute(
        "SELECT section_label, content_role FROM pages WHERE page_number = 1"
    ).fetchone()
    chunk = conn.execute(
        """
        SELECT section_label, content_role, section_confidence
        FROM chunks
        WHERE chunk_index = 1
        """
    ).fetchone()
    assert dict(page) == {"section_label": "front_matter", "content_role": "admin"}
    assert chunk["section_label"] == "front_matter"
    assert chunk["content_role"] == "admin"
    assert chunk["section_confidence"] == 1.0


def test_section_status_helper_counts_labels(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_three_page_document(conn)
    apply_section_preset(conn, document_id, get_section_preset("ethics"))

    status = section_label_status(conn, document_id)

    assert status["pages"] == [
        {"section_label": "front_matter", "content_role": "admin", "count": 3}
    ]
    assert status["chunks"] == [
        {"section_label": "front_matter", "content_role": "admin", "count": 3}
    ]
    assert status["unlabeled_pages"] == 0
    assert status["unlabeled_chunks"] == 0


def test_label_sections_cli_dry_run_does_not_write_labels(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    _stored_three_page_document(conn)

    exit_code = main(
        ["--db", str(db_path), "label-sections", "1", "--preset", "ethics", "--dry-run"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Section label dry run for document 1 using preset ethics" in output
    assert "front_matter / admin: 3" in output
    assert conn.execute("SELECT COUNT(*) AS count FROM pages WHERE section_label IS NOT NULL").fetchone()[
        "count"
    ] == 0


def test_inspect_chunk_helper_and_cli_output(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)

    inspection = inspect_chunk(conn, document_id, chunks[0].id)
    records = chunk_records(conn, chunks[0].id)

    assert inspection["chunk"]["section_label"] == "chapter_content"
    assert inspection["counts"]["key_terms"] == 1
    assert inspection["counts"]["questions"] == 1
    assert records["key_terms"][0]["term"] == "Evolutionary ethics"

    exit_code = main(["--db", str(db_path), "inspect-chunk", str(document_id), str(chunks[0].id), "--records"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Document: labeled.pdf" in output
    assert f"Chunk id: {chunks[0].id}" in output
    assert "Section: chapter_content" in output
    assert "term: Evolutionary ethics" in output
    assert "question: What does evolutionary ethics study?" in output


def test_search_chunks_filters_by_role_and_section(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    core_results = search_chunks(conn, "evolutionary", document_id=document_id, role="core")
    admin_results = search_chunks(conn, "evolutionary", document_id=document_id, role="admin")
    section_results = search_chunks(
        conn,
        "evolutionary",
        document_id=document_id,
        section="chapter_content",
    )

    assert [row["content_role"] for row in core_results] == ["core"]
    assert [row["section_label"] for row in admin_results] == ["front_matter"]
    assert [row["section_label"] for row in section_results] == ["chapter_content"]


def test_records_filter_by_type_role_section_and_chunk_id(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)

    core_terms = list_structured_records(
        conn, document_id, record_type="key_terms", role="core"
    )
    chapter_questions = list_structured_records(
        conn, document_id, record_type="questions", section="chapter_content"
    )
    support_records = list_structured_records(conn, document_id, chunk_id=chunks[1].id)

    assert [row["term"] for row in core_terms] == ["Evolutionary ethics"]
    assert [row["question"] for row in chapter_questions] == [
        "What does evolutionary ethics study?"
    ]
    assert {row["record_type"] for row in support_records} == {"key_terms"}
    assert support_records[0]["chunk_id"] == chunks[1].id


def test_quality_report_summarizes_assimilation_scope(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)
    run_id = create_extraction_run(conn, document_id, "test-model", "prompt")
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunks[0].id,
        raw_prompt="prompt",
        raw_response="{}",
        parsed_json={},
        validation_status="valid",
        validation_error=None,
    )
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunks[1].id,
        raw_prompt="prompt",
        raw_response="{",
        parsed_json=None,
        validation_status="invalid_json",
        validation_error="bad json",
    )

    report = quality_report(conn, document_id)

    assert report["model_output_status_counts"] == [
        {"validation_status": "invalid_json", "count": 1},
        {"validation_status": "valid", "count": 1},
    ]
    assert report["latest_output_status_counts"] == [
        {"validation_status": "invalid_json", "count": 1},
        {"validation_status": "never_attempted", "count": 2},
        {"validation_status": "valid", "count": 1},
    ]
    assert {"content_role": "core", "count": 1} in report["key_terms_by_role"]
    assert report["top_repeated_key_terms"] == [{"term": "evolutionary ethics", "count": 2}]
    assert [row["id"] for row in report["chunks_with_no_terms_or_questions"]] == [chunks[3].id]
    assert {row["content_role"] for row in report["non_core_chunks_with_records"]} == {
        "admin",
        "support",
    }


def test_context_chunks_defaults_to_core_and_supports_filters(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    default_results = context_chunks(conn, document_id, "evolutionary", limit=10)
    support_results = context_chunks(
        conn, document_id, "evolutionary", limit=10, role="support"
    )

    assert [row["content_role"] for row in default_results] == ["core"]
    assert "Naturalism appears in evolutionary ethics" in default_results[0]["text"]
    assert [row["section_label"] for row in support_results] == ["chapter_references"]


def test_answer_prompt_construction_is_grounded_and_cited(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    rows = context_chunks(conn, document_id, "evolutionary", limit=1)

    prompt = build_answer_prompt("What is evolutionary ethics?", rows, max_chars=120)

    assert "Answer only from the context below." in prompt
    assert "If the context does not contain enough information" in prompt
    assert "What is evolutionary ethics?" in prompt
    assert "[labeled.pdf p. 1, chunk 1]" in prompt
    assert "source_citation: labeled.pdf p. 1, chunk 1" in prompt
    assert "Naturalism appears in evolutionary ethics" in prompt


def test_normalize_answer_role_all_means_no_filter():
    assert normalize_answer_role("all") is None
    assert normalize_answer_role("core") == "core"


def test_question_to_fts_query_removes_question_filler_words():
    assert (
        question_to_fts_query("What is methodological ethical naturalism?")
        == "methodological ethical naturalism"
    )
    assert (
        question_to_fts_query("What are the main ideas in evolutionary ethics?")
        == "evolutionary ethics"
    )


def test_ask_cli_uses_core_context_without_real_ollama(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)
    calls = []

    def fake_answer_question(**kwargs):
        calls.append(kwargs)
        return AnswerCallResult(
            raw_prompt=kwargs["prompt"],
            raw_response="Evolutionary ethics is answered from core context. (labeled.pdf p. 1, chunk 1)",
        )

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(["--db", str(db_path), "ask", str(document_id), "evolutionary ethics"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert len(calls) == 1
    assert "Question: evolutionary ethics" in output
    assert f"chunk {chunks[0].id}: labeled.pdf p. 1, chunk 1" in output
    assert f"chunk {chunks[1].id}: labeled.pdf p. 2, chunk 2" not in output
    assert "Answer:" in output
    assert "Evolutionary ethics is answered from core context." in output
    assert "source_citation: labeled.pdf p. 1, chunk 1" in calls[0]["prompt"]


def test_ask_cli_role_all_disables_role_filter(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        ["--db", str(db_path), "ask", str(document_id), "evolutionary", "--role", "all", "--limit", "10"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"chunk {chunks[0].id}: labeled.pdf p. 1, chunk 1" in output
    assert f"chunk {chunks[1].id}: labeled.pdf p. 2, chunk 2" in output
    assert f"chunk {chunks[2].id}: labeled.pdf p. 3, chunk 3" in output


def test_ask_cli_section_filter_selects_matching_context(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered from references.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ask",
            str(document_id),
            "evolutionary",
            "--role",
            "all",
            "--section",
            "chapter_references",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"chunk {chunks[1].id}: labeled.pdf p. 2, chunk 2" in output
    assert f"chunk {chunks[0].id}: labeled.pdf p. 1, chunk 1" not in output


def test_ask_cli_empty_context_does_not_call_ollama(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    def fail_answer_question(**kwargs):
        raise AssertionError("Ollama should not be called when no context is found")

    monkeypatch.setattr("ethnos.cli.answer_question", fail_answer_question)

    exit_code = main(["--db", str(db_path), "ask", str(document_id), "missingterm"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Selected context chunks: none" in output
    assert "The document context did not contain enough information" in output


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


def test_select_chunks_for_structure_retry_failed_and_force(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="retryfailed",
        title="Course",
        page_count=3,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=index,
            raw_text=f"Chunk {index}",
            cleaned_text=f"Chunk {index}",
            char_count=7,
        )
        for index in range(1, 4)
    ]
    document_id = save_document_pages(conn, document, pages)
    stored_document = document.model_copy(update={"id": document_id})
    save_chunks(conn, document_id, build_chunks(stored_document, pages, target_chars=1))
    chunks = select_chunks_for_structure(conn, document_id, force=True)

    run_id = create_extraction_run(conn, document_id, "test-model", "test-prompt")
    assert chunks[0].id is not None
    assert chunks[1].id is not None
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunks[0].id,
        raw_prompt="prompt",
        raw_response='{"chunk_summary": "ok"}',
        parsed_json={"chunk_summary": "ok"},
        validation_status="valid",
        validation_error=None,
    )
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunks[1].id,
        raw_prompt="prompt",
        raw_response="{",
        parsed_json=None,
        validation_status="invalid_json",
        validation_error="bad json",
    )

    assert [chunk.chunk_index for chunk in select_chunks_for_structure(conn, document_id)] == [3]
    assert [
        chunk.chunk_index
        for chunk in select_chunks_for_structure(conn, document_id, retry_failed=True)
    ] == [2]
    assert [chunk.chunk_index for chunk in select_chunks_for_structure(conn, document_id, force=True)] == [
        1,
        2,
        3,
    ]


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


def test_structure_status_summarizes_document_progress(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="status",
        title="Course",
        page_count=3,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=index,
            raw_text=f"Chunk {index}",
            cleaned_text=f"Chunk {index}",
            char_count=7,
        )
        for index in range(1, 4)
    ]
    document_id = save_document_pages(conn, document, pages)
    stored_document = document.model_copy(update={"id": document_id})
    save_chunks(conn, document_id, build_chunks(stored_document, pages, target_chars=1))
    chunks = select_chunks_for_structure(conn, document_id, force=True)
    run_id = create_extraction_run(conn, document_id, "test-model", "test-prompt")
    assert chunks[0].id is not None
    assert chunks[1].id is not None
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunks[0].id,
        raw_prompt="prompt",
        raw_response='{"chunk_summary": "ok"}',
        parsed_json={"chunk_summary": "ok"},
        validation_status="valid",
        validation_error=None,
    )
    save_model_output(
        conn,
        run_id=run_id,
        chunk_id=chunks[1].id,
        raw_prompt="prompt",
        raw_response="",
        parsed_json=None,
        validation_status="empty_response",
        validation_error="empty",
    )

    status = structure_status(conn, document_id)

    assert status["total_chunks"] == 3
    assert status["chunks_with_valid_output"] == 1
    assert status["chunks_latest_failed"] == 1
    assert status["chunks_never_attempted"] == 1
    assert [row["chunk_index"] for row in status["latest_failed_chunks"]] == [2]
    assert [row["chunk_index"] for row in status["never_attempted_chunks"]] == [3]


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


def test_export_study_uses_terms_questions_and_source_pages(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=2, page_end=3)
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Ethics concepts.",
            "topics": [],
            "key_terms": [
                {
                    "term": "Moral relativism",
                    "definition": "The view that moral judgments depend on a context or standpoint.",
                    "context": "",
                    "source_pages": [],
                }
            ],
            "examples": [],
            "questions": [
                {
                    "question": "What does moral relativism claim?",
                    "answer": "It claims moral judgments depend on a context or standpoint.",
                    "difficulty": "medium",
                    "source_pages": [],
                }
            ],
        }
    )

    from ethnos.db import save_extraction_result

    save_extraction_result(conn, chunk_id, result)
    guide = export_study(conn, 1)

    assert guide.key_term_count == 1
    assert guide.question_count == 1
    assert "# Study Guide: course.pdf" in guide.markdown
    assert "## Key Terms" in guide.markdown
    assert "**Moral relativism**" in guide.markdown
    assert "Source pages: pp. 2-3" in guide.markdown
    assert "## Study Questions" in guide.markdown
    assert "What does moral relativism claim?" in guide.markdown
    assert "- [ ] Can I explain Moral relativism? (pp. 2-3)" in guide.markdown


def test_export_study_cli_requires_output_and_writes_file(tmp_path):
    db_path = tmp_path / "ethnos.sqlite"
    output_path = tmp_path / "exports" / "study.md"
    conn = connect(db_path)
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=5, page_end=5)
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Ethics concepts.",
            "topics": [],
            "key_terms": [
                {
                    "term": "Virtue ethics",
                    "definition": "An approach focused on character and virtue.",
                    "context": "",
                    "source_pages": [],
                }
            ],
            "examples": [],
            "questions": [],
        }
    )

    from ethnos.db import save_extraction_result

    save_extraction_result(conn, chunk_id, result)

    exit_code = main(["--db", str(db_path), "export-study", "1", "--output", str(output_path)])

    assert exit_code == 0
    markdown = output_path.read_text(encoding="utf-8")
    assert "# Study Guide: course.pdf" in markdown
    assert "Virtue ethics" in markdown
    assert "Source pages: p. 5" in markdown


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


def _stored_labeled_record_document(conn):
    document = DocumentRecord(
        source_path="/tmp/labeled.pdf",
        filename="labeled.pdf",
        sha256="labeled-fixture",
        title="Labeled",
        page_count=4,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=index,
            raw_text=f"Page {index}",
            cleaned_text=f"Page {index}",
            char_count=6,
        )
        for index in range(1, 5)
    ]
    document_id = save_document_pages(conn, document, pages)
    save_chunks(
        conn,
        document_id,
        [
            ChunkRecord(
                document_id=document_id,
                page_start=1,
                page_end=1,
                chunk_index=1,
                text="Naturalism appears in evolutionary ethics as core course content.",
                char_count=64,
                source_citation="labeled.pdf p. 1, chunk 1",
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=2,
                page_end=2,
                chunk_index=2,
                text="References mention evolutionary ethics and related bibliography.",
                char_count=62,
                source_citation="labeled.pdf p. 2, chunk 2",
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=3,
                page_end=3,
                chunk_index=3,
                text="Front matter says evolutionary ethics appears in the book.",
                char_count=58,
                source_citation="labeled.pdf p. 3, chunk 3",
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=4,
                page_end=4,
                chunk_index=4,
                text="A quiet unlabeled inspection chunk.",
                char_count=35,
                source_citation="labeled.pdf p. 4, chunk 4",
            ),
        ],
    )
    conn.execute(
        """
        UPDATE chunks
        SET section_label = 'chapter_content', content_role = 'core', section_confidence = 1.0
        WHERE document_id = ? AND chunk_index = 1
        """,
        (document_id,),
    )
    conn.execute(
        """
        UPDATE chunks
        SET section_label = 'chapter_references', content_role = 'support', section_confidence = 1.0
        WHERE document_id = ? AND chunk_index = 2
        """,
        (document_id,),
    )
    conn.execute(
        """
        UPDATE chunks
        SET section_label = 'front_matter', content_role = 'admin', section_confidence = 1.0
        WHERE document_id = ? AND chunk_index = 3
        """,
        (document_id,),
    )
    conn.execute(
        """
        UPDATE chunks
        SET section_label = 'chapter_content', content_role = 'core', section_confidence = 1.0
        WHERE document_id = ? AND chunk_index = 4
        """,
        (document_id,),
    )
    conn.commit()
    chunks = select_chunks_for_structure(conn, document_id, force=True)
    core_result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Core discussion.",
            "topics": [],
            "key_terms": [
                {
                    "term": "Evolutionary ethics",
                    "definition": "An approach that connects ethics with evolutionary explanations.",
                    "context": "",
                    "source_pages": [1],
                }
            ],
            "examples": [],
            "questions": [
                {
                    "question": "What does evolutionary ethics study?",
                    "answer": "It studies ethical ideas in relation to evolutionary explanations.",
                    "difficulty": "medium",
                    "source_pages": [1],
                }
            ],
        }
    )
    support_result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Reference material.",
            "topics": [],
            "key_terms": [
                {
                    "term": "Evolutionary ethics",
                    "definition": "A repeated reference term in support material.",
                    "context": "",
                    "source_pages": [2],
                }
            ],
            "examples": [],
            "questions": [],
        }
    )
    admin_result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Administrative material.",
            "topics": [],
            "key_terms": [],
            "examples": [],
            "questions": [
                {
                    "question": "Where is evolutionary ethics mentioned?",
                    "answer": "It is mentioned in the front matter.",
                    "difficulty": "easy",
                    "source_pages": [3],
                }
            ],
        }
    )
    save_extraction_result(conn, chunks[0].id, core_result)
    save_extraction_result(conn, chunks[1].id, support_result)
    save_extraction_result(conn, chunks[2].id, admin_result)
    return document_id, chunks


def _stored_three_page_document(conn) -> int:
    document = DocumentRecord(
        source_path="/tmp/sections.pdf",
        filename="sections.pdf",
        sha256="sections-fixture",
        title="Sections",
        page_count=3,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=index,
            raw_text=f"Page {index}",
            cleaned_text=f"Page {index}",
            char_count=6,
        )
        for index in range(1, 4)
    ]
    document_id = save_document_pages(conn, document, pages)
    save_chunks(
        conn,
        document_id,
        [
            ChunkRecord(
                document_id=document_id,
                page_start=index,
                page_end=index,
                chunk_index=index,
                text=f"Chunk {index}",
                char_count=7,
                source_citation=f"sections.pdf p. {index}, chunk {index}",
            )
            for index in range(1, 4)
        ],
    )
    return document_id


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
