"""Equations with the unknown in a denominator, answered exactly.

`sympy.Poly` refuses an expression whose own generator appears raised to a
negative power, and `1/x` is precisely that. So every solve route declined this
whole shape, the question fell through to the reasoning fallback, and on
`1/x + 1/(x+2) = 3/4` the model twice produced nothing at all and once produced
a confident "No solution" for an equation with two roots.

The difficulty of the shape is not the algebra. Clearing denominators makes it
solvable, and in the same step makes it a *different equation* -- one satisfied
at values where the original is not defined. So what is checked here is mostly
the restrictions: that they are collected from the equation as written, that a
root landing on one is refused, and that the solver hands back anything it
cannot settle rather than producing something plausible.
"""

from __future__ import annotations

import pytest

from facet_loopback import facet

from ethnos.hawkes_host import handle
from ethnos.symbolic_solver import solve_rational_equation

#: The live failure. Two roots, neither of them excluded.
FAILING_SHAPE = r"\frac{1}{x}+\frac{1}{x+2}=\frac{3}{4}"

#: MathJax presentation markup for the same equation.
FAILING_MATHML = (
    "<math><mrow>"
    "<mfrac><mn>1</mn><mi>x</mi></mfrac><mo>+</mo>"
    "<mfrac><mn>1</mn><mrow><mi>x</mi><mo>+</mo><mn>2</mn></mrow></mfrac>"
    "<mo>=</mo><mfrac><mn>3</mn><mn>4</mn></mfrac>"
    "</mrow></math>"
)
INSTRUCTION = (
    "Solve the following rational equation. Separate multiple answers with a comma."
)


def test_the_equation_that_fell_through_to_a_model_is_now_exact() -> None:
    result = solve_rational_equation(FAILING_SHAPE)

    assert result is not None
    assert result.classification == "Two Solutions"
    assert result.solutions == (r"\frac{-4}{3}", "2")
    # Both denominators are restrictions, and neither root lands on one.
    assert result.excluded == ("-2", "0")


def test_a_root_that_clearing_denominators_invented_is_refused() -> None:
    """`(x^2-4)/(x-2) = 0` cancels to `x+2 = 0` -- and loses a restriction.

    The cancelled equation offers two roots. The equation as asked is not
    defined at one of them, so only the other is an answer.
    """
    result = solve_rational_equation(r"\frac{x^2-4}{x-2}=0")

    assert result is not None
    assert result.excluded == ("2",)
    assert result.solutions == ("-2",)
    assert result.classification == "One Solution"


def test_an_equation_whose_only_root_is_excluded_has_no_solution() -> None:
    """The classic extraneous-root question: it solves, and then it does not."""
    result = solve_rational_equation(r"\frac{x}{x-3}=\frac{3}{x-3}+2")

    assert result is not None
    assert result.excluded == ("3",)
    assert result.solutions == ()
    assert result.classification == "No Solution"


def test_an_equation_with_no_root_at_all_says_so() -> None:
    result = solve_rational_equation(r"\frac{1}{x-1}=\frac{1}{x-1}+1")

    assert result is not None
    assert result.classification == "No Solution"
    assert result.solutions == ()


def test_two_distinct_roots_are_kept_as_two() -> None:
    result = solve_rational_equation(r"\frac{6}{x}=x-1")

    assert result is not None
    assert result.classification == "Two Solutions"
    assert result.solutions == ("-2", "3")


def test_an_identity_is_infinite_solutions_and_still_reports_its_restriction() -> None:
    """True wherever it is defined -- which is not everywhere."""
    result = solve_rational_equation(r"\frac{2}{x}=\frac{2}{x}")

    assert result is not None
    assert result.classification == "Infinite Solutions"
    assert result.excluded == ("0",)


def test_a_denominator_with_no_real_zero_restricts_nothing() -> None:
    result = solve_rational_equation(r"\frac{1}{x^2+1}=\frac{1}{5}")

    assert result is not None
    assert result.excluded == ()
    assert result.solutions == ("-2", "2")


@pytest.mark.parametrize(
    ("expression", "why"),
    [
        ("x+1=5", "linear: the polynomial solvers own it"),
        ("x^2-4=0", "quadratic: likewise"),
        (r"\frac{1}{2}x+1=5", "a numeric denominator is not the unknown's"),
        (r"\frac{1}{x}+\frac{1}{y}=1", "two unknowns name no single answer"),
        (r"\frac{x^3-6x^2+11x-6}{x-4}=0", "three roots: no answer shape carries them"),
        (r"\frac{1}{x}", "not an equation at all"),
        (r"\frac{1}{x}=\frac{1}{x}=1", "two equals signs"),
    ],
)
def test_what_this_solver_hands_back(expression: str, why: str) -> None:
    """Declining is the safe outcome, and the reason differs in each case."""
    assert solve_rational_equation(expression) is None, why


def test_a_complex_root_is_handed_back_rather_than_called_no_real_solution() -> None:
    """Calling a complex root "no solution" would be a claim this has not earned."""
    assert solve_rational_equation(r"\frac{1}{x}=\frac{-1}{x^3}") is None


# --- through the real host path --------------------------------------------


def solve_through_host(monkeypatch, *, engine="facet"):
    """Answer it through the host, with a real Facet whose model never speaks."""
    loopback = facet(monkeypatch)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "rational-1",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": engine,
            "problem": {
                "prompt_text": INSTRUCTION,
                "mathml": [FAILING_MATHML],
                "answer_shape": {"kind": "field"},
            },
        }
    )
    assert loopback.prompts == [], "a model was asked a question the solvers settled"
    return response


@pytest.mark.parametrize("engine", ["ethnos", "facet"])
def test_the_host_answers_it_exactly_and_never_reaches_a_model(
    monkeypatch, engine
) -> None:
    """Exact-first routing holds on both engines, and answers identically.

    The local engine runs the deterministic solvers here; the Facet engine runs
    the same solvers on the Facet side. That they are the same implementation
    is the point: the structured two-root answer is byte-identical either way.
    """
    response = solve_through_host(monkeypatch, engine=engine)

    assert response.status == "ready"
    # Two roots, carried as two values rather than as prose to be split later.
    assert response.answer.parts == ["-4/3", "2"]
    assert response.answer.keyboard_entry == ""
    assert response.answer.display_text == r"x = \frac{-4}{3} or x = 2"


def test_the_panel_reports_an_exact_answer_and_names_no_model(
    monkeypatch,
) -> None:
    certainty = solve_through_host(monkeypatch).certainty

    assert certainty.answered_by == "exact"
    assert certainty.method == "SymPy exact symbolic"
    assert certainty.router == "solved"
    assert certainty.reading == "mathml"
    # Facet answered it, deterministically, and says which route that was.
    assert certainty.facet_invoked is True
    assert certainty.source == "Facet Exact"
    # Nothing Facet-shaped on an answer Facet did not produce.
    assert certainty.model is None
    assert certainty.device is None
