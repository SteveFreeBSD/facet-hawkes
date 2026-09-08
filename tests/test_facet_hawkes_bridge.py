"""Hawkes across the Facet boundary: Ethnos keeps the page, Facet the answering.

The protocol itself is covered in `test_facet_client.py`. What is checked here
is the division of labour, and it is not the division it used to be. Ethnos ran
the exact solvers and asked Facet only about what they declined, so the routing
decision -- exact mathematics or a reasoning model -- was made by the side that
owns the browser. Facet makes it now.

These tests run the real Facet in-process (see `facet_loopback`), so the route
is genuinely decided on the far side: Ethnos builds its real request, Facet's
real router runs the real deterministic solvers, and only the model is a stand-
in. That is also what makes the two routes distinguishable -- if the stand-in
is ever asked anything, reasoning ran.

What must still hold on this side: the browser cannot reach past the boundary,
nothing about the page crosses it, structured answers survive intact, and a
Facet failure is reported rather than quietly answered locally.
"""

from __future__ import annotations

import re
import json
from pathlib import Path

import pytest

from facet_loopback import FakeAdapter, facet, reasoning
from facet_runtime.prompts import leaks
from facet_runtime.solve import MathProblem, reasoning_prompt

from ethnos import hawkes_host
from ethnos.facet_client import (
    FacetExecutionError,
    FacetProtocolError,
    FacetTransportError,
)
from ethnos.hawkes_host import handle
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
    representations=None,
    choices=None,
):
    problem = {
        "prompt_text": instruction,
        "mathml": [MATHML] if mathml is None else mathml,
    }
    if shape is not None:
        problem["answer_shape"] = {"kind": shape, "count": shape_count}
        if representations is not None:
            problem["answer_shape"]["representations"] = representations
        if choices is not None:
            problem["answer_shape"]["choices"] = choices
    return {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "hawkes-1",
        "origin": "https://learn.hawkeslearning.com",
        "solve_engine": engine,
        "problem": problem,
    }


def prompt_for(instruction, expressions, *, label="", parts=1) -> str:
    """The prompt Facet writes for a question it decided to reason about."""
    return reasoning_prompt(MathProblem(instruction, tuple(expressions), parts, label))


def answering(monkeypatch, text="FINAL ANSWER: x^2", **overrides):
    """A real Facet whose reasoning route, if reached, answers with `text`."""
    adapters = reasoning(text)
    adapters.update(overrides)
    return facet(monkeypatch, **adapters)


def test_a_hawkes_question_succeeds_through_the_new_bridge(monkeypatch) -> None:
    answering(monkeypatch)

    response = handle(request())

    assert response.status == "ready"
    assert response.answer.display_text == "x^2"
    assert response.answer.keyboard_entry == "x^2"
    assert response.certainty.insertable is True
    assert response.certainty.transcription == "exact"


def test_the_panel_reports_where_the_work_actually_ran(monkeypatch) -> None:
    answering(
        monkeypatch,
        gpu=FakeAdapter("gpu", available=False),
        npu=FakeAdapter("npu", text="FINAL ANSWER: x^2", device="AMD XDNA2 NPU"),
    )

    certainty = handle(request()).certainty

    # Not "GPU", and not "casbox": the provenance is what Facet reported, and
    # which accelerator answered was Facet's decision, not a request.
    assert certainty.source == "Facet Reasoning · NPU"
    assert certainty.device == "AMD XDNA2 NPU"
    assert certainty.model == "gpt-oss:20b"
    assert certainty.runtime == "Ollama 0.33.2"
    assert certainty.elapsed_ms >= 0


def test_ethnos_asks_for_a_constraint_and_never_for_a_device(monkeypatch) -> None:
    loopback = answering(monkeypatch)

    handle(request())

    crossed = loopback.requests[0]
    assert crossed["constraints"] == {
        "accelerator_required": True,
        "allow_fallback": False,
    }
    # The whole of what crosses: an operation, an id to correlate a reply, the
    # question, and a need. No runtime, model, device, host, or path.
    assert set(crossed) == {
        "facet_protocol_version",
        "operation",
        "request_id",
        "problem",
        "constraints",
    }


def test_nothing_about_the_page_crosses_the_boundary(monkeypatch) -> None:
    """The request describes a question. There is no way to describe a page."""
    loopback = answering(monkeypatch)

    handle(request())

    problem = loopback.problems[0]
    assert set(problem) == {"instruction", "expressions", "answer_parts"}
    assert problem["instruction"] == "Simplify x squared."
    # The markup itself stays here: converting MathJax is a fact about the
    # page, and Facet is handed the mathematics rather than the document.
    assert problem["expressions"] == ["x^2"]
    assert "<math" not in json.dumps(loopback.requests)


def test_a_browser_request_id_is_reduced_before_it_crosses(monkeypatch) -> None:
    loopback = answering(monkeypatch)
    hostile = request()
    hostile["request_id"] = "id with spaces; and ;$(id)"

    handle(hostile)

    assert loopback.requests[0]["request_id"] == "ethnos-id-with-spaces--and----id"


def test_the_reasoning_prompt_is_facets_to_write(monkeypatch) -> None:
    """Ethnos hands over a question; the prompt is a consequence of routing.

    It used to be built here and sent whether or not it was needed. Facet
    decides whether reasoning happens at all, so Facet writes what it asks.
    """
    loopback = answering(monkeypatch)

    handle(request())

    assert loopback.prompts == [prompt_for("Simplify x squared.", ["x^2"])]
    assert "FINAL ANSWER:" in loopback.prompts[0]


def test_the_fixed_prompt_does_not_teach_placeholder_tags() -> None:
    prompt = prompt_for("Simplify.", ["x^2"])

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


def test_a_request_that_names_no_pipeline_is_routed_by_facet(monkeypatch) -> None:
    """The default is the architecture, not the one it replaced.

    It used to be the companion's own path, from when the browser decided how a
    question got answered. A caller that says nothing now gets how questions are
    answered today; the companion's reader is reached by asking for it.
    """
    plain = request()
    plain.pop("solve_engine")
    loopback = answering(monkeypatch)

    response = handle(plain)

    assert loopback.requests, "a default request did not reach Facet"
    assert response.status == "ready"
    assert response.certainty.facet_invoked is True


def test_a_request_may_still_ask_for_the_companions_own_reader(monkeypatch) -> None:
    """A question drawn as a picture has no mathematics for Facet to route."""
    plain = request(engine="ethnos")
    monkeypatch.setattr(
        "ethnos.hawkes_host._solve_from_markup",
        lambda *_args: (AnswerPayload(display_text="x^2", keyboard_entry="x^2"), ""),
    )
    loopback = facet(monkeypatch)

    response = handle(plain)

    assert loopback.requests == [], "the companion's own path reached Facet"
    assert response.status == "ready"
    assert response.certainty.source == "markup"


def test_facet_mode_requires_exact_markup_and_reaches_nothing_without_it(
    monkeypatch,
) -> None:
    loopback = facet(monkeypatch)
    without = request(mathml=[])
    without["problem"]["screenshot_png_base64"] = "not-used"

    response = handle(without)

    assert loopback.requests == [], "Facet was called without MathML"
    assert response.status == "unsupported"
    assert response.answer is None
    assert "none could be read" in response.message


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
    def failing(**_kwargs):
        raise failure

    monkeypatch.setattr("ethnos.facet_client.solve_math", failing)
    # The invariant is what happens after Facet fails: nothing may answer in
    # its place, because a substituted answer would carry a provenance nobody
    # asked for. The local solvers are now the ones that must not run -- Facet
    # owns the routing, so a local answer here would be a second opinion the
    # panel would label as Facet's.
    attempts = []
    real = hawkes_host._solve_from_markup

    def counting(instruction, markup):
        attempts.append(instruction)
        return real(instruction, markup)

    monkeypatch.setattr("ethnos.hawkes_host._solve_from_markup", counting)

    response = handle(request())

    assert attempts == [], "the local solver answered in Facet's place"
    assert response.status == "error"
    assert response.answer is None
    assert response.certainty is None
    assert "Facet did not answer" in response.message


def test_a_facet_run_with_no_final_answer_is_ambiguous_not_inserted(
    monkeypatch,
) -> None:
    answering(monkeypatch, text="I think it is probably x squared.")

    response = handle(request())

    assert response.status == "ambiguous"
    assert response.answer is None
    assert response.certainty is None


def test_an_unwanted_origin_never_reaches_facet(monkeypatch) -> None:
    loopback = facet(monkeypatch)
    foreign = request()
    foreign["origin"] = "https://example.com"

    response = handle(foreign)

    assert loopback.requests == [], "a foreign origin reached Facet"
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


def test_an_exactly_solvable_question_never_reaches_a_model(monkeypatch) -> None:
    """Facet keeps what its solvers can answer, and no model is asked.

    This is the whole of the routing decision, and it is made on the far side
    now. Facet runs the deterministic solvers first and answers from them, so a
    question exact mathematics settles in a millisecond never costs a model's
    opinion -- and the answer is the one the exact path always gave.
    """
    loopback = answering(monkeypatch)

    response = handle(
        request(
            mathml=[RATIONAL_EXPONENTS],
            instruction="Simplify. Express your answer using rational exponents.",
        )
    )

    assert loopback.prompts == [], "an exactly solvable question reached a model"
    assert response.status == "ready"
    assert response.answer.display_text == "y^(27/20)"
    # Reported as the exact route it was, not as a reasoned one.
    assert response.certainty.source == "Facet Exact"
    assert response.certainty.answered_by == "exact"
    assert response.certainty.router == "solved"
    assert response.certainty.transcription == "exact"
    assert response.certainty.insertable is True
    assert response.certainty.model is None


def test_facet_answers_the_question_that_falls_past_the_exact_solver(
    monkeypatch,
) -> None:
    """The live shape: exact path declines, Facet reasons, no screenshot."""
    loopback = answering(monkeypatch, text="FINAL ANSWER: (-∞,-3)∪(-3,3)∪(3,∞)")

    response = handle(request(mathml=[DOMAIN_RATIONAL], instruction=DOMAIN_INSTRUCTION))

    # Ethnos handed Facet the exact expression off the page. Nothing was
    # transcribed, and no picture was taken.
    assert loopback.problems[0]["expressions"] == ["\\frac{x+1}{x^2-9}"]
    assert DOMAIN_INSTRUCTION in loopback.prompts[0]
    assert response.status == "ready"
    assert response.answer.display_text == "(-∞,-3)∪(-3,3)∪(3,∞)"
    assert response.certainty.source == "Facet Reasoning · GPU"
    assert response.certainty.router == "declined"
    assert response.certainty.router_detail == (
        "no exact operation matched the instruction"
    )
    assert response.certainty.insertable is True


def test_the_question_label_reaches_facet_when_the_page_supplied_one() -> None:
    """The label is the only thing separating two steps of one problem."""
    labelled = prompt_for("Simplify.", ["x^2"], label="Question 4 of 12")
    plain = prompt_for("Simplify.", ["x^2"])

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
    loopback = answering(monkeypatch)

    response = handle(request(shape="field"))

    # The single-value contract, word for word as it was.
    prompt = loopback.prompts[0]
    assert "Your entire response must be one line" in prompt
    assert "PART 1:" not in prompt
    assert prompt == prompt_for("Simplify x squared.", ["x^2"])
    assert response.answer.display_text == "x^2"
    assert response.answer.keyboard_entry == "x^2"
    assert response.answer.parts == []


def test_an_absent_shape_is_read_as_the_single_box_it_always_was(
    monkeypatch,
) -> None:
    """An add-on that says nothing gets exactly the old behaviour."""
    loopback = answering(monkeypatch)

    handle(request())

    assert loopback.problems[0]["answer_parts"] == 1
    assert loopback.prompts[0] == prompt_for("Simplify x squared.", ["x^2"])


def test_a_paired_answer_shape_reaches_facet_as_a_two_part_contract(
    monkeypatch,
) -> None:
    """The shape crosses as a requirement on the reply, not as a page."""
    loopback = answering(monkeypatch, text=TWO_PART_REPLY)

    handle(
        request(
            mathml=[QUADRATIC],
            instruction=INTERCEPTS,
            shape="multi",
            shape_count=2,
        )
    )

    # What crosses is a count. Which controls the add-on saw, and what it is
    # going to do with two values, stays here.
    assert loopback.problems[0]["answer_parts"] == 2
    assert set(loopback.problems[0]) == {"instruction", "expressions", "answer_parts"}
    prompt = loopback.prompts[0]
    assert "This question takes 2 separate answers." in prompt
    # The labels are listed bare; what belongs after each is said separately.
    # Facet stopped listing them as filled-in examples because a model copied
    # one onto a live answer card as the answer.
    assert "\nPART 1:\n" in prompt and "\nPART 2:\n" in prompt
    # Facet is told what to produce, never what the page is made of -- and
    # never that a page is what is asking. The vocabulary is Facet's own list,
    # so this gate tightens whenever Facet's does.
    assert leaks(prompt) == ()
    for leak in ("input", "radio"):
        assert leak not in prompt


# Retained failure f1:6079e2061820668f.  Only the page-owned shape is kept:
# two enabled textboxes, each six characters and restricted to digits/minus.
# The real answer and coursework text are deliberately not fixtures.
RETAINED_NUMERIC_PAIR = [
    {"kind": "signed-integer", "maxLength": 6},
    {"kind": "signed-integer", "maxLength": 6},
]


def test_a_numeric_only_pair_reaches_facet_as_an_answer_form_contract(
    monkeypatch,
) -> None:
    """The count-only request let the reasoner return five-character structure."""
    loopback = answering(monkeypatch, text=TWO_PART_REPLY)

    response = handle(
        request(
            mathml=[QUADRATIC],
            instruction=INTERCEPTS,
            shape="multi",
            shape_count=2,
            representations=RETAINED_NUMERIC_PAIR,
        )
    )

    crossed = loopback.problems[0]
    assert crossed["answer_parts"] == 2
    assert crossed["instruction"].startswith(INTERCEPTS)
    assert "only digits and an optional leading minus sign" in crossed["instruction"]
    assert "at most 6 characters" in crossed["instruction"]
    for structure in ("fraction", "radical", "exponent notation", "parentheses"):
        assert structure in crossed["instruction"]
    assert "field" not in crossed["instruction"].lower()
    assert "editor" not in crossed["instruction"].lower()
    # The representation is a request constraint, not a browser description
    # added to Facet's protocol. It crosses twice on purpose and in two
    # registers: as the sentence above, which a model reads, and as the pair
    # below, which the deterministic route filters its own solutions by and
    # which the verifier holds a reasoned answer to. A requirement only a model
    # can read is not a requirement anything can check.
    assert set(crossed) == {
        "instruction",
        "expressions",
        "answer_parts",
        "answer_representation",
    }
    assert crossed["answer_representation"] == {
        "kind": "signed-integer",
        "max_length": 6,
    }
    assert response.status == "ready"


def test_answer_representations_must_align_with_the_answer_count() -> None:
    with pytest.raises(ValueError):
        SolveRequest.model_validate(
            request(
                shape="multi",
                shape_count=2,
                representations=RETAINED_NUMERIC_PAIR[:1],
            )
        )


def test_a_structured_two_part_reply_survives_validation_intact(
    monkeypatch,
) -> None:
    """The parts arrive as parts, never as prose to be split later."""
    answering(monkeypatch, text=TWO_PART_REPLY)

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
    assert response.certainty.source == "Facet Reasoning · GPU"
    assert response.certainty.insertable is True


def test_a_structured_four_part_facet_reply_survives_validation_intact(
    monkeypatch,
) -> None:
    answering(monkeypatch, text=FOUR_PART_REPLY)

    response = handle(request(shape="multi", shape_count=4))

    assert response.status == "ready"
    assert response.answer.parts == ["-2", "2", "-3", "3"]
    assert response.answer.keyboard_entry == ""
    assert response.certainty.answered_by == "facet"


def test_the_comma_instruction_makes_one_box_a_two_value_answer(
    monkeypatch,
) -> None:
    """Ethnos reads the shape out of the question, not only out of the page."""
    loopback = answering(monkeypatch, text=TWO_PART_REPLY)

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

    assert loopback.problems[0]["answer_parts"] == 2
    assert "This question takes 2 separate answers." in loopback.prompts[0]


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
    types them into real answer fields. Facet refuses first, because it is what
    asked for the shape; Ethnos refuses again, because it is what would type it.
    """
    answering(monkeypatch, text=reply)

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
    """Shape changes what a model would be asked, never whether one is."""
    loopback = answering(monkeypatch)

    response = handle(
        request(
            mathml=[RATIONAL_EXPONENTS],
            instruction="Simplify. Express your answer using rational exponents.",
            shape="multi",
            shape_count=2,
        )
    )

    assert loopback.prompts == [], "a shaped question preempted the exact solver"
    assert response.status == "ready"
    assert response.certainty.source == "Facet Exact"


def test_four_exact_roots_never_reach_a_model(monkeypatch) -> None:
    loopback = answering(monkeypatch)

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
    assert loopback.prompts == [], "a complete exact quartic reached a model"
    assert response.certainty.answered_by == "exact"
    assert response.certainty.router == "solved"
    # Facet answered it -- with mathematics, which is the distinction that
    # matters. `answered_by` is what says no model took part.
    assert response.certainty.facet_invoked is True


def test_the_page_prefix_is_stated_so_facet_does_not_repeat_it() -> None:
    """`r = [box]` already prints the label; repeating it would be typed in.

    Ethnos cares that Facet is told to answer with the value alone. How Facet
    words that is Facet's own business, and it no longer words it in terms of
    a page, because nothing on the far side of that boundary has a page.
    """
    prompt = prompt_for(
        "Solve the following formula for the indicated variable. Solve for r.",
        ["C=2*pi*r"],
    )

    assert "`r =` is already written for you" in prompt
    assert "give only what follows it in each answer" in prompt


def test_a_prefixed_question_may_still_take_several_answers(monkeypatch) -> None:
    """`x = [box]` and two roots is one question, not two contradictory ones.

    Ethnos reaches this pairing two ways, and neither consults the other: the
    add-on reports a multi control, or the instruction asks for comma-separated
    answers. A quadratic solved for x does both. Facet is therefore told the
    variable *and* the count, and this holds that it may be -- refusing the
    combination here would refuse a real Hawkes question.
    """
    loopback = answering(monkeypatch, text=TWO_PART_REPLY)

    handle(
        request(
            mathml=[QUADRATIC],
            instruction="Solve for x. Separate multiple answers with a comma.",
            shape="multi",
            shape_count=2,
        )
    )

    crossed = loopback.problems[0]
    assert crossed["answer_parts"] == 2
    assert "Solve for x." in crossed["instruction"]
    # Both statements reach the model, and they agree about how many answers
    # there are. A singular one beside a contract asking for two is the fault
    # this pairing used to carry.
    prompt = loopback.prompts[0]
    assert "`x =` is already written for you" in prompt
    assert "This question takes 2 separate answers." in prompt
    assert "only the value that follows it" not in prompt
    assert leaks(prompt) == ()


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


def _normaliser():
    """`answerShapeOf`, over the real bound on how many parts an answer has."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    # Read from the module the event page imports it from, so a bound that
    # moves in one place and not the other fails here.
    context.eval(
        (EXTENSION / "common" / "config.js")
        .read_text(encoding="utf-8")
        .replace("export ", "")
    )
    # And the rules module it now reads the table mapping's shape from, for the
    # same reason: one definition of "this is a placeable mapping", checked
    # here against the file the event page actually imports.
    rules = re.sub(
        r"^export ",
        "",
        (EXTENSION / "common" / "editor-rules.js").read_text(encoding="utf-8"),
        flags=re.MULTILINE,
    )
    context.eval(re.sub(r"^import .*\n", "", rules, flags=re.MULTILINE))
    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    # `optionShape` too: a radio group's shape is stated once and read from
    # both the option branch and the group-of-options branch, so lifting only
    # the caller would leave the one shape this file most needs undefined.
    context.eval(_lift(source, "optionShape"))
    context.eval(_lift(source, "answerShapeOf"))
    return context


def _lift(source: str, name: str) -> str:
    """Lift one brace-balanced function out of `background.js`.

    The event page is an ES module and cannot be evaluated whole here, but the
    normaliser is pure, so it runs beside the one constant it reads --
    see `_normaliser`.
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
    import json

    context = _normaliser()

    shape = json.loads(
        context.eval(f"JSON.stringify(answerShapeOf({json.dumps(described)}))")
    )

    expected_shape = {"kind": expected}
    if expected == "multi":
        expected_shape["count"] = 2
    # An option question states its count too: one answer, whatever the size of
    # the group it is chosen from. Saying it is what keeps a five-button radio
    # group from being read as five answers.
    if expected == "option":
        expected_shape["count"] = 1
    assert shape == expected_shape
    # Whatever the browser reports, the protocol must accept it.
    assert (
        SolveRequest.model_validate(
            {**request(), "problem": {"mathml": [MATHML], "answer_shape": shape}}
        ).problem.answer_shape.kind
        == expected
    )


def test_the_retained_numeric_pair_is_normalised_without_crossing_editor_rules() -> (
    None
):
    context = _normaliser()
    editor = {
        "kind": "multi",
        "editors": [
            {
                "kind": "textbox",
                "enabled": True,
                "maxLength": 6,
                "allowedCharacters": "[0-9-]",
                "templates": {},
            },
            {
                "kind": "textbox",
                "enabled": True,
                "maxLength": 6,
                "allowedCharacters": "[0-9-]",
                "templates": {},
            },
        ],
    }

    shape = json.loads(
        context.eval(f"JSON.stringify(answerShapeOf({json.dumps(editor)}))")
    )

    assert shape == {
        "kind": "multi",
        "count": 2,
        "representations": RETAINED_NUMERIC_PAIR,
    }
    assert set(shape) == {"kind", "count", "representations"}
    assert all(set(item) == {"kind", "maxLength"} for item in shape["representations"])


def test_the_editor_description_itself_never_crosses_to_the_host() -> None:
    """Raw character sets, templates, slots and field ids stay browser-side."""
    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    normaliser = _lift(source, "answerShapeOf")

    # `allowedCharacters` is read here only to recognize the one closed
    # signed-integer contract. Its raw value is absent from the returned shape,
    # as the retained-evidence test above proves.
    for browser_only in ("templates", "slots", "fieldId"):
        assert browser_only not in normaliser


#: Facet's own description of the FINAL ANSWER line, which a model handed back
#: as the answer on a live quadrant question. Data here, not a pattern: what
#: refuses it is that it is a sentence, whichever sentence it is.
ECHOED_CONTRACT = "all answers as they would ordinarily be written"


def test_an_echoed_contract_never_crosses_as_an_answer(monkeypatch) -> None:
    """The live leak, through the real protocol and the real router.

    The parts were checked all along -- the right number of them, numbered in
    order, non-empty. Their *rendering* was not, and the rendering is what a
    person is shown. Facet rebuilds it from the parts it did check rather than
    publishing a line it never read.
    """
    answering(
        monkeypatch,
        text=f"FINAL ANSWER: {ECHOED_CONTRACT}\nPART 1: -1\nPART 2: 5",
    )

    response = handle(
        request(
            mathml=[QUADRATIC], instruction=INTERCEPTS, shape="multi", shape_count=2
        )
    )

    assert response.status == "ready"
    assert response.answer.parts == ["-1", "5"]
    assert response.answer.display_text == "-1, 5"
    assert ECHOED_CONTRACT not in response.model_dump_json()


def test_an_echoed_part_is_refused_rather_than_rendered_around(monkeypatch) -> None:
    """A part is what would be typed into a real answer box."""
    answering(
        monkeypatch,
        text="FINAL ANSWER: -1, 5\nPART 1: answer number 1 by itself\nPART 2: 5",
    )

    response = handle(
        request(
            mathml=[QUADRATIC], instruction=INTERCEPTS, shape="multi", shape_count=2
        )
    )

    assert response.status == "ambiguous"
    assert response.answer is None
    assert "no usable answer" in response.message


def test_prose_on_a_single_value_question_is_refused(monkeypatch) -> None:
    """There is no checked part list to rebuild a single answer from."""
    answering(monkeypatch, text=f"FINAL ANSWER: {ECHOED_CONTRACT}")

    response = handle(request(mathml=[QUADRATIC], instruction=INTERCEPTS))

    assert response.status == "ambiguous"
    assert response.answer is None
    assert ECHOED_CONTRACT not in response.model_dump_json()


#: The live question: one radio group, five choices, one answer.
QUADRANT_POINT = (
    "<math><mrow><mo>(</mo><mn>3</mn><mo>,</mo><mo>-</mo><mn>4</mn><mo>)</mo>"
    "</mrow></math>"
)
QUADRANT_CHOICES = [
    "Quadrant I",
    "Quadrant II",
    "Quadrant III",
    "Quadrant IV",
    "The point is on an axis",
]


def test_a_choice_question_crosses_as_one_answer_and_its_alternatives(
    monkeypatch,
) -> None:
    """The live defect, end to end.

    A five-button radio group was crossing as `answer_parts: 5`, and a model
    was asked for five separate values to a question with one. What crosses now
    is one answer and the words the page printed beside each button.
    """
    loopback = answering(monkeypatch)

    response = handle(
        request(
            mathml=[QUADRANT_POINT],
            instruction="In which quadrant does the point lie?",
            shape="option",
            choices=QUADRANT_CHOICES,
        )
    )

    problem = loopback.problems[0]
    assert problem["answer_parts"] == 1
    assert problem["answer_choices"] == QUADRANT_CHOICES
    # Still a question and nothing about a page: no control, no field, no group.
    assert set(problem) == {
        "instruction",
        "expressions",
        "answer_parts",
        "answer_choices",
    }
    assert response.status == "ready"
    assert response.answer.display_text == "Quadrant IV"
    assert response.answer.parts == []


def test_the_family_engages_no_model_at_all(monkeypatch) -> None:
    """Two comparisons against zero. There is nothing here to reason about."""
    loopback = answering(monkeypatch)

    response = handle(
        request(
            mathml=[QUADRANT_POINT],
            instruction="In which quadrant does the point lie?",
            shape="option",
            choices=QUADRANT_CHOICES,
        )
    )

    assert loopback.prompts == []
    assert response.certainty.answered_by == "exact"
    assert response.certainty.router == "solved"
    assert response.certainty.model is None
    assert response.certainty.method == "exact quadrant classification"


def test_the_answer_is_one_of_the_pages_own_choices(monkeypatch) -> None:
    answering(monkeypatch)

    response = handle(
        request(
            mathml=[
                "<math><mrow><mo>(</mo><mn>0</mn><mo>,</mo><mn>5</mn><mo>)</mo>"
                "</mrow></math>"
            ],
            instruction="In which quadrant does the point lie?",
            shape="option",
            choices=QUADRANT_CHOICES,
        )
    )

    assert response.answer.display_text == "The point is on an axis"
    assert response.answer.display_text in QUADRANT_CHOICES
