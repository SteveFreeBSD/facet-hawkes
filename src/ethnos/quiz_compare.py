"""Comparison helpers for MC benchmark reports."""

from __future__ import annotations

import json
from pathlib import Path


def load_mc_bench_report(path: Path, label: str) -> dict[str, object]:
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} report is not valid JSON: {path}") from exc
    if not isinstance(report, dict) or not isinstance(report.get("items"), list):
        raise ValueError(f"{label} report must be an mc-bench JSON object with items")
    return report


def compare_mc_bench_reports(
    baseline: dict[str, object], candidate: dict[str, object]
) -> dict[str, object]:
    baseline_items = _mc_report_items_by_id(baseline)
    candidate_items = _mc_report_items_by_id(candidate)
    common_ids = sorted(set(baseline_items) & set(candidate_items))
    added_ids = sorted(set(candidate_items) - set(baseline_items))
    removed_ids = sorted(set(baseline_items) - set(candidate_items))

    correct_to_incorrect = []
    incorrect_to_correct = []
    answer_changes = []
    retrieval_changes = []
    for item_id in common_ids:
        before = baseline_items[item_id]
        after = candidate_items[item_id]
        before_correct = _mc_item_correctness(before)
        after_correct = _mc_item_correctness(after)
        change = _mc_item_change(item_id, before, after)
        if before_correct is True and after_correct is False:
            correct_to_incorrect.append(change)
        elif before_correct is False and after_correct is True:
            incorrect_to_correct.append(change)
        if before.get("selected_option") != after.get("selected_option"):
            answer_changes.append(change)
        if _mc_retrieval_signature(before) != _mc_retrieval_signature(after):
            retrieval_changes.append(change)

    baseline_accuracy = optional_float(baseline.get("accuracy"))
    candidate_accuracy = optional_float(candidate.get("accuracy"))
    accuracy_delta = (
        candidate_accuracy - baseline_accuracy
        if baseline_accuracy is not None and candidate_accuracy is not None
        else None
    )
    return {
        "baseline_model": baseline.get("model"),
        "candidate_model": candidate.get("model"),
        "baseline_accuracy": baseline_accuracy,
        "candidate_accuracy": candidate_accuracy,
        "accuracy_delta": accuracy_delta,
        "baseline_total": baseline.get("total"),
        "candidate_total": candidate.get("total"),
        "common_count": len(common_ids),
        "added_item_ids": added_ids,
        "removed_item_ids": removed_ids,
        "correct_to_incorrect": correct_to_incorrect,
        "incorrect_to_correct": incorrect_to_correct,
        "answer_changes": answer_changes,
        "retrieval_changes": retrieval_changes,
    }


def tuple_list(value: object) -> tuple[object, ...]:
    return tuple(value) if isinstance(value, list) else ()


def optional_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    return None


def _mc_report_items_by_id(report: dict[str, object]) -> dict[str, dict[str, object]]:
    items_by_id = {}
    for item in report.get("items", []):
        if isinstance(item, dict) and item.get("id") is not None:
            items_by_id[str(item["id"])] = item
    return items_by_id


def _mc_item_correctness(item: dict[str, object]) -> bool | None:
    value = item.get("is_correct")
    return value if isinstance(value, bool) else None


def _mc_item_change(
    item_id: str, before: dict[str, object], after: dict[str, object]
) -> dict[str, object]:
    return {
        "id": item_id,
        "question": before.get("question") or after.get("question"),
        "before_status": before.get("status"),
        "after_status": after.get("status"),
        "before_selected_option": before.get("selected_option"),
        "after_selected_option": after.get("selected_option"),
        "before_selected_option_text": before.get("selected_option_text"),
        "after_selected_option_text": after.get("selected_option_text"),
        "correct": before.get("correct") or after.get("correct"),
        "before_chunks": before.get("selected_chunks", []),
        "after_chunks": after.get("selected_chunks", []),
        "before_queries": before.get("retrieval_questions")
        or before.get("queries_tried", []),
        "after_queries": after.get("retrieval_questions")
        or after.get("queries_tried", []),
    }


def _mc_retrieval_signature(
    item: dict[str, object]
) -> tuple[tuple[object, ...], tuple[object, ...]]:
    chunks = item.get("selected_chunks", [])
    queries = item.get("retrieval_questions") or item.get("queries_tried", [])
    return (tuple_list(chunks), tuple_list(queries))
