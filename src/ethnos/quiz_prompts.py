"""Prompt and context builders for quiz answering."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .quiz_core import limit_option_text, normalize_options, _normalize_option


DEFAULT_MC_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "mc_answer.md"
DEFAULT_CHOICE_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "choice_answer.md"
DEFAULT_ESSAY_PROMPT = Path(__file__).resolve().parents[2] / "prompts" / "essay_answer.md"


def build_mc_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_MC_PROMPT,
) -> str:
    template = _prompt_template(prompt_path)
    options = "\n".join(
        f"{label}. {text}" for label, text in normalize_options(item["options"]).items()
    )
    option_labels = ", ".join(normalize_options(item["options"]))
    target = item.get("target") or ""
    source_citation = item.get("source_citation") or ""
    context = build_mc_context(
        _prioritized_context_rows(item, context_rows),
        max_chars,
        target=target,
    )
    return template.format(
        question=item["question"],
        question_type=item.get("question_type") or "multiple_choice",
        target=target,
        source_citation=source_citation,
        option_labels=option_labels,
        options=options,
        context=context,
    )


def build_choice_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_CHOICE_PROMPT,
) -> str:
    template = _prompt_template(prompt_path)
    options = "\n".join(
        f"{label}. {text}" for label, text in normalize_options(item["options"]).items()
    )
    option_labels = ", ".join(normalize_options(item["options"]))
    target = item.get("target") or ""
    context_target = target or item.get("_context_target") or ""
    source_citation = item.get("source_citation") or ""
    context = build_mc_context(
        _prioritized_context_rows(item, context_rows),
        max_chars,
        target=context_target,
    )
    question_guidance = build_choice_question_guidance(item, context_rows)
    return template.format(
        question=item["question"],
        question_type=item.get("question_type") or "multiple_choice",
        target=target,
        source_citation=source_citation,
        option_labels=option_labels,
        options=options,
        question_guidance=question_guidance,
        context=context,
    )


def build_choice_question_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str:
    guidance = []
    question = str(item.get("question") or "")
    if re.search(r"\b(?:not|except)\b", question, flags=re.IGNORECASE):
        guidance.append(
            "This is a negative question: choose the option that the context does not state as true or directly contradicts."
        )
        negative_guidance = _negative_option_guidance(item, context_rows)
        if negative_guidance:
            guidance.append(negative_guidance)
    both_guidance = _both_option_guidance(item, context_rows)
    if both_guidance:
        guidance.append(both_guidance)
    purpose_guidance = _purpose_option_guidance(item, context_rows)
    if purpose_guidance:
        guidance.append(purpose_guidance)
    percent_guidance = _percentage_complement_guidance(item, context_rows)
    if percent_guidance:
        guidance.append(percent_guidance)
    return "\n".join(guidance) if guidance else "None."


def _negative_option_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    options = normalize_options(item.get("options") or {})
    if len(options) < 3:
        return None
    context = _choice_guidance_context(context_rows)
    if not context:
        return None
    supported = []
    unsupported = []
    for label, text in options.items():
        if _option_text_supported(text, context):
            supported.append(label)
        else:
            unsupported.append(label)
    if len(unsupported) == 1 and len(supported) >= 2:
        label = unsupported[0]
        return (
            f"Direct option-text check: options {', '.join(supported)} appear in the context; "
            f"option {label} does not. For this negative question, select option {label}."
        )
    return None


def _both_option_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    options = normalize_options(item.get("options") or {})
    context = _choice_guidance_context(context_rows)
    if not options or not context:
        return None
    both_options = [
        (label, text)
        for label, text in options.items()
        if re.search(r"\bboth\b", text, flags=re.IGNORECASE)
    ]
    if not both_options:
        return None
    supported = [
        label
        for label, text in options.items()
        if not re.search(r"\b(?:both|neither|none|all)\b", text, flags=re.IGNORECASE)
        and _option_text_supported(text, context)
    ]
    if len(supported) >= 2:
        both_label = both_options[0][0]
        return (
            f"The context supports multiple individual options ({', '.join(supported)}). "
            f"Because option {both_label} is a 'Both' answer, select option {both_label}."
        )
    return None


def _purpose_option_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    question = str(item.get("question") or "").lower()
    if not re.search(r"\b(?:aimed|purpose|primary purpose|intended)\b", question):
        return None
    options = normalize_options(item.get("options") or {})
    context = _choice_guidance_context(context_rows)
    if not options or not context:
        return None
    context_norm = _guidance_normalized_text(context)
    for label, text in options.items():
        option_norm = _guidance_normalized_text(text)
        if _option_text_supported(text, context):
            return (
                "This purpose question asks for the policy aim. "
                f"The context directly supports option {label}, so select option {label}."
            )
        if _purpose_paraphrase_supported(option_norm, context_norm):
            return (
                "This purpose question asks for the policy aim, not a narrower implementation detail. "
                f"The context paraphrases option {label}, so select option {label}."
            )
    return None


def _choice_guidance_context(context_rows: list[dict[str, Any]]) -> str:
    return " ".join(" ".join(str(row.get("text", "")).split()) for row in context_rows)


def _option_text_supported(option_text: str, context: str) -> bool:
    option_norm = _guidance_normalized_text(option_text)
    context_norm = _guidance_normalized_text(context)
    if not option_norm:
        return False
    if re.search(rf"\b{re.escape(option_norm)}\b", context_norm) is not None:
        return True
    option_terms = _guidance_significant_terms(option_norm)
    if len(option_terms) < 3:
        return False
    matched_terms = [
        term for term in option_terms if re.search(rf"\b{re.escape(term)}\b", context_norm)
    ]
    return len(matched_terms) / len(option_terms) >= 0.75


def _guidance_normalized_text(text: str) -> str:
    dehyphenated = re.sub(r"(\w)-\s+(\w)", r"\1\2", str(text))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", dehyphenated.lower()).split())


def _guidance_significant_terms(text: str) -> list[str]:
    stopwords = {
        "about",
        "above",
        "also",
        "being",
        "both",
        "from",
        "into",
        "that",
        "their",
        "there",
        "these",
        "this",
        "through",
        "under",
        "with",
    }
    return [
        token
        for token in _guidance_normalized_text(text).split()
        if len(token) >= 4 and token not in stopwords
    ]


def _purpose_paraphrase_supported(option_norm: str, context_norm: str) -> bool:
    if "assimil" in option_norm:
        has_target_group = any(term in context_norm for term in ("native", "indian"))
        has_culture_goal = any(
            phrase in context_norm
            for phrase in (
                "civilization",
                "american style",
                "american culture",
                "mainstream culture",
            )
        )
        return has_target_group and has_culture_goal
    return False


def _percentage_complement_guidance(
    item: dict[str, Any], context_rows: list[dict[str, Any]]
) -> str | None:
    question = str(item.get("question") or "").lower()
    if "percent" not in question and "%" not in question:
        return None
    question_group = _percentage_group(question)
    if question_group is None:
        return None
    context = " ".join(str(row.get("text", "")) for row in context_rows)
    context_compact = " ".join(context.split())
    context_lower = context_compact.lower()
    for match in re.finditer(r"\b(\d{1,3})\s*(?:%|percent)(?=\W|$)", context_lower):
        value = int(match.group(1))
        if not 0 <= value <= 100:
            continue
        window = context_lower[match.start() : match.end() + 140]
        clause = re.split(r"[,.;:]", window, maxsplit=1)[0]
        context_group = _percentage_group(clause)
        if context_group is None or context_group == question_group:
            continue
        complement = 100 - value
        options = normalize_options(item["options"])
        label = _percentage_option_label(options, complement)
        if label is None:
            continue
        return (
            f"The context says about {value} percent were {context_group}; "
            f"the question asks for {question_group}, so use the complement "
            f"100 - {value} = {complement} percent. Select option {label}."
        )
    return None


def _percentage_group(text: str) -> str | None:
    if re.search(r"\b(?:women|woman|female|females)\b", text):
        return "women"
    if re.search(r"\b(?:men|man|male|males)\b", text):
        return "men"
    return None


def _percentage_option_label(options: dict[str, str], value: int) -> str | None:
    value_patterns = {
        f"{value}%",
        f"{value} percent",
        f"{value} per cent",
    }
    for label, text in options.items():
        normalized = _normalize_option(text)
        if normalized in value_patterns:
            return label
    return None


def build_essay_prompt(
    item: dict[str, Any],
    context_rows: list[dict[str, Any]],
    *,
    max_chars: int,
    prompt_path: Path = DEFAULT_ESSAY_PROMPT,
) -> str:
    template = _prompt_template(prompt_path)
    target = item.get("target") or ""
    context_target = target or item.get("_context_target") or ""
    source_citation = item.get("source_citation") or ""
    context = build_mc_context(
        _prioritized_context_rows(item, context_rows),
        max_chars,
        target=context_target,
    )
    return template.format(
        question=item["question"],
        points=item.get("points") or "",
        target=target,
        source_citation=source_citation,
        context=context,
    )


@lru_cache(maxsize=16)
def _prompt_template(prompt_path: Path) -> str:
    return prompt_path.read_text(encoding="utf-8")


def build_mc_context(
    rows: list[dict[str, Any]], max_chars: int, *, target: str | None = None
) -> str:
    parts = []
    for row in rows:
        text = _targeted_context_text(str(row.get("text", "")), max_chars, target)
        parts.append(
            "\n".join(
                [
                    f"[{row['source_citation']}]",
                    f"chunk_id: {row['id']}",
                    f"source_citation: {row['source_citation']}",
                    f"section_label: {row['section_label'] or 'unlabeled'}",
                    f"content_role: {row['content_role'] or 'unlabeled'}",
                    "text:",
                    text,
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _targeted_context_text(text: str, max_chars: int, target: str | None) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    target = (target or "").strip()
    if not target:
        return limit_option_text(compact, max_chars)
    index = compact.lower().find(target.lower())
    if index < 0:
        index = _best_token_window_center(compact, target, max_chars)
    if index < 0:
        return limit_option_text(compact, max_chars)
    half_window = max((max_chars - len(target)) // 2, 0)
    start = max(index - half_window, 0)
    end = min(start + max_chars, len(compact))
    start = max(end - max_chars, 0)
    excerpt = compact[start:end].strip()
    if start > 0:
        excerpt = "..." + excerpt
    if end < len(compact):
        excerpt = excerpt.rstrip() + "..."
    return excerpt


def _best_token_window_center(text: str, target: str, max_chars: int) -> int:
    lowered = text.lower()
    tokens = [
        token
        for token in re.findall(r"[a-z0-9]+", target.lower())
        if len(token) > 2
    ]
    if not tokens:
        return -1
    unique_tokens = list(dict.fromkeys(tokens))
    best_index = -1
    best_score: tuple[int, int, int] | None = None
    for token in unique_tokens:
        start = 0
        while True:
            index = lowered.find(token, start)
            if index < 0:
                break
            window_start = max(index - max_chars // 2, 0)
            window_end = min(window_start + max_chars, len(text))
            window = lowered[window_start:window_end]
            score = (
                sum(1 for candidate in unique_tokens if candidate in window),
                len(token),
                index,
            )
            if best_score is None or score > best_score:
                best_score = score
                best_index = index
            start = index + len(token)
    return best_index


def _prioritized_context_rows(
    item: dict[str, Any], rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    source_chunks = {int(chunk_id) for chunk_id in item.get("source_chunks", [])}
    if not source_chunks:
        return rows
    return sorted(rows, key=lambda row: 0 if int(row["id"]) in source_chunks else 1)
