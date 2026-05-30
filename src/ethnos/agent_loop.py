"""Structured action loop for source-grounded agent review."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .agent_models import (
    AgentAction,
    AgentReviewItem,
    AgentReviewReport,
    EvidenceCitation,
    ModelProfile,
    QuestionQualityFinding,
)
from .agent_tools import AgentToolContext, build_agent_tool_registry, call_agent_tool
from .ollama_client import structured_chat_json


StructuredChat = Callable[..., object]


def run_agent_review(
    *,
    conn,
    document_id: int,
    quiz: dict[str, Any],
    quiz_path: Path,
    output_dir: Path,
    model_name: str,
    model_profile: ModelProfile,
    allow_web: bool,
    vision_pages: str,
    max_steps: int,
    debug_agent: bool,
    client: object | None,
    structured_chat: StructuredChat = structured_chat_json,
) -> AgentReviewReport:
    items = quiz["questions"]
    quiz_items = {str(item["id"]): item for item in items}
    duplicate_findings = _duplicate_question_findings(items)
    typo_findings = _typo_findings(items)
    tool_context = AgentToolContext(
        conn=conn,
        document_id=document_id,
        quiz_items=quiz_items,
        output_dir=output_dir,
        allow_web=allow_web,
        vision_pages=vision_pages,
        model_name=model_name,
        num_predict=model_profile.num_predict,
        num_ctx=model_profile.num_ctx,
        client=client,
    )
    registry = build_agent_tool_registry(tool_context)
    output_dir.mkdir(parents=True, exist_ok=True)
    trace_path = output_dir / "tool_trace.jsonl" if debug_agent else None
    reviews = []
    for item in items:
        quality_findings = [
            *duplicate_findings.get(str(item["id"]), []),
            *typo_findings.get(str(item["id"]), []),
        ]
        reviews.append(
            review_quiz_item(
                item=item,
                registry=registry,
                model_name=model_name,
                model_profile=model_profile,
                max_steps=max_steps,
                client=client,
                structured_chat=structured_chat,
                quality_findings=quality_findings,
                trace_path=trace_path,
            )
        )
    report = _build_report(
        document_id=document_id,
        quiz_path=quiz_path,
        model_name=model_name,
        model_profile=model_profile,
        allow_web=allow_web,
        vision_pages=vision_pages,
        reviews=reviews,
        trace_path=trace_path,
    )
    write_agent_report(output_dir, report)
    return report


def review_quiz_item(
    *,
    item: dict[str, Any],
    registry,
    model_name: str,
    model_profile: ModelProfile,
    max_steps: int,
    client: object | None,
    structured_chat: StructuredChat,
    quality_findings: list[QuestionQualityFinding],
    trace_path: Path | None,
) -> AgentReviewItem:
    messages = _initial_messages(item)
    tool_calls: list[str] = []
    observations: list[dict[str, Any]] = []

    for _step in range(max_steps):
        if client is None:
            break
        response = structured_chat(
            client=client,
            model_name=model_name,
            messages=messages,
            schema=AgentAction.model_json_schema(),
            num_predict=model_profile.num_predict,
            num_ctx=model_profile.num_ctx,
            think=model_profile.think,
        )
        parsed_json = getattr(response, "parsed_json", None)
        if not parsed_json:
            break
        try:
            action = AgentAction.model_validate(parsed_json)
        except ValidationError:
            break
        tool_calls.append(action.tool)
        _write_trace(
            trace_path,
            {"item_id": item.get("id"), "kind": "model_action", "action": parsed_json},
        )
        if action.tool == "finalize_item_review":
            final = action.final_review
            assert final is not None
            return _merge_review_defaults(item, final, quality_findings, tool_calls)
        result = call_agent_tool(registry, action.tool, action.arguments)
        observations.append(result.model_dump(mode="json"))
        _write_trace(
            trace_path,
            {
                "item_id": item.get("id"),
                "kind": "tool_result",
                "result": result.model_dump(mode="json"),
            },
        )
        messages.append(
            {
                "role": "assistant",
                "content": json.dumps(parsed_json, sort_keys=True),
            }
        )
        messages.append(
            {
                "role": "user",
                "content": "Tool result:\n"
                + json.dumps(result.model_dump(mode="json"), sort_keys=True),
            }
        )

    return _fallback_review(item, observations, quality_findings, tool_calls)


def write_agent_report(output_dir: Path, report: AgentReviewReport) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "agent_review.json").write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    (output_dir / "agent_review.md").write_text(
        render_agent_review_markdown(report),
        encoding="utf-8",
    )


def render_agent_review_markdown(report: AgentReviewReport) -> str:
    lines = [
        "# Agent Review",
        "",
        f"- document_id: {report.document_id}",
        f"- quiz: `{report.quiz}`",
        f"- model: `{report.model}`",
        f"- model_profile: `{report.model_profile}`",
        f"- items: {report.item_count}",
        f"- verdicts: {json.dumps(report.verdict_counts, sort_keys=True)}",
        f"- quality findings: {json.dumps(report.quality_counts, sort_keys=True)}",
        "",
        "## Items",
        "",
    ]
    for item in report.items:
        lines.extend(
            [
                f"### {item.id}",
                "",
                f"**Verdict:** `{item.verdict}`",
                "",
                item.question,
                "",
                f"**Keyed:** {item.keyed_option or 'n/a'}"
                + (f" - {item.keyed_option_text}" if item.keyed_option_text else ""),
                "",
                item.explanation,
                "",
            ]
        )
        if item.evidence:
            lines.append("Evidence:")
            for citation in item.evidence:
                source = citation.citation or citation.source
                lines.append(f"- {source}: {citation.snippet}")
            lines.append("")
        if item.quality_findings:
            lines.append("Quality findings:")
            for finding in item.quality_findings:
                lines.append(
                    f"- `{finding.severity}` `{finding.finding_type}`: {finding.message}"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _initial_messages(item: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are an Ethnos source-grounded reviewer. "
                "Choose one tool call at a time, inspect evidence, and finalize only "
                "when your review is supported. Return only schema-valid JSON."
            ),
        },
        {
            "role": "user",
            "content": (
                "Review this quiz item. Start by calling ground_quiz_item or "
                "compare_options, then finalize with a verdict.\n"
                + json.dumps(item, sort_keys=True)
            ),
        },
    ]


def _fallback_review(
    item: dict[str, Any],
    observations: list[dict[str, Any]],
    quality_findings: list[QuestionQualityFinding],
    tool_calls: list[str],
) -> AgentReviewItem:
    grounding = _latest_grounding(observations)
    source_status = grounding.get("source_status") if grounding else None
    verdict = "source_missing" if source_status in {"ungrounded", "source_missing_in_local_pdf"} else "needs_human_review"
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    evidence = _evidence_from_observations(observations)
    return AgentReviewItem(
        id=str(item.get("id") or ""),
        question=str(item.get("question") or ""),
        verdict=verdict,
        keyed_option=str(correct) if isinstance(correct, str) else None,
        keyed_option_text=options.get(correct) if isinstance(correct, str) else None,
        explanation=(
            "The deterministic agent tools collected available context, but the model "
            "did not produce a validated final review. This item needs human review."
        ),
        evidence=evidence,
        quality_findings=quality_findings,
        source_status=str(source_status) if source_status else None,
        tool_calls=tool_calls,
        needs_human_review_reason="model_final_review_unavailable",
    )


def _merge_review_defaults(
    item: dict[str, Any],
    review: AgentReviewItem,
    quality_findings: list[QuestionQualityFinding],
    tool_calls: list[str],
) -> AgentReviewItem:
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    merged_findings = [*review.quality_findings, *quality_findings]
    return review.model_copy(
        update={
            "id": review.id or str(item.get("id") or ""),
            "question": review.question or str(item.get("question") or ""),
            "keyed_option": review.keyed_option
            or (str(correct) if isinstance(correct, str) else None),
            "keyed_option_text": review.keyed_option_text
            or (options.get(correct) if isinstance(correct, str) else None),
            "quality_findings": merged_findings,
            "tool_calls": [*tool_calls, *review.tool_calls],
        }
    )


def _latest_grounding(observations: list[dict[str, Any]]) -> dict[str, Any]:
    for observation in reversed(observations):
        result = observation.get("result")
        if isinstance(result, dict) and isinstance(result.get("grounding"), dict):
            return result["grounding"]
    return {}


def _evidence_from_observations(observations: list[dict[str, Any]]) -> list[EvidenceCitation]:
    citations: list[EvidenceCitation] = []
    for observation in observations:
        result = observation.get("result")
        if not isinstance(result, dict):
            continue
        rows = result.get("context_rows") or result.get("rows") or []
        if not isinstance(rows, list):
            continue
        for row in rows[:3]:
            if not isinstance(row, dict):
                continue
            citations.append(
                EvidenceCitation(
                    source="pdf",
                    chunk_id=row.get("id") if isinstance(row.get("id"), int) else None,
                    page=row.get("page_start") if isinstance(row.get("page_start"), int) else None,
                    citation=str(row.get("source_citation") or ""),
                    snippet=str(row.get("text") or row.get("snippet") or "")[:500],
                )
            )
    return citations[:5]


def _build_report(
    *,
    document_id: int,
    quiz_path: Path,
    model_name: str,
    model_profile: ModelProfile,
    allow_web: bool,
    vision_pages: str,
    reviews: list[AgentReviewItem],
    trace_path: Path | None,
) -> AgentReviewReport:
    verdict_counts = Counter(item.verdict for item in reviews)
    quality_counts = Counter(
        finding.finding_type
        for item in reviews
        for finding in item.quality_findings
    )
    return AgentReviewReport(
        document_id=document_id,
        quiz=str(quiz_path),
        model=model_name,
        model_profile=model_profile.name,
        allow_web=allow_web,
        vision_pages=vision_pages,
        item_count=len(reviews),
        verdict_counts=dict(sorted(verdict_counts.items())),
        quality_counts=dict(sorted(quality_counts.items())),
        items=reviews,
        tool_trace_path=str(trace_path) if trace_path else None,
    )


def _duplicate_question_findings(
    items: list[dict[str, Any]]
) -> dict[str, list[QuestionQualityFinding]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        key = " ".join(str(item.get("question") or "").lower().split())
        grouped.setdefault(key, []).append(item)
    findings: dict[str, list[QuestionQualityFinding]] = {}
    for group in grouped.values():
        if len(group) < 2:
            continue
        ids = ", ".join(str(item.get("id")) for item in group)
        for item in group:
            findings.setdefault(str(item.get("id")), []).append(
                QuestionQualityFinding(
                    severity="low",
                    finding_type="duplicate_prompt",
                    message=f"Question prompt is duplicated across: {ids}.",
                )
            )
    return findings


def _typo_findings(items: list[dict[str, Any]]) -> dict[str, list[QuestionQualityFinding]]:
    findings: dict[str, list[QuestionQualityFinding]] = {}
    typo_pairs = {"temperence": "Temperance"}
    for item in items:
        option_text = " ".join(
            str(value)
            for value in (
                item.get("options", {}).values()
                if isinstance(item.get("options"), dict)
                else []
            )
        )
        for typo, correction in typo_pairs.items():
            if typo in option_text.lower():
                findings.setdefault(str(item.get("id")), []).append(
                    QuestionQualityFinding(
                        severity="low",
                        finding_type="typo",
                        message=f"Option text contains '{typo}'; intended spelling is '{correction}'.",
                    )
                )
    return findings


def _write_trace(path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")
