"""Reading a Hawkes question from its MathML rather than from a screenshot.

Hawkes renders with MathJax, which leaves the expression in the page as
presentation MathML. Reading that is exact and instant: it skips the two
independent image transcriptions that are otherwise almost the whole of a
solve, and removes an error class outright, because nothing can misread an
exponent that was never rendered to pixels.

Every case below is markup taken from a live lesson.
"""

from __future__ import annotations

import pytest

from ethnos.answer_image import extract_final_math
from ethnos.hawkes_mathml import UnsupportedMathML, mathml_to_latex
from ethnos.symbolic_solver import answer_symbolic_math

RATIONAL_EXPONENTS = (
    "<math><mstyle>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>4</mn></mfrac></msup>"
    "<mo>⋅</mo>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>5</mn></mfrac></msup>"
    "</mstyle></math>"
)
NEGATIVE_BASE = "<math><msup><mrow><mo>−</mo><mn>2</mn></mrow><mn>6</mn></msup></math>"
RADICAL_FRACTION = (
    "<math><msqrt><mfrac>"
    "<mrow><mn>6</mn><mi>y</mi></mrow><mrow><mn>5</mn><mi>z</mi></mrow>"
    "</mfrac></msqrt></math>"
)
INDEXED_ROOT = (
    "<math><mroot><mrow>"
    "<msup><mi>y</mi><mn>49</mn></msup><msup><mi>z</mi><mn>28</mn></msup>"
    "<msup><mi>x</mi><mn>42</mn></msup>"
    "</mrow><mn>7</mn></mroot></math>"
)
COMPLEX_Q8 = (
    "<math><mstyle><mrow><mo>(</mo><mn>11</mn>"
    "<msup><mi>i</mi><mn>2</mn></msup><mo>−</mo><mn>9</mn><mi>i</mi><mo>)</mo>"
    "<mo>+</mo><mo>(</mo><mn>4</mn><mo>+</mo><mn>7</mn><mi>i</mi><mo>)</mo>"
    "</mrow></mstyle></math>"
)
COMPLEX_Q9 = (
    "<math><mstyle><mrow><msup><mrow><mo>(</mo><mo>−</mo><mi>i</mi><mo>)</mo>"
    "</mrow><mn>6</mn></msup><msqrt><mrow><mo>−</mo><mn>100</mn></mrow>"
    "</msqrt></mrow></mstyle></math>"
)
COMPLEX_Q11 = (
    "<math><mstyle><mrow><mo>(</mo><mn>5</mn><mo>−</mo><mn>4</mn><mi>i</mi>"
    "<mo>)</mo><mo>(</mo><mn>6</mn><mo>+</mo><mi>i</mi><mo>)</mo>"
    "</mrow></mstyle></math>"
)


def test_a_dot_product_of_rational_powers():
    assert mathml_to_latex(RATIONAL_EXPONENTS) == r"y^{\frac{3}{4}}*y^{\frac{3}{5}}"


def test_a_negative_base_keeps_its_parentheses():
    """`(-2)^6` is 64; `-2^6` is -64.

    The grouping the MathML carries is the whole difference between the two, so
    a power's base is parenthesised unless it is a single token.
    """
    assert mathml_to_latex(NEGATIVE_BASE) == "(-2)^6"


def test_a_radical_over_a_fraction():
    assert mathml_to_latex(RADICAL_FRACTION) == r"\sqrt{\frac{6y}{5z}}"


def test_an_indexed_root():
    assert mathml_to_latex(INDEXED_ROOT) == r"\sqrt[7]{y^{49}z^{28}x^{42}}"


def test_live_complex_sum_keeps_i_and_its_power_exactly():
    assert mathml_to_latex(COMPLEX_Q8) == "(11i^2-9i)+(4+7i)"


def test_live_complex_root_has_a_power_then_an_unindexed_square_root():
    """The visible 6 belongs to `(-i)`, while `<msqrt>` has implicit index 2."""
    assert mathml_to_latex(COMPLEX_Q9) == r"(-i)^6\sqrt{-100}"


def test_live_complex_product_keeps_both_factors():
    assert mathml_to_latex(COMPLEX_Q11) == "(5-4i)(6+i)"


def test_namespaced_markup_is_read():
    markup = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'
    assert mathml_to_latex(markup) == "x"


def test_mathjax_semantic_attributes_are_ignored():
    # The page's markup carries far more annotation than expression.
    markup = (
        '<math data-semantic-structure="(1 0)"><mstyle displaystyle="true" '
        'data-semantic-type="infixop"><mi data-semantic-font="italic">x</mi>'
        "</mstyle></math>"
    )
    assert mathml_to_latex(markup) == "x"


@pytest.mark.parametrize(
    "markup",
    [
        pytest.param("<math></math>", id="empty"),
        pytest.param("<math><mtable><mtr><mtd/></mtr></mtable></math>", id="table"),
        pytest.param("not markup at all", id="unparseable"),
    ],
)
def test_what_cannot_be_read_exactly_is_refused(markup):
    """Refused rather than guessed: a screenshot can still read it.

    A plausible expression that is not the question is worse than falling back.
    """
    with pytest.raises(UnsupportedMathML):
        mathml_to_latex(markup)


@pytest.mark.parametrize(
    ("markup", "problem", "expected"),
    [
        (
            RATIONAL_EXPONENTS,
            "Simplify. Express your answer using rational exponents.",
            "y^(27/20)",
        ),
        (NEGATIVE_BASE, "Simplify the following expression.", "64"),
        (INDEXED_ROOT, "Simplify the following radical expression.", "x^6y^7z^4"),
        (COMPLEX_Q8, "Simplify the following expression.", "-7 - 2i"),
        (COMPLEX_Q9, "Evaluate the following square root expression.", "-10i"),
        (COMPLEX_Q11, "Simplify the following expression.", "34 - 19i"),
    ],
)
def test_the_solver_answers_straight_from_the_markup(markup, problem, expected):
    result = answer_symbolic_math(
        problem_text=problem, expressions=[mathml_to_latex(markup)]
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == expected


def test_the_host_reports_an_exact_reading():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "m1",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Simplify. Express your answer using rational exponents.",
                "mathml": [RATIONAL_EXPONENTS],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "y^(27/20)"
    # Nothing was transcribed, so there is nothing to dispute.
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"
    assert response.certainty.insertable is True


def test_the_host_answers_live_complex_q8_from_markup():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "complex-q8",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Simplify the following expression.",
                "mathml": [COMPLEX_Q8],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "-7 - 2i"
    assert response.answer.keyboard_entry == "-7-2*i"
    assert response.certainty.source == "markup"


def test_the_host_answers_live_complex_q9_from_markup():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "complex-q9",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Evaluate the following square root expression.",
                "mathml": [COMPLEX_Q9],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "-10i"
    assert response.answer.keyboard_entry == "-10*i"
    assert response.certainty.source == "markup"


def test_the_host_answers_live_complex_q11_from_markup():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "complex-q11",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Simplify the following expression.",
                "mathml": [COMPLEX_Q11],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "34 - 19i"
    assert response.answer.keyboard_entry == "34-19*i"
    assert response.certainty.source == "markup"


def test_markup_that_cannot_be_solved_exactly_does_not_reach_the_model():
    """Without a transcription there is no independent check on a reading.

    So the markup path uses the exact solvers only; anything else falls back to
    a screenshot, where the two-reader verification applies.
    """
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "m2",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Graph the function.",
                "mathml": ["<math><mi>x</mi></math>"],
            },
        }
    )

    assert response.status == "unsupported"
    assert response.answer is None
