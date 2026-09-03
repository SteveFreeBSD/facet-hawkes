"""Native messaging host: the add-on's only way to reach Ethnos.

Firefox starts this process itself, on demand, for one specifically identified
extension. Nothing listens on a port, so no other local program or web page can
reach it.

The host accepts two operations. `health` answers without loading a model.
`solve_hawkes_problem` runs the existing pipeline — two-reader image
transcription, then the exact symbolic solver, the polynomial solver, and only
then the language model — and returns a structured answer. It has no general
command execution, no arbitrary file access, no URL fetching, and no
caller-selected model.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import struct
import sys
import tempfile
from pathlib import Path
from typing import BinaryIO

from .hawkes_protocol import (
    MAX_MESSAGE_BYTES,
    AnswerPayload,
    Certainty,
    SolveProgress,
    SolveRequest,
    SolveResponse,
    error_response,
)

LENGTH_PREFIX = struct.Struct("=I")


def read_message(stream: BinaryIO) -> dict | None:
    """Read one native message, or None at clean end of input."""
    header = stream.read(LENGTH_PREFIX.size)
    if len(header) < LENGTH_PREFIX.size:
        return None  # Firefox closed the pipe; this is an ordinary shutdown.
    (length,) = LENGTH_PREFIX.unpack(header)
    if length > MAX_MESSAGE_BYTES:
        raise ValueError(f"message of {length} bytes exceeds the {MAX_MESSAGE_BYTES} limit")
    body = stream.read(length)
    if len(body) < length:
        raise ValueError("message body ended early")
    return json.loads(body.decode("utf-8"))


def write_message(stream: BinaryIO, payload: dict) -> None:
    """Write one length-prefixed native message."""
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_MESSAGE_BYTES:
        raise ValueError("response exceeds the native messaging size limit")
    stream.write(LENGTH_PREFIX.pack(len(body)))
    stream.write(body)
    stream.flush()


def _decode_screenshot(encoded: str, directory: Path) -> Path:
    """Write the screenshot to a temp file for the vision pipeline to read."""
    prefix = "data:image/png;base64,"
    if encoded.startswith(prefix):
        encoded = encoded[len(prefix) :]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"screenshot was not valid base64: {exc}") from exc
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("screenshot was not a PNG")
    path = directory / "question.png"
    path.write_bytes(raw)
    return path


def solve(request: SolveRequest, report=None) -> SolveResponse:
    """Run the existing Ethnos pipeline over the captured question.

    `report(stage, detail)` is called as each stage begins so the add-on can
    show progress rather than a single line for the whole minute.
    """
    announce = report or (lambda *_args, **_kwargs: None)
    # Imported lazily so `health` stays fast and needs no model stack.
    from .answer_image import extract_final_math, keyboard_entry_for_math
    from .cli import create_client
    from .config import load_settings
    from .polynomial_solver import answer_polynomial_product
    from .question_image import (
        answer_question_image,
        build_solver_question,
        transcribe_question_image,
    )
    from .symbolic_solver import answer_symbolic_math

    problem = request.problem
    if problem is None or not (problem.screenshot_png_base64 or problem.mathml):
        return error_response(
            request.request_id, "No question content was supplied.", "unsupported"
        )

    settings = load_settings()
    # An empty prompt is not a small loss. Every exact operation is selected by
    # reading a verb out of this text, so without it the markup path cannot
    # match anything and the question always reaches a model as a picture with
    # no statement of what to do about it. Recorded, not refused: the answer
    # may still be right, and the panel reviews every one before insertion.
    prompt_seen = bool(problem.prompt_text.strip())
    instruction = problem.prompt_text.strip() or "Solve the question in the image."

    # Read the page's own mathematics first. It is exact, instant, and skips
    # the two image transcriptions that are otherwise almost the whole of a
    # solve. A screenshot is the fallback, not the default.
    if problem.mathml:
        announce("reading", "page markup")
        answer, decline = _solve_from_markup(instruction, problem.mathml)
        if answer is not None:
            return SolveResponse(
                request_id=request.request_id,
                status="ready",
                problem_text=instruction,
                answer=answer,
                certainty=Certainty(
                    prompt_seen=prompt_seen,
                    source="markup",
                    # Nothing was transcribed, so there is nothing to dispute:
                    # the expression came from the page, not from a reading of
                    # a picture of the page.
                    transcription="exact",
                    insertable=True,
                    issues=[],
                ),
            )
        if not problem.screenshot_png_base64:
            return error_response(
                request.request_id,
                f"The question's markup was not solved exactly ({decline}), and "
                "no screenshot was supplied to fall back on.",
                "unsupported",
            )

    with tempfile.TemporaryDirectory(prefix="ethnos-hawkes-") as workspace:
        image_path = _decode_screenshot(problem.screenshot_png_base64, Path(workspace))
        client = create_client(settings.ollama_host, settings.ollama_timeout)

        announce("reading", settings.ollama_vision_model)
        image_result = transcribe_question_image(
            image_path=image_path,
            instruction=instruction,
            model_name=settings.ollama_vision_model,
            verifier_model_name=settings.ollama_vision_verifier_model,
            client=client,
            num_predict=settings.ollama_vision_num_predict,
            num_ctx=settings.ollama_num_ctx,
            # The CLI may cache expensive transcriptions, but the browser
            # assistant's zero-coursework-footprint contract is stricter: the
            # temporary PNG and both readings disappear with this host call.
            cache_dir=None,
        )
        transcription = image_result.transcription
        question = build_solver_question(instruction, transcription)
        announce("solving", "exact solver")

        # Exact first: sympy answers many of these with no model call at all,
        # and its result is checkable rather than merely plausible.
        source = "symbolic"
        result = answer_symbolic_math(
            problem_text=transcription.problem_text,
            expressions=transcription.expressions,
        )
        if result is None:
            source = "polynomial"
            result = answer_polynomial_product(question)
        if result is None:
            source = "model"
            announce("solving", settings.ollama_math_model)
            result = answer_question_image(
                question=question,
                # No textbook retrieval: the host has no CLI arguments to open
                # a database with, and the answer prompt already tolerates an
                # empty context. Most of these questions are answered exactly
                # above and never reach the model at all.
                context_rows=[],
                max_chars=700,
                model_name=settings.ollama_math_model,
                client=client,
                num_predict=settings.ollama_answer_num_predict,
                num_ctx=settings.ollama_num_ctx,
            )

    final_math = extract_final_math(result.raw_response)
    if not final_math:
        return error_response(
            request.request_id,
            "Ethnos produced no final answer for this question.",
            "ambiguous",
        )

    # Some answers are prose -- "Not a Real Number" -- and the maths keyboard
    # conversion turns those into implicit multiplication between letters.
    prose = re.fullmatch(r"[A-Za-z][A-Za-z ]*", final_math) is not None
    keyboard_entry = final_math if prose else keyboard_entry_for_math(final_math)

    issues = list(image_result.verification_issues)
    return SolveResponse(
        request_id=request.request_id,
        status="ready",
        problem_text=transcription.problem_text,
        answer=AnswerPayload(
            display_text=final_math,
            keyboard_entry=keyboard_entry,
        ),
        certainty=Certainty(
            prompt_seen=prompt_seen,
            source=source,
            transcription="verified" if not issues else "disputed",
            # The two readers must agree before an answer may be inserted.
            insertable=not issues,
            issues=issues,
        ),
    )


def markup_decline_reason(markup_failed: bool) -> str:
    """Name which of the two markup declines happened.

    They fall back identically -- a screenshot, a vision model, and the better
    part of a minute -- and are fixed in completely different places. Without
    the distinction, a live fallback says only that the exact path did not
    work, which is the one thing already obvious.
    """
    return (
        "markup could not be converted"
        if markup_failed
        else "no exact operation matched the instruction"
    )


def _solve_from_markup(
    instruction: str, markup: list[str]
) -> tuple[AnswerPayload | None, str]:
    """Solve straight from the page's MathML.

    Returns the answer and an empty reason, or None and why it declined.
    """
    from .answer_image import extract_final_math, keyboard_entry_for_math
    from .hawkes_mathml import UnsupportedMathML, mathml_to_latex
    from .polynomial_solver import answer_polynomial_product
    from .symbolic_solver import answer_symbolic_math

    expressions: list[str] = []
    conversion_failed = False
    for item in markup:
        try:
            expressions.append(mathml_to_latex(item))
        except UnsupportedMathML:
            conversion_failed = True
    if conversion_failed or not expressions:
        return None, markup_decline_reason(True)

    classification = _polynomial_classification(instruction, expressions)
    if classification is not None:
        return classification, ""

    # "Is this a real number?" is decidable before any solver runs: an even
    # root of a negative number is not real, and every other case here is.
    # Observed repeatedly in lesson 1.2 -- the square root of -100 -- where the
    # symbolic solver produced `10*I`, which is not an answer to the question
    # asked, and the host then reported the question unsupported.
    realness = _realness_answer(instruction, expressions)
    if realness is not None:
        return realness, ""

    result = answer_symbolic_math(problem_text=instruction, expressions=expressions)
    if result is None:
        result = answer_polynomial_product(f"{instruction}\n{expressions[0]}")
    if result is None:
        # Only the exact solvers are trusted without a transcription. Handing
        # the markup to the model here would give an answer with no independent
        # check behind it at all.
        return None, markup_decline_reason(False)

    final_math = extract_final_math(result.raw_response)
    if not final_math:
        return None, "the exact solver produced no final answer"
    prose = re.fullmatch(r"[A-Za-z][A-Za-z ]*", final_math) is not None
    return AnswerPayload(
        display_text=final_math,
        keyboard_entry=final_math if prose else keyboard_entry_for_math(final_math),
    ), ""


def _polynomial_classification(instruction: str, expressions: list[str]) -> AnswerPayload | None:
    """Classify polynomial-choice questions without needing a screenshot."""
    if not re.search(r"polynomial\s+or\s+a\s+non[- ]polynomial", instruction, re.I):
        return None
    from .symbolic_solver import _safe_sympy_expression

    for expression in expressions:
        try:
            value = _safe_sympy_expression(expression)
            if not value.is_polynomial(*value.free_symbols):
                raise ValueError("fractional or negative exponent")
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError):
            return AnswerPayload(display_text="Non-Polynomial", keyboard_entry="Non-Polynomial")
        return AnswerPayload(display_text="Polynomial", keyboard_entry="Polynomial")
    return None


def _realness_answer(instruction: str, expressions: list[str]) -> AnswerPayload | None:
    """Answer "determine if this is a real number", or None if not asked.

    The question offers two options -- "Real Number" and "Not a Real Number" --
    and asks for the value only when it is real. Selecting the option stays the
    reader's action; this only says which one is right.

    The test is the index's parity, not SymPy's principal branch: `(-27)**(1/3)`
    evaluates to a complex number, but the real cube root of -27 is -3, and the
    question means the real one. Only an *even* root of a negative fails to be
    real.
    """
    import sympy

    text = instruction.lower()
    if "real number" not in text:
        return None
    # Hawkes uses two prompt families for the same rule. Some ask whether the
    # radical is real; others say to evaluate it and explicitly direct the
    # student to indicate "Not a Real Number" when it is not. The latter is
    # what the live sqrt(-36) question used, so limiting this branch to
    # determine/decide/whether allowed SymPy's complex `6*I` to escape.
    asks_for_realness = any(
        phrase in text
        for phrase in (
            "determine",
            "decide",
            "whether",
            "not a real number",
        )
    )
    if not asks_for_realness:
        return None

    from .symbolic_solver import _safe_sympy_expression

    match = re.fullmatch(r"\\sqrt(?:\[(\d+)\])?\{(.+)\}", expressions[0].strip(), re.DOTALL)
    if match is None:
        return None
    index = int(match.group(1) or 2)
    try:
        radicand = _safe_sympy_expression(match.group(2), positive_symbols=False)
    except Exception:
        return None
    if radicand.free_symbols or not radicand.is_real:
        return None  # a value that depends on a variable is not this question

    if radicand.is_negative and index % 2 == 0:
        return AnswerPayload(
            display_text="Not a Real Number",
            keyboard_entry="Not a Real Number",
        )
    value = sympy.real_root(radicand, index)
    exact = sympy.nsimplify(value, rational=True)
    if not exact.is_rational:
        return None  # an irrational value is not what this question asks for
    return AnswerPayload(display_text=str(exact), keyboard_entry=str(exact))


def handle(raw: dict, report=None) -> SolveResponse:
    """Validate one message and route it to its operation."""
    try:
        request = SolveRequest.model_validate(raw)
    except ValueError as exc:
        return error_response(str(raw.get("request_id", ""))[:64], f"Invalid request: {exc}")

    if request.operation == "health":
        return SolveResponse(request_id=request.request_id, status="ok", message="ethnos ready")
    if request.origin != "https://learn.hawkeslearning.com":
        return error_response(request.request_id, "The requesting origin is not allowed.")
    try:
        return solve(request, report)
    except Exception as exc:  # noqa: BLE001 - the pipeline must never kill the host
        return error_response(request.request_id, f"{type(exc).__name__}: {exc}")


def main() -> int:
    stdin, stdout = sys.stdin.buffer, sys.stdout.buffer
    while True:
        try:
            raw = read_message(stdin)
        except (ValueError, json.JSONDecodeError) as exc:
            write_message(stdout, error_response("", f"Malformed message: {exc}").model_dump())
            return 1
        if raw is None:
            return 0
        if not isinstance(raw, dict):
            write_message(stdout, error_response("", "Message was not an object").model_dump())
            continue
        request_id = str(raw.get("request_id", ""))[:64]

        def report(stage: str, detail: str = "") -> None:
            """Emit a progress message ahead of the final response."""
            try:
                write_message(
                    stdout,
                    SolveProgress(
                        request_id=request_id, stage=stage, detail=detail[:80]
                    ).model_dump(),
                )
            except (ValueError, OSError):
                pass  # progress is advisory; never fail a solve over it

        write_message(stdout, handle(raw, report).model_dump(exclude_none=True))


if __name__ == "__main__":
    raise SystemExit(main())
