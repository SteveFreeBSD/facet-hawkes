"""Hawkes across the Facet boundary: Ethnos keeps the question, Facet the run.

The protocol itself is covered in `test_facet_client.py`. What is checked here
is the division of labour: that Hawkes prompting and answer handling stay on
the Ethnos side, that the browser cannot reach past the boundary, and that a
Facet failure is reported rather than quietly answered locally.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ethnos import hawkes_host
from ethnos.facet_client import (
    FacetExecutionError,
    FacetProtocolError,
    FacetResult,
    FacetTransportError,
)
from ethnos.hawkes_host import _facet_prompt, handle
from ethnos.hawkes_protocol import AnswerPayload, SolveRequest

MATHML = "<math><msup><mi>x</mi><mn>2</mn></msup></math>"
QUARTIC = (
    "<math><mrow><msup><mi>y</mi><mn>4</mn></msup><mo>=</mo><mn>400</mn></mrow></math>"
)


def request(
    *,
    engine="facet",
    mathml=None,
    instruction="Simplify x squared.",
    shape=None,
    shape_count=1,
):
    problem = {
        "prompt_text": instruction,
        "mathml": [MATHML] if mathml is None else mathml,
    }
    if shape is not None:
        problem["answer_shape"] = {"kind": shape, "count": shape_count}
    return {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "hawkes-1",
        "origin": "https://learn.hawkeslearning.com",
        "solve_engine": engine,
        "problem": problem,
    }


def facet_result(**changes) -> FacetResult:
    fields = {
        "text": "FINAL ANSWER: x^2",
        "requested_backend": "gpu",
        "actual_backend": "gpu",
        "runtime": "Ollama 0.33.2",
        "model": "gpt-oss:20b",
        "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
        "elapsed_ms": 812.5,
        "fallback": False,
        "metrics": {"generated_tokens": 12, "decode_tps": 21.2},
        "evidence": {"source": "ollama /api/ps", "device_resident_fraction": 1.0},
    }
    fields.update(changes)
    return FacetResult(**fields)


def answering(monkeypatch, result):
    """Stand in for the whole Facet call, and record what Ethnos asked for."""
    seen: dict = {}

    def fake_generate_text(prompt, **kwargs):
        seen["prompt"] = prompt
        seen["kwargs"] = kwargs
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("ethnos.facet_client.generate_text", fake_generate_text)
    return seen


def test_a_hawkes_question_succeeds_through_the_new_bridge(monkeypatch) -> None:
    answering(monkeypatch, facet_result())

    response = handle(request())

    assert response.status == "ready"
    assert response.answer.display_text == "x^2"
    assert response.answer.keyboard_entry == "x^2"
    assert response.certainty.insertable is True
    assert response.certainty.transcription == "exact"


def test_the_panel_reports_where_the_work_actually_ran(monkeypatch) -> None:
    answering(monkeypatch, facet_result(actual_backend="npu", device="AMD XDNA2 NPU"))

    certainty = handle(request()).certainty

    # Not "GPU", and not "casbox": the provenance is what Facet reported.
    assert certainty.source == "Facet · NPU"
    assert certainty.device == "AMD XDNA2 NPU"
    assert certainty.model == "gpt-oss:20b"
    assert certainty.runtime == "Ollama 0.33.2"
    assert certainty.elapsed_ms == 812.5


def test_ethnos_asks_for_a_constraint_and_never_for_a_device(monkeypatch) -> None:
    seen = answering(monkeypatch, facet_result())

    handle(request())

    assert seen["kwargs"]["accelerator_required"] is True
    assert seen["kwargs"]["allow_fallback"] is False
    assert set(seen["kwargs"]) == {
        "request_id",
        "accelerator_required",
        "allow_fallback",
    }


def test_a_browser_request_id_is_reduced_before_it_crosses(monkeypatch) -> None:
    seen = answering(monkeypatch, facet_result())
    hostile = request()
    hostile["request_id"] = "id with spaces; and ;$(id)"

    handle(hostile)

    assert seen["kwargs"]["request_id"] == "ethnos-id-with-spaces--and----id"


def test_the_hawkes_prompt_is_built_by_ethnos_not_by_facet(monkeypatch) -> None:
    seen = answering(monkeypatch, facet_result())

    handle(request())

    # Facet receives a bounded intelligence request. Everything that makes it a
    # Hawkes request -- the instruction, the expression, the answer format --
    # was decided on this side of the boundary.
    assert seen["prompt"] == _facet_prompt("Simplify x squared.", ["x^2"])
    assert "FINAL ANSWER:" in seen["prompt"]


def test_the_fixed_prompt_does_not_teach_placeholder_tags() -> None:
    prompt = _facet_prompt("Simplify.", ["x^2"])

    assert "FINAL ANSWER:" in prompt
    assert "<answer>" not in prompt
    assert "Do not repeat the input expression or output an equals sign" in prompt


@pytest.mark.parametrize(
    "field",
    [
        "ssh_host",
        "username",
        "executable",
        "backend",
        "remote_command",
        "model",
        "device",
        "path",
        "constraints",
    ],
)
def test_the_browser_cannot_name_execution_configuration(field: str) -> None:
    with pytest.raises(ValueError):
        SolveRequest.model_validate({**request(), field: "browser-controlled"})


def test_the_browser_chooses_an_engine_and_nothing_else() -> None:
    assert SolveRequest.model_validate(request()).solve_engine == "facet"
    assert (
        SolveRequest.model_validate(request(engine="ethnos")).solve_engine == "ethnos"
    )
    with pytest.raises(ValueError):
        SolveRequest.model_validate({**request(), "solve_engine": "garbage"})


def test_the_default_request_still_takes_the_local_ethnos_path(monkeypatch) -> None:
    plain = request(engine="ethnos")
    plain.pop("solve_engine")
    monkeypatch.setattr(
        "ethnos.hawkes_host._solve_from_markup",
        lambda *_args: (AnswerPayload(display_text="x^2", keyboard_entry="x^2"), ""),
    )
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("a default request reached Facet"),
    )

    response = handle(plain)

    assert response.status == "ready"
    assert response.certainty.source == "markup"


def test_facet_mode_requires_exact_markup_and_reaches_nothing_without_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("Facet was called without MathML"),
    )
    without = request(mathml=[])
    without["problem"]["screenshot_png_base64"] = "not-used"

    response = handle(without)

    assert response.status == "unsupported"
    assert response.answer is None
    assert "requires readable Hawkes MathML" in response.message


@pytest.mark.parametrize(
    "failure",
    [
        FacetTransportError("Facet SSH transport failed: no route to host"),
        FacetProtocolError("Facet returned malformed JSON"),
        FacetExecutionError("execution_failed", "Ollama returned no response text"),
        FacetExecutionError("constraint_unsatisfied", "no Facet accelerator"),
    ],
)
def test_a_facet_failure_is_reported_and_never_answered_locally(
    monkeypatch, failure
) -> None:
    answering(monkeypatch, failure)
    # The exact solvers run once, ahead of Facet, and decline this question.
    # The invariant is what happens after Facet fails: nothing may answer in
    # its place, because a substituted answer would carry a provenance nobody
    # asked for. Counting the calls says both things at once.
    attempts = []
    real = hawkes_host._solve_from_markup

    def counting(instruction, markup):
        attempts.append(instruction)
        return real(instruction, markup)

    monkeypatch.setattr("ethnos.hawkes_host._solve_from_markup", counting)

    response = handle(request())

    assert len(attempts) == 1, "the local solver ran again after Facet failed"
    assert response.status == "error"
    assert response.answer is None
    assert response.certainty is None
    assert "Facet did not answer" in response.message


def test_a_facet_run_with_no_final_answer_is_ambiguous_not_inserted(
    monkeypatch,
) -> None:
    answering(monkeypatch, facet_result(text="I think it is probably x squared."))

    response = handle(request())

    assert response.status == "ambiguous"
    assert response.answer is None


def test_an_unwanted_origin_never_reaches_facet(monkeypatch) -> None:
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("a foreign origin reached Facet"),
    )
    foreign = request()
    foreign["origin"] = "https://example.com"

    response = handle(foreign)

    assert response.status == "error"
    assert "origin is not allowed" in response.message


# Markup taken from a live lesson, and already answered exactly. Facet must
# never see it: a checkable millisecond is not worth trading for a second.
RATIONAL_EXPONENTS = (
    "<math><mstyle>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>4</mn></mfrac></msup>"
    "<mo>⋅</mo>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>5</mn></mfrac></msup>"
    "</mstyle></math>"
)
#: (x + 1) / (x^2 - 9), as MathJax leaves it in the page. "Find the domain"
#: matches no exact operation, so this is the shape that costs a screenshot,
#: two vision readings and the better part of a minute today.
DOMAIN_RATIONAL = (
    "<math><mrow><mfrac>"
    "<mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow>"
    "<mrow><msup><mi>x</mi><mn>2</mn></msup><mo>−</mo><mn>9</mn></mrow>"
    "</mfrac></mrow></math>"
)
DOMAIN_INSTRUCTION = (
    "Find the domain of the following function. Write your answer in interval notation."
)


def test_an_exactly_solvable_question_never_reaches_facet(monkeypatch) -> None:
    """SymPy keeps what it can answer, even when the browser chose Facet.

    Choosing the Facet engine chooses where the *remainder* goes. It does not
    buy a model's opinion of a question that exact mathematics already settles
    in a millisecond, and settles checkably.
    """
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("an exactly solvable question reached Facet"),
    )

    response = handle(
        request(
            mathml=[RATIONAL_EXPONENTS],
            instruction="Simplify. Express your answer using rational exponents.",
        )
    )

    assert response.status == "ready"
    assert response.answer.display_text == "y^(27/20)"
    # Reported as the exact reading it was, not as a Facet run.
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"
    assert response.certainty.insertable is True
    assert response.certainty.model is None


def test_facet_answers_the_question_that_falls_past_the_exact_solver(
    monkeypatch,
) -> None:
    """The live shape: exact path declines, Facet reasons, no screenshot."""
    seen = answering(
        monkeypatch,
        facet_result(text="FINAL ANSWER: (-∞,-3)∪(-3,3)∪(3,∞)"),
    )

    response = handle(request(mathml=[DOMAIN_RATIONAL], instruction=DOMAIN_INSTRUCTION))

    # Ethnos handed Facet the exact expression off the page. Nothing was
    # transcribed, and no picture was taken.
    assert "\\frac{x+1}{x^2-9}" in seen["prompt"]
    assert DOMAIN_INSTRUCTION in seen["prompt"]
    assert response.status == "ready"
    assert response.answer.display_text == "(-∞,-3)∪(-3,3)∪(3,∞)"
    assert response.certainty.source == "Facet · GPU"
    assert response.certainty.insertable is True


def test_the_question_label_reaches_facet_when_the_page_supplied_one() -> None:
    """The label is the only thing separating two steps of one problem."""
    labelled = _facet_prompt("Simplify.", ["x^2"], label="Question 4 of 12")
    plain = _facet_prompt("Simplify.", ["x^2"])

    assert "Question: Question 4 of 12" in labelled
    # A page that supplied no label adds no empty line to the prompt.
    assert "Question:" not in plain


# A real Hawkes shape with two answers and no exact operation to match: the
# roots of a quadratic asked for as intercepts rather than as a solve.
QUADRATIC = (
    "<math><mrow><msup><mi>y</mi><mn>2</mn></msup><mo>−</mo><mn>4</mn>"
    "<mo>⁢</mo><mi>y</mi><mo>−</mo><mn>5</mn><mo>=</mo><mn>0</mn></mrow></math>"
)
INTERCEPTS = "Find the x-intercepts of the following function."
TWO_PART_REPLY = "FINAL ANSWER: y = -1 or y = 5\nPART 1: -1\nPART 2: 5"
FOUR_PART_REPLY = (
    "FINAL ANSWER: y = -2 or y = 2 or y = -3 or y = 3\n"
    "PART 1: -2\nPART 2: 2\nPART 3: -3\nPART 4: 3"
)


def test_a_single_field_answer_is_unchanged_by_the_shape_field(monkeypatch) -> None:
    """The one-box path is exactly what it was before shapes existed."""
    seen = answering(monkeypatch, facet_result())

    response = handle(request(shape="field"))

    # The single-value contract, word for word as it was.
    assert "Your entire response must be one line" in seen["prompt"]
    assert "PART 1:" not in seen["prompt"]
    assert seen["prompt"] == _facet_prompt("Simplify x squared.", ["x^2"])
    assert response.answer.display_text == "x^2"
    assert response.answer.keyboard_entry == "x^2"
    assert response.answer.parts == []


def test_an_absent_shape_is_read_as_the_single_box_it_always_was(
    monkeypatch,
) -> None:
    """An add-on that says nothing gets exactly the old behaviour."""
    seen = answering(monkeypatch, facet_result())

    handle(request())

    assert seen["prompt"] == _facet_prompt("Simplify x squared.", ["x^2"])


def test_a_paired_answer_shape_reaches_facet_as_a_two_part_contract(
    monkeypatch,
) -> None:
    """The shape crosses as a requirement on the reply, not as a page."""
    seen = answering(monkeypatch, facet_result(text=TWO_PART_REPLY))

    handle(
        request(
            mathml=[QUADRATIC],
            instruction=INTERCEPTS,
            shape="multi",
            shape_count=2,
        )
    )

    assert "This question takes 2 separate answers." in seen["prompt"]
    assert "PART 1: answer number 1 by itself" in seen["prompt"]
    assert "PART 2: answer number 2 by itself" in seen["prompt"]
    # Facet is told what to produce, never what the page is made of.
    for leak in ("field", "editor", "input", "box id", "DOM", "radio"):
        assert leak not in seen["prompt"].replace("answer box", "")


def test_a_structured_two_part_reply_survives_validation_intact(
    monkeypatch,
) -> None:
    """The parts arrive as parts, never as prose to be split later."""
    answering(monkeypatch, facet_result(text=TWO_PART_REPLY))

    response = handle(
        request(
            mathml=[QUADRATIC],
            instruction=INTERCEPTS,
            shape="multi",
            shape_count=2,
        )
    )

    assert response.status == "ready"
    assert response.answer.display_text == "y = -1 or y = 5"
    assert response.answer.parts == ["-1", "5"]
    # No single string can be typed into two separate boxes, and the exact
    # two-root path already leaves this empty for the same reason.
    assert response.answer.keyboard_entry == ""
    assert response.certainty.source == "Facet · GPU"
    assert response.certainty.insertable is True


def test_a_structured_four_part_facet_reply_survives_validation_intact(
    monkeypatch,
) -> None:
    answering(monkeypatch, facet_result(text=FOUR_PART_REPLY))

    response = handle(request(shape="multi", shape_count=4))

    assert response.status == "ready"
    assert response.answer.parts == ["-2", "2", "-3", "3"]
    assert response.answer.keyboard_entry == ""
    assert response.certainty.answered_by == "facet"


def test_the_comma_instruction_makes_one_box_a_two_value_answer(
    monkeypatch,
) -> None:
    """Ethnos reads the shape out of the question, not only out of the page."""
    seen = answering(monkeypatch, facet_result(text=TWO_PART_REPLY))

    handle(
        request(
            mathml=[QUADRATIC],
            instruction=(
                "Find the x-intercepts of the following function. "
                "Separate multiple answers with a comma."
            ),
            shape="field",
        )
    )

    assert "This question takes 2 separate answers." in seen["prompt"]


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ("FINAL ANSWER: y = -1 or y = 5", "no PART lines at all"),
        ("FINAL ANSWER: -1\nPART 1: -1", "one part where two were asked for"),
        (
            "FINAL ANSWER: a\nPART 1: -1\nPART 2: 5\nPART 3: 7",
            "three parts where two were asked for",
        ),
        (
            "FINAL ANSWER: a\nPART 1: -1\nPART 3: 5",
            "parts that are not numbered from one",
        ),
        (
            "FINAL ANSWER: a\nPART 2: 5\nPART 1: -1",
            "parts out of order, so which box is which is a guess",
        ),
    ],
)
def test_a_mismatched_part_count_fails_closed(monkeypatch, reply, why) -> None:
    """An answer of the wrong shape is worse than no answer.

    Nothing downstream would question it: the insertion path takes `parts` and
    types them into real answer fields.
    """
    answering(monkeypatch, facet_result(text=reply))

    response = handle(
        request(
            mathml=[QUADRATIC],
            instruction=INTERCEPTS,
            shape="multi",
            shape_count=2,
        )
    )

    assert response.status == "ambiguous", why
    assert response.answer is None
    assert "2 separate answers" in response.message


def test_a_paired_shape_still_never_preempts_the_exact_solver(monkeypatch) -> None:
    """Shape changes what Facet is asked for, never whether it is asked."""
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("an exactly solvable question reached Facet"),
    )

    response = handle(
        request(
            mathml=[RATIONAL_EXPONENTS],
            instruction="Simplify. Express your answer using rational exponents.",
            shape="multi",
            shape_count=2,
        )
    )

    assert response.status == "ready"
    assert response.certainty.source == "markup"


def test_four_exact_roots_never_invoke_facet(monkeypatch) -> None:
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("a complete exact quartic reached Facet"),
    )

    response = handle(
        request(
            mathml=[QUARTIC],
            instruction="Solve the following polynomial equation.",
            shape="multi",
            shape_count=4,
        )
    )

    assert response.status == "ready"
    assert response.answer.parts == [
        "-2*sqrt(5)",
        "2*sqrt(5)",
        "-2*i*sqrt(5)",
        "2*i*sqrt(5)",
    ]
    assert response.certainty.answered_by == "exact"
    assert response.certainty.router == "solved"
    assert response.certainty.facet_invoked is False


def test_the_page_prefix_is_stated_so_facet_does_not_repeat_it() -> None:
    """`r = [box]` already prints the label; repeating it would be typed in."""
    prompt = _facet_prompt(
        "Solve the following formula for the indicated variable. Solve for r.",
        ["C=2*pi*r"],
        prefix="r",
    )

    assert "already prints `r =` beside the answer" in prompt


def test_the_browser_cannot_invent_an_answer_shape() -> None:
    with pytest.raises(ValueError):
        SolveRequest.model_validate(request(shape="freeform"))
    with pytest.raises(ValueError):
        SolveRequest.model_validate(
            {
                **request(),
                "problem": {"mathml": [MATHML], "answer_shape": {"fieldId": "QBase1"}},
            }
        )
    with pytest.raises(ValueError):
        SolveRequest.model_validate(
            {
                **request(),
                "problem": {
                    "mathml": [MATHML],
                    "answer_shape": {"kind": "multi", "count": 1},
                },
            }
        )


EXTENSION = Path(__file__).resolve().parents[1] / "extension"


def _lift(source: str, name: str) -> str:
    """Lift one brace-balanced function out of `background.js`.

    The event page is an ES module and cannot be evaluated whole here, but the
    normaliser is pure and has no imports, so it runs on its own.
    """
    start = source.index(f"function {name}(")
    depth, index = 0, source.index("{", start)
    for cursor in range(index, len(source)):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return source[start : cursor + 1]
    raise AssertionError(f"{name} is not brace-balanced")


@pytest.mark.parametrize(
    ("described", "expected"),
    [
        ({"kind": "multi", "editors": [{}, {}]}, "multi"),
        ({"kind": "option"}, "option"),
        ({"kind": "dynamic"}, "field"),
        ({"kind": "textbox"}, "field"),
        # An editor the browser could not describe is the single box, which is
        # what every version before answer shapes existed implied.
        ({"kind": "something-new"}, "field"),
        (None, "field"),
    ],
)
def test_the_browser_normalises_every_editor_into_one_shape_word(
    described, expected
) -> None:
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    import json

    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    context = quickjs.Context()
    context.eval(_lift(source, "answerShapeOf"))

    shape = json.loads(
        context.eval(f"JSON.stringify(answerShapeOf({json.dumps(described)}))")
    )

    expected_shape = {"kind": expected}
    if expected == "multi":
        expected_shape["count"] = 2
    assert shape == expected_shape
    # Whatever the browser reports, the protocol must accept it.
    assert (
        SolveRequest.model_validate(
            {**request(), "problem": {"mathml": [MATHML], "answer_shape": shape}}
        ).problem.answer_shape.kind
        == expected
    )


def test_the_editor_description_itself_never_crosses_to_the_host() -> None:
    """Character sets, templates and field ids stay on the browser side."""
    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    normaliser = _lift(source, "answerShapeOf")

    for browser_only in ("allowedCharacters", "templates", "slots", "fieldId"):
        assert browser_only not in normaliser
