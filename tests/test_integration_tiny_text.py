from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from ethnos.chunking import build_chunks
from ethnos.cli import limit_benchmark_items, main, parse_models_arg, progress_line
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
    inspect_page,
    list_structured_records,
    quality_report,
    search_chunks,
    section_label_status,
    select_chunks_for_structure,
    structure_status,
)
from ethnos.models import ChunkRecord, DocumentRecord, ExtractionResult, PageRecord
from ethnos.export import export_json, export_study
from ethnos.ollama_client import AnswerCallResult
from ethnos.qa import (
    answer_query_candidates,
    benchmark_hit,
    build_answer_prompt,
    detect_comparison_question,
    detect_chat_followup,
    evaluate_answer_quality,
    extract_comparison_subqueries,
    load_qa_benchmark,
    normalize_answer_role,
    rank_model_summaries,
    question_to_fts_query,
    resolve_chat_followup,
    retrieve_with_fallbacks,
    summarize_answer_items,
)
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


def test_inspect_page_helper_returns_source_page_with_document_metadata(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_page_inspection_document(conn)

    page = inspect_page(conn, document_id, 1)

    assert page["filename"] == "page-inspect.pdf"
    assert page["page_number"] == 1
    assert page["raw_text"] == "Title\n\nRaw   line"
    assert page["cleaned_text"] == "Title\nCleaned line"
    assert page["char_count"] == 18
    assert page["extraction_method"] == "test:extract"
    assert page["id"] is not None


def test_inspect_page_cli_shows_cleaned_text_by_default(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id = _stored_page_inspection_document(conn)

    exit_code = main(["--db", str(db_path), "inspect-page", str(document_id), "1"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Document: page-inspect.pdf" in output
    assert "Page: 1" in output
    assert "Extraction method: test:extract" in output
    assert "Cleaned text:" in output
    assert "Title\nCleaned line" in output
    assert "Raw   line" not in output


def test_inspect_page_cli_raw_text_with_limit_preserves_whitespace(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id = _stored_page_inspection_document(conn)

    exit_code = main(
        ["--db", str(db_path), "inspect-page", str(document_id), "1", "--raw", "--limit", "12"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Raw text:" in output
    assert "Title\n\nRaw" in output
    assert "... [truncated]" in output
    assert "Raw   line" not in output


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


def test_answer_query_candidates_preserve_phrases_and_tune_trolley_questions():
    assert answer_query_candidates("What is Kantian deontology?")[0] == "kantian deontology"
    assert answer_query_candidates("What is virtue ethics?")[0] == "virtue ethics"
    assert answer_query_candidates("What is natural law?")[0] == "natural law"
    assert answer_query_candidates("What is social contract theory?")[0] == "social contract theory"
    assert (
        answer_query_candidates("What is methodological ethical naturalism?")[0]
        == "methodological ethical naturalism"
    )

    candidates = answer_query_candidates(
        "What does the book say about trolley cases and utilitarianism?"
    )

    assert candidates[:3] == [
        "trolley cases utilitarianism",
        "trolley problem utilitarianism",
        "trolley utilitarianism",
    ]


def test_retrieve_with_fallbacks_tries_looser_queries_until_context_found():
    calls = []

    def fake_search(document_id, query, limit, role, section):
        calls.append(query)
        if query == "trolley utilitarianism":
            return [
                {
                    "id": 55,
                    "chunk_index": 55,
                    "page_start": 65,
                    "page_end": 65,
                    "source_citation": "ethics.pdf p. 65, chunk 55",
                    "section_label": "chapter_content",
                    "content_role": "core",
                    "text": "Trolley text",
                }
            ]
        return []

    result = retrieve_with_fallbacks(
        search_func=fake_search,
        document_id=1,
        question="What does the book say about trolley cases and utilitarianism?",
        limit=5,
        role="core",
        section=None,
    )

    assert result.selected_query == "trolley utilitarianism"
    assert result.stopped_reason == "context_found"
    assert calls == [
        "trolley cases utilitarianism",
        "trolley problem utilitarianism",
        "trolley utilitarianism",
    ]


def test_comparison_question_detection_and_subquery_extraction():
    assert detect_comparison_question("How is virtue ethics different from Kantian deontology?")
    assert extract_comparison_subqueries(
        "How is virtue ethics different from Kantian deontology?"
    ) == ["virtue ethics", "kantian deontology"]
    assert extract_comparison_subqueries(
        "How does virtue ethics differ from Kantian deontology?"
    ) == ["virtue ethics", "kantian deontology"]
    assert extract_comparison_subqueries("Compare utilitarianism and Kantian deontology.") == [
        "utilitarianism",
        "kantian deontology",
    ]
    assert extract_comparison_subqueries(
        "How does utilitarianism compare to Kantian deontology?"
    ) == ["utilitarianism", "kantian deontology"]
    assert extract_comparison_subqueries("natural law vs divine command theory") == [
        "natural law",
        "divine command",
    ]
    assert extract_comparison_subqueries("compare social contract with ethical egoism") == [
        "social contract",
        "ethical egoism",
    ]
    assert not detect_comparison_question("What is virtue ethics?")


def test_comparison_retrieval_merges_both_sides_and_deduplicates():
    row_a = {"id": 1, "source_citation": "a", "text": "virtue ethics"}
    row_shared = {"id": 2, "source_citation": "shared", "text": "shared"}
    row_b = {"id": 3, "source_citation": "b", "text": "kantian deontology"}
    calls = []

    def search_func(document_id, query, limit, role, section):
        calls.append((query, limit, role, section))
        if query == "virtue ethics":
            return [row_a, row_shared]
        if query == "kantian deontology":
            return [row_shared, row_b]
        return []

    result = retrieve_with_fallbacks(
        search_func=search_func,
        document_id=1,
        question="How is virtue ethics different from Kantian deontology?",
        limit=3,
        role="core",
        section=None,
    )

    assert result.comparison_detected is True
    assert result.comparison_subqueries == ["virtue ethics", "kantian deontology"]
    assert [row["id"] for row in result.rows] == [1, 2, 3]
    assert result.selected_query == "virtue ethics | kantian deontology"
    assert len(result.subquery_results) == 2
    assert calls[0] == ("virtue ethics", 3, "core", None)
    assert calls[1] == ("kantian deontology", 3, "core", None)


def test_ask_retrieval_adds_incomplete_chunk_continuation(tmp_path, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/course.pdf",
        filename="course.pdf",
        sha256="continuation-fixture",
        title="Course",
        page_count=2,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="Virtue ethics links goodness with wisdom because",
            cleaned_text="Virtue ethics links goodness with wisdom because",
            char_count=50,
        ),
        PageRecord(
            document_id=0,
            page_number=2,
            raw_text="character and wisdom matter.",
            cleaned_text="character and wisdom matter.",
            char_count=28,
        ),
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
                text="Virtue ethics links goodness with wisdom because",
                char_count=50,
                source_citation="course.pdf p. 1, chunk 1",
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=2,
                page_end=2,
                chunk_index=2,
                text="character and wisdom matter.",
                char_count=28,
                source_citation="course.pdf p. 2, chunk 2",
            ),
        ],
    )
    conn.execute(
        "UPDATE chunks SET section_label = 'chapter_content', content_role = 'core'"
    )
    conn.commit()

    calls = []

    def fake_answer_question(**kwargs):
        calls.append(kwargs)
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ask",
            str(document_id),
            "virtue ethics",
            "--limit",
            "1",
        ]
    )
    assert exit_code == 0
    assert "course.pdf p. 1, chunk 1" in calls[0]["prompt"]
    assert "course.pdf p. 2, chunk 2" in calls[0]["prompt"]


def test_normal_retrieval_does_not_use_comparison_logic():
    def search_func(document_id, query, limit, role, section):
        return [{"id": 1, "source_citation": "a", "text": "virtue ethics"}]

    result = retrieve_with_fallbacks(
        search_func=search_func,
        document_id=1,
        question="What is virtue ethics?",
        limit=3,
        role="core",
        section=None,
    )

    assert result.comparison_detected is False
    assert result.comparison_subqueries == []
    assert result.subquery_results == []
    assert result.selected_query == "virtue ethics"


def test_chat_followup_detection_and_rewrite_helpers():
    previous = retrieve_with_fallbacks(
        search_func=lambda document_id, query, limit, role, section: [
            {"id": 1, "source_citation": "a", "text": "virtue ethics"}
        ],
        document_id=1,
        question="What is virtue ethics?",
        limit=3,
        role="core",
        section=None,
    )

    resolution = resolve_chat_followup(
        "How is that different from utilitarianism?",
        previous_question="What is virtue ethics?",
        previous_retrieval=previous,
    )

    assert detect_chat_followup("How is that different from utilitarianism?")
    assert resolution.detected is True
    assert resolution.previous_topic == "virtue ethics"
    assert resolution.rewritten_question == "How is virtue ethics different from utilitarianism?"


def test_chat_followup_uses_previous_topic_for_retrieval_and_trace(
    tmp_path, capsys, monkeypatch
):
    db_path = tmp_path / "ethnos.sqlite"
    trace_dir = tmp_path / "runs"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)
    inputs = iter(["What is evolutionary ethics?", "How is that different from references?", "quit"])
    calls = []

    def fake_input(prompt):
        return next(inputs)

    def fake_answer_question(**kwargs):
        calls.append(kwargs)
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered.")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "chat",
            str(document_id),
            "--role",
            "all",
            "--debug-retrieval",
            "--trace-dir",
            str(trace_dir),
        ]
    )
    output = capsys.readouterr().out
    traces = sorted(trace_dir.glob("*.json"))
    followup_trace = json.loads(traces[-1].read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(calls) == 2
    assert "Resolved follow-up for retrieval: How is evolutionary ethics different from references?" in calls[1]["prompt"]
    assert "follow-up detected: True" in output
    assert "rewritten retrieval question: How is evolutionary ethics different from references?" in output
    assert f"chunk {chunks[0].id}: labeled.pdf p. 1, chunk 1" in output
    assert f"chunk {chunks[1].id}: labeled.pdf p. 2, chunk 2" in output
    assert followup_trace["follow_up_detected"] is True
    assert followup_trace["previous_question"] == "What is evolutionary ethics?"
    assert (
        followup_trace["rewritten_retrieval_question"]
        == "How is evolutionary ethics different from references?"
    )
    assert followup_trace["comparison_detected"] is True


def test_ask_remains_stateless_for_followup_words(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    calls = []

    def fake_answer_question(**kwargs):
        calls.append(kwargs)
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        ["--db", str(db_path), "ask", str(document_id), "How is that different from references?"]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Follow-up debug:" not in output
    if calls:
        assert "Resolved follow-up for retrieval:" not in calls[0]["prompt"]


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


def test_ask_cli_writes_trace_when_requested(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    trace_dir = tmp_path / "runs" / "answers"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(
            raw_prompt=kwargs["prompt"],
            raw_response="Evolutionary ethics is answered [labeled.pdf p. 1, chunk 1].",
        )

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ask",
            str(document_id),
            "What is evolutionary ethics?",
            "--model",
            "custom-model",
            "--trace-dir",
            str(trace_dir),
        ]
    )
    output = capsys.readouterr().out
    traces = list(trace_dir.glob("*.json"))
    trace = json.loads(traces[0].read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(traces) == 1
    assert "Trace:" in output
    assert trace["document_id"] == document_id
    assert trace["question"] == "What is evolutionary ethics?"
    assert trace["model"] == "custom-model"
    assert trace["num_predict"] == 8192
    assert trace["context_found"] is True
    assert trace["command_mode"] == "ask"
    assert trace["selected_chunks"][0]["chunk_id"] == chunks[0].id
    assert trace["selected_chunks"][0]["source_citation"] == "labeled.pdf p. 1, chunk 1"
    assert trace["answer_text"].startswith("Evolutionary ethics is answered")


def test_ask_cli_does_not_write_trace_by_default(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(["--db", str(db_path), "ask", str(document_id), "evolutionary ethics"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Trace:" not in output
    assert not list(tmp_path.glob("*.json"))


def test_chat_cli_exits_on_quit_without_ollama(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    monkeypatch.setattr("builtins.input", lambda prompt: "quit")

    exit_code = main(["--db", str(db_path), "chat", str(document_id)])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert f"ethnos chat for document {document_id}" in output
    assert "model: gemma-python" in output


def test_chat_cli_answers_and_writes_trace(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    trace_dir = tmp_path / "nested" / "runs"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    inputs = iter(["What is evolutionary ethics?", "quit"])

    def fake_input(prompt):
        return next(inputs)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Chat answered.")

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "chat",
            str(document_id),
            "--trace-dir",
            str(trace_dir),
        ]
    )
    output = capsys.readouterr().out
    traces = list(trace_dir.glob("*.json"))
    trace = json.loads(traces[0].read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Question: What is evolutionary ethics?" in output
    assert "Chat answered." in output
    assert len(traces) == 1
    assert trace["command_mode"] == "chat"
    assert trace["context_found"] is True


def test_ask_cli_debug_retrieval_shows_query_attempts(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Answered.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ask",
            str(document_id),
            "What does the book say about evolutionary ethics?",
            "--debug-retrieval",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "Retrieval debug:" in output
    assert "original question: What does the book say about evolutionary ethics?" in output
    assert "derived query: evolutionary ethics" in output
    assert "stopped reason: context_found" in output


def test_ask_cli_debug_retrieval_shows_comparison_subqueries(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document_id, chunks = _stored_labeled_record_document(conn)

    def fake_answer_question(**kwargs):
        return AnswerCallResult(raw_prompt=kwargs["prompt"], raw_response="Compared.")

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "ask",
            str(document_id),
            "How is evolutionary ethics different from references?",
            "--role",
            "all",
            "--debug-retrieval",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "comparison detected: True" in output
    assert "subqueries: evolutionary ethics, references" in output
    assert "subquery: evolutionary ethics" in output
    assert "subquery: references" in output
    assert f"merged selected chunks: {chunks[1].id}, {chunks[0].id}, {chunks[2].id}" in output


def test_benchmark_file_loading_and_hit_detection(tmp_path):
    benchmark_path = tmp_path / "bench.json"
    benchmark_path.write_text(
        json.dumps(
            [
                {
                    "id": "sample",
                    "question": "What is evolutionary ethics?",
                    "expected_source_chunks": [1],
                    "expected_source_pages": [1],
                    "expected_answer_terms": ["evolutionary ethics"],
                }
            ]
        ),
        encoding="utf-8",
    )

    items = load_qa_benchmark(benchmark_path)
    row = {"id": 1, "chunk_index": 1, "page_start": 1, "page_end": 1}

    assert items[0]["id"] == "sample"
    assert items[0]["expected_answer_terms"] == ["evolutionary ethics"]
    assert benchmark_hit(items[0], [row]) is True
    assert benchmark_hit({"expected_source_chunks": [], "expected_source_pages": []}, []) is True
    assert benchmark_hit({"expected_source_chunks": [], "expected_source_pages": []}, [row]) is False


def test_answer_quality_evaluation_pass_partial_fail_and_forbidden_terms():
    row = {
        "id": 1,
        "chunk_index": 1,
        "page_start": 1,
        "page_end": 1,
        "source_citation": "labeled.pdf p. 1, chunk 1",
    }
    item = {
        "expected_answer_terms": ["evolutionary ethics", "core context"],
        "expected_citation_chunks": [1],
        "forbidden_terms": ["invented"],
    }

    passed = evaluate_answer_quality(
        item,
        "Evolutionary ethics appears in core context [labeled.pdf p. 1, chunk 1].",
        [row],
    )
    partial = evaluate_answer_quality(
        item,
        "Evolutionary ethics appears here, but without the rest.",
        [row],
    )
    failed = evaluate_answer_quality(item, "A thin answer.", [row])
    forbidden = evaluate_answer_quality(item, "An invented answer about evolutionary ethics.", [row])

    assert passed.status == "pass"
    assert passed.citation_hit is True
    assert partial.status == "partial"
    assert partial.missing_expected_terms == ["core context"]
    assert failed.status == "fail"
    assert forbidden.status == "fail"
    assert forbidden.forbidden_terms_found == ["invented"]


def test_answer_quality_expected_any_terms_groups():
    row = {
        "id": 1,
        "chunk_index": 1,
        "page_start": 1,
        "page_end": 1,
        "source_citation": "labeled.pdf p. 1, chunk 1",
    }
    item = {
        "expected_answer_terms": ["consequences"],
        "expected_any_terms": [
            ["utility", "happiness", "pleasure"],
            ["duty", "duties", "obligation"],
        ],
    }

    passed = evaluate_answer_quality(
        item,
        "Consequences, happiness, and obligation matter here.",
        [row],
    )
    partial = evaluate_answer_quality(
        item,
        "Consequences and happiness are discussed.",
        [row],
    )

    assert passed.status == "pass"
    assert partial.status == "partial"
    assert partial.missing_expected_terms == ["any of: duty | duties | obligation"]


def test_answer_quality_expected_citation_page_detection():
    row = {
        "id": 1,
        "chunk_index": 1,
        "page_start": 2,
        "page_end": 3,
        "source_citation": "labeled.pdf pp. 2-3, chunk 1",
    }
    evaluation = evaluate_answer_quality(
        {"expected_answer_terms": ["term"], "expected_citation_pages": [2]},
        "The term appears here [labeled.pdf pp. 2-3, chunk 1].",
        [row],
    )

    assert evaluation.status == "pass"
    assert evaluation.citation_hit is True


def test_answer_quality_no_context_expected_behavior():
    evaluation = evaluate_answer_quality(
        {"expected_source_chunks": [], "expected_source_pages": []},
        "",
        [],
    )

    assert evaluation.status == "no_context_expected"


def test_qa_bench_retrieval_only_path(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    benchmark_path = tmp_path / "bench.json"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    benchmark_path.write_text(
        json.dumps(
            [
                {
                    "id": "core-hit",
                    "question": "What is evolutionary ethics?",
                    "expected_source_chunks": [1],
                },
                {
                    "id": "no-context",
                    "question": "quantum computing",
                    "expected_source_chunks": [],
                    "expected_source_pages": [],
                },
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--db",
            str(db_path),
            "qa-bench",
            str(document_id),
            "--benchmark",
            str(benchmark_path),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "core-hit: What is evolutionary ethics?" in output
    assert "no-context: quantum computing" in output
    assert "hits: 2" in output
    assert "misses: 0" in output
    assert "no-context cases: 1" in output


def test_limit_benchmark_items_and_progress_line():
    items = [{"id": "one"}, {"id": "two"}, {"id": "three"}]

    assert limit_benchmark_items(items, None) == items
    assert limit_benchmark_items(items, 2) == [{"id": "one"}, {"id": "two"}]
    assert progress_line("gemma-python", 2, 14, "virtue-ethics") == (
        "[gemma-python] question 2/14: virtue-ethics"
    )


def test_qa_bench_max_questions_limits_processed_items(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    benchmark_path = tmp_path / "bench.json"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    benchmark_path.write_text(
        json.dumps(
            [
                {"id": "one", "question": "evolutionary ethics", "expected_source_chunks": [1]},
                {"id": "two", "question": "evolutionary ethics", "expected_source_chunks": [1]},
                {"id": "three", "question": "evolutionary ethics", "expected_source_chunks": [1]},
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--db",
            str(db_path),
            "qa-bench",
            str(document_id),
            "--benchmark",
            str(benchmark_path),
            "--max-questions",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "one: evolutionary ethics" in output
    assert "two: evolutionary ethics" in output
    assert "three: evolutionary ethics" not in output
    assert "total: 2" in output


def test_qa_bench_limit_remains_retrieved_chunk_limit(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    benchmark_path = tmp_path / "bench.json"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    benchmark_path.write_text(
        json.dumps(
            [
                {
                    "id": "all-roles",
                    "question": "evolutionary",
                    "expected_source_chunks": [1],
                }
            ]
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--db",
            str(db_path),
            "qa-bench",
            str(document_id),
            "--benchmark",
            str(benchmark_path),
            "--role",
            "all",
            "--limit",
            "2",
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    selected_line = next(line for line in output.splitlines() if "selected chunks:" in line)
    selected_chunks = selected_line.split("selected chunks:", 1)[1].strip().split(", ")
    assert len(selected_chunks) == 2


def test_qa_bench_with_ask_writes_json_report(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    benchmark_path = tmp_path / "bench.json"
    output_path = tmp_path / "report.json"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    benchmark_path.write_text(
        json.dumps(
            [
                {
                    "id": "core-answer",
                    "question": "What is evolutionary ethics?",
                    "expected_source_chunks": [1],
                    "expected_answer_terms": ["evolutionary ethics"],
                    "expected_citation_chunks": [1],
                }
            ]
        ),
        encoding="utf-8",
    )

    def fake_answer_question(**kwargs):
        return AnswerCallResult(
            raw_prompt=kwargs["prompt"],
            raw_response="Evolutionary ethics is answered [labeled.pdf p. 1, chunk 1].",
        )

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "qa-bench",
            str(document_id),
            "--benchmark",
            str(benchmark_path),
            "--ask",
            "--output",
            str(output_path),
        ]
    )
    output = capsys.readouterr().out
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "answer pass: 1" in output
    assert report["answer_pass"] == 1
    assert report["items"][0]["answer_text"].startswith("Evolutionary ethics")
    assert report["items"][0]["answer_evaluation"]["status"] == "pass"
    assert "timings" in report["items"][0]


def test_parse_models_arg_accepts_comma_separated_models():
    assert parse_models_arg("gemma-python, gemma4:e2b,gemma-python") == [
        "gemma-python",
        "gemma4:e2b",
    ]


def test_model_summary_aggregation_and_ranking():
    items = [
        {
            "hit": True,
            "selected_chunks": [1],
            "answer_text": "short answer",
            "answer_evaluation": {"status": "pass"},
            "timings": {"answer_seconds": 2.0},
        },
        {
            "hit": True,
            "selected_chunks": [2],
            "answer_text": "partial answer",
            "answer_evaluation": {"status": "partial"},
            "timings": {"answer_seconds": 4.0},
        },
    ]

    summary = summarize_answer_items(items)
    summary["model"] = "model-a"
    summary["total_elapsed_seconds"] = 6.0
    other = {
        **summary,
        "model": "model-b",
        "answer_pass": 2,
        "answer_partial": 0,
        "answer_fail": 0,
        "total_elapsed_seconds": 8.0,
    }
    ranking = rank_model_summaries([summary, other])

    assert summary["answer_pass"] == 1
    assert summary["answer_partial"] == 1
    assert summary["average_answer_seconds"] == 3.0
    assert ranking["best_pass_count"] == ["model-b"]
    assert ranking["lowest_fail_count"] == ["model-a", "model-b"]
    assert ranking["fastest_no_fail"] == "model-a"


def test_model_summary_counts_model_errors():
    summary = summarize_answer_items(
        [
            {
                "hit": True,
                "selected_chunks": [1],
                "answer_evaluation": {"status": "model_error"},
                "timings": {"answer_seconds": 0.1},
            }
        ]
    )

    assert summary["model_error"] == 1
    assert summary["answer_fail"] == 0


def test_qa_bench_model_compare_writes_json_report(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    benchmark_path = tmp_path / "bench.json"
    output_path = tmp_path / "compare.json"
    conn = connect(db_path)
    init_db(conn)
    document_id, _ = _stored_labeled_record_document(conn)
    benchmark_path.write_text(
        json.dumps(
            [
                {
                    "id": "core-answer",
                    "question": "What is evolutionary ethics?",
                    "expected_source_chunks": [1],
                    "expected_answer_terms": ["evolutionary ethics"],
                    "expected_citation_chunks": [1],
                }
            ]
        ),
        encoding="utf-8",
    )

    def fake_answer_question(**kwargs):
        if kwargs["model_name"] == "missing-model":
            raise RuntimeError("model not found")
        return AnswerCallResult(
            raw_prompt=kwargs["prompt"],
            raw_response=(
                f"Evolutionary ethics is answered by {kwargs['model_name']} "
                "[labeled.pdf p. 1, chunk 1]."
            ),
        )

    monkeypatch.setattr("ethnos.cli.answer_question", fake_answer_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "qa-bench",
            str(document_id),
            "--benchmark",
            str(benchmark_path),
            "--ask",
            "--models",
            "model-a,missing-model",
            "--output",
            str(output_path),
        ]
    )
    output = capsys.readouterr().out
    report = json.loads(output_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Model: model-a" in output
    assert "Model: missing-model" in output
    assert report["mode"] == "model_compare"
    assert report["models"] == ["model-a", "missing-model"]
    assert report["model_summaries"][0]["answer_pass"] == 1
    assert report["model_summaries"][1]["model_error"] == 1
    assert report["models_report"][1]["items"][0]["answer_evaluation"]["status"] == "model_error"


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

    summary_rows = conn.execute(
        "SELECT chunk_id, summary FROM chunk_summaries WHERE chunk_id = ?", (chunk_id,)
    ).fetchall()
    assert [dict(row) for row in summary_rows] == [
        {"chunk_id": chunk_id, "summary": "Second result."}
    ]
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


def test_export_json_includes_normalized_chunk_summary(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    chunk_id = _stored_chunk(conn, page_start=2, page_end=3)
    result = ExtractionResult.model_validate(
        {
            "chunk_summary": "Ethics concepts.",
            "topics": [],
            "key_terms": [],
            "examples": [],
            "questions": [],
        }
    )

    from ethnos.db import save_extraction_result

    save_extraction_result(conn, chunk_id, result)
    exported = json.loads(export_json(conn, 1))

    assert len(exported["chunk_summaries"]) == 1
    summary = exported["chunk_summaries"][0]
    assert summary["chunk_id"] == chunk_id
    assert summary["summary"] == "Ethics concepts."
    assert summary["created_at"]
    assert "chunk_summary" not in exported["chunks"][0]


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


def _stored_page_inspection_document(conn) -> int:
    document = DocumentRecord(
        source_path="/tmp/page-inspect.pdf",
        filename="page-inspect.pdf",
        sha256="page-inspect-fixture",
        title="Page Inspect",
        page_count=1,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="Title\n\nRaw   line",
            cleaned_text="Title\nCleaned line",
            char_count=18,
            extraction_method="test:extract",
        )
    ]
    return save_document_pages(conn, document, pages)


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
