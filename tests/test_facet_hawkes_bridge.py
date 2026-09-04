"""Hawkes across the Facet boundary: Ethnos keeps the question, Facet the run.

The protocol itself is covered in `test_facet_client.py`. What is checked here
is the division of labour: that Hawkes prompting and answer handling stay on
the Ethnos side, that the browser cannot reach past the boundary, and that a
Facet failure is reported rather than quietly answered locally.
"""

from __future__ import annotations

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


def request(*, engine="facet", mathml=None, instruction="Simplify x squared."):
    return {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "hawkes-1",
        "origin": "https://learn.hawkeslearning.com",
        "solve_engine": engine,
        "problem": {
            "prompt_text": instruction,
            "mathml": [MATHML] if mathml is None else mathml,
        },
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
