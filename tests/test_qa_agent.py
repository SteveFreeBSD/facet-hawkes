from __future__ import annotations

from pathlib import Path

from ethnos.agent_tools import AgentToolContext, build_agent_tool_registry
from ethnos.db import connect, init_db, save_chunks, save_document_pages
from ethnos.models import ChunkRecord, DocumentRecord, PageRecord
from ethnos.qa_agent import (
    QAAgentAction,
    call_qa_agent_tool,
    run_agentic_qa,
)


def test_qa_agent_action_requires_final_answer_for_finalize():
    parsed = QAAgentAction.model_validate(
        {
            "tool": "finalize_answer",
            "arguments": {},
            "final_answer": {
                "answer": "Evolutionary ethics is discussed in the source.",
                "citations": ["labeled.pdf p. 1, chunk 1"],
                "evidence_chunk_ids": [1],
                "confidence_score": 0.9,
                "source_status": "source_supported",
            },
        }
    )

    assert parsed.final_answer is not None
    assert parsed.final_answer.source_status == "source_supported"


def test_qa_agent_tool_dispatch_rejects_non_v1_tools(tmp_path):
    conn = _qa_agent_db(tmp_path)
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
    )
    registry = build_agent_tool_registry(context)

    result = call_qa_agent_tool(registry, "web_search", {"query": "anything"})

    assert result.ok is False
    assert "not allowed" in str(result.error)


def test_qa_agent_loop_searches_inspects_and_finalizes(tmp_path):
    conn = _qa_agent_db(tmp_path)
    actions = iter(
        [
            {
                "tool": "search_pdf",
                "arguments": {"query": "evolutionary ethics", "limit": 2},
            },
            {"tool": "inspect_chunk", "arguments": {"chunk_id": 1}},
            {
                "tool": "finalize_answer",
                "arguments": {},
                "final_answer": {
                    "answer": "Evolutionary ethics connects ethics with evolution.",
                    "citations": ["labeled.pdf p. 1, chunk 1"],
                    "evidence_chunk_ids": [1],
                    "evidence_pages": [1],
                    "confidence_score": 0.92,
                    "source_status": "source_supported",
                },
            },
        ]
    )

    def fake_structured_chat(**kwargs):
        return type(
            "FakeStructuredResponse",
            (),
            {
                "parsed_json": next(actions),
                "response_summary": {"done_reason": "stop"},
            },
        )()

    result = run_agentic_qa(
        conn=conn,
        document_id=1,
        question="What is evolutionary ethics?",
        output_dir=tmp_path,
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
        think=False,
        role="core",
        section=None,
        limit=3,
        chars=900,
        max_steps=4,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    assert result.finalized is True
    assert result.answer_text.startswith("Evolutionary ethics")
    assert result.retrieval.rows[0]["source_citation"] == "labeled.pdf p. 1, chunk 1"
    assert [action["tool"] for action in result.trace["actions"]] == [
        "search_pdf",
        "inspect_chunk",
        "finalize_answer",
    ]


def test_qa_agent_invalid_model_action_falls_back(tmp_path):
    conn = _qa_agent_db(tmp_path)

    def fake_structured_chat(**kwargs):
        return type(
            "FakeStructuredResponse",
            (),
            {"parsed_json": None, "response_summary": {"done_reason": "stop"}},
        )()

    result = run_agentic_qa(
        conn=conn,
        document_id=1,
        question="What is evolutionary ethics?",
        output_dir=tmp_path,
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
        think=False,
        role="core",
        section=None,
        limit=3,
        chars=900,
        max_steps=4,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    assert result.finalized is False
    assert result.fallback_reason == "empty_or_invalid_model_action"
    assert result.trace["fallback_reason"] == "empty_or_invalid_model_action"


def _qa_agent_db(tmp_path: Path):
    conn = connect(tmp_path / "ethnos.sqlite")
    init_db(conn)
    document = DocumentRecord(
        source_path="/tmp/labeled.pdf",
        filename="labeled.pdf",
        sha256="qa-agent",
        title="QA Agent",
        page_count=1,
    )
    pages = [
        PageRecord(
            document_id=0,
            page_number=1,
            raw_text="Evolutionary ethics connects ethics with evolution.",
            cleaned_text="Evolutionary ethics connects ethics with evolution.",
            char_count=53,
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
                text="Evolutionary ethics connects ethics with evolution.",
                char_count=53,
                source_citation="labeled.pdf p. 1, chunk 1",
            )
        ],
    )
    conn.execute(
        """
        UPDATE chunks
        SET section_label = 'chapter_content', content_role = 'core',
            section_confidence = 1.0
        WHERE document_id = ?
        """,
        (document_id,),
    )
    conn.commit()
    return conn
