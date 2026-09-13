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
COMPLEX_Q12 = (
    "<math><mstyle><msup><mrow><mo>(</mo><mn>6</mn><mo>+</mo><msqrt>"
    "<mrow><mo>−</mo><mn>2</mn></mrow></msqrt><mo>)</mo></mrow><mn>2</mn>"
    "</msup></mstyle></math>"
)
LINEAR_EQUATION_Q1 = (
    "<math><mrow><mrow><mn>4</mn><mo>⁢</mo><mi>x</mi><mo>+</mo><mn>8</mn>"
    "</mrow><mo>=</mo><mrow><mrow><mn>4</mn><mo>⁢</mo><mrow><mo>(</mo>"
    "<mrow><mi>x</mi><mo>+</mo><mn>4</mn></mrow><mo>)</mo></mrow></mrow>"
    "<mo>−</mo><mn>8</mn></mrow></mrow></math>"
)
FORMULA_Q3 = (
    "<math><mrow><mi>C</mi><mo>=</mo><mrow><mn>2</mn><mo>⁢</mo>"
    "<mi>π</mi><mo>⁢</mo><mi>r</mi></mrow></mrow></math>"
)
ABSOLUTE_VALUE_Q9 = (
    "<math><mrow><mrow><mo>|</mo><mrow><mo>−</mo><mn>14</mn><mo>⁢</mo>"
    "<mi>y</mi><mo>+</mo><mn>5</mn></mrow><mo>|</mo></mrow><mo>+</mo>"
    "<mn>8</mn><mo>=</mo><mn>7</mn></mrow></math>"
)
QUADRATIC_LESSON_18_Q1 = (
    "<math><mrow><msup><mi>y</mi><mn>2</mn></msup><mo>−</mo><mn>4</mn>"
    "<mo>⁢</mo><mi>y</mi><mo>−</mo><mn>5</mn><mo>=</mo><mn>0</mn>"
    "</mrow></math>"
)
QUADRATIC_LESSON_18_Q2 = (
    "<math><mrow><msup><mrow><mo>(</mo><mn>7</mn><mo>⁢</mo><mi>z</mi>"
    "<mo>+</mo><mn>4</mn><mo>)</mo></mrow><mn>2</mn></msup><mo>+</mo>"
    "<mn>36</mn><mo>=</mo><mn>0</mn></mrow></math>"
)
QUADRATIC_LESSON_18_Q4 = (
    "<math><mrow><msup><mi>y</mi><mn>2</mn></msup><mo>+</mo><mn>3</mn>"
    "<mo>⁢</mo><mi>y</mi><mo>−</mo><mn>2</mn><mo>=</mo><mn>0</mn>"
    "</mrow></math>"
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


def test_live_complex_binomial_power_keeps_the_negative_radicand_grouped():
    assert mathml_to_latex(COMPLEX_Q12) == r"(6+\sqrt{-2})^2"


def test_live_linear_equation_keeps_both_sides_and_grouping():
    assert mathml_to_latex(LINEAR_EQUATION_Q1) == "4*x+8=4*(x+4)-8"


def test_live_formula_keeps_pi_and_the_target_factor():
    assert mathml_to_latex(FORMULA_Q3) == "C=2*π*r"


def test_live_absolute_value_equation_keeps_both_fences():
    assert mathml_to_latex(ABSOLUTE_VALUE_Q9) == "|-14*y+5|+8=7"


def test_live_lesson_18_quadratic_keeps_its_degree_and_both_sides():
    assert mathml_to_latex(QUADRATIC_LESSON_18_Q1) == "y^2-4*y-5=0"


def test_live_square_root_method_quadratic_keeps_its_grouped_square():
    assert mathml_to_latex(QUADRATIC_LESSON_18_Q2) == "(7*z+4)^2+36=0"


def test_live_quadratic_formula_equation_keeps_every_term():
    assert mathml_to_latex(QUADRATIC_LESSON_18_Q4) == "y^2+3*y-2=0"


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


def fenced(inner: str, **attributes: str) -> str:
    stated = "".join(f' {name}="{value}"' for name, value in attributes.items())
    return f"<math><mfenced{stated}>{inner}</mfenced><mo>+</mo><mn>1</mn></math>"


@pytest.mark.parametrize(
    ("markup", "latex"),
    [
        pytest.param(
            fenced("<mrow><mo>-</mo><mn>2</mn></mrow>", open="|", close="|"),
            "|-2|+1",
            id="bars-are-an-absolute-value",
        ),
        pytest.param(fenced("<mn>1</mn><mn>2</mn>"), "(1,2)+1", id="default-comma"),
        pytest.param(
            fenced("<mn>1</mn><mn>2</mn><mn>3</mn>", separators=" , "),
            "(1,2,3)+1",
            id="a-separator-repeats",
        ),
        pytest.param(
            fenced("<mi>x</mi><mo>-</mo><mn>3</mn>", separators=""),
            "(x-3)+1",
            id="no-separators-is-one-run",
        ),
    ],
)
def test_an_mfenced_keeps_the_fences_and_separators_it_states(markup, latex):
    assert mathml_to_latex(markup) == latex


@pytest.mark.parametrize(
    "markup",
    [
        pytest.param(fenced("<mi>x</mi>", open="{", close="}"), id="braces"),
        pytest.param(fenced("<mn>1</mn><mn>2</mn>", close="]"), id="half-open"),
        pytest.param(fenced("<mn>1</mn><mn>2</mn>", separators=";"), id="semicolon"),
        pytest.param(
            fenced("<mn>1</mn><mn>2</mn>", open="|", close="|"), id="bars-around-two"
        ),
        pytest.param(fenced("", open="|", close="|"), id="empty"),
    ],
)
def test_an_mfenced_the_solver_cannot_read_the_same_way_is_refused(markup):
    with pytest.raises(UnsupportedMathML):
        mathml_to_latex(markup)


def test_bars_written_as_an_mfenced_are_answered_as_an_absolute_value():
    """Audit F04: `|-2|+1` crossed as `(-2)+1`, and `-1` was ready to insert."""
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "operation": "solve_hawkes_problem",
            "request_id": "mfenced-bars",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": "Simplify the following expression.",
                "mathml": [
                    fenced("<mrow><mo>-</mo><mn>2</mn></mrow>", open="|", close="|")
                ],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "3"


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
        (
            COMPLEX_Q12,
            "Simplify the following square root expression.",
            "34 + 12i√2",
        ),
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
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
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


def test_the_host_answers_live_linear_q1_from_mathml_without_a_screenshot():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "linear-q1",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": "Solve the following linear equation.",
                "mathml": [LINEAR_EQUATION_Q1],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "Infinite Solutions"
    assert response.answer.keyboard_entry == "Infinite Solutions"
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"


def test_the_host_rearranges_live_formula_q3_and_returns_only_its_rhs_for_entry():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "formula-q3",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": (
                    "Solve the following formula for the indicated variable. "
                    "Solve for r."
                ),
                "mathml": [FORMULA_Q3],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == r"r = \frac{C}{2π}"
    assert response.answer.keyboard_entry == "C/(2π)"
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"


def test_the_host_answers_live_absolute_value_q9_without_a_screenshot():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "absolute-q9",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": "Solve the following absolute value equation.",
                "mathml": [ABSOLUTE_VALUE_Q9],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "No Solution"
    assert response.answer.keyboard_entry == "No Solution"
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"


def test_the_host_answers_live_lesson_18_q1_without_a_screenshot():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "lesson-18-q1",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": (
                    "Solve the following quadratic equation by factoring. "
                    "If needed, write your answer as a fraction reduced to lowest terms."
                ),
                "mathml": [QUADRATIC_LESSON_18_Q1],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "y = -1 or y = 5"
    assert response.answer.keyboard_entry == ""
    assert response.answer.parts == ["-1", "5"]
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"


def test_the_host_answers_live_lesson_18_q2_without_a_screenshot():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "lesson-18-q2",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": (
                    "Solve the following quadratic equation by the square root method. "
                    "If needed, write your answer as a fraction reduced to lowest terms."
                ),
                "mathml": [QUADRATIC_LESSON_18_Q2],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == (
        r"z = \frac{-4 - 6i}{7} or z = \frac{-4 + 6i}{7}"
    )
    assert response.answer.keyboard_entry == ""
    assert response.answer.parts == ["(-4-6*i)/7", "(-4+6*i)/7"]
    assert response.certainty.source == "markup"
    assert response.certainty.transcription == "exact"


def test_the_host_keeps_live_q4_roots_separate_for_the_comma_editor():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "lesson-18-q4",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": (
                    "Solve the following quadratic equation using the quadratic "
                    "formula. Separate multiple answers with a comma if necessary."
                ),
                "mathml": [QUADRATIC_LESSON_18_Q4],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == (
        r"y = \frac{-3 + √17}{2} or y = \frac{-√17 - 3}{2}"
    )
    assert response.answer.parts == [
        "(-3+sqrt(17))/2",
        "(-sqrt(17)-3)/2",
    ]
    assert response.certainty.source == "markup"


def test_the_host_answers_live_complex_q8_from_markup():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "complex-q8",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
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
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
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
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
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


def test_the_host_answers_live_complex_q12_from_markup():
    from ethnos.hawkes_host import handle

    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "complex-q12",
            "origin": "https://learn.hawkeslearning.com",
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": "Simplify the following square root expression.",
                "mathml": [COMPLEX_Q12],
            },
        }
    )

    assert response.status == "ready"
    assert response.answer.display_text == "34 + 12i√2"
    assert response.answer.keyboard_entry == "34+12*i*sqrt(2)"
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
            # The companion's own reader, which is what these check.
            "solve_engine": "ethnos",
            "problem": {
                "prompt_text": "Graph the function.",
                "mathml": ["<math><mi>x</mi></math>"],
            },
        }
    )

    assert response.status == "unsupported"
    assert response.answer is None
