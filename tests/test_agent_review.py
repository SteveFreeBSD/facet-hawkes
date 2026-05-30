from __future__ import annotations

import json
from pathlib import Path

from ethnos.agent_loop import render_agent_review_markdown, run_agent_review
from ethnos.agent_models import (
    AgentAction,
    AgentReviewItem,
    MODEL_PROFILES,
    resolve_model_profile,
)
from ethnos.agent_tools import AgentToolContext, build_agent_tool_registry, call_agent_tool
from ethnos.cli import main
from ethnos.db import (
    agent_report_summary,
    connect,
    create_agent_run,
    finish_agent_run,
    init_db,
    save_agent_findings,
    save_chunks,
    save_document_pages,
)
from ethnos.models import ChunkRecord, DocumentRecord, PageRecord
from ethnos.quiz import load_quiz


def test_model_profile_resolution_uses_gemma3_defaults():
    profile = resolve_model_profile("gemma3-local")

    assert profile.recommended_model == "gemma3:12b"
    assert profile.fallback_model == "gemma3:4b"
    assert profile.num_ctx == 65536

    explicit = resolve_model_profile("gemma3-fast", "custom:latest")

    assert explicit.recommended_model == "custom:latest"
    assert explicit.num_predict == MODEL_PROFILES["gemma3-fast"].num_predict


def test_agent_action_requires_final_review_for_finalize():
    parsed = AgentAction.model_validate(
        {
            "tool": "finalize_item_review",
            "arguments": {},
            "final_review": {
                "id": "q1",
                "question": "What happened?",
                "verdict": "key_supported",
                "keyed_option": "A",
                "keyed_option_text": "Answer",
                "explanation": "Supported by the source.",
            },
        }
    )

    assert parsed.final_review is not None
    assert parsed.final_review.verdict == "key_supported"


def test_agent_tool_registry_dispatches_pdf_tools(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={quiz["questions"][0]["id"]: quiz["questions"][0]},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="gemma3:4b",
        num_predict=256,
        num_ctx=8192,
    )
    registry = build_agent_tool_registry(context)

    search = call_agent_tool(registry, "search_pdf", {"query": "muckrakers"})
    grounding = call_agent_tool(registry, "ground_quiz_item", {"item_id": "q1"})
    web = call_agent_tool(registry, "web_search", {"query": "muckrakers"})

    assert search.ok is True
    assert search.result["rows"][0]["source_citation"] == "history.pdf p. 1, chunk 1"
    assert grounding.ok is True
    assert grounding.result["grounding"]["source_status"] == "retrieved_candidate"
    assert web.ok is True
    assert web.result["status"] == "blocked"


def test_agent_review_writes_reports_and_persists_findings(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()
    quiz_path = tmp_path / "quiz.json"
    quiz_path.write_text(json.dumps(quiz), encoding="utf-8")

    def fake_structured_chat(**kwargs):
        messages = kwargs["messages"]
        if "Tool result:" not in messages[-1]["content"]:
            parsed = {
                "tool": "ground_quiz_item",
                "arguments": {"item_id": "q1"},
            }
        else:
            parsed = {
                "tool": "finalize_item_review",
                "arguments": {},
                "final_review": {
                    "id": "q1",
                    "question": "Which group exposed corruption?",
                    "verdict": "key_supported",
                    "keyed_option": "A",
                    "keyed_option_text": "Muckrakers",
                    "explanation": "The source identifies muckrakers as investigative journalists exposing corruption.",
                    "evidence": [
                        {
                            "source": "pdf",
                            "chunk_id": 1,
                            "page": 1,
                            "citation": "history.pdf p. 1, chunk 1",
                            "snippet": "Muckrakers were investigative journalists.",
                        }
                    ],
                },
            }
        return type(
            "FakeStructuredResponse",
            (),
            {
                "parsed_json": parsed,
                "validation_status": "valid",
                "validation_error": None,
            },
        )()

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=quiz_path,
        output_dir=tmp_path / "agent_review",
        model_name="gemma3:4b",
        model_profile=MODEL_PROFILES["gemma3-fast"],
        allow_web=False,
        vision_pages="off",
        max_steps=3,
        debug_agent=True,
        client=object(),
        structured_chat=fake_structured_chat,
    )
    run_id = create_agent_run(
        conn,
        document_id=1,
        quiz_path=quiz_path,
        model_name="gemma3:4b",
        model_profile="gemma3-fast",
        config={},
        output_path=tmp_path / "agent_review",
    )
    save_agent_findings(conn, run_id, report.items)
    finish_agent_run(conn, run_id, status="succeeded", summary=agent_report_summary(report))

    rows = conn.execute("SELECT * FROM agent_findings WHERE run_id = ?", (run_id,)).fetchall()

    assert report.verdict_counts == {"key_supported": 1}
    assert (tmp_path / "agent_review" / "agent_review.md").exists()
    assert (tmp_path / "agent_review" / "agent_review.json").exists()
    assert (tmp_path / "agent_review" / "tool_trace.jsonl").exists()
    assert rows[0]["verdict"] == "key_supported"


def test_agent_report_renderer_includes_quality_findings():
    item = AgentReviewItem(
        id="q9",
        question="What movement?",
        verdict="needs_human_review",
        keyed_option="B",
        keyed_option_text="Temperence",
        explanation="Needs review.",
    )
    report = type(
        "Report",
        (),
        {
            "document_id": 2,
            "quiz": "quiz.json",
            "model": "gemma3:4b",
            "model_profile": "gemma3-fast",
            "item_count": 1,
            "verdict_counts": {"needs_human_review": 1},
            "quality_counts": {},
            "items": [item],
        },
    )()

    markdown = render_agent_review_markdown(report)

    assert "# Agent Review" in markdown
    assert "q9" in markdown


def test_agent_review_cli_with_fake_agent(tmp_path, monkeypatch, capsys):
    db_path = tmp_path / "ethnos.sqlite"
    conn = _agent_test_db(tmp_path, db_path=db_path)
    conn.close()
    quiz_path = tmp_path / "quiz.json"
    quiz_path.write_text(json.dumps(_sample_quiz()), encoding="utf-8")

    def fake_run_agent_review(**kwargs):
        output_dir = kwargs["output_dir"]
        item = AgentReviewItem(
            id="q1",
            question="Which group exposed corruption?",
            verdict="key_supported",
            keyed_option="A",
            keyed_option_text="Muckrakers",
            explanation="Supported.",
        )
        report = type(
            "FakeReport",
            (),
            {
                "document_id": 1,
                "quiz": str(quiz_path),
                "model": kwargs["model_name"],
                "model_profile": kwargs["model_profile"].name,
                "allow_web": False,
                "vision_pages": "off",
                "item_count": 1,
                "verdict_counts": {"key_supported": 1},
                "quality_counts": {},
                "items": [item],
                "model_dump": lambda self, mode="json": {
                    "document_id": 1,
                    "quiz": str(quiz_path),
                    "model": kwargs["model_name"],
                    "model_profile": kwargs["model_profile"].name,
                    "allow_web": False,
                    "vision_pages": "off",
                    "item_count": 1,
                    "verdict_counts": {"key_supported": 1},
                    "quality_counts": {},
                    "items": [item.model_dump(mode="json")],
                },
            },
        )()
        output_dir.mkdir(parents=True)
        (output_dir / "agent_review.md").write_text("# Agent Review\n", encoding="utf-8")
        (output_dir / "agent_review.json").write_text("{}", encoding="utf-8")
        return report

    monkeypatch.setenv("ETHNOS_DB_PATH", str(db_path))
    monkeypatch.setattr("ethnos.cli.create_client", lambda host, timeout: object())
    monkeypatch.setattr("ethnos.cli.commands.agent.run_agent_review", fake_run_agent_review)

    exit_code = main(
        [
            "agent-review",
            "1",
            "--quiz",
            str(quiz_path),
            "--output",
            str(tmp_path / "out"),
            "--model",
            "gemma3:4b",
            "--profile",
            "cto",
            "--vision-pages",
            "off",
        ]
    )
    text = capsys.readouterr().out

    assert exit_code == 0
    assert "Agent review" in text
    assert (tmp_path / "out" / "agent_review.md").exists()


def test_history_ch20_agent_quality_acceptance(tmp_path):
    quiz = load_quiz(Path("benchmarks/history_ch20_canvas.json"))
    report = run_agent_review(
        conn=_agent_test_db(tmp_path),
        document_id=1,
        quiz=quiz,
        quiz_path=Path("benchmarks/history_ch20_canvas.json"),
        output_dir=tmp_path / "ethnos-agent-quality-test",
        model_name="gemma3:4b",
        model_profile=MODEL_PROFILES["gemma3-fast"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        debug_agent=False,
        client=None,
    )

    by_id = {item.id: item for item in report.items}

    assert report.item_count == 20
    assert by_id["ch20-q015"].quality_findings[0].finding_type == "duplicate_prompt"
    assert by_id["ch20-q020"].quality_findings[0].finding_type == "duplicate_prompt"
    assert any(finding.finding_type == "typo" for finding in by_id["ch20-q009"].quality_findings)
    assert all(
        item.verdict
        in {
            "key_supported",
            "source_missing",
            "needs_human_review",
            "ambiguous_question",
            "key_conflict_candidate",
        }
        for item in report.items
    )


def _agent_test_db(tmp_path, *, db_path=None):
    db_path = db_path or tmp_path / "ethnos.sqlite"
    conn = connect(db_path)
    init_db(conn)
    document = DocumentRecord(
        source_path=str(tmp_path / "history.pdf"),
        filename="history.pdf",
        sha256="history-agent-test",
        title="History",
        page_count=1,
        metadata={},
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="Muckrakers were investigative journalists who exposed corruption.",
            cleaned_text="Muckrakers were investigative journalists who exposed corruption.",
            char_count=68,
            extraction_method="test",
        )
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
                text="Muckrakers were investigative journalists who exposed corruption.",
                char_count=68,
                source_citation="history.pdf p. 1, chunk 1",
            )
        ],
    )
    conn.execute("UPDATE chunks SET content_role = 'core', section_label = 'chapter'")
    conn.execute("UPDATE pages SET content_role = 'core', section_label = 'chapter'")
    conn.commit()
    return conn


def _sample_quiz():
    return {
        "version": "external-quiz-v2",
        "document_id": 1,
        "questions": [
            {
                "id": "q1",
                "question": "Which group exposed corruption?",
                "question_type": "multiple_choice",
                "options": {"A": "Muckrakers", "B": "Industrialists"},
                "correct": "A",
                "source_chunks": [],
                "source_pages": [],
            }
        ],
    }
