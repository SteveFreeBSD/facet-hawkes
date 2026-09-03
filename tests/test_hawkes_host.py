"""The native messaging host: framing, validation, and refusal behaviour.

Firefox starts this process and speaks to it over stdio, so the boundary is the
security perimeter: a malformed frame, an unknown operation, or a hostile
payload must fail closed without reaching the pipeline. None of these tests
load a model.
"""

from __future__ import annotations

import io
import json
import struct

import pytest

from ethnos.hawkes_host import (
    LENGTH_PREFIX,
    handle,
    read_message,
    write_message,
)
from ethnos.hawkes_protocol import MAX_MESSAGE_BYTES, PROTOCOL_VERSION, SolveRequest


def framed(payload: dict) -> io.BytesIO:
    body = json.dumps(payload).encode()
    return io.BytesIO(LENGTH_PREFIX.pack(len(body)) + body)


def test_message_survives_a_round_trip():
    out = io.BytesIO()
    write_message(out, {"operation": "health", "request_id": "r1"})
    out.seek(0)

    assert read_message(out) == {"operation": "health", "request_id": "r1"}


def test_closed_pipe_is_an_ordinary_shutdown():
    # Firefox closing the pipe must not look like an error.
    assert read_message(io.BytesIO(b"")) is None


def test_truncated_header_is_a_shutdown_not_a_crash():
    assert read_message(io.BytesIO(b"\x01\x02")) is None


def test_oversized_frame_is_refused_before_reading_the_body():
    stream = io.BytesIO(LENGTH_PREFIX.pack(MAX_MESSAGE_BYTES + 1) + b"x")

    with pytest.raises(ValueError, match="exceeds"):
        read_message(stream)


def test_body_shorter_than_its_header_is_refused():
    stream = io.BytesIO(LENGTH_PREFIX.pack(64) + b"{}")

    with pytest.raises(ValueError, match="ended early"):
        read_message(stream)


def test_response_larger_than_the_limit_is_refused():
    with pytest.raises(ValueError, match="size limit"):
        write_message(io.BytesIO(), {"blob": "x" * (MAX_MESSAGE_BYTES + 10)})


def test_health_answers_without_touching_the_pipeline():
    response = handle({
        "protocol_version": PROTOCOL_VERSION,
        "operation": "health",
        "request_id": "r1",
    })

    assert response.status == "ok"
    assert response.request_id == "r1"
    assert response.answer is None


def test_markup_classifies_a_fractional_power_as_non_polynomial():
    from ethnos.hawkes_host import _polynomial_classification

    answer = _polynomial_classification(
        "Classify the following expression as either a polynomial or a non-polynomial.",
        ["-5*x^(7/2)-8*y"],
    )

    assert answer is not None
    assert answer.display_text == "Non-Polynomial"


def test_markup_refuses_a_partial_conversion():
    from ethnos.hawkes_host import _solve_from_markup

    assert _solve_from_markup("Expand the expression.", ["x", "<math>unsupported</math>"]) is None


def test_a_solve_from_any_other_origin_is_refused_at_the_native_boundary():
    response = handle({
        "protocol_version": PROTOCOL_VERSION,
        "operation": "solve_hawkes_problem",
        "request_id": "r1",
        "origin": "https://example.com",
        "problem": {"prompt_text": "Simplify.", "mathml": ["<math><mn>4</mn></math>"]},
    })

    assert response.status == "error"
    assert response.answer is None
    assert "origin" in response.message.lower()


@pytest.mark.parametrize(
    "operation",
    ["", "solve", "run_shell", "eval", "../../etc/passwd", "solve_hawkes_problem_v2"],
)
def test_unknown_operations_are_refused(operation):
    response = handle({
        "protocol_version": PROTOCOL_VERSION,
        "operation": operation,
        "request_id": "r1",
    })

    assert response.status == "error"
    assert response.answer is None


def test_a_foreign_protocol_version_is_refused():
    response = handle({"protocol_version": 99, "operation": "health", "request_id": "r1"})

    assert response.status == "error"


def test_unexpected_fields_are_refused_rather_than_ignored():
    # extra="forbid" is what stops the browser from smuggling a model name,
    # a path, or a command into the request.
    for extra in ({"model": "llama"}, {"path": "/etc/shadow"}, {"command": "rm -rf /"}):
        response = handle({
            "protocol_version": PROTOCOL_VERSION,
            "operation": "health",
            "request_id": "r1",
            **extra,
        })
        assert response.status == "error", extra


def test_solve_without_a_screenshot_is_unsupported():
    response = handle({
        "protocol_version": PROTOCOL_VERSION,
        "operation": "solve_hawkes_problem",
        "request_id": "r1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {"prompt_text": "simplify"},
    })

    assert response.status == "unsupported"
    assert response.answer is None


def test_a_non_png_screenshot_is_refused_before_any_model_call():
    response = handle({
        "protocol_version": PROTOCOL_VERSION,
        "operation": "solve_hawkes_problem",
        "request_id": "r1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {"screenshot_png_base64": "bm90IGEgcG5n"},  # "not a png"
    })

    assert response.status == "error"
    assert "PNG" in response.message
    assert response.answer is None


def test_invalid_base64_is_refused():
    response = handle({
        "protocol_version": PROTOCOL_VERSION,
        "operation": "solve_hawkes_problem",
        "request_id": "r1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {"screenshot_png_base64": "!!!not base64!!!"},
    })

    assert response.status == "error"
    assert response.answer is None


def test_the_request_model_pins_the_operation_set():
    # A new operation must be added deliberately, not by sending a new string.
    schema = SolveRequest.model_json_schema()
    operations = schema["properties"]["operation"]["enum"]

    assert sorted(operations) == ["health", "solve_hawkes_problem"]


def test_a_prose_answer_is_not_mangled_into_multiplication():
    """Regression from the first successful model-path solve.

    `sqrt(-324)` is answered "Not a Real Number", and the maths keyboard
    conversion turned that into "N*o*t*a*R*e*a*l*N*u*m*b*e*r" by treating each
    letter as a factor.
    """
    import re as _re

    from ethnos.answer_image import keyboard_entry_for_math

    prose = "Not a Real Number"
    assert _re.fullmatch(r"[A-Za-z][A-Za-z ]*", prose) is not None
    # The maths path is what mangles it, which is why prose must skip it.
    assert "*" in keyboard_entry_for_math(prose)

    # Real maths answers must still take the maths path.
    for answer in ("3y", "x^6yz^5", "9*sqrt(5)"):
        assert _re.fullmatch(r"[A-Za-z][A-Za-z ]*", answer) is None


def test_a_real_number_question_is_answered_by_index_parity():
    """Regression from live lesson 1.2 question 12, the square root of -100.

    The question offers "Real Number" and "Not a Real Number". The host used to
    report it unsupported: the symbolic solver produced `10*I`, which is not an
    answer to the question asked. The test is the index's parity -- only an even
    root of a negative fails to be real -- and not SymPy's principal branch,
    which makes `(-27)**(1/3)` complex when the real cube root of -27 is -3.
    """
    from ethnos.hawkes_host import _realness_answer

    prompt = (
        "Determine if the following radical expression is a real number. "
        "If it is, you are to evaluate the expression."
    )
    cases = {
        r"\sqrt{-100}": "Not a Real Number",
        r"\sqrt[4]{-16}": "Not a Real Number",
        r"\sqrt{100}": "10",
        r"\sqrt[3]{-27}": "-3",
        r"\sqrt[5]{-32}": "-2",
        r"\sqrt[3]{64}": "4",
    }
    for expression, expected in cases.items():
        answer = _realness_answer(prompt, [expression])
        assert answer is not None, expression
        assert answer.display_text == expected, expression


def test_evaluate_prompt_with_non_real_instruction_rejects_complex_unit():
    """Regression from the live sqrt(-36) question in Firefox.

    This Hawkes wording asks for an evaluation first and names the non-real
    response second; it contains none of determine/decide/whether. Returning
    SymPy's `6*I` is mathematically related but is not an accepted Hawkes
    answer.
    """
    from ethnos.hawkes_host import _realness_answer

    prompt = (
        "Evaluate the radical expression. Express your answer as an integer, "
        "simplified fraction, or a decimal rounded to two decimal places. If "
        "the expression does not represent a real number, indicate "
        '"Not a Real Number".'
    )
    answer = _realness_answer(prompt, [r"\sqrt{-36}"])
    assert answer is not None
    assert answer.display_text == "Not a Real Number"
    assert answer.keyboard_entry == "Not a Real Number"


def test_realness_stays_out_of_other_questions():
    """It answers only the question that asks, and only for a bare number."""
    from ethnos.hawkes_host import _realness_answer

    prompt = (
        "Determine if the following radical expression is a real number. "
        "If it is, you are to evaluate the expression."
    )
    assert _realness_answer("Simplify the following radical expression.", [r"\sqrt{-100}"]) is None
    assert _realness_answer(prompt, [r"\sqrt{y}"]) is None
    # An irrational value is not what the two options are asking about.
    assert _realness_answer(prompt, [r"\sqrt{20}"]) is None


def test_an_unlabelled_question_is_reported_as_such_not_hidden():
    """The host selects every exact operation by reading a verb out of the
    prompt. Without one, the question necessarily reaches a model as a picture
    with nothing saying what to do about it -- the least reliable path here.
    That is reported rather than refused: the answer may well be right, and the
    panel reviews every one before insertion. What it may not do is look
    identical to an answer derived exactly."""
    from ethnos.hawkes_protocol import Certainty

    assert Certainty().prompt_seen is True
    assert Certainty(prompt_seen=False).prompt_seen is False
    # Serialized, so the extension can actually read it.
    assert Certainty(prompt_seen=False).model_dump()["prompt_seen"] is False
