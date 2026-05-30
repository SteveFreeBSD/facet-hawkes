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
    DistractorReview,
    EvidenceCitation,
    ModelProfile,
    QuestionQualityFinding,
)
from .agent_tools import (
    COMMON_ANSWER_SPELLING_FIXES,
    AgentToolContext,
    answer_support_details,
    build_agent_tool_registry,
    call_agent_tool,
)
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
    preflight = call_agent_tool(
        registry,
        "ground_quiz_item",
        {"item_id": item.get("id")},
    )
    observations.append(preflight.model_dump(mode="json"))
    tool_calls.append("ground_quiz_item")
    _write_trace(
        trace_path,
        {
            "item_id": item.get("id"),
            "kind": "tool_result",
            "phase": "preflight",
            "result": preflight.model_dump(mode="json"),
        },
    )

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
        action = _repair_item_scoped_action(action, item)
        tool_calls.append(action.tool)
        _write_trace(
            trace_path,
            {"item_id": item.get("id"), "kind": "model_action", "action": parsed_json},
        )
        if action.tool == "finalize_item_review":
            final = action.final_review
            assert final is not None
            evidence = _evidence_from_observations(observations)
            return _merge_review_defaults(
                item,
                final,
                quality_findings,
                tool_calls,
                grounding=_latest_grounding(observations),
                evidence=evidence,
            )
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


def _repair_item_scoped_action(
    action: AgentAction,
    item: dict[str, Any],
) -> AgentAction:
    if action.tool not in {"ground_quiz_item", "compare_options"}:
        return action
    arguments = dict(action.arguments)
    item_id = item.get("id")
    if "item_id" not in arguments:
        for alias in ("question_id", "id"):
            if alias in arguments:
                arguments["item_id"] = arguments[alias]
                break
    if "item_id" not in arguments and item_id:
        arguments["item_id"] = item_id
    return action.model_copy(update={"arguments": arguments})


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
        f"- review priorities: {json.dumps(getattr(report, 'priority_counts', {}), sort_keys=True)}",
        "",
        "## Review Queue",
        "",
        *_review_queue_lines(report.items),
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
                f"**Priority:** `{item.review_priority}`",
                "",
                f"**Evidence strength:** `{item.evidence_strength}` "
                f"({item.confidence_score:.2f})",
                "",
                item.question,
                "",
                f"**Keyed:** {item.keyed_option or 'n/a'}"
                + (f" - {item.keyed_option_text}" if item.keyed_option_text else ""),
                "",
                f"**Support:** {item.support_reason or 'n/a'}",
                "",
                item.explanation,
                "",
            ]
        )
        if item.distractor_verdicts:
            lines.append("Distractor audit:")
            for distractor in item.distractor_verdicts.values():
                lines.append(
                    f"- `{distractor.option}` {distractor.option_text}: "
                    f"`{distractor.verdict}` ({distractor.confidence_score:.2f})"
                )
            lines.append("")
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


def _review_queue_lines(items: list[AgentReviewItem]) -> list[str]:
    priority_order = {"fix": 0, "inspect": 1, "pass": 2}
    queued = sorted(
        items,
        key=lambda item: (
            priority_order.get(item.review_priority, 9),
            item.confidence_score,
            item.id,
        ),
    )
    lines = []
    for item in queued[:10]:
        if item.review_priority == "pass":
            continue
        note = item.support_reason or item.verdict
        lines.append(
            f"- `{item.review_priority}` `{item.id}`: {item.verdict}, "
            f"{item.evidence_strength} evidence ({item.confidence_score:.2f}) - {note}"
        )
    if not lines:
        return ["- No fix or inspection items were identified."]
    return lines


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
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    keyed_text = options.get(correct) if isinstance(correct, str) else None
    evidence = _evidence_from_observations(observations)
    evidence_rows = _evidence_rows(evidence)
    key_support = _key_support_details(
        grounding=grounding,
        keyed_option_text=keyed_text,
        evidence_rows=evidence_rows,
    )
    verdict = _fallback_verdict(
        source_status=source_status,
        key_support=key_support,
    )
    review_reason = (
        None if verdict == "key_supported" else "model_final_review_unavailable"
    )
    explanation = _fallback_explanation(verdict, key_support)
    review_priority = _review_priority(
        verdict=verdict,
        evidence_strength=str(key_support["evidence_strength"]),
        quality_findings=quality_findings,
    )
    return AgentReviewItem(
        id=str(item.get("id") or ""),
        question=str(item.get("question") or ""),
        verdict=verdict,
        keyed_option=str(correct) if isinstance(correct, str) else None,
        keyed_option_text=options.get(correct) if isinstance(correct, str) else None,
        explanation=explanation,
        evidence_strength=str(key_support["evidence_strength"]),
        confidence_score=float(key_support["confidence_score"]),
        support_reason=str(key_support["support_reason"]),
        distractor_verdicts=_distractor_verdicts(
            options=options,
            correct=correct,
            evidence_rows=evidence_rows,
            key_supported=verdict == "key_supported",
        ),
        evidence=evidence,
        quality_findings=quality_findings,
        source_status=str(source_status) if source_status else None,
        tool_calls=tool_calls,
        needs_human_review_reason=review_reason,
        review_priority=review_priority,
    )


def _fallback_verdict(
    *,
    source_status: object,
    key_support: dict[str, object],
) -> str:
    if source_status in {"ungrounded", "source_missing_in_local_pdf"}:
        return "source_missing"
    if key_support.get("supported") is True:
        return "key_supported"
    return "needs_human_review"


def _fallback_explanation(verdict: str, key_support: dict[str, object]) -> str:
    if verdict == "key_supported":
        return (
            "The model did not produce a validated final review, but deterministic "
            "retrieval found PDF evidence supporting the keyed answer. "
            f"Evidence strength is {key_support['evidence_strength']}."
        )
    if verdict == "source_missing":
        return (
            "The model did not produce a validated final review, and deterministic "
            "retrieval did not find usable local PDF evidence for this item."
        )
    return (
        "The deterministic agent tools collected available context, but the model "
        "did not produce a validated final review. This item needs human review."
    )


def _key_support_details(
    *,
    grounding: dict[str, Any],
    keyed_option_text: str | None,
    evidence_rows: list[dict[str, object]],
) -> dict[str, object]:
    support = grounding.get("keyed_answer_support")
    if isinstance(support, dict):
        return support
    if keyed_option_text:
        return answer_support_details(keyed_option_text, evidence_rows)
    return {
        "supported": False,
        "evidence_strength": "missing",
        "confidence_score": 0.0,
        "support_reason": "No keyed answer text was available to score.",
        "hit_terms": [],
    }


def _distractor_verdicts(
    *,
    options: dict[str, Any],
    correct: object,
    evidence_rows: list[dict[str, object]],
    key_supported: bool,
) -> dict[str, DistractorReview]:
    verdicts: dict[str, DistractorReview] = {}
    for option, option_text in options.items():
        if option == correct:
            continue
        text = str(option_text)
        support = answer_support_details(text, evidence_rows)
        strength = str(support["evidence_strength"])
        if support["supported"]:
            verdict = "ambiguous" if key_supported else "plausible_but_wrong"
            rationale = (
                "The retrieved evidence also contains direct or sufficient terms "
                "for this distractor, so a reviewer should inspect the item."
            )
        elif strength == "weak":
            verdict = "plausible_but_wrong"
            rationale = (
                "The retrieved evidence mentions some distractor terms, but not "
                "enough to support it as the answer."
            )
        else:
            verdict = "not_discussed"
            rationale = (
                "The retrieved evidence does not materially discuss this option."
            )
        verdicts[str(option)] = DistractorReview(
            option=str(option),
            option_text=text,
            verdict=verdict,
            confidence_score=float(support["confidence_score"]),
            rationale=rationale,
        )
    return verdicts


def _review_priority(
    *,
    verdict: str,
    evidence_strength: str,
    quality_findings: list[QuestionQualityFinding],
) -> str:
    if verdict in {"source_missing", "key_conflict_candidate", "ambiguous_question"}:
        return "fix"
    if verdict != "key_supported":
        return "inspect"
    if evidence_strength in {"missing", "weak"}:
        return "inspect"
    if quality_findings:
        return "inspect"
    return "pass"


def _merge_review_defaults(
    item: dict[str, Any],
    review: AgentReviewItem,
    quality_findings: list[QuestionQualityFinding],
    tool_calls: list[str],
    *,
    grounding: dict[str, Any] | None = None,
    evidence: list[EvidenceCitation] | None = None,
) -> AgentReviewItem:
    options = item.get("options") if isinstance(item.get("options"), dict) else {}
    correct = item.get("correct")
    merged_findings = [*review.quality_findings, *quality_findings]
    merged_evidence = review.evidence or evidence or []
    evidence_rows = _evidence_rows(merged_evidence)
    keyed_text = options.get(correct) if isinstance(correct, str) else None
    key_support = _key_support_details(
        grounding=grounding or {},
        keyed_option_text=keyed_text,
        evidence_rows=evidence_rows,
    )
    evidence_strength = (
        str(key_support["evidence_strength"])
        if review.evidence_strength == "missing"
        else review.evidence_strength
    )
    confidence_score = (
        float(key_support["confidence_score"])
        if review.confidence_score == 0
        else review.confidence_score
    )
    review_priority = (
        _review_priority(
            verdict=review.verdict,
            evidence_strength=evidence_strength,
            quality_findings=merged_findings,
        )
        if review.review_priority == "inspect"
        else review.review_priority
    )
    return review.model_copy(
        update={
            "id": review.id or str(item.get("id") or ""),
            "question": review.question or str(item.get("question") or ""),
            "keyed_option": review.keyed_option
            or (str(correct) if isinstance(correct, str) else None),
            "keyed_option_text": review.keyed_option_text
            or (options.get(correct) if isinstance(correct, str) else None),
            "quality_findings": merged_findings,
            "evidence": merged_evidence,
            "evidence_strength": evidence_strength,
            "confidence_score": confidence_score,
            "support_reason": review.support_reason or key_support["support_reason"],
            "distractor_verdicts": review.distractor_verdicts
            or _distractor_verdicts(
                options=options,
                correct=correct,
                evidence_rows=evidence_rows,
                key_supported=review.verdict == "key_supported",
            ),
            "review_priority": review_priority,
            "tool_calls": [*tool_calls, *review.tool_calls],
        }
    )


def _latest_grounding(observations: list[dict[str, Any]]) -> dict[str, Any]:
    for observation in reversed(observations):
        result = observation.get("result")
        if isinstance(result, dict) and isinstance(result.get("grounding"), dict):
            return result["grounding"]
    return {}


def _evidence_from_observations(
    observations: list[dict[str, Any]],
) -> list[EvidenceCitation]:
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
                    page=row.get("page_start")
                    if isinstance(row.get("page_start"), int)
                    else None,
                    citation=str(row.get("source_citation") or ""),
                    snippet=str(row.get("text") or row.get("snippet") or "")[:500],
                )
            )
    return citations[:5]


def _evidence_rows(evidence: list[EvidenceCitation]) -> list[dict[str, object]]:
    return [
        {
            "id": citation.chunk_id,
            "page_start": citation.page,
            "source_citation": citation.citation,
            "text": citation.snippet,
        }
        for citation in evidence
    ]


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
        finding.finding_type for item in reviews for finding in item.quality_findings
    )
    priority_counts = Counter(item.review_priority for item in reviews)
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
        priority_counts=dict(sorted(priority_counts.items())),
        items=reviews,
        tool_trace_path=str(trace_path) if trace_path else None,
    )


def _duplicate_question_findings(
    items: list[dict[str, Any]],
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


def _typo_findings(
    items: list[dict[str, Any]],
) -> dict[str, list[QuestionQualityFinding]]:
    findings: dict[str, list[QuestionQualityFinding]] = {}
    for item in items:
        option_text = " ".join(
            str(value)
            for value in (
                item.get("options", {}).values()
                if isinstance(item.get("options"), dict)
                else []
            )
        )
        for typo, correction in COMMON_ANSWER_SPELLING_FIXES.items():
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
