from __future__ import annotations

import json
from pathlib import Path
from random import Random

from ethnos.cli import _add_quiz_source_context, main
from ethnos.db import connect, init_db, save_chunks, save_document_pages, save_extraction_result
from ethnos.models import ChunkRecord, DocumentRecord, ExtractionResult, PageRecord
from ethnos.ollama_client import MCAnswerResult
from ethnos.quiz import (
    build_mc_prompt,
    build_quiz_item,
    _filter_ambiguous_broad_terms,
    generate_quiz,
    import_lms_mc_quiz,
    load_quiz,
    normalize_quiz,
    parse_source_pages,
)


def test_generate_quiz_uses_terms_by_default_and_is_reproducible(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_quiz_document(conn)

    first = generate_quiz(conn, document_id, limit=2, seed=7)
    second = generate_quiz(conn, document_id, limit=2, seed=7)

    assert first["source"] == "terms"
    assert first["role"] == "core"
    assert first["generated_count"] == 2
    assert first["record_counts"]["available_terms"] == 4
    assert first["record_counts"]["available_questions"] == 0
    assert first["questions"] == second["questions"]
    assert first["difficulty"] == "medium"
    assert first["questions"][0]["question"] == "Which definition best matches Virtue ethics in this text?"
    assert first["questions"][0]["target"] == "Virtue ethics"
    assert first["questions"][0]["source_record_type"] == "key_terms"
    assert set(first["questions"][0]["options"]) == {"A", "B", "C", "D"}
    assert first["questions"][0]["correct"] in {"A", "B", "C", "D"}
    assert first["questions"][0]["source_pages"] == [1]
    assert first["questions"][0]["source_chunks"]


def test_generate_quiz_supports_questions_source_and_option_cap(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_quiz_document(conn)

    quiz = generate_quiz(
        conn,
        document_id,
        source="questions",
        limit=1,
        seed=2,
        max_option_chars=36,
    )
    item = quiz["questions"][0]

    assert quiz["record_counts"]["available_questions"] == 4
    assert item["source_record_type"] == "questions"
    assert item["question"] == "What does virtue ethics emphasize?"
    assert item["difficulty"] == "medium"
    assert all(len(text) <= 36 for text in item["options"].values())
    assert any(text.endswith("...") for text in item["options"].values())


def test_build_quiz_item_rejects_display_collisions_after_truncation():
    records = [
        _record(1, 1, "Alpha answer expands one way"),
        _record(2, 2, "Bravo answer expands one way"),
        _record(3, 3, "Bravo answer expands another way"),
        _record(4, 4, "Charlie answer"),
        _record(5, 5, "Delta answer"),
    ]

    item = build_quiz_item(
        records[0],
        records,
        topics_by_chunk={},
        rng=Random(1),
        max_option_chars=15,
    )

    assert item is not None
    assert len(set(item["options"].values())) == 4


def test_topic_and_proximity_distractor_preference_is_used_before_section_fallback():
    records = [
        _record(1, 10, "Correct"),
        _record(2, 11, "Shared nearby"),
        _record(3, 30, "Shared far"),
        _record(4, 12, "Same section nearby"),
        _record(5, 13, "Other"),
    ]
    topics = {10: {"ethics"}, 11: {"ethics"}, 30: {"ethics"}}

    item = build_quiz_item(
        records[0],
        records,
        topics_by_chunk=topics,
        rng=Random(4),
        max_option_chars=80,
        difficulty="hard",
    )

    assert item is not None
    assert "Shared nearby" in item["options"].values()
    assert "Shared far" in item["options"].values()


def test_easy_distractor_difficulty_prefers_farther_less_local_options():
    records = [
        _record(1, 10, "Correct"),
        _record(2, 11, "Shared nearby"),
        _record(3, 12, "Same section nearby"),
        _record(4, 50, "Far option"),
        _record(5, 51, "Farther option"),
    ]
    topics = {10: {"ethics"}, 11: {"ethics"}}

    item = build_quiz_item(
        records[0],
        records,
        topics_by_chunk=topics,
        rng=Random(4),
        max_option_chars=80,
        difficulty="easy",
    )

    assert item is not None
    assert "Far option" in item["options"].values()
    assert "Farther option" in item["options"].values()


def test_easy_generation_filters_broad_single_word_term_with_specific_sibling():
    records = [
        _record(1, 10, "Broad answer", target="Egoism"),
        _record(2, 10, "Specific answer", target="Ethical Egoism"),
        _record(3, 11, "Other answer", target="Utilitarianism"),
    ]

    filtered = _filter_ambiguous_broad_terms(records)

    assert [record.target for record in filtered] == ["Ethical Egoism", "Utilitarianism"]


def test_source_page_parsing_and_external_quiz_normalization(tmp_path):
    assert parse_source_pages("[3, 2, 2]") == [2, 3]
    assert parse_source_pages("not json") == []
    assert parse_source_pages(["4", "bad", 5]) == [4, 5]

    path = tmp_path / "quiz.json"
    path.write_text(
        json.dumps(
            [
                {
                    "question": "Pick one",
                    "options": ["One", "Two", "Three", "Four"],
                    "source_pages": ["2"],
                }
            ]
        ),
        encoding="utf-8",
    )

    quiz = load_quiz(path)

    assert quiz["version"] == "external-list"
    assert quiz["generated_count"] == 1
    assert quiz["questions"][0]["id"] == "q0001"
    assert quiz["questions"][0]["options"]["D"] == "Four"
    assert "correct" not in quiz["questions"][0]
    assert normalize_quiz({"questions": quiz["questions"]})["generated_count"] == 1


def test_external_quiz_normalization_allows_true_false_and_five_options():
    quiz = normalize_quiz(
        {
            "questions": [
                {
                    "question": "True or false?",
                    "options": ["True", "False"],
                    "correct": "B",
                },
                {
                    "question": "Pick all of the above",
                    "options": ["One", "Two", "Three", "Four", "All of the above"],
                    "correct": "E",
                },
            ]
        }
    )

    assert quiz["questions"][0]["options"] == {"A": "True", "B": "False"}
    assert quiz["questions"][1]["options"]["E"] == "All of the above"
    assert quiz["questions"][1]["correct"] == "E"


def test_import_lms_mc_quiz_parses_chapter_one_fixture():
    raw_text = Path("benchmarks/ethics_ch1_mc_raw.txt").read_text(encoding="utf-8")
    answer_key_text = Path("benchmarks/ethics_ch1_mc_answer_key.txt").read_text(
        encoding="utf-8"
    )

    quiz = import_lms_mc_quiz(
        raw_text,
        document_id=1,
        answer_key_text=answer_key_text,
        id_prefix="ch1-q",
    )

    assert quiz["version"] == "external-mc-v1"
    assert quiz["document_id"] == 1
    assert quiz["title"] == "Quiz CH 1"
    assert quiz["generated_count"] == 10
    assert quiz["questions"][0]["id"] == "ch1-q001"
    assert quiz["questions"][0]["question"] == "What is a fallacy?"
    assert quiz["questions"][0]["options"]["B"] == (
        "a failure in reasoning which renders an argument invalid"
    )
    assert quiz["questions"][0]["correct"] == "B"
    assert quiz["questions"][6]["options"]["E"] == "All of the above"
    assert quiz["questions"][6]["correct"] == "E"
    assert quiz["questions"][8]["options"] == {"A": "True", "B": "False"}
    assert quiz["questions"][9]["correct"] == "B"


def test_import_lms_mc_quiz_accepts_numbered_label_answer_key():
    raw_text = """
Quiz
Question at position 1
Question at position 1
Pick one?
One
Two
Question at position 2
Question at position 2
Pick truth?
True
False
"""

    quiz = import_lms_mc_quiz(raw_text, answer_key_text="1 B\n2 A\n")

    assert quiz["questions"][0]["correct"] == "B"
    assert quiz["questions"][1]["correct"] == "A"


def test_import_mc_quiz_cli_writes_external_json(tmp_path, capsys):
    output = tmp_path / "nested" / "quiz.json"

    exit_code = main(
        [
            "import-mc-quiz",
            "benchmarks/ethics_ch1_mc_raw.txt",
            "--answer-key",
            "benchmarks/ethics_ch1_mc_answer_key.txt",
            "--output",
            str(output),
            "--document-id",
            "1",
            "--id-prefix",
            "ch1-q",
        ]
    )
    text = capsys.readouterr().out
    quiz = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output.exists()
    assert quiz["generated_count"] == 10
    assert quiz["questions"][6]["correct"] == "E"
    assert "Imported MC quiz" in text
    assert "keyed: 10" in text


def test_mc_prompt_formats_context_options_and_json_instruction(tmp_path):
    prompt_path = tmp_path / "mc.md"
    prompt_path.write_text(
        "Q: {question}\nLabels: {option_labels}\nOptions:\n{options}\nContext:\n{context}\nJSON only",
        encoding="utf-8",
    )
    item = {
        "question": "What does virtue ethics emphasize?",
        "target": "virtue ethics",
        "options": {"A": "Rules", "B": "Character", "C": "Utility", "D": "Contracts"},
    }
    rows = [
        {
            "id": 1,
            "source_citation": "quiz.pdf p. 1, chunk 1",
            "section_label": "chapter_content",
            "content_role": "core",
            "text": "Virtue ethics emphasizes character.",
        }
    ]

    prompt = build_mc_prompt(item, rows, max_chars=80, prompt_path=prompt_path)

    assert "Q: What does virtue ethics emphasize?" in prompt
    assert "Labels: A, B, C, D" in prompt
    assert "virtue ethics" in prompt
    assert "B. Character" in prompt
    assert "source_citation: quiz.pdf p. 1, chunk 1" in prompt
    assert "Virtue ethics emphasizes character." in prompt


def test_generate_quiz_cli_writes_versioned_json(tmp_path, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    output = tmp_path / "nested" / "quiz.json"
    conn = connect(db_path)
    init_db(conn)
    document_id = _stored_quiz_document(conn)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "generate-quiz",
            str(document_id),
            "--output",
            str(output),
            "--limit",
            "1",
            "--seed",
            "3",
        ]
    )
    generated = json.loads(output.read_text(encoding="utf-8"))
    text = capsys.readouterr().out

    assert exit_code == 0
    assert output.exists()
    assert generated["version"] == "mc-quiz-v1"
    assert generated["difficulty"] == "medium"
    assert generated["generated_count"] == 1
    assert "correct" in generated["questions"][0]
    assert "Generated quiz" in text


def test_mc_bench_cli_scores_keyed_and_unkeyed_items(tmp_path, capsys, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    quiz_path = tmp_path / "quiz.json"
    report_path = tmp_path / "report.json"
    conn = connect(db_path)
    init_db(conn)
    document_id = _stored_quiz_document(conn)
    quiz = generate_quiz(conn, document_id, source="terms", limit=2, seed=5)
    quiz["questions"][1].pop("correct")
    quiz_path.write_text(json.dumps(quiz), encoding="utf-8")

    calls = []

    def fake_create_client(host, timeout):
        return object()

    def fake_answer_mc_question(**kwargs):
        calls.append(kwargs)
        return MCAnswerResult(
            raw_prompt=kwargs["prompt"],
            raw_response='{"selected_option":"%s"}' % quiz["questions"][0]["correct"],
            selected_option=quiz["questions"][0]["correct"],
            validation_status="valid",
            validation_error=None,
        )

    monkeypatch.setattr("ethnos.cli.create_client", fake_create_client)
    monkeypatch.setattr("ethnos.cli.answer_mc_question", fake_answer_mc_question)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "mc-bench",
            str(document_id),
            "--quiz",
            str(quiz_path),
            "--output",
            str(report_path),
            "--max-questions",
            "2",
        ]
    )
    output = capsys.readouterr().out
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert len(calls) == 2
    assert report["keyed_total"] == 1
    assert report["scored_total"] == 1
    assert report["correct_count"] == 1
    assert report["accuracy"] == 1.0
    assert report["items"][0]["options"] == quiz["questions"][0]["options"]
    assert report["items"][0]["source_record_type"] == quiz["questions"][0]["source_record_type"]
    assert report["items"][0]["source_record_id"] == quiz["questions"][0]["source_record_id"]
    assert report["items"][0]["target"] == quiz["questions"][0]["target"]
    assert report["items"][0]["selected_option_text"] == quiz["questions"][0]["options"][
        quiz["questions"][0]["correct"]
    ]
    assert report["items"][0]["correct_option_text"] == quiz["questions"][0]["options"][
        quiz["questions"][0]["correct"]
    ]
    assert report["items"][1]["status"] == "unkeyed"
    assert "accuracy: 100.0%" in output
    assert "status: correct" in output
    assert "status: unkeyed" in output


def test_mc_context_adds_missing_generated_source_chunk(tmp_path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document_id = _stored_quiz_document(conn)
    quiz = generate_quiz(conn, document_id, source="terms", limit=1, seed=5)
    item = quiz["questions"][0]
    existing_rows = []

    rows = _add_quiz_source_context(
        conn,
        document_id,
        existing_rows,
        item,
        role="core",
        section=None,
    )

    assert [row["id"] for row in rows] == item["source_chunks"]
    assert rows[0]["text"]
    assert rows[0]["source_citation"] == item["source_citation"]


def test_mc_bench_skips_no_context_and_can_retry_with_options(tmp_path, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    quiz_path = tmp_path / "quiz.json"
    report_path = tmp_path / "report.json"
    conn = connect(db_path)
    init_db(conn)
    document_id = _stored_quiz_document(conn)
    quiz = {
        "questions": [
            {
                "id": "q1",
                "question": "What is it?",
                "options": {
                    "A": "Virtue ethics",
                    "B": "Virtue ethics",
                    "C": "Virtue ethics",
                    "D": "Virtue ethics",
                },
                "correct": "A",
            }
        ]
    }
    quiz_path.write_text(json.dumps(quiz), encoding="utf-8")
    calls = []

    def fake_answer_mc_question(**kwargs):
        calls.append(kwargs)
        return MCAnswerResult(
            raw_prompt=kwargs["prompt"],
            raw_response='{"selected_option":"A"}',
            selected_option="A",
            validation_status="valid",
            validation_error=None,
        )

    monkeypatch.setattr("ethnos.cli.create_client", lambda host, timeout: object())
    monkeypatch.setattr("ethnos.cli.answer_mc_question", fake_answer_mc_question)

    no_retry = main(
        [
            "--db",
            str(db_path),
            "mc-bench",
            str(document_id),
            "--quiz",
            str(quiz_path),
            "--output",
            str(report_path),
        ]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert no_retry == 0
    assert calls == []
    assert report["no_context_count"] == 1

    retry_report = tmp_path / "retry.json"
    retry = main(
        [
            "--db",
            str(db_path),
            "mc-bench",
            str(document_id),
            "--quiz",
            str(quiz_path),
            "--output",
            str(retry_report),
            "--options-retrieval",
        ]
    )
    retried = json.loads(retry_report.read_text(encoding="utf-8"))

    assert retry == 0
    assert len(calls) == 1
    assert retried["scored_total"] == 1
    assert retried["items"][0]["retrieval_questions"][1].startswith("What is it? Virtue ethics")


def test_mc_bench_uses_external_retrieval_queries(tmp_path, monkeypatch):
    db_path = tmp_path / "ethnos.sqlite"
    quiz_path = tmp_path / "quiz.json"
    report_path = tmp_path / "report.json"
    conn = connect(db_path)
    init_db(conn)
    document_id = _stored_quiz_document(conn)
    quiz = {
        "questions": [
            {
                "id": "q1",
                "question": "What is it?",
                "retrieval_queries": ["virtue ethics"],
                "options": {"A": "True", "B": "False"},
                "correct": "A",
            }
        ]
    }
    quiz_path.write_text(json.dumps(quiz), encoding="utf-8")

    monkeypatch.setattr("ethnos.cli.create_client", lambda host, timeout: object())
    monkeypatch.setattr(
        "ethnos.cli.answer_mc_question",
        lambda **kwargs: MCAnswerResult(
            raw_prompt=kwargs["prompt"],
            raw_response='{"selected_option":"A"}',
            selected_option="A",
            validation_status="valid",
            validation_error=None,
        ),
    )

    assert (
        main(
            [
                "--db",
                str(db_path),
                "mc-bench",
                str(document_id),
                "--quiz",
                str(quiz_path),
                "--output",
                str(report_path),
            ]
        )
        == 0
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["no_context_count"] == 0
    assert report["items"][0]["retrieval_questions"] == ["What is it?", "virtue ethics"]


def _stored_quiz_document(conn) -> int:
    document = DocumentRecord(
        source_path="/tmp/quiz.pdf",
        filename="quiz.pdf",
        sha256="quiz-fixture",
        title="Quiz",
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
    chunks = [
        ChunkRecord(
            document_id=document_id,
            page_start=index,
            page_end=index,
            chunk_index=index,
            text=text,
            char_count=len(text),
            source_citation=f"quiz.pdf p. {index}, chunk {index}",
        )
        for index, text in enumerate(
            [
                "Virtue ethics emphasizes character and habits.",
                "Utilitarianism emphasizes consequences and utility.",
                "Deontology emphasizes duties and moral rules.",
                "Social contract theory emphasizes agreements and political order.",
            ],
            start=1,
        )
    ]
    save_chunks(conn, document_id, chunks)
    conn.execute(
        """
        UPDATE chunks
        SET section_label = 'chapter_content', content_role = 'core', section_confidence = 1.0
        WHERE document_id = ?
        """,
        (document_id,),
    )
    conn.commit()
    stored_chunks = conn.execute(
        "SELECT id, chunk_index FROM chunks WHERE document_id = ? ORDER BY chunk_index",
        (document_id,),
    ).fetchall()
    for row, result in zip(stored_chunks, _quiz_results()):
        save_extraction_result(conn, row["id"], result)
    return document_id


def _quiz_results() -> list[ExtractionResult]:
    return [
        ExtractionResult.model_validate(data)
        for data in [
            {
                "chunk_summary": "Virtue ethics.",
                "topics": [
                    {"name": "Ethical theories", "summary": "Theory", "confidence": 1, "source_pages": [1]}
                ],
                "key_terms": [
                    {
                        "term": "Virtue ethics",
                        "definition": "An ethical approach that emphasizes character, habits, and moral virtues.",
                        "context": "",
                        "source_pages": [1],
                    }
                ],
                "examples": [],
                "questions": [
                    {
                        "question": "What does virtue ethics emphasize?",
                        "answer": "It emphasizes character, habits, and moral virtues in ethical life.",
                        "difficulty": "medium",
                        "source_pages": [1],
                    }
                ],
            },
            {
                "chunk_summary": "Utilitarianism.",
                "topics": [
                    {"name": "Ethical theories", "summary": "Theory", "confidence": 1, "source_pages": [2]}
                ],
                "key_terms": [
                    {
                        "term": "Utilitarianism",
                        "definition": "An ethical approach that judges actions by consequences and overall utility.",
                        "context": "",
                        "source_pages": [2],
                    }
                ],
                "examples": [],
                "questions": [
                    {
                        "question": "What does utilitarianism emphasize?",
                        "answer": "It emphasizes consequences and overall utility when judging actions.",
                        "difficulty": "medium",
                        "source_pages": [2],
                    }
                ],
            },
            {
                "chunk_summary": "Deontology.",
                "topics": [
                    {"name": "Ethical theories", "summary": "Theory", "confidence": 1, "source_pages": [3]}
                ],
                "key_terms": [
                    {
                        "term": "Deontology",
                        "definition": "An ethical approach that emphasizes duties, rules, and moral obligations.",
                        "context": "",
                        "source_pages": [3],
                    }
                ],
                "examples": [],
                "questions": [
                    {
                        "question": "What does deontology emphasize?",
                        "answer": "It emphasizes duties, rules, and moral obligations.",
                        "difficulty": "medium",
                        "source_pages": [3],
                    }
                ],
            },
            {
                "chunk_summary": "Social contract.",
                "topics": [
                    {"name": "Political ethics", "summary": "Theory", "confidence": 1, "source_pages": [4]}
                ],
                "key_terms": [
                    {
                        "term": "Social contract theory",
                        "definition": "An ethical and political approach that emphasizes agreements and social order.",
                        "context": "",
                        "source_pages": [4],
                    }
                ],
                "examples": [],
                "questions": [
                    {
                        "question": "What does social contract theory emphasize?",
                        "answer": "It emphasizes agreements, consent, and political order.",
                        "difficulty": "medium",
                        "source_pages": [4],
                    }
                ],
            },
        ]
    ]


def _record(record_id: int, chunk_index: int, answer: str, target: str | None = None):
    from ethnos.quiz import QuizSourceRecord

    return QuizSourceRecord(
        source_record_type="key_terms",
        source_record_id=record_id,
        chunk_id=chunk_index,
        chunk_index=chunk_index,
        section_label="chapter_content",
        content_role="core",
        source_citation=f"quiz.pdf p. {chunk_index}, chunk {chunk_index}",
        source_pages=[chunk_index],
        question=f"Question {record_id}?",
        correct_answer=answer,
        target=target,
        difficulty="medium",
    )
