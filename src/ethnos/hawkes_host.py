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
import time
from pathlib import Path
from typing import BinaryIO

from facet_runtime.exact import EXACT_METHOD as FACET_EXACT_METHOD

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
        raise ValueError(
            f"message of {length} bytes exceeds the {MAX_MESSAGE_BYTES} limit"
        )
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
    if problem is None or not (
        problem.screenshot_png_base64 or problem.mathml or problem.graph_points
    ):
        return error_response(
            request.request_id, "No question content was supplied.", "unsupported"
        )

    # An empty prompt is not a small loss. Every exact operation is selected by
    # reading a verb out of this text, so without it the markup path cannot
    # match anything and the question always reaches a model as a picture with
    # no statement of what to do about it. Recorded, not refused: the answer
    # may still be right, and the panel reviews every one before insertion.
    prompt_seen = bool(problem.prompt_text.strip())
    instruction = problem.prompt_text.strip() or "Solve the question in the image."

    if problem.data_table is not None and asks_for_an_optimum(instruction):
        return _solve_table_optimum_with_facet(request, instruction, announce)

    if problem.graph_points:
        return _solve_regression_with_facet(request, instruction, announce)

    if problem.answer_shape and problem.answer_shape.kind == "graph":
        # A graph answered by placing the points the question wrote down. Its
        # own route, because there is nothing to derive: the answer is stated,
        # and no model is asked.
        if problem.answer_shape.graph and problem.answer_shape.graph.family == "points":
            return _solve_point_plot_with_facet(request, instruction, announce)
        return _solve_graph_with_facet(request, instruction, announce)

    if request.solve_engine == "facet":
        return _solve_with_facet(request, instruction, prompt_seen, announce)

    settings = load_settings()

    # Read the page's own mathematics first. It is exact, instant, and skips
    # the two image transcriptions that are otherwise almost the whole of a
    # solve. A screenshot is the fallback, not the default.
    if problem.mathml:
        announce("reading", "page markup")
        started = time.perf_counter()
        answer, decline = _solve_from_markup(instruction, problem.mathml)
        exact_ms = (time.perf_counter() - started) * 1000
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
                    answered_by="exact",
                    router="solved",
                    reading="mathml",
                    method=EXACT_METHOD,
                    facet_invoked=False,
                    elapsed_ms=exact_ms,
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
        solve_started = time.perf_counter()
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
            # A screenshot solve names its own layers: the picture was read by
            # a vision model, and the answer came either from a solver or from
            # a second model. Saying "model" for both would hide the one
            # distinction that decides how much to trust it.
            answered_by="model" if source == "model" else "exact",
            router="solved" if source != "model" else "declined",
            reading="screenshot",
            method=(
                settings.ollama_math_model
                if source == "model"
                else EXACT_METHOD
                if source == "symbolic"
                else POLYNOMIAL_METHOD
            ),
            facet_invoked=False,
            elapsed_ms=(time.perf_counter() - solve_started) * 1000,
        ),
    )


#: How many separate values a question wants, read out of its own wording.
#: Hawkes states this in the instruction whenever one box takes two answers.
COMMA_SEPARATED = re.compile(
    r"separate\s+multiple\s+answers\s+with\s+a\s+comma", re.IGNORECASE
)

#: Names for the deterministic solvers, so a reader is never left wondering
#: whether the thing that answered was a model. Neither of these is one.
#: `EXACT_METHOD` is taken from the solver itself, which lives in Facet now:
#: two places naming the same solver differently is how a panel ends up
#: claiming an engine that did not run.
EXACT_METHOD = FACET_EXACT_METHOD
POLYNOMIAL_METHOD = "exact polynomial expansion"


def required_answer_parts(shape, instruction: str) -> int:
    """How many separate values this page will take.

    Ethnos owns this reading, not the add-on and not Facet. The browser
    reports the control it saw; what that control means for an answer depends
    on the question as much as on the page, because a single box is still a
    two-value answer when the instruction says to separate them with a comma.
    """
    if shape is not None and shape.kind == "multi":
        return shape.count
    if COMMA_SEPARATED.search(instruction):
        return 2
    return 1


def shared_answer_representation(shape) -> tuple[str, int] | None:
    """The one form every answer part must take, when there is exactly one.

    The browser sends a mathematical representation only when every part has
    the same narrow, published contract, and this is the reading of that: a
    kind and a length, or nothing. Anything mixed, anything unrecognised, and
    anything absent is nothing, because a requirement that holds for some
    answers and not others is not a requirement on the reply.
    """
    representations = list(shape.representations) if shape is not None else []
    if not representations:
        return None
    if any(item.kind != "signed-integer" for item in representations):
        return None
    limits = {item.maxLength for item in representations}
    if len(limits) != 1:
        return None
    [limit] = limits
    return "signed-integer", limit


def answer_representation_payload(shape) -> dict[str, object] | None:
    """The same reading, in the terms Facet takes it in.

    Sent as well as stated in the instruction, and for a different consumer:
    the sentence is for a model, and this is what the deterministic route
    filters its solutions by and what the verifier holds a reasoned answer to.
    A requirement only a model can read is not a requirement that can be
    checked.
    """
    reading = shared_answer_representation(shape)
    if reading is None:
        return None
    kind, limit = reading
    return {"kind": kind, "max_length": limit}


def instruction_with_answer_representation(instruction: str, shape) -> str:
    """Add the normalized answer-form requirement Facet otherwise cannot know.

    The browser does not send editor vocabulary here.  It sends a mathematical
    representation only when every answer part has the same narrow, published
    contract.  Facet owns its prompt, so the requirement is appended to the
    question handed to Facet rather than implemented as an editor exception.
    """
    reading = shared_answer_representation(shape)
    if reading is None:
        return instruction
    _, limit = reading
    subject = (
        "Each separate answer"
        if len(shape.representations) > 1
        else "The answer"
    )
    return (
        f"{instruction}\n{subject} must use only digits and an optional leading "
        f"minus sign, with at most {limit} characters. Do not use a fraction, "
        "radical, exponent notation, parentheses, or any other characters."
    )


def answer_table_payload(table, parts_required: int = 0) -> dict[str, object] | None:
    """The grid a completion question is answered in, in Facet's terms.

    A completion question's givens are the question. `x = y²` and "complete the
    table" is not a question anybody can answer; the same words beside the five
    cells the page states are.

    This used to be flattened into the instruction, which put the grid in front
    of a model and nowhere else -- so the only thing that could read it was the
    one route whose answers cannot be checked. It crosses as structure now:
    the columns, and each cell as either a stated value or a numbered blank.
    That is what a deterministic route can compute from and what a verifier can
    hold a reasoned answer to. Facet renders it into its own prompt when a
    model does end up being asked.

    A cell MathJax rendered arrives as MathML and is converted by the same
    converter the expressions use; anything that converter will not translate
    means the table cannot be stated faithfully, and then it is not stated at
    all. A partial grid would be a different question, so the choice is the
    whole thing or nothing.

    `parts_required` is the other reading of the same fact -- how many separate
    values the page will take -- and the grid is sent only when the two agree.
    They are read from different places: the blanks come from the table's own
    markup and the count from the editor the page publishes, and a question
    where those disagree has been half-read. Facet refuses such a request
    outright, and rightly; sending it anyway would turn a question that was
    merely answered narrowly into one that cannot be answered at all.
    """
    from .hawkes_mathml import UnsupportedMathML, mathml_to_latex

    if table is None:
        return None
    blanks = sum(1 for row in table.rows for cell in row if cell.blank is not None)
    if blanks != parts_required:
        return None
    rows: list[list[dict[str, object]]] = []
    for row in table.rows:
        cells: list[dict[str, object]] = []
        for cell in row:
            if cell.blank is not None:
                cells.append({"blank": cell.blank})
                continue
            if cell.mathml:
                try:
                    cells.append({"value": mathml_to_latex(cell.mathml)})
                except UnsupportedMathML:
                    return None
            else:
                cells.append({"value": cell.text})
        rows.append(cells)
    return {"columns": list(table.columns), "rows": rows}


def optimum_direction(instruction: str) -> str | None:
    """Which end of a fitted curve this question asks for, or None.

    The words are Facet's, imported rather than copied: what counts as asking
    for a quadratic regression, or for a maximum, is Facet's reading of a
    question, and two spellings of it would drift apart on the first question
    that only one of them recognised. What Ethnos does with the reading is its
    own -- it decides which request to send, and then holds Facet's answer to
    the same reading afterwards.

    A question naming both ends, or neither, is not one of these.
    """
    from facet_runtime.exact.regression import (
        MAXIMISE,
        MINIMISE,
        QUADRATIC_REGRESSION,
    )

    if not QUADRATIC_REGRESSION.search(instruction):
        return None
    wants_maximum = bool(MAXIMISE.search(instruction))
    wants_minimum = bool(MINIMISE.search(instruction))
    if wants_maximum == wants_minimum:
        return None
    return "maximum" if wants_maximum else "minimum"


def asks_for_an_optimum(instruction: str) -> bool:
    """Whether this question fits a curve to data and then reads its turning point."""
    return optimum_direction(instruction) is not None


def _solve_table_optimum_with_facet(request, instruction, announce):
    """Answer a question about the page's own table, and prove the answer here.

    The page states three measurements and asks where the quadratic through
    them is highest. Facet computes that exactly -- no model, no accelerator,
    nothing rounded -- and returns both the answers and its working. What this
    function does is refuse to take either on trust.

    Three separate proofs run here, against the table this host read for
    itself:

    * the coefficients Facet fitted satisfy the exact least-squares normal
      equations over those points, which is a statement about the fit rather
      than about the fitter;
    * the turning point Facet reported is where that curve actually turns, and
      it is the end of the curve this question asked for -- read from the
      instruction here, not taken from Facet's account of it;
    * the second answer, a rate, times the first answer gives the curve's value
      at the turning point -- so `36 x 9 = 324` is checked, not assumed.

    Anything that fails is a refusal. A reasoned answer is refused too: this
    question has an exact answer, and a plausible one has no working to check.
    """
    from .facet_client import FacetError, safe_request_id, solve_math
    from .hawkes_table import TableUnreadable, agrees_with_plot, read_table

    problem = request.problem
    table = problem.data_table
    try:
        announce("reading", "the question's own table")
        reading = read_table(table.columns, table.rows, instruction)
        checks = list(reading.checks)
        if problem.graph_points:
            # The same numbers, read a second time out of entirely different
            # markup. Agreement between them is free and is worth more than any
            # check this host could invent on its own.
            agrees_with_plot(reading, problem.graph_points)
            checks.append("table agrees with the plotted points")

        parts_required = required_answer_parts(problem.answer_shape, instruction)
        announce("solving", "Facet exact regression optimum")
        solution = solve_math(
            instruction=instruction_with_answer_representation(
                instruction, problem.answer_shape
            ),
            request_id=safe_request_id(request.request_id),
            # The measurements and how many answers the question takes. Which
            # columns they came from, and what the page looks like, stay here.
            points=[{"x": x, "y": y} for x, y in reading.points],
            answer_parts=parts_required,
            label=problem.question_label,
            accelerator_required=False,
            allow_fallback=False,
        )
        if solution.route != "exact":
            raise ValueError(
                "this question has an exact answer and a reasoned one cannot be "
                f"checked; Facet took the {solution.route} route"
            )
        announce("checking", "proving the fit and the turning point")
        values = _proved_optimum(
            solution,
            reading,
            parts_required,
            checks,
            optimum_direction(instruction),
        )
    except (FacetError, TableUnreadable, ValueError, TypeError) as error:
        return error_response(
            request.request_id, f"Table question refused: {error}", "unsupported"
        )

    return SolveResponse(
        request_id=request.request_id,
        status="ready",
        problem_text="\n".join(
            (
                instruction,
                f"{reading.output_column} against {reading.input_column}: "
                + ", ".join(f"({x},{y})" for x, y in reading.points),
            )
        ),
        # Separate answers stay separate values all the way to the two boxes.
        answer=answer_payload(
            solution.answer.display, "", values, solution.answer.entry_mode
        ),
        certainty=_plan_certainty(solution, reading="table", issues=checks),
    )


def _proved_optimum(
    solution, reading, parts_required, checks, direction
) -> tuple[str, ...]:
    """Check Facet's answer against this host's own reading of the table.

    Returns the answer's separate values once every check has passed, and
    raises otherwise. Facet's working is required rather than optional: an
    answer with nothing behind it is one nothing here can prove, and an
    unprovable answer is not inserted.
    """
    import sympy

    from .hawkes_graph import RegressionPlan, regression_coefficients
    from .hawkes_protocol import GraphPoint

    values = list(solution.answer.parts) or (
        [solution.answer.entry] if solution.answer.entry else []
    )
    if len(values) != parts_required:
        raise ValueError(
            f"Facet returned {len(values)} answers, not the {parts_required} "
            "this question takes"
        )
    working = solution.evidence.get("computation")
    if not isinstance(working, dict) or "coefficients" not in working:
        raise ValueError(
            "Facet reported no working for this answer to be checked against"
        )

    points = [GraphPoint(x=x, y=y) for x, y in reading.points]
    coefficients = regression_coefficients(
        RegressionPlan(
            kind="quadratic-regression",
            coefficients=str(working["coefficients"]).split(","),
        ),
        points,
    )
    checks.append("Facet's fit satisfies the exact least-squares normal equations")

    # Facet read the instruction to decide which end of the curve to report.
    # This host read it too, and requires the two readings to agree: an answer
    # to the opposite question is well-formed, exact, and wrong.
    if working.get("direction") != direction:
        raise ValueError(
            f"this question asks for a {direction} and Facet reports a "
            f"{working.get('direction')!r}"
        )
    a, b, c = coefficients
    if (a < 0) != (direction == "maximum"):
        raise ValueError(f"the fitted curve has no {direction}")
    optimum = sympy.Rational(-b, 2 * a)
    if sympy.Rational(values[0]) != optimum:
        raise ValueError(
            f"Facet's answer {values[0]} is not where the fit turns ({optimum})"
        )
    peak = a * optimum**2 + b * optimum + c
    checks.append(f"{direction} at {optimum} proved from the fit; value there {peak}")

    if parts_required == 2:
        # The second answer is a rate: what one unit is worth at the optimum.
        # Multiplying it back out is the whole check, and it is exact.
        if sympy.Rational(values[1]) * optimum != peak:
            raise ValueError(
                f"{values[1]} x {optimum} is not {peak}, so the second answer "
                "is not the rate at the turning point"
            )
        checks.append(f"{values[1]} x {optimum} = {peak} confirms the rate")
    return tuple(values)


def _solve_regression_with_facet(request, instruction, announce):
    """Fit a quadratic to the points the page drew, and prove the fit here.

    Facet proposes coefficients; this proves them. The proof is the exact
    least-squares normal equations against the same normalised coordinates the
    add-on measured, so a plausible-looking fit that is not the least-squares
    fit is refused rather than rounded and typed in.
    """
    import sympy

    from .facet_client import FacetError, safe_request_id, solve_math
    from .hawkes_graph import RegressionPlan, regression_coefficients

    points = request.problem.graph_points
    try:
        if not re.search(r"\bquadratic regression\b", instruction, re.I):
            raise ValueError(
                "SVG point data requires a quadratic regression instruction"
            )
        announce("solving", "Facet quadratic regression from exact SVG points")
        solution = solve_math(
            instruction=instruction,
            request_id=safe_request_id(request.request_id),
            result_kind="quadratic_regression",
            # Normalised coordinates only. Which SVG elements they came from,
            # and how they were measured, stays here.
            points=[point.model_dump() for point in points],
            accelerator_required=False,
            allow_fallback=False,
        )
        announce("checking", "verifying exact least-squares normal equations")
        # Re-validated here rather than trusted: Facet parsed this plan too,
        # and two independent readings of an untrusted reply is the point.
        plan = RegressionPlan.model_validate(solution.answer.plan)
        coefficients = regression_coefficients(plan, points)
        rounded = coefficients
        if re.search(r"three decimal places", instruction, re.I):
            rounded = [
                sympy.sign(c) * sympy.floor(abs(c) * 1000 + sympy.Rational(1, 2)) / 1000
                for c in coefficients
            ]
        elif any(c.q != 1 for c in coefficients):
            raise ValueError(
                "fractional regression requires the supported three-decimal instruction"
            )

        def number(value):
            return (
                str(value)
                if value.q == 1
                else f"{float(value):.3f}".rstrip("0").rstrip(".")
            )

        terms = []
        for value, suffix in zip(rounded, ["x^2", "x", ""], strict=True):
            if not value:
                continue
            sign = "-" if value < 0 else "+" if terms else ""
            magnitude = "" if suffix and abs(value) == 1 else number(abs(value))
            terms.append(sign + magnitude + suffix)
        entry = "".join(terms)
    except (FacetError, ValueError, TypeError, SyntaxError) as error:
        return error_response(
            request.request_id, f"Regression refused: {error}", "unsupported"
        )
    return SolveResponse(
        request_id=request.request_id,
        status="ready",
        problem_text=instruction
        + "\nPoints: "
        + ", ".join(f"({p.x},{p.y})" for p in points),
        answer=AnswerPayload(display_text=entry, keyboard_entry=entry),
        certainty=_plan_certainty(
            solution,
            reading="svg",
            issues=[
                "Facet coefficients validated with exact least-squares normal equations"
            ],
        ),
    )


def _solve_point_plot_with_facet(request, instruction, announce):
    """Plot the points the question states, without asking anything.

    "Plot the following points in the Cartesian plane" writes its own answer
    down. Facet reads the pairs exactly and returns where each control must end
    up; every check that matters -- that the graph offers one control per point,
    that each lands on the grid, that none moved anywhere else -- is the
    browser's, against the live graph, and is made before a key is pressed.
    """
    from .facet_client import safe_request_id, solve_math
    from .hawkes_graph import PointPlotPlan
    from .hawkes_mathml import mathml_to_latex

    problem = request.problem
    try:
        announce("solving", "Facet stated points")
        solution = solve_math(
            instruction=instruction,
            request_id=safe_request_id(request.request_id),
            # The pairs are the page's own mathematics and reach us as MathML;
            # the prompt text around them can be a dozen characters.
            expressions=[mathml_to_latex(item) for item in (problem.mathml or [])],
            result_kind="point_plot_plan",
            accelerator_required=False,
            allow_fallback=False,
        )
        plan = PointPlotPlan.model_validate(solution.answer.plan)
        offered = problem.answer_shape.graph.count
        if offered != len(plan.points):
            raise ValueError(
                f"the graph offers {offered} controls and the question states "
                f"{len(plan.points)} points"
            )
    except Exception as error:  # noqa: BLE001 - a refusal, never a host fault
        return error_response(
            request.request_id, f"Point plot refused: {error}", "unsupported"
        )
    # The panel showed an empty card for every plotting question: a graph plan
    # carries no writable value, and the card reads `display_text`. The places
    # the controls are about to go are exactly what a reader is being asked to
    # review before pressing Insert, so they are what the card now says.
    placed = ", ".join(f"({point.x},{point.y})" for point in plan.points)
    return SolveResponse(
        request_id=request.request_id,
        status="ready",
        problem_text=instruction,
        answer=AnswerPayload(graph_plan=plan, display_text=placed),
        # Facet's own account of the run, read off the solution it returned.
        # Stated here rather than through `_plan_certainty` because this route
        # engaged no model and no processor: `answered_by` says "exact", and a
        # helper that reports "facet" would be claiming a reasoner ran.
        certainty=Certainty(
            prompt_seen=True,
            source=solution.source,
            transcription="verified",
            insertable=True,
            answered_by="exact",
            facet_invoked=True,
            router=solution.router,
            # The pairs were read off the page's own MathML, which is the same
            # reading a value question gets from the same source.
            reading="mathml",
            method=solution.method,
            runtime=solution.runtime,
            elapsed_ms=solution.elapsed_ms,
        ),
    )


def _solve_graph_with_facet(request, instruction, announce):
    """Ask Facet for a parabola plan, and prove the geometry here.

    Facet proposes a vertex, an opening and two defining points. Every one of
    them is then checked against the page's own MathML -- re-converted here
    rather than taken from what was sent -- so a plan that is well-formed but
    wrong about the function never reaches the graph actuator.
    """
    from .facet_client import FacetError, safe_request_id, solve_math
    from .hawkes_graph import GraphPlan, validate_graph_plan
    from .hawkes_mathml import mathml_to_latex

    problem = request.problem
    try:
        if not problem.mathml or not re.search(
            r"\bgraph\b.*\bparabola\b", instruction, re.I
        ):
            raise ValueError("graph requires exact MathML and a parabola instruction")
        announce("solving", "Facet graph plan")
        solution = solve_math(
            instruction=instruction,
            request_id=safe_request_id(request.request_id),
            # The mathematics, not the markup: reading MathJax is a fact about
            # the page, and the page does not cross.
            expressions=[mathml_to_latex(item) for item in problem.mathml],
            result_kind="parabola_plan",
            # Normalised geometry: a family, an orientation, bounds and a snap
            # grid. No element, no handle, and no way to move anything.
            # `exclude_none` so a parabola's request is byte-identical to
            # what it has always been; only a plotting graph carries a count.
            graph=problem.answer_shape.graph.model_dump(exclude_none=True),
            accelerator_required=False,
            allow_fallback=False,
        )
        announce("checking", "validating Facet geometry against exact function")
        # Re-validated here rather than trusted, and then proved against the
        # markup this host converts for itself.
        plan = GraphPlan.model_validate(solution.answer.plan)
        coefficients = validate_graph_plan(plan, problem.mathml)
    except (FacetError, ValueError, TypeError, SyntaxError) as error:
        return error_response(
            request.request_id, f"Graph plan refused: {error}", "unsupported"
        )
    return SolveResponse(
        request_id=request.request_id,
        status="ready",
        problem_text="\n".join(
            (instruction, *(mathml_to_latex(m) for m in problem.mathml))
        ),
        answer=AnswerPayload(
            graph_plan=plan,
            graph_coefficients=coefficients,
            display_text=f"Vertex ({plan.vertex.x}, {plan.vertex.y}); opens {plan.opening}; "
            + "; ".join(f"({p.x}, {p.y})" for p in plan.points),
        ),
        certainty=_plan_certainty(
            solution,
            reading="mathml",
            issues=["Graph plan mathematically validated against exact MathML"],
        ),
    )


def _plan_certainty(solution, *, reading: str, issues: list[str]) -> Certainty:
    """Provenance for a plan Facet proposed and this host then proved.

    Facet's own account of the run is reported rather than assembled here --
    which specialist answered, on which processor, with which model. The
    `issues` line is the one claim that is not Facet's: it is this host saying
    what it checked before letting anything be actuated.
    """
    return Certainty(
        source=solution.source,
        transcription="exact",
        insertable=True,
        answered_by="facet",
        router=solution.router,
        router_detail=solution.router_detail,
        reading=reading,
        method=solution.method,
        facet_invoked=True,
        requested_backend=solution.requested_backend,
        actual_backend=solution.actual_backend,
        fallback=solution.fallback,
        model=solution.model,
        runtime=solution.runtime,
        device=solution.device,
        elapsed_ms=solution.elapsed_ms,
        issues=issues,
    )


def answer_payload(
    display: str, entry: str, parts: tuple[str, ...] | list[str], entry_mode: str
) -> AnswerPayload:
    """Turn one exactly-shaped answer into the page's answer model.

    This is the browser side of the boundary and stays here: Facet reports the
    values and how literally to take them, and Ethnos decides what has to be
    typed to produce them. The maths keyboard, its function forms and its
    implicit multiplication are facts about the Hawkes editor, not about the
    mathematics, so Facet is never told about any of it.
    """
    from facet_runtime.exact import entry_text

    from .answer_image import keyboard_entry_for_math

    def render(value: str) -> str:
        literal = entry_text(value, entry_mode)
        return literal if literal is not None else keyboard_entry_for_math(value)

    return AnswerPayload(
        display_text=display,
        # A multi-part answer is carried in `parts`; there is no one string
        # that can be typed into several separate boxes.
        keyboard_entry=render(entry) if entry else "",
        parts=[render(value) for value in parts],
    )


def _solve_with_facet(
    request: SolveRequest, instruction: str, prompt_seen: bool, announce
) -> SolveResponse:
    """Hand the question to Facet, and let Facet decide how it is answered.

    This is the boundary that moved. Ethnos used to run the exact solvers here
    and ask Facet only about what they declined, which meant the routing
    decision -- the single most consequential thing about a solve -- was made
    by the side that owns the browser. It is now made by the side that owns the
    answering: Facet runs the same deterministic solvers first, in milliseconds
    with no model and no accelerator, and reaches a reasoning model only for
    what genuinely falls past them. Which route ran comes back in the result.

    What crosses is the question: the instruction, the exact expressions read
    off the page's own markup, how many separate values the answer takes, and
    the question's label. The markup itself does not cross, because converting
    it is a fact about MathJax rather than about mathematics, and nothing about
    the document, the window, the frame, the editor or the fields crosses at
    all. What comes back is validated here before anything is typed anywhere.
    """
    from .facet_client import (
        FacetError,
        FacetExecutionError,
        safe_request_id,
        solve_math,
    )
    from .hawkes_mathml import UnsupportedMathML, mathml_to_latex

    problem = request.problem
    if problem is None or not problem.mathml:
        return error_response(
            request.request_id,
            "Facet needs mathematics read from the page; none could be read here.",
            "unsupported",
        )
    try:
        expressions = [mathml_to_latex(item) for item in problem.mathml]
    except UnsupportedMathML:
        return error_response(
            request.request_id,
            "Facet needs mathematics read from the page; none could be read here.",
            "unsupported",
        )
    if not expressions:
        return error_response(
            request.request_id,
            "Facet needs mathematics read from the page; none could be read here.",
            "unsupported",
        )

    announce("reading", "exact page markup")
    # What the page will take, decided here and stated to Facet as a
    # requirement on its reply. How many values a question has, and whether
    # their published representation is signed-integer-only, are properties of
    # the answer the question requests. Where they are typed remains nobody's
    # business but Ethnos's.
    parts_required = required_answer_parts(problem.answer_shape, instruction)
    announce("solving", "Facet solver routing")
    # A need, not a device. Ethnos requires accelerated execution and refuses a
    # fallback; which accelerator satisfies that is Facet's to decide and
    # Facet's to report, so nothing here assumes a GPU or a particular host.
    # An exactly solved question satisfies it by needing no processor at all.
    try:
        solution = solve_math(
            instruction=instruction_with_answer_representation(
                instruction, problem.answer_shape
            ),
            expressions=expressions,
            request_id=safe_request_id(request.request_id),
            answer_parts=parts_required,
            # The grid and the form of an answer, as structure. Facet computes
            # from these and checks a reasoned answer against them; neither is
            # possible against a sentence.
            answer_table=answer_table_payload(problem.answer_table, parts_required),
            answer_representation=answer_representation_payload(
                problem.answer_shape
            ),
            label=problem.question_label,
            accelerator_required=True,
            allow_fallback=False,
        )
    except FacetExecutionError as error:
        if error.kind == "unusable_result":
            # Facet ran and what came back cannot be an answer. Reported as
            # ambiguous rather than as a failure, because the distinction is
            # what tells a reader whether to try again or to look at the page.
            return error_response(
                request.request_id,
                f"Facet returned no usable answer: {error.detail}",
                "ambiguous",
            )
        return error_response(request.request_id, f"Facet did not answer: {error}")
    except FacetError as error:
        # Facet is where every question stated as mathematics is answered. A
        # failure here is reported as a failure and never quietly becomes a
        # local answer: a substituted answer would carry a provenance nobody
        # asked for.
        return error_response(request.request_id, f"Facet did not answer: {error}")

    # Fail closed on a result of the wrong shape. Facet already refuses to
    # return the wrong number of reasoned answers; Ethnos checks it too,
    # because Ethnos is what would type them into real answer boxes. The exact
    # route is deliberately not held to this: a quartic has four roots whatever
    # the page's control looked like, and that is the mathematics answering.
    if (
        solution.route == "reasoning"
        and len(solution.answer.parts or (solution.answer.entry,)) != parts_required
    ):
        return error_response(
            request.request_id,
            f"Facet did not return the {parts_required} separate answers "
            "this question needs.",
            "ambiguous",
        )

    return SolveResponse(
        request_id=request.request_id,
        status="ready",
        problem_text="\n".join((instruction, *expressions)),
        answer=answer_payload(
            solution.answer.display,
            solution.answer.entry,
            solution.answer.parts,
            solution.answer.entry_mode,
        ),
        certainty=Certainty(
            prompt_seen=prompt_seen,
            answer_parts=parts_required,
            # Facet's own identity for the route it took, reported rather than
            # assembled here: "Facet Exact", or "Facet Reasoning · GPU".
            source=solution.source,
            transcription="exact",
            insertable=True,
            issues=[],
            # An exact answer is an exact answer wherever it was computed. The
            # question a reader is asking is whether a model produced it, and
            # on the exact route none did.
            answered_by="exact" if solution.route == "exact" else "facet",
            router=solution.router,
            router_detail=solution.router_detail,
            reading="mathml",
            method=solution.method,
            # True on both routes now: Facet answered, one way or the other.
            facet_invoked=True,
            requested_backend=solution.requested_backend,
            actual_backend=solution.actual_backend,
            fallback=solution.fallback,
            model=solution.model,
            runtime=solution.runtime,
            device=solution.device,
            elapsed_ms=solution.elapsed_ms,
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
    """Solve straight from the page's MathML, or say why not.

    Ethnos converts the markup, because reading MathJax is a fact about the
    page. The mathematics itself is Facet's deterministic solver -- the same
    one Facet runs when it routes a question -- so the local engine and the
    Facet engine cannot answer the same question differently.

    Returns the answer and an empty reason, or None and why it declined.
    """
    from facet_runtime.exact import solve_exact

    from .hawkes_mathml import UnsupportedMathML, mathml_to_latex

    expressions: list[str] = []
    conversion_failed = False
    for item in markup:
        try:
            expressions.append(mathml_to_latex(item))
        except UnsupportedMathML:
            conversion_failed = True
    if conversion_failed or not expressions:
        return None, markup_decline_reason(True)

    solution, decline = solve_exact(instruction, expressions)
    if solution is None:
        return None, decline
    return answer_payload(
        solution.display, solution.entry, solution.parts, solution.entry_mode
    ), ""


def _equation_answer(instruction: str, expressions: list[str]) -> AnswerPayload | None:
    """Map one exact equation result onto the page's structured answer model."""
    from facet_runtime.exact import solve_one_equation

    return _shaped(solve_one_equation(instruction, expressions))


def _polynomial_classification(
    instruction: str, expressions: list[str]
) -> AnswerPayload | None:
    """Classify polynomial-choice questions without needing a screenshot."""
    from facet_runtime.exact import classify_polynomial

    return _shaped(classify_polynomial(instruction, expressions))


def _realness_answer(instruction: str, expressions: list[str]) -> AnswerPayload | None:
    """Answer "determine if this is a real number", or None if not asked."""
    from facet_runtime.exact import evaluate_real_radical

    return _shaped(evaluate_real_radical(instruction, expressions))


def _shaped(solution) -> AnswerPayload | None:
    """One exact solution as an answer this page could take, or nothing."""
    if solution is None:
        return None
    return answer_payload(
        solution.display, solution.entry, solution.parts, solution.entry_mode
    )


def _health(request_id: str) -> SolveResponse:
    """Answer `health`, and say which transport a solve would actually use.

    A health check that only says "ready" cannot distinguish a companion that
    would run Facet here from one that would reach for a machine across the
    room, and for a while the documentation and the code disagreed about which.
    Naming the transport costs one stdlib import -- no model, no Facet process
    -- and is the fastest honest answer to "where would this solve run?".

    A transport that cannot be resolved is a refusal rather than a "ready" with
    a caveat: a solve would fail on it, so health should not read as green.
    """
    try:
        from .facet_client import transport_report  # noqa: PLC0415

        transport = transport_report()
    # The import is inside the guard on purpose: an unrecognised transport is
    # refused where the client is loaded, and `health` is answered before the
    # try/except that protects a solve. A misconfiguration must be a refusal
    # this host reports, not one that takes the host down with it.
    except Exception as error:  # noqa: BLE001 - health must always answer
        return error_response(
            request_id,
            f"Facet transport misconfigured: {type(error).__name__}: {error}",
        )
    return SolveResponse(
        request_id=request_id,
        status="ok",
        message=f"ethnos ready; facet transport {transport['transport']}",
    )


def handle(raw: dict, report=None) -> SolveResponse:
    """Validate one message and route it to its operation."""
    try:
        request = SolveRequest.model_validate(raw)
    except ValueError as exc:
        return error_response(
            str(raw.get("request_id", ""))[:64], f"Invalid request: {exc}"
        )

    if request.operation == "health":
        return _health(request.request_id)
    if request.origin != "https://learn.hawkeslearning.com":
        return error_response(
            request.request_id, "The requesting origin is not allowed."
        )
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
            write_message(
                stdout, error_response("", f"Malformed message: {exc}").model_dump()
            )
            return 1
        if raw is None:
            return 0
        if not isinstance(raw, dict):
            write_message(
                stdout, error_response("", "Message was not an object").model_dump()
            )
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
