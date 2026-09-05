from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from ethnos.agent_loop import render_agent_review_markdown, run_agent_review
from ethnos.agent_models import (
    AgentAction,
    AgentReviewItem,
    MODEL_PROFILES,
    resolve_model_profile,
)
from ethnos.agent_tools import (
    AgentToolContext,
    answer_support_details,
    build_agent_tool_registry,
    call_agent_tool,
)
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


def test_model_profile_resolution_uses_its_profile_defaults():
    cpu_profile = resolve_model_profile(None)
    assert cpu_profile.name == "cpu-local"
    assert cpu_profile.recommended_model == "qwen3.5:9b"

    profile = resolve_model_profile("gemma3-local")

    assert profile.recommended_model == "gemma3:12b"
    assert profile.fallback_model == "gemma3:4b"
    assert profile.num_ctx == 65536

    explicit = resolve_model_profile("gemma3-fast", "custom:latest")

    assert explicit.recommended_model == "custom:latest"
    assert explicit.num_predict == MODEL_PROFILES["gemma3-fast"].num_predict


def test_answer_support_uses_normalized_token_boundaries_and_acronyms():
    assert (
        answer_support_details(
            "civil rights", [{"text": "An uprights culture is unrelated."}]
        )["supported"]
        is False
    )
    assert (
        answer_support_details("AIM", [{"text": "The AIM organized protests."}])[
            "evidence_strength"
        ]
        == "direct"
    )
    assert (
        answer_support_details("AIM", [{"text": "The A.I.M. organized protests."}])[
            "evidence_strength"
        ]
        == "direct"
    )
    assert (
        answer_support_details(
            "African American", [{"text": "African-American activists organized."}]
        )["evidence_strength"]
        == "direct"
    )
    assert (
        answer_support_details(
            "John F. Kennedy", [{"text": "John F Kennedy won the election."}]
        )["evidence_strength"]
        == "direct"
    )
    assert (
        answer_support_details(
            "interconnected", [{"text": "inter\u00adconnected systems"}]
        )["evidence_strength"]
        == "direct"
    )
    assert (
        answer_support_details("well-known", [{"text": "a well-\nknown organizer"}])[
            "evidence_strength"
        ]
        == "direct"
    )
    assert (
        answer_support_details(
            "César Chávez", [{"text": "Cesar Chavez organized farmworkers."}]
        )["evidence_strength"]
        == "direct"
    )
    assert (
        answer_support_details("not a victory", [{"text": "It was a victory."}])[
            "supported"
        ]
        is False
    )
    assert (
        answer_support_details(
            "not a victory", [{"text": "It was a victory, not a defeat."}]
        )["supported"]
        is False
    )
    assert (
        answer_support_details(
            "not a victory", [{"text": "It was not a victory for either side."}]
        )["supported"]
        is True
    )
    assert (
        answer_support_details("AIM", [{"text": "Their aim was reform."}])["supported"]
        is False
    )
    assert (
        answer_support_details("AIM", [{"text": "The claimant was unaimed."}])[
            "supported"
        ]
        is False
    )


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

    with pytest.raises(ValidationError, match="requires final_review"):
        AgentAction.model_validate({"tool": "finalize_item_review", "arguments": {}})

    with pytest.raises(ValidationError, match="only valid"):
        AgentAction.model_validate(
            {
                "tool": "ground_quiz_item",
                "arguments": {"item_id": "q1"},
                "final_review": parsed.final_review.model_dump(mode="json"),
            }
        )


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


def test_ground_quiz_item_skips_retrieval_for_declared_external_source(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()
    item = quiz["questions"][0]
    item["warnings"] = ["external_source_item"]
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={item["id"]: item},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
    )

    grounding = call_agent_tool(
        build_agent_tool_registry(context),
        "ground_quiz_item",
        {"item_id": item["id"]},
    )

    assert grounding.ok is True
    assert grounding.result["context_rows"] == []
    assert grounding.result["grounding"]["queries_tried"] == []
    assert (
        grounding.result["grounding"]["source_status"] == "source_missing_in_local_pdf"
    )
    assert (
        grounding.result["grounding"]["keyed_answer_support"]["evidence_strength"]
        == "missing"
    )


def test_ground_quiz_item_uses_declared_anchors_as_complete_context(tmp_path):
    conn = _agent_test_db(tmp_path)
    anchor = conn.execute(
        "SELECT id, source_citation FROM chunks WHERE chunk_index = 1"
    ).fetchone()
    item = {
        "id": "anchored",
        "question": "Who photographed tenement housing?",
        "question_type": "multiple_choice",
        "options": {"A": "Jacob Riis", "B": "A muckraker"},
        "correct": "A",
        "target": "Muckrakers",
        "source_chunks": [anchor["id"]],
        "source_pages": [1],
        "source_citation": anchor["source_citation"],
    }
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={item["id"]: item},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
    )

    grounding = call_agent_tool(
        build_agent_tool_registry(context),
        "ground_quiz_item",
        {"item_id": item["id"]},
    )

    assert grounding.ok is True
    assert [row["id"] for row in grounding.result["context_rows"]] == [anchor["id"]]
    assert grounding.result["grounding"]["source_chunks"] == [anchor["id"]]
    assert grounding.result["grounding"]["queries_tried"] == []
    assert grounding.result["grounding"]["keyed_answer_supported"] is False


def test_ground_quiz_item_uses_key_and_option_aware_queries(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz_with_key_only_evidence()
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={quiz["questions"][0]["id"]: quiz["questions"][0]},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
    )
    registry = build_agent_tool_registry(context)

    grounding = call_agent_tool(registry, "ground_quiz_item", {"item_id": "q2"})

    assert grounding.ok is True
    assert grounding.result["grounding"]["keyed_answer_supported"] is True
    assert (
        grounding.result["grounding"]["keyed_answer_support"]["evidence_strength"]
        == "direct"
    )
    assert any(
        "jacob riis" in query
        for query in grounding.result["grounding"]["queries_tried"]
    )
    assert (
        grounding.result["context_rows"][0]["source_citation"]
        == "history.pdf p. 2, chunk 2"
    )


def test_ground_quiz_item_supports_canonicalized_answer_text(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz_with_typo_key()
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={quiz["questions"][0]["id"]: quiz["questions"][0]},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
    )
    registry = build_agent_tool_registry(context)

    grounding = call_agent_tool(registry, "ground_quiz_item", {"item_id": "q3"})

    assert grounding.ok is True
    assert grounding.result["grounding"]["keyed_answer_supported"] is True
    assert any(
        "temperance" in query
        for query in grounding.result["grounding"]["queries_tried"]
    )
    assert (
        grounding.result["context_rows"][0]["source_citation"]
        == "history.pdf p. 3, chunk 3"
    )


def test_ground_quiz_item_ranks_conceptual_key_support_first(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz_with_conceptual_key()
    context = AgentToolContext(
        conn=conn,
        document_id=1,
        quiz_items={quiz["questions"][0]["id"]: quiz["questions"][0]},
        output_dir=tmp_path,
        allow_web=False,
        vision_pages="off",
        model_name="qwen3.5:9b",
        num_predict=256,
        num_ctx=8192,
    )
    registry = build_agent_tool_registry(context)

    grounding = call_agent_tool(registry, "ground_quiz_item", {"item_id": "q4"})

    assert grounding.ok is True
    assert grounding.result["grounding"]["keyed_answer_supported"] is True
    assert (
        grounding.result["context_rows"][0]["source_citation"]
        == "history.pdf p. 4, chunk 4"
    )


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
                    "id": "wrong-item",
                    "question": "Wrong model-supplied question",
                    "verdict": "key_supported",
                    "keyed_option": "B",
                    "keyed_option_text": "Industrialists",
                    "explanation": "The source identifies muckrakers as investigative journalists exposing corruption.",
                    "tool_calls": ["web_search"],
                    "evidence": [
                        {
                            "source": "pdf",
                            "chunk_id": 999,
                            "page": 999,
                            "citation": "fake.pdf p. 999, chunk 999",
                            "snippet": "Fabricated model citation.",
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
        item_timeout=None,
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
    finish_agent_run(
        conn, run_id, status="succeeded", summary=agent_report_summary(report)
    )

    rows = conn.execute(
        "SELECT * FROM agent_findings WHERE run_id = ?", (run_id,)
    ).fetchall()

    assert report.verdict_counts == {"key_supported": 1}
    assert report.priority_counts == {"pass": 1}
    assert report.model_finalized_count == 1
    assert report.fallback_item_count == 0
    assert report.items[0].evidence_strength == "direct"
    assert report.items[0].confidence_score > 0.9
    assert report.items[0].review_priority == "pass"
    assert report.items[0].id == "q1"
    assert report.items[0].question == "Which group exposed corruption?"
    assert report.items[0].keyed_option == "A"
    assert report.items[0].keyed_option_text == "Muckrakers"
    assert [citation.chunk_id for citation in report.items[0].evidence] == [1]
    assert report.items[0].evidence[0].citation == "history.pdf p. 1, chunk 1"
    assert "Fabricated" not in report.items[0].evidence[0].snippet
    assert "web_search" not in report.items[0].tool_calls
    assert report.items[0].distractor_verdicts["B"].verdict in {
        "not_discussed",
        "plausible_but_wrong",
    }
    assert (tmp_path / "agent_review" / "agent_review.md").exists()
    assert (tmp_path / "agent_review" / "agent_review.json").exists()
    assert (tmp_path / "agent_review" / "tool_trace.jsonl").exists()
    assert rows[0]["verdict"] == "key_supported"


def test_agent_loop_repairs_item_scoped_tool_arguments(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()
    quiz_path = tmp_path / "quiz.json"
    quiz_path.write_text(json.dumps(quiz), encoding="utf-8")

    def fake_structured_chat(**kwargs):
        messages = kwargs["messages"]
        if "Tool result:" not in messages[-1]["content"]:
            parsed = {
                "tool": "compare_options",
                "arguments": {
                    "item_id": "wrong-item",
                    "question_id": "also-wrong",
                },
            }
        else:
            parsed = {
                "tool": "finalize_item_review",
                "arguments": {},
                "final_review": {
                    "id": "q1",
                    "question": "Which group exposed corruption?",
                    "verdict": "key_supported",
                    "explanation": "Supported.",
                },
            }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=quiz_path,
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=2,
        item_timeout=None,
        debug_agent=True,
        client=object(),
        structured_chat=fake_structured_chat,
    )
    trace = (tmp_path / "agent_review" / "tool_trace.jsonl").read_text(encoding="utf-8")

    assert report.items[0].verdict == "key_supported"
    assert report.items[0].evidence_strength == "direct"
    assert report.items[0].review_priority == "pass"
    assert report.items[0].distractor_verdicts["B"].verdict == "not_discussed"
    assert '"keyed_option": "A"' in trace
    assert "Unknown quiz item id" not in trace
    assert '"error": null' in trace


def test_agent_loop_retries_runtime_invalid_action(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()
    calls = 0

    def fake_structured_chat(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            parsed = {
                "tool": "search_pdf",
                "arguments": {"query": "muckrakers"},
                "final_review": {
                    "id": "q1",
                    "question": "Which group exposed corruption?",
                    "verdict": "key_supported",
                    "explanation": "Premature payload.",
                },
            }
        else:
            assert (
                "failed runtime schema validation" in kwargs["messages"][-1]["content"]
            )
            parsed = {
                "tool": "finalize_item_review",
                "arguments": {},
                "final_review": {
                    "id": "q1",
                    "question": "Which group exposed corruption?",
                    "verdict": "key_supported",
                    "explanation": "Corrected final review.",
                },
            }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    output_dir = tmp_path / "agent_review"
    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=output_dir,
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=2,
        item_timeout=None,
        debug_agent=True,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    trace = (output_dir / "tool_trace.jsonl").read_text(encoding="utf-8")
    assert calls == 2
    assert report.items[0].model_finalized is True
    assert report.model_finalized_count == 1
    assert report.fallback_item_count == 0
    assert "model_action_invalid" in trace


def test_agent_anchored_review_excludes_later_unrelated_search_evidence(tmp_path):
    conn = _agent_test_db(tmp_path)
    anchor = conn.execute(
        "SELECT id, source_citation FROM chunks WHERE chunk_index = 1"
    ).fetchone()
    quiz = _sample_quiz()
    quiz["questions"][0].update(
        {
            "target": "Muckrakers",
            "source_chunks": [anchor["id"]],
            "source_pages": [1],
            "source_citation": anchor["source_citation"],
        }
    )
    calls = 0

    def fake_structured_chat(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            parsed = {
                "tool": "search_pdf",
                "arguments": {"query": "Jacob Riis"},
            }
        else:
            parsed = {
                "tool": "finalize_item_review",
                "arguments": {},
                "final_review": {
                    "id": "q1",
                    "question": "Which group exposed corruption?",
                    "verdict": "key_supported",
                    "explanation": "The anchored evidence supports the key.",
                    "evidence_strength": "direct",
                    "confidence_score": 0.98,
                },
            }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=2,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    assert [citation.chunk_id for citation in report.items[0].evidence] == [
        anchor["id"]
    ]
    assert "Jacob Riis" not in report.items[0].evidence[0].snippet


def test_agent_evidence_excerpt_keeps_late_support_and_trace_is_fresh(tmp_path):
    conn = _agent_test_db(tmp_path)
    long_text = (
        "Background material unrelated to the keyed answer. " * 40
    ) + "Muckrakers were investigative journalists who exposed corruption."
    conn.execute(
        "UPDATE chunks SET text = ?, char_count = ? WHERE chunk_index = 1",
        (long_text, len(long_text)),
    )
    conn.commit()
    anchor = conn.execute(
        "SELECT id, source_citation FROM chunks WHERE chunk_index = 1"
    ).fetchone()
    quiz = _sample_quiz()
    quiz["questions"][0].update(
        {
            "target": "Muckrakers",
            "source_chunks": [anchor["id"]],
            "source_pages": [1],
            "source_citation": anchor["source_citation"],
        }
    )
    output_dir = tmp_path / "agent_review"

    reports = []
    for _ in range(2):
        reports.append(
            run_agent_review(
                conn=conn,
                document_id=1,
                quiz=quiz,
                quiz_path=tmp_path / "quiz.json",
                output_dir=output_dir,
                model_name="qwen3.5:9b",
                model_profile=MODEL_PROFILES["cpu-local"],
                allow_web=False,
                vision_pages="off",
                max_steps=0,
                item_timeout=None,
                debug_agent=True,
                client=None,
            )
        )

    item = reports[-1].items[0]
    trace_lines = (
        (output_dir / "tool_trace.jsonl").read_text(encoding="utf-8").splitlines()
    )
    assert item.verdict == "key_supported"
    assert item.evidence_strength == "direct"
    assert "Muckrakers were investigative journalists" in item.evidence[0].snippet
    assert len(item.evidence[0].snippet) <= 900
    assert len(trace_lines) == 1


def test_agent_source_missing_fallback_discards_later_search_evidence(tmp_path):
    quiz = _sample_quiz()
    quiz["questions"][0]["warnings"] = ["external_source_item"]

    def fake_structured_chat(**_kwargs):
        parsed = {"tool": "search_pdf", "arguments": {"query": "muckrakers"}}
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=_agent_test_db(tmp_path),
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    assert report.items[0].verdict == "source_missing"
    assert report.items[0].evidence == []


def test_agent_source_missing_preflight_skips_model_call(tmp_path):
    quiz = _sample_quiz()
    quiz["questions"][0]["warnings"] = ["external_source_item"]
    calls = []

    def fake_structured_chat(**_kwargs):
        calls.append(True)
        raise AssertionError("deterministic source-missing status should short-circuit")

    report = run_agent_review(
        conn=_agent_test_db(tmp_path),
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=8,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    assert calls == []
    assert report.items[0].verdict == "source_missing"


def test_agent_fallback_can_support_key_from_evidence(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()
    quiz["questions"][0]["instructor_key_note"] = (
        "Instructor wording should be reviewed before publication."
    )
    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=None,
    )

    assert report.items[0].verdict == "key_supported"
    assert report.items[0].review_priority == "inspect"
    assert report.quality_counts == {"instructor_key_note": 1}
    assert report.model_finalized_count == 0
    assert report.fallback_item_count == 1


def test_agent_fallback_does_not_treat_same_chunk_mention_as_ambiguity(tmp_path):
    conn = _agent_test_db(tmp_path)
    anchor = conn.execute(
        "SELECT id, source_citation FROM chunks WHERE chunk_index = 1"
    ).fetchone()
    quiz = _sample_quiz()
    item = quiz["questions"][0]
    item.update(
        {
            "options": {
                "A": "Muckrakers",
                "B": "Investigative journalists",
            },
            "target": "Muckrakers",
            "source_chunks": [anchor["id"]],
            "source_pages": [1],
            "source_citation": anchor["source_citation"],
        }
    )

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=None,
    )

    item = report.items[0]
    assert item.verdict == "key_supported"
    assert item.distractor_verdicts["B"].verdict == "plausible_but_wrong"
    assert item.review_priority == "pass"


def test_agent_source_missing_does_not_report_incidental_partial_evidence(tmp_path):
    quiz = _sample_quiz()
    quiz["questions"][0]["warnings"] = ["external_source_item"]
    quiz["questions"][0]["source_missing_note"] = "Not present in the local PDF."

    report = run_agent_review(
        conn=_agent_test_db(tmp_path),
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=None,
    )

    item = report.items[0]
    assert item.verdict == "source_missing"
    assert item.evidence_strength == "missing"
    assert item.confidence_score == 0.0
    assert item.review_priority == "fix"
    assert item.evidence == []
    assert item.distractor_verdicts == {}


def test_agent_declared_external_source_overrides_conflicting_model_review(tmp_path):
    quiz = _sample_quiz()
    quiz["questions"][0]["warnings"] = ["external_source_item"]

    def fake_structured_chat(**_kwargs):
        parsed = {
            "tool": "finalize_item_review",
            "arguments": {},
            "final_review": {
                "id": "q1",
                "question": "Which group exposed corruption?",
                "verdict": "key_supported",
                "explanation": "Incidental terms appear in retrieval.",
                "evidence_strength": "partial",
                "confidence_score": 0.72,
                "support_reason": "Incidental retrieval overlap.",
                "review_priority": "pass",
                "evidence": [
                    {
                        "source": "pdf",
                        "chunk_id": 1,
                        "page": 1,
                        "citation": "history.pdf p. 1, chunk 1",
                        "snippet": "Incidental terms appear in retrieval.",
                    }
                ],
            },
        }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=_agent_test_db(tmp_path),
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    item = report.items[0]
    assert item.verdict == "source_missing"
    assert item.source_status == "source_missing_in_local_pdf"
    assert item.evidence_strength == "missing"
    assert item.confidence_score == 0.0
    assert (
        item.support_reason
        == "No usable local PDF evidence was available for this item."
    )
    assert item.review_priority == "fix"
    assert item.evidence == []
    assert "Incidental" not in item.explanation
    serialized = json.loads(
        (tmp_path / "agent_review" / "agent_review.json").read_text(encoding="utf-8")
    )["items"][0]
    markdown = (tmp_path / "agent_review" / "agent_review.md").read_text(
        encoding="utf-8"
    )
    assert serialized["evidence_strength"] == "missing"
    assert serialized["confidence_score"] == 0.0
    assert "source_missing, missing evidence (0.00)" in markdown


def test_agent_ungrounded_source_overrides_conflicting_model_review(tmp_path):
    quiz = _sample_quiz()
    quiz["questions"][0].update(
        {
            "question": "Which nonexistent lunar program is described?",
            "options": {"A": "Apollo 99", "B": "Gemini 99"},
        }
    )

    def fake_structured_chat(**_kwargs):
        parsed = {
            "tool": "finalize_item_review",
            "arguments": {},
            "final_review": {
                "id": "q1",
                "question": "Which nonexistent lunar program is described?",
                "verdict": "key_supported",
                "explanation": "Supported.",
                "evidence_strength": "direct",
                "confidence_score": 0.98,
                "review_priority": "pass",
                "evidence": [
                    {
                        "source": "pdf",
                        "chunk_id": 1,
                        "page": 1,
                        "citation": "history.pdf p. 1, chunk 1",
                        "snippet": "Unrelated evidence supplied by the model.",
                    }
                ],
            },
        }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=_agent_test_db(tmp_path),
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    item = report.items[0]
    assert item.source_status == "ungrounded"
    assert item.verdict == "source_missing"
    assert item.evidence_strength == "missing"
    assert item.confidence_score == 0.0
    assert item.review_priority == "fix"
    assert item.evidence == []


@pytest.mark.parametrize(
    ("evidence_strength", "confidence_score"),
    [("partial", 0.72), ("direct", 0.01)],
)
def test_agent_model_evidence_requires_strength_and_confidence_for_pass(
    tmp_path, evidence_strength, confidence_score
):
    conn = _agent_test_db(tmp_path)
    anchor = conn.execute(
        "SELECT id, source_citation FROM chunks WHERE chunk_index = 1"
    ).fetchone()
    quiz = _sample_quiz()
    quiz["questions"][0].update(
        {
            "target": "Muckrakers",
            "source_chunks": [anchor["id"]],
            "source_pages": [1],
            "source_citation": anchor["source_citation"],
        }
    )

    def fake_structured_chat(**_kwargs):
        parsed = {
            "tool": "finalize_item_review",
            "arguments": {},
            "final_review": {
                "id": "q1",
                "question": "Which group exposed corruption?",
                "verdict": "key_supported",
                "explanation": "Only partial support was identified.",
                "evidence_strength": evidence_strength,
                "confidence_score": confidence_score,
                "review_priority": "pass",
            },
        }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    item = report.items[0]
    assert item.verdict == "key_supported"
    assert item.evidence_strength == evidence_strength
    assert item.confidence_score == confidence_score
    assert item.review_priority == "inspect"


def test_agent_invalid_anchor_cannot_pass_from_incidental_key_support(tmp_path):
    conn = _agent_test_db(tmp_path)
    anchor = conn.execute("SELECT id FROM chunks WHERE chunk_index = 1").fetchone()
    quiz = _sample_quiz()
    item = quiz["questions"][0]
    item.update(
        {
            "target": "Muckrakers",
            "source_chunks": [anchor["id"]],
            "source_pages": [1],
            "source_citation": "history.pdf p. 99, chunk 99",
        }
    )

    def fake_structured_chat(**_kwargs):
        parsed = {
            "tool": "finalize_item_review",
            "arguments": {},
            "final_review": {
                "id": "q1",
                "question": "Which group exposed corruption?",
                "verdict": "source_missing",
                "explanation": "The model used the wrong blocking verdict.",
            },
        }
        return type("FakeStructuredResponse", (), {"parsed_json": parsed})()

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=None,
        debug_agent=False,
        client=object(),
        structured_chat=fake_structured_chat,
    )

    item = report.items[0]
    assert item.source_status == "invalid_anchor"
    assert item.verdict == "needs_human_review"
    assert item.review_priority == "inspect"
    assert "invalid_anchor" in item.explanation
    assert "declared anchors" in item.explanation
    assert "wrong blocking verdict" not in item.explanation


def test_agent_review_item_timeout_uses_deterministic_fallback(tmp_path):
    conn = _agent_test_db(tmp_path)
    quiz = _sample_quiz()

    def slow_structured_chat(**kwargs):
        time.sleep(0.05)

    report = run_agent_review(
        conn=conn,
        document_id=1,
        quiz=quiz,
        quiz_path=tmp_path / "quiz.json",
        output_dir=tmp_path / "agent_review",
        model_name="qwen3.5:9b",
        model_profile=MODEL_PROFILES["cpu-local"],
        allow_web=False,
        vision_pages="off",
        max_steps=1,
        item_timeout=0.01,
        debug_agent=False,
        client=object(),
        structured_chat=slow_structured_chat,
    )

    item = report.items[0]
    assert item.verdict == "key_supported"
    assert any(
        finding.finding_type == "agent_item_timeout"
        for finding in item.quality_findings
    )


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
            "priority_counts": {"inspect": 1},
            "items": [item],
        },
    )()

    markdown = render_agent_review_markdown(report)

    assert "# Agent Review" in markdown
    assert "Review Queue" in markdown
    assert "Evidence strength" in markdown
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
                "priority_counts": {"pass": 1},
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
                    "priority_counts": {"pass": 1},
                    "items": [item.model_dump(mode="json")],
                },
            },
        )()
        output_dir.mkdir(parents=True)
        (output_dir / "agent_review.md").write_text(
            "# Agent Review\n", encoding="utf-8"
        )
        (output_dir / "agent_review.json").write_text("{}", encoding="utf-8")
        return report

    monkeypatch.setenv("ETHNOS_DB_PATH", str(db_path))

    def unexpected_client(*_args, **_kwargs):
        raise AssertionError("deterministic-only review must not create a client")

    monkeypatch.setattr("ethnos.cli.create_client", unexpected_client)
    monkeypatch.setattr(
        "ethnos.cli.commands.agent.run_agent_review", fake_run_agent_review
    )

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
            "--max-steps",
            "0",
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
        item_timeout=None,
        debug_agent=False,
        client=None,
    )

    by_id = {item.id: item for item in report.items}

    assert report.item_count == 20
    assert sum(report.priority_counts.values()) == 20
    assert by_id["ch20-q015"].quality_findings[0].finding_type == "duplicate_prompt"
    assert by_id["ch20-q020"].quality_findings[0].finding_type == "duplicate_prompt"
    assert any(
        finding.finding_type == "typo"
        for finding in by_id["ch20-q009"].quality_findings
    )
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
    assert all(0.0 <= item.confidence_score <= 1.0 for item in report.items)
    assert all(
        item.evidence_strength != "missing"
        for item in report.items
        if item.verdict == "key_supported"
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
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=2,
                page_end=2,
                chunk_index=2,
                text="Jacob Riis photographed tenement housing to expose urban poverty.",
                char_count=64,
                source_citation="history.pdf p. 2, chunk 2",
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=3,
                page_end=3,
                chunk_index=3,
                text=(
                    "The WCTU was founded as a temperance organization, and "
                    "temperance and the full prohibition of alcohol loomed large."
                ),
                char_count=117,
                source_citation="history.pdf p. 3, chunk 3",
            ),
            ChunkRecord(
                document_id=document_id,
                page_start=4,
                page_end=4,
                chunk_index=4,
                text=(
                    "A host of social problems turned Americans toward reform "
                    "politics. Progressive reformers believed scientific expertise "
                    "and principles offered ways of solving social problems."
                ),
                char_count=166,
                source_citation="history.pdf p. 4, chunk 4",
            ),
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


def _sample_quiz_with_key_only_evidence():
    return {
        "version": "external-quiz-v2",
        "document_id": 1,
        "questions": [
            {
                "id": "q2",
                "question": "Which author used images to expose urban poverty?",
                "question_type": "multiple_choice",
                "options": {
                    "A": "Upton Sinclair",
                    "B": "Jacob Riis",
                    "C": "Mark Twain",
                    "D": "Edward Bellamy",
                },
                "correct": "B",
                "source_chunks": [],
                "source_pages": [],
            }
        ],
    }


def _sample_quiz_with_typo_key():
    return {
        "version": "external-quiz-v2",
        "document_id": 1,
        "questions": [
            {
                "id": "q3",
                "question": "What women's movement eventually led to Prohibition?",
                "question_type": "multiple_choice",
                "options": {
                    "A": "Suffrage",
                    "B": "Temperence",
                    "C": "Social Gospel",
                    "D": "Settlement houses",
                },
                "correct": "B",
                "source_chunks": [],
                "source_pages": [],
            }
        ],
    }


def _sample_quiz_with_conceptual_key():
    return {
        "version": "external-quiz-v2",
        "document_id": 1,
        "questions": [
            {
                "id": "q4",
                "question": "What belief guided many Progressive reformers?",
                "question_type": "multiple_choice",
                "options": {
                    "A": "Only businesses should lead reform",
                    "B": "Scientific principles could solve social problems",
                    "C": "Tradition should be preserved at all costs",
                    "D": "Government should not intervene in society",
                },
                "correct": "B",
                "source_chunks": [],
                "source_pages": [],
            }
        ],
    }
