"""The coverage sweep, and the regressions it found on its first run.

Coverage used to be discovered one live failure at a time: meet an unhandled
question, lose about seventy seconds to the vision-plus-model fallback, report
it. Nothing about that discovery needs a browser or a model, so this sweep does
it offline in about a second.
"""

from __future__ import annotations

from pathlib import Path

from ethnos.answer_image import extract_final_math
from ethnos.hawkes_coverage import (
    CoverageCase,
    evaluate,
    format_report,
    load_cases,
    summarize,
    sweep,
)
from ethnos.symbolic_solver import _requested_operation, answer_symbolic_math

CORPUS = (
    Path(__file__).resolve().parents[1] / "benchmarks" / "hawkes_lesson_coverage.json"
)


def test_the_shipped_corpus_loads_and_sweeps():
    results = sweep(load_cases(CORPUS))

    assert len(results) >= 20
    assert format_report(results).startswith(tuple("0123456789"))


def test_no_question_in_the_corpus_is_answered_incorrectly():
    """The one verdict that must always be zero.

    A gap is a backlog item: the question falls through to a model, slowly, and
    the panel says so. A *wrong* exact answer is worse than either, because it
    is fast, confident, and nothing downstream questions it.
    """
    wrong = [r for r in sweep(load_cases(CORPUS)) if r.verdict == "wrong"]

    assert wrong == [], [(r.case.id, r.answer, r.case.expected) for r in wrong]


def test_a_gap_says_which_kind_of_gap_it_is():
    """The two fall through to a model identically and are fixed in completely
    different places, so the sweep separates them."""
    unrecognized = evaluate(
        CoverageCase(
            id="x",
            topic="t",
            prompt="Describe the end behavior of the polynomial.",
            expressions=["x^2 + 3x + 2"],
        )
    )
    declined = evaluate(
        CoverageCase(
            id="y",
            topic="t",
            prompt="Express the polynomial in descending order.",
            expressions=["a x^2 + b y^3"],
        )
    )

    assert unrecognized.verdict == "no-verb"
    assert unrecognized.operation is None
    assert declined.verdict == "solver-declined"
    assert declined.operation == "descending_order"


def test_a_deliberate_guard_is_not_reported_as_a_gap():
    """Declining an ordering over two variables is the solver being right.

    Counted as a gap, the guards that make it safe would read as the holes that
    make it incomplete, and the sweep would push toward removing them.
    """
    guard = evaluate(
        CoverageCase(
            id="g",
            topic="guards",
            prompt="Express the polynomial in descending order.",
            expressions=["a x^2 + b y^3"],
            expects_decline=True,
        )
    )

    assert guard.verdict == "guarded"
    assert summarize([guard])["no-verb"] == 0


def test_a_guard_that_answers_is_a_failed_guard():
    answered = evaluate(
        CoverageCase(
            id="g",
            topic="guards",
            prompt="Factor the following trinomial completely.",
            expressions=["x^2 + 7x + 12"],
            expects_decline=True,
        )
    )

    assert answered.verdict == "wrong"


def test_multiply_and_simplify_is_a_multiplication():
    """Found by the sweep's first run.

    "Multiply the following polynomials and simplify your answer" was claimed
    by the `simplify` check, which runs before the product verbs. SymPy then
    returned the already-simple factored form -- the question's own input,
    handed back as its answer.
    """
    assert (
        _requested_operation(
            "Multiply the following polynomials and simplify your answer."
        )
        == "expand"
    )

    result = answer_symbolic_math(
        problem_text="Multiply the following polynomials and simplify your answer.",
        expressions=["(2x + 1)(x + 4)"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "2x^2 + 9x + 4"


def test_factoring_out_the_gcf_stops_at_the_gcf():
    """Also found by the sweep's first run.

    `sympy.factor` keeps going and returns a complete factorization, which
    answers a question that was not asked: the GCF of `-10xy^2 - 15xy + 25x`
    came back as `-5x(y - 1)(2y + 5)`.
    """
    assert _requested_operation("Factor out the greatest common factor.") == "gcf"
    assert _requested_operation("Factor out the GCF.") == "gcf"
    # And a plain factoring question is still a plain factoring question.
    assert (
        _requested_operation("Factor the following trinomial completely.") == "factor"
    )

    result = answer_symbolic_math(
        problem_text="Factor out the greatest common factor.",
        expressions=["-10xy^2 - 15xy + 25x"],
    )

    assert result is not None
    # The bracket opens positive, with the sign carried out in front.
    assert extract_final_math(result.raw_response) == "-5x(2y^2 + 3y - 5)"
