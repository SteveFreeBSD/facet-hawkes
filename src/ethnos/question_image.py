"""Two-pass vision transcription for image-based math questions."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from pydantic import BaseModel, ConfigDict, Field

from .ollama_client import (
    AnswerCallResult,
    OllamaClientProtocol,
    OllamaDebugInfo,
    structured_chat_json,
)
from .qa import build_answer_context


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
CACHE_VERSION = "question-image-v1"


class QuestionImageTranscription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    problem_text: str
    expressions: list[str] = Field(default_factory=list)
    answer_choices: list[str] = Field(default_factory=list)
    interface_metadata: list[str] = Field(default_factory=list)
    diagram_description: str = ""
    uncertainties: list[str] = Field(default_factory=list)


class QuestionImageAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Field order makes the model derive and check before committing to an answer.
    work: str = Field(min_length=1, max_length=400)
    verification: str = Field(min_length=1, max_length=240)
    final_answer: str = Field(min_length=1, max_length=120)


@dataclass(frozen=True)
class QuestionImageResult:
    image_path: Path
    vision_model: str
    verifier_model: str
    transcription: QuestionImageTranscription
    initial_transcription: QuestionImageTranscription
    verification_issues: list[str]
    response_summary: dict
    cache_hit: bool = False


VISION_TRANSCRIPTION_PROMPT = """\
Read this image as a precise mathematical question transcription task.
Do not solve the problem.

Requirements:
- Transcribe every visible instruction and mathematical expression.
- Treat question numbers, progress counters, scores, and Correct/Incorrect totals
  as interface metadata, not as answer choices.
- Put that non-question page chrome in interface_metadata so it can be excluded
  deterministically.
- Only put text in answer_choices when it is visibly offered as a selectable
  response to the math problem.
- Preserve signs, grouping, exponents, subscripts, roots, fraction numerators
  and denominators, interval endpoints, and equality/inequality symbols.
- Put every visible mathematical expression in the expressions list.
- Copy answer choices exactly and in their visible order.
- Describe every graph or diagram needed to solve the problem, including axes,
  labels, coordinates, curves, shaded regions, arrows, and open/closed points.
- Put anything unreadable or ambiguous in uncertainties. Never silently guess.
- Use an empty uncertainties list only when the image is genuinely clear.

User instruction: {instruction}
"""

VISION_VERIFICATION_PROMPT = """\
Independently re-read the attached mathematical question image as a proofreader.
Do not solve the problem and do not assume the first transcription is correct.
Return a complete fresh transcription using the same schema.

Check every sign, exponent, subscript, radical, fraction boundary, grouping
symbol, interval endpoint, answer choice, graph label, shaded region, and
open/closed point directly against the pixels. Put every visible mathematical
expression in the expressions list. Use an empty uncertainties list only when
the image is genuinely clear. Never write "none" as an uncertainty.
Question numbers, progress counters, scores, and Correct/Incorrect totals are
interface metadata, not answer choices. Put them in interface_metadata.

First-pass transcription to audit:
{candidate}
"""


def transcribe_question_image(
    *,
    image_path: Path,
    instruction: str,
    model_name: str,
    verifier_model_name: str | None = None,
    client: OllamaClientProtocol,
    num_predict: int,
    num_ctx: int,
    cache_dir: Path | None = None,
) -> QuestionImageResult:
    image_path = _validated_image_path(image_path)
    verifier_model_name = verifier_model_name or model_name
    cache_path = _cache_path(
        cache_dir=cache_dir,
        image_path=image_path,
        instruction=instruction,
        model_name=model_name,
        verifier_model_name=verifier_model_name,
        num_predict=num_predict,
        num_ctx=num_ctx,
    )
    if cache_path is not None:
        cached = _read_cache(
            cache_path=cache_path,
            image_path=image_path,
            model_name=model_name,
            verifier_model_name=verifier_model_name,
        )
        if cached is not None:
            return cached
    initial, initial_summary = _transcription_call(
        client=client,
        model_name=model_name,
        image_path=image_path,
        prompt=VISION_TRANSCRIPTION_PROMPT.format(
            instruction=instruction.strip() or "Solve the pictured problem."
        ),
        num_predict=num_predict,
        num_ctx=num_ctx,
        stage="transcription",
    )
    verified, verification_summary = _transcription_call(
        client=client,
        model_name=verifier_model_name,
        image_path=image_path,
        prompt=VISION_VERIFICATION_PROMPT.format(
            candidate=json.dumps(initial.model_dump(), indent=2, ensure_ascii=False)
        ),
        num_predict=num_predict,
        num_ctx=num_ctx,
        stage="verification",
    )
    initial, verified = _reconcile_interface_choices(initial, verified)
    result = QuestionImageResult(
        image_path=image_path,
        vision_model=model_name,
        verifier_model=verifier_model_name,
        transcription=verified,
        initial_transcription=initial,
        verification_issues=_verification_issues(initial, verified),
        response_summary={
            "initial": initial_summary,
            "verification": verification_summary,
            "cache_hit": False,
        },
    )
    if cache_path is not None:
        _write_cache(cache_path, result)
    return result


def _cache_path(
    *,
    cache_dir: Path | None,
    image_path: Path,
    instruction: str,
    model_name: str,
    verifier_model_name: str,
    num_predict: int,
    num_ctx: int,
) -> Path | None:
    if cache_dir is None:
        return None
    image_hash = hashlib.sha256()
    with image_path.open("rb") as image_file:
        for block in iter(lambda: image_file.read(1024 * 1024), b""):
            image_hash.update(block)
    cache_identity = {
        "version": CACHE_VERSION,
        "image_sha256": image_hash.hexdigest(),
        "instruction": instruction.strip(),
        "model_name": model_name,
        "verifier_model_name": verifier_model_name,
        "num_predict": num_predict,
        "num_ctx": num_ctx,
        "transcription_prompt": VISION_TRANSCRIPTION_PROMPT,
        "verification_prompt": VISION_VERIFICATION_PROMPT,
    }
    digest = hashlib.sha256(
        json.dumps(cache_identity, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return cache_dir.expanduser().resolve() / f"{digest}.json"


def _read_cache(
    *,
    cache_path: Path,
    image_path: Path,
    model_name: str,
    verifier_model_name: str,
) -> QuestionImageResult | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        initial = QuestionImageTranscription.model_validate(
            payload["initial_transcription"]
        )
        verified = QuestionImageTranscription.model_validate(payload["transcription"])
        response_summary = dict(payload.get("response_summary") or {})
    except (FileNotFoundError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
    response_summary["cache_hit"] = True
    return QuestionImageResult(
        image_path=image_path,
        vision_model=model_name,
        verifier_model=verifier_model_name,
        transcription=verified,
        initial_transcription=initial,
        verification_issues=_verification_issues(initial, verified),
        response_summary=response_summary,
        cache_hit=True,
    )


def _write_cache(cache_path: Path, result: QuestionImageResult) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": CACHE_VERSION,
        "vision_model": result.vision_model,
        "verifier_model": result.verifier_model,
        "transcription": result.transcription.model_dump(),
        "initial_transcription": result.initial_transcription.model_dump(),
        "response_summary": result.response_summary,
    }
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=cache_path.parent,
            prefix=f".{cache_path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            json.dump(payload, temporary_file, indent=2, sort_keys=True)
            temporary_file.write("\n")
            temporary_path = Path(temporary_file.name)
        os.replace(temporary_path, cache_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _transcription_call(
    *,
    client: OllamaClientProtocol,
    model_name: str,
    image_path: Path,
    prompt: str,
    num_predict: int,
    num_ctx: int,
    stage: str,
) -> tuple[QuestionImageTranscription, dict]:
    response = structured_chat_json(
        client=client,
        model_name=model_name,
        messages=[{"role": "user", "content": prompt}],
        schema=QuestionImageTranscription.model_json_schema(),
        num_predict=num_predict,
        num_ctx=num_ctx,
        images=[str(image_path)],
    )
    if response.parsed_json is None:
        detail = response.validation_error or response.validation_status
        raise RuntimeError(f"Question-image {stage} failed: {detail}")
    try:
        transcription = QuestionImageTranscription.model_validate(response.parsed_json)
    except ValueError as exc:
        raise RuntimeError(f"Question-image {stage} was invalid: {exc}") from exc
    if not transcription.problem_text.strip():
        raise RuntimeError(f"Question-image {stage} returned no problem text")
    return _without_interface_choices(transcription), response.response_summary


def build_solver_question(
    instruction: str, transcription: QuestionImageTranscription
) -> str:
    parts = [instruction.strip() or "Solve the pictured problem."]
    parts.append(f"Recognized problem text:\n{transcription.problem_text.strip()}")
    if transcription.expressions:
        parts.append(
            "Recognized expressions:\n"
            + "\n".join(f"- {item}" for item in transcription.expressions)
        )
    if transcription.answer_choices:
        parts.append(
            "Recognized answer choices:\n"
            + "\n".join(f"- {item}" for item in transcription.answer_choices)
        )
    if transcription.diagram_description.strip():
        parts.append(
            "Recognized graph/diagram details:\n"
            + transcription.diagram_description.strip()
        )
    if transcription.uncertainties:
        parts.append(
            "Image-reading uncertainties (do not silently assume):\n"
            + "\n".join(f"- {item}" for item in transcription.uncertainties)
        )
    parts.append(
        "Answer-output requirements:\n"
        "- Give a concise solution and verify the result.\n"
        "- End with `FINAL ANSWER: ...` on its own line.\n"
        "- End with `KEYBOARD ENTRY: ...` on its own line, using plain ASCII "
        "homework syntax: * for explicit multiplication, ^ for exponents, "
        "sqrt(...) for roots, / for division, and parentheses for grouping."
    )
    return "\n\n".join(parts)


def answer_question_image(
    *,
    question: str,
    context_rows: list[dict],
    max_chars: int,
    model_name: str,
    client: OllamaClientProtocol,
    num_predict: int,
    num_ctx: int,
) -> AnswerCallResult:
    """Solve a verified image question with compact, structured output."""
    context = build_answer_context(context_rows[:3], min(max_chars, 700))
    prompt = (
        "Solve this verified pre-calculus question using the textbook context. "
        "Derive the result in 1-3 concise calculation steps, independently "
        "check it, and return only the requested JSON object. Do not restate "
        "the question. The final_answer field must contain only the answer "
        "expression, without prose or a box command.\n\n"
        f"Question:\n{question}\n\n"
        f"Textbook context:\n{context}"
    )
    budget = min(num_predict, 384)
    schema = QuestionImageAnswer.model_json_schema()
    response = structured_chat_json(
        client=client,
        model_name=model_name,
        messages=[{"role": "user", "content": prompt}],
        schema=schema,
        num_predict=budget,
        num_ctx=num_ctx,
        think=False,
    )
    if response.parsed_json is None:
        detail = response.validation_error or response.validation_status
        raise RuntimeError(f"Structured image-question solve failed: {detail}")
    try:
        answer = QuestionImageAnswer.model_validate(response.parsed_json)
    except ValueError as exc:
        raise RuntimeError(
            f"Structured image-question answer was invalid: {exc}"
        ) from exc
    answer_text = (
        f"Work: {answer.work.strip()}\n"
        f"Verification: {answer.verification.strip()}\n"
        f"FINAL ANSWER: {answer.final_answer.strip()}"
    )
    return AnswerCallResult(
        raw_prompt=prompt,
        raw_response=answer_text,
        debug_info=OllamaDebugInfo(
            prompt_char_length=len(prompt),
            schema_top_level_keys=list(schema.get("properties", {})),
            format_kind="json_schema",
            num_predict=budget,
            num_ctx=num_ctx,
            response_summary=response.response_summary,
        ),
    )


def _structured_expressions(items: list[str]) -> list[str]:
    """Expressions with actual structure, dropping single-token fragments.

    A reader sometimes decomposes one expression into its characters --
    `["1", "6", "n", "5"]` for `\\frac{1}{6n^{-5}}` -- which is not a list of
    expressions and must not read as disagreement with a reader that listed
    none.
    """
    return _normalized_items(
        [item for item in items if re.search(r"[=+\-*/^√≤≥<>]|[A-Za-z0-9]{2,}", item)]
    )


def _verification_issues(
    initial: QuestionImageTranscription,
    verified: QuestionImageTranscription,
) -> list[str]:
    issues: list[str] = []
    expression_lists_disagree = _structured_expressions(
        initial.expressions
    ) != _structured_expressions(verified.expressions)
    problem_math_agrees = _problem_math_lines(
        initial.problem_text
    ) and _problem_math_lines(initial.problem_text) == _problem_math_lines(
        verified.problem_text
    )
    if expression_lists_disagree and not problem_math_agrees:
        issues.append("The two vision passes disagreed about mathematical expressions.")
    if _normalized_items(initial.answer_choices) != _normalized_items(
        verified.answer_choices
    ):
        issues.append("The two vision passes disagreed about answer choices.")
    if bool(initial.diagram_description.strip()) != bool(
        verified.diagram_description.strip()
    ):
        issues.append(
            "The two vision passes disagreed about whether a diagram is present."
        )
    uncertainties = [
        *_meaningful_uncertainties(initial.uncertainties),
        *_meaningful_uncertainties(verified.uncertainties),
    ]
    for uncertainty in uncertainties:
        issue = f"Vision uncertainty: {uncertainty}"
        if issue not in issues:
            issues.append(issue)
    return issues


def _normalized_items(items: list[str]) -> list[str]:
    return sorted(_normalize_math_text(item) for item in items)


def _normalize_math_text(text: str) -> str:
    replacements = {
        r"\pm": "±",
        r"\sqrt": "√",
        r"\leq": "≤",
        r"\le": "≤",
        r"\geq": "≥",
        r"\ge": "≥",
        r"\neq": "≠",
        r"\ne": "≠",
        r"\pi": "π",
        r"\theta": "θ",
        r"\times": "×",
    }
    normalized = text.lower()
    # A reader sometimes writes the escape "\n" as two literal characters
    # instead of a newline. Left in, the same expression compares unequal and
    # a perfectly agreed reading is reported as a disagreement.
    normalized = normalized.replace("\\n", " ").replace("\\r", " ")
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    normalized = re.sub(
        r"[⁰¹²³⁴⁵⁶⁷⁸⁹]+",
        lambda match: (
            "^" + match.group(0).translate(str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789"))
        ),
        normalized,
    )
    normalized = re.sub(r"\^\{(-?\d+)\}", r"^\1", normalized)
    return re.sub(r"[\s${}()]", "", normalized)


def _problem_math_lines(text: str) -> list[str]:
    """Return math-bearing lines, independent of prose and display syntax."""
    return [
        _normalize_math_text(line)
        for line in text.splitlines()
        if re.search(r"[=+\-*/^√≤≥<>⁰¹²³⁴⁵⁶⁷⁸⁹\d]", line)
        and re.search(r"[A-Za-z\d]", line)
    ]


def _meaningful_uncertainties(items: list[str]) -> list[str]:
    ignored = {
        "none",
        "no uncertainty",
        "no uncertainties",
        "no uncertainty found",
        "none noted",
    }
    return [
        item.strip()
        for item in items
        if item.strip().lower().rstrip(".") not in ignored
    ]


def _without_interface_choices(
    transcription: QuestionImageTranscription,
) -> QuestionImageTranscription:
    """Drop a choice list that consists entirely of common quiz-page counters."""
    metadata = {_normalize_math_text(item) for item in transcription.interface_metadata}
    choices = [
        choice
        for choice in transcription.answer_choices
        if _normalize_math_text(choice) not in metadata
    ]
    if choices != transcription.answer_choices:
        transcription = transcription.model_copy(update={"answer_choices": choices})
    if not choices or not any(
        choice.strip().lower() in {"correct", "incorrect"} for choice in choices
    ):
        return transcription
    interface_pattern = re.compile(
        r"^\s*(?:correct|incorrect|\d+\s*/\s*\d+|\d+)\s*$",
        flags=re.IGNORECASE,
    )
    if not all(interface_pattern.fullmatch(choice) for choice in choices):
        return transcription
    return transcription.model_copy(update={"answer_choices": []})


def _reconcile_interface_choices(
    initial: QuestionImageTranscription,
    verified: QuestionImageTranscription,
) -> tuple[QuestionImageTranscription, QuestionImageTranscription]:
    """Use either pass's UI labels to clean both passes before comparison."""
    metadata = {
        _normalize_math_text(item)
        for item in [*initial.interface_metadata, *verified.interface_metadata]
    }
    if not metadata:
        return initial, verified

    def cleaned(value: QuestionImageTranscription) -> QuestionImageTranscription:
        choices = [
            choice
            for choice in value.answer_choices
            if _normalize_math_text(choice) not in metadata
        ]
        return value.model_copy(update={"answer_choices": choices})

    return cleaned(initial), cleaned(verified)


def _validated_image_path(image_path: Path) -> Path:
    resolved = image_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if not resolved.is_file():
        raise ValueError(f"Question image is not a file: {resolved}")
    if resolved.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_IMAGE_SUFFIXES))
        raise ValueError(f"Question image must use one of: {supported}")
    return resolved
