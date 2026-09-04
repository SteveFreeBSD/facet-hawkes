"""Structured action loop for source-grounded agent review."""

from __future__ import annotations

import json
import signal
import threading
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from pydantic import ValidationError

from .agent_models import (
    AgentAction,
    AgentReviewItem,
    AgentReviewReport,
    AgentToolResult,
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
from .ollama_client import OllamaClientProtocol, structured_chat_json


StructuredChat = Callable[..., object]
ProgressCallback = Callable[[int, int, dict[str, Any]], None]


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
    item_timeout: float | None,
    debug_agent: bool,
    client: OllamaClientProtocol | None,
    structured_chat: StructuredChat = structured_chat_json,
    progress: ProgressCallback | None = None,
) -> AgentReviewReport:
    items = quiz["questions"]
    quiz_items = {str(item["id"]): item for item in items}
    duplicate_findings = _duplicate_question_findings(items)
    typo_findings = _typo_findings(items)
    instructor_note_findings = _instructor_note_findings(items)
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
    if trace_path is not None:
        trace_path.write_text("", encoding="utf-8")
    reviews = []
    for index, item in enumerate(items, start=1):
        if progress is not None:
            progress(index, len(items), item)
        quality_findings = [
            *duplicate_findings.get(str(item["id"]), []),
            *typo_findings.get(str(item["id"]), []),
            *instructor_note_findings.get(str(item["id"]), []),
        ]
        try:
            with _item_timeout(item_timeout):
                review = review_quiz_item(
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
        except AgentItemTimeout:
            timeout_finding = QuestionQualityFinding(
                severity="medium",
                finding_type="agent_item_timeout",
                message=(
                    f"Agent review exceeded the per-item timeout "
                    f"of {item_timeout:g} seconds and used deterministic fallback."
                ),
            )
            review = review_quiz_item(
                item=item,
                registry=registry,
                model_name=model_name,
                model_profile=model_profile,
                max_steps=0,
                client=None,
                structured_chat=structured_chat,
                quality_findings=[*quality_findings, timeout_finding],
                trace_path=trace_path,
            )
        reviews.append(review)
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


class AgentItemTimeout(TimeoutError):
    """Raised when one Agent Review item exceeds its total time budget."""


@contextmanager
def _item_timeout(seconds: float | None):
    if (
        seconds is None
        or seconds <= 0
        or not hasattr(signal, "SIGALRM")
        or threading.current_thread() is not threading.main_thread()
    ):
        yield
        return

    def _handle_timeout(_signum, _frame):
        raise AgentItemTimeout

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, seconds)
    signal.signal(signal.SIGALRM, _handle_timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *previous_timer)


def review_quiz_item(
    *,
    item: dict[str, Any],
    registry,
    model_name: str,
    model_profile: ModelProfile,
    max_steps: int,
    client: OllamaClientProtocol | None,
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
    grounding = preflight.result.get("grounding") if preflight.ok else None
    if _deterministic_grounding_terminal(grounding):
        return _fallback_review(item, observations, quality_findings, tool_calls)
    messages.append(
        {
            "role": "user",
            "content": (
                "Deterministic preflight grounding is complete. Finalize now if "
                "this evidence is sufficient; otherwise call one different tool. "
                "Do not repeat ground_quiz_item.\n"
                + json.dumps(preflight.model_dump(mode="json"), sort_keys=True)
            ),
        }
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
        except ValidationError as exc:
            _write_trace(
                trace_path,
                {
                    "item_id": item.get("id"),
                    "kind": "model_action_invalid",
                    "action": parsed_json,
                    "error": str(exc),
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
                    "content": (
                        "That action failed runtime schema validation. Correct it "
                        "and return one schema-valid action. final_review is required "
                        "only with finalize_item_review and forbidden for every other "
                        f"tool. Validation error: {exc}"
                    ),
                }
            )
            continue
        action = _repair_item_scoped_action(action, item)
        tool_calls.append(action.tool)
        _write_trace(
            trace_path,
            {"item_id": item.get("id"), "kind": "model_action", "action": parsed_json},
        )
        if action.tool == "finalize_item_review":
            final = action.final_review
            if final is None:
                break
            evidence = _evidence_from_observations(observations, item=item)
            return _merge_review_defaults(
                item,
                final,
                quality_findings,
                tool_calls,
                grounding=_latest_grounding(observations),
                evidence=evidence,
            )
        if action.tool == "ground_quiz_item":
            result = AgentToolResult(
                tool=action.tool,
                ok=False,
                error=(
                    "ground_quiz_item already ran as deterministic preflight; "
                    "finalize or call a different inspection tool"
                ),
            )
        else:
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


def _deterministic_grounding_terminal(grounding: object) -> bool:
    """Whether grounding already determines that a model cannot change the verdict."""
    if not isinstance(grounding, dict):
        return False
    return grounding.get("source_status") in {
        "source_missing_in_local_pdf",
        "ungrounded",
        "invalid_anchor",
        "incomplete",
    }


def _repair_item_scoped_action(
    action: AgentAction,
    item: dict[str, Any],
) -> AgentAction:
    if action.tool not in {"ground_quiz_item", "compare_options"}:
        return action
    arguments = dict(action.arguments)
    item_id = item.get("id")
    arguments.pop("question_id", None)
    arguments.pop("id", None)
    if item_id is not None:
        arguments["item_id"] = str(item_id)
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
        f"- model finalized: {getattr(report, 'model_finalized_count', 0)}",
        f"- deterministic fallback: {getattr(report, 'fallback_item_count', 0)}",
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
                "Review this quiz item. A deterministic grounding preflight will "
                "follow. Use it, inspect further only when needed, then finalize "
                "with a verdict.\n" + json.dumps(item, sort_keys=True)
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
    evidence = _evidence_from_observations(observations, item=item)
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
    if verdict == "source_missing":
        key_support = _missing_source_support_details()
        evidence = []
        evidence_rows = []
    if verdict == "key_supported":
        review_reason = None
    elif verdict == "source_missing":
        review_reason = str(source_status or "source_missing")
    else:
        review_reason = "model_final_review_unavailable"
    explanation = (
        _blocking_grounding_explanation(str(source_status))
        if source_status in {"invalid_anchor", "incomplete"}
        else _fallback_explanation(verdict, key_support)
    )
    distractor_verdicts = (
        {}
        if verdict == "source_missing"
        else _distractor_verdicts(
            options=options,
            correct=correct,
            evidence_rows=evidence_rows,
        )
    )
    review_priority = _review_priority(
        verdict=verdict,
        evidence_strength=str(key_support["evidence_strength"]),
        confidence_score=float(key_support["confidence_score"]),
        quality_findings=quality_findings,
        distractor_verdicts=distractor_verdicts,
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
        distractor_verdicts=distractor_verdicts,
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
    if source_status in {"invalid_anchor", "incomplete"}:
        return "needs_human_review"
    if key_support.get("supported") is True:
        return "key_supported"
    return "needs_human_review"


def _fallback_explanation(verdict: str, key_support: dict[str, object]) -> str:
    if verdict == "key_supported":
        return (
            "No validated model final review was used; deterministic retrieval "
            "found PDF evidence supporting the keyed answer. "
            f"Evidence strength is {key_support['evidence_strength']}."
        )
    if verdict == "source_missing":
        return (
            "No validated model final review was used, and deterministic retrieval "
            "did not find usable local PDF evidence for this item."
        )
    return (
        "The deterministic agent tools collected available context, but no "
        "validated model final review was used. This item needs human review."
    )


def _source_grounding_explanation(source_status: object) -> str:
    status = str(source_status or "source_missing")
    return (
        f"Source grounding status is {status}; no usable local PDF evidence can "
        "be cited to validate this item."
    )


def _blocking_grounding_explanation(source_status: str) -> str:
    return (
        f"Source grounding status is {source_status}; the declared anchors or "
        "item completeness must be fixed before the review can pass."
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


def _missing_source_support_details() -> dict[str, object]:
    return {
        "supported": False,
        "evidence_strength": "missing",
        "confidence_score": 0.0,
        "support_reason": "No usable local PDF evidence was available for this item.",
        "hit_terms": [],
    }


def _distractor_verdicts(
    *,
    options: dict[str, Any],
    correct: object,
    evidence_rows: list[dict[str, object]],
) -> dict[str, DistractorReview]:
    verdicts: dict[str, DistractorReview] = {}
    for option, option_text in options.items():
        if option == correct:
            continue
        text = str(option_text)
        support = answer_support_details(text, evidence_rows)
        strength = str(support["evidence_strength"])
        if support["supported"]:
            verdict = "plausible_but_wrong"
            rationale = (
                "The anchored context mentions this option, but lexical presence "
                "alone does not establish that it also answers the question."
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
    confidence_score: float,
    quality_findings: list[QuestionQualityFinding],
    distractor_verdicts: dict[str, DistractorReview] | None = None,
) -> str:
    if verdict in {"source_missing", "key_conflict_candidate", "ambiguous_question"}:
        return "fix"
    if verdict != "key_supported":
        return "inspect"
    if evidence_strength in {"missing", "weak", "partial"}:
        return "inspect"
    if confidence_score < 0.75:
        return "inspect"
    if quality_findings:
        return "inspect"
    if any(
        distractor.verdict == "ambiguous"
        for distractor in (distractor_verdicts or {}).values()
    ):
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
    merged_findings = _dedupe_quality_findings(
        [*review.quality_findings, *quality_findings]
    )
    warnings = item.get("warnings")
    declared_source_missing = (
        isinstance(warnings, list) and "external_source_item" in warnings
    )
    # Citations are derived only from successful tool observations. Model-supplied
    # citations are prose claims and are not authoritative evidence provenance.
    merged_evidence = [] if declared_source_missing else list(evidence or [])
    evidence_rows = _evidence_rows(merged_evidence)
    keyed_text = options.get(correct) if isinstance(correct, str) else None
    key_support = _key_support_details(
        grounding=grounding or {},
        keyed_option_text=keyed_text,
        evidence_rows=evidence_rows,
    )
    grounding_status = (grounding or {}).get("source_status")
    blocking_grounding = grounding_status in {"invalid_anchor", "incomplete"}
    missing_grounding = grounding_status in {
        "ungrounded",
        "source_missing_in_local_pdf",
    }
    source_missing = (
        declared_source_missing
        or missing_grounding
        or (not blocking_grounding and review.verdict == "source_missing")
    )
    if source_missing:
        verdict = "source_missing"
    elif blocking_grounding:
        verdict = "needs_human_review"
    else:
        verdict = review.verdict
    if source_missing:
        key_support = _missing_source_support_details()
        merged_evidence = []
        evidence_rows = []
    evidence_strength = (
        str(key_support["evidence_strength"])
        if source_missing or review.evidence_strength == "missing"
        else review.evidence_strength
    )
    confidence_score = (
        float(key_support["confidence_score"])
        if source_missing or review.confidence_score == 0
        else review.confidence_score
    )
    distractor_verdicts = (
        {}
        if source_missing
        else review.distractor_verdicts
        or _distractor_verdicts(
            options=options,
            correct=correct,
            evidence_rows=evidence_rows,
        )
    )
    derived_priority = _review_priority(
        verdict=verdict,
        evidence_strength=evidence_strength,
        confidence_score=confidence_score,
        quality_findings=merged_findings,
        distractor_verdicts=distractor_verdicts,
    )
    priority_rank = {"pass": 0, "inspect": 1, "fix": 2}
    if "review_priority" not in review.model_fields_set:
        review_priority = derived_priority
    else:
        review_priority = max(
            (review.review_priority, derived_priority),
            key=lambda priority: priority_rank[priority],
        )
    return review.model_copy(
        update={
            "verdict": verdict,
            "id": str(item.get("id") or ""),
            "question": str(item.get("question") or ""),
            "keyed_option": str(correct) if isinstance(correct, str) else None,
            "keyed_option_text": (
                options.get(correct) if isinstance(correct, str) else None
            ),
            "explanation": (
                _source_grounding_explanation(grounding_status)
                if source_missing
                else (
                    _blocking_grounding_explanation(str(grounding_status))
                    if blocking_grounding
                    else review.explanation
                )
            ),
            "quality_findings": merged_findings,
            "evidence": merged_evidence,
            "evidence_strength": evidence_strength,
            "confidence_score": confidence_score,
            "support_reason": (
                key_support["support_reason"]
                if source_missing
                else (
                    f"Source grounding status is {grounding_status}; "
                    "the item cannot pass review."
                    if blocking_grounding
                    else review.support_reason or key_support["support_reason"]
                )
            ),
            "distractor_verdicts": distractor_verdicts,
            "review_priority": review_priority,
            "source_status": (
                str(grounding_status) if grounding_status else review.source_status
            ),
            "needs_human_review_reason": (
                str(grounding_status)
                if blocking_grounding
                else review.needs_human_review_reason
            ),
            "model_finalized": True,
            "tool_calls": tool_calls,
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
    *,
    item: dict[str, Any] | None = None,
) -> list[EvidenceCitation]:
    citations: list[EvidenceCitation] = []
    seen: set[tuple[object, str]] = set()
    allowed_chunk_ids: set[int] | None = None
    if item and isinstance(item.get("source_chunks"), list) and item["source_chunks"]:
        allowed_chunk_ids = {
            int(chunk_id)
            for chunk_id in item["source_chunks"]
            if isinstance(chunk_id, int) and not isinstance(chunk_id, bool)
        }
    for observation in observations:
        result = observation.get("result")
        if not isinstance(result, dict):
            continue
        rows = result.get("context_rows") or result.get("rows") or []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            chunk_id = row.get("id")
            if allowed_chunk_ids is not None and chunk_id not in allowed_chunk_ids:
                continue
            identity = (row.get("id"), str(row.get("source_citation") or ""))
            if identity in seen:
                continue
            seen.add(identity)
            citations.append(
                EvidenceCitation(
                    source="pdf",
                    chunk_id=row.get("id") if isinstance(row.get("id"), int) else None,
                    page=row.get("page_start")
                    if isinstance(row.get("page_start"), int)
                    else None,
                    citation=str(row.get("source_citation") or ""),
                    snippet=str(row.get("text") or row.get("snippet") or "")[:900],
                )
            )
    return citations


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
    model_finalized_count = sum(item.model_finalized for item in reviews)
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
        model_finalized_count=model_finalized_count,
        fallback_item_count=len(reviews) - model_finalized_count,
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


def _instructor_note_findings(
    items: list[dict[str, Any]],
) -> dict[str, list[QuestionQualityFinding]]:
    findings: dict[str, list[QuestionQualityFinding]] = {}
    for item in items:
        note = str(item.get("instructor_key_note") or "").strip()
        if not note:
            continue
        findings.setdefault(str(item.get("id")), []).append(
            QuestionQualityFinding(
                severity="low",
                finding_type="instructor_key_note",
                message=note,
            )
        )
    return findings


def _dedupe_quality_findings(
    findings: list[QuestionQualityFinding],
) -> list[QuestionQualityFinding]:
    deduped: list[QuestionQualityFinding] = []
    seen: set[tuple[str, str, str]] = set()
    for finding in findings:
        identity = (finding.severity, finding.finding_type, finding.message)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(finding)
    return deduped


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
