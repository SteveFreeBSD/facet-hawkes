import pytest

from ethnos.answer_image import extract_final_math, keyboard_entry_for_math
from ethnos.symbolic_solver import (
    _assume_positive,
    _python_expression,
    _requested_operation,
    answer_symbolic_math,
    solve_linear_equation,
    solve_symbolic_operation,
)


def test_factors_verified_polynomial_exactly():
    result = answer_symbolic_math(
        problem_text="Factor the following trinomial.\n-10xy^2 - 15xy + 25x",
        expressions=["-10xy^2 - 15xy + 25x"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: -5x(y - 1)(2y + 5)")
    assert result.debug_info is not None
    assert result.debug_info.format_kind == "sympy_exact"
    assert result.debug_info.response_summary["eval_count"] == 0


def test_factors_the_live_gcf_question_exactly():
    result = answer_symbolic_math(
        problem_text=(
            "Factor the following polynomial by factoring out the greatest "
            "common factor."
        ),
        expressions=["8*x^4*y - 16*x^3*y + 4*x^4*y^3"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: 4x^3y(xy^2 + 2x - 4)")
    assert result.debug_info is not None
    assert result.debug_info.response_summary["eval_count"] == 0


def test_expands_binomial_exactly():
    result = answer_symbolic_math(
        problem_text="Find the product.\n(x + 8)^2",
        expressions=["(x + 8)^2"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: x^2 + 16x + 64")


def test_adds_or_subtracts_polynomials_exactly():
    result = answer_symbolic_math(
        problem_text="Add or subtract the following polynomials, as indicated.",
        expressions=["(-8x^3+6-8x)-(11-3x+4x^3)"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: -12x^3 - 5x - 5")


def test_multiplies_polynomials_exactly():
    result = answer_symbolic_math(
        problem_text="Multiply the following polynomials, as indicated.",
        expressions=["(3x-2y)(x+4y)"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: 3x^2 + 10xy - 8y^2")


def test_linear_equations_are_reduced_and_classified_exactly():
    cases = {
        "4x + 8 = 4(x + 4) - 8": ("Infinite Solutions", None),
        "5x + 2 = 5x - 3": ("No Solution", None),
        "3x + 6 = 0": ("One Solution", "-2"),
        "0.6y + 0.6 = 0.7y": ("One Solution", "6"),
        "1.2y + 8 = 3.2y": ("One Solution", "4"),
    }

    for expression, expected in cases.items():
        result = solve_linear_equation(expression)

        assert result is not None, expression
        assert (result.classification, result.solution) == expected


def test_solve_prompt_uses_the_exact_linear_equation_operation():
    result = answer_symbolic_math(
        problem_text="Solve the following linear equation.",
        expressions=["4x + 8 = 4(x + 4) - 8"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "Infinite Solutions"
    assert result.debug_info.response_summary["operation"] == "solve"


def test_rational_equations_use_the_unified_solve_operation():
    result = solve_symbolic_operation(
        operation="solve",
        problem_text=(
            "Solve the following rational equation. "
            "Separate multiple answers with a comma."
        ),
        expressions=[r"\frac{1}{x}+\frac{1}{x+2}=\frac{3}{4}"],
    )

    assert result is not None
    assert result.answer == r"x = \frac{-4}{3} or x = 2"


def test_solve_declines_an_equation_outside_the_linear_and_quadratic_contracts():
    assert (
        answer_symbolic_math(
            problem_text="Solve the following equation.", expressions=["x^3 = 4"]
        )
        is None
    )


def test_formula_is_rearranged_for_the_explicitly_requested_variable():
    result = answer_symbolic_math(
        problem_text=(
            "Solve the following formula for the indicated variable. Solve for r."
        ),
        expressions=["C = 2πr"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == r"r = \frac{C}{2π}"


def test_expands_latex_braced_exponent_exactly():
    result = answer_symbolic_math(
        problem_text="Expand the product.\n(x - 3)^{2}",
        expressions=["(x - 3)^{2}"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: x^2 - 6x + 9")


def test_simplifies_parenthesized_negative_power_exactly():
    result = answer_symbolic_math(
        problem_text="Simplify the following expression.\n(-4)^2",
        expressions=["(-4)^2"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: 16")
    assert result.debug_info is not None
    assert result.debug_info.response_summary["operation"] == "simplify"


def test_simplifies_indexed_cube_root_exactly():
    result = answer_symbolic_math(
        problem_text="Simplify the following radical expression.",
        expressions=[r"\sqrt[3]{648}"],
    )

    assert result is not None
    assert r"Work: \sqrt[3]{648} = 6∛3" in result.raw_response
    assert result.raw_response.endswith("FINAL ANSWER: 6∛3")
    assert result.debug_info is not None
    assert result.debug_info.format_kind == "sympy_exact"
    assert result.debug_info.num_predict == 0


def test_simplifies_positive_variable_radical_fraction_exactly():
    result = answer_symbolic_math(
        problem_text=(
            "Simplify the following radical expression, assuming all variables "
            "are positive.\n"
            r"\sqrt{\frac{y^3}{25y^5z^{14}}}"
        ),
        expressions=[r"\sqrt{\frac{y^3}{25y^5z^{14}}}"],
    )

    assert result is not None
    assert result.raw_response.endswith(r"FINAL ANSWER: \frac{1}{5yz^7}")
    assert result.debug_info is not None
    assert result.debug_info.format_kind == "sympy_exact"
    assert result.debug_info.num_predict == 0


def test_unsupported_question_returns_none():
    assert (
        answer_symbolic_math(problem_text="Solve x^2 = 9", expressions=["x^2 = 9"])
        is None
    )


def test_parser_rejects_calls_and_attributes():
    assert (
        solve_symbolic_operation(
            operation="expand",
            problem_text="Expand this.",
            expressions=["danger()", "x.__class__"],
        )
        is None
    )


def test_rationalizing_the_denominator_is_not_a_generic_simplify():
    """Regression from the first live Hawkes solve.

    "Simplify ... by rationalizing the denominator" contains the word
    "simplify", so the request was answered with sympy.simplify, which returned
    an equivalent form that still had a radical in the denominator: the wrong
    answer to the question actually asked, wearing a plausible face.
    """
    result = answer_symbolic_math(
        problem_text=(
            "Simplify the following radical expression by rationalizing "
            "the denominator."
        ),
        expressions=[r"\frac{9}{\sqrt{5x}}"],
    )

    assert result is not None
    final = extract_final_math(result.raw_response)
    # The denominator must be free of radicals.
    numerator, _, denominator = final.partition("}{")
    assert "√" in numerator
    assert "√" not in denominator
    # One radical, not three: SymPy splits a root over a product and keeps it
    # split, which is not how the answer is written.
    assert final == r"\frac{9√(5x)}{5x}"
    assert keyboard_entry_for_math(final) == "9*sqrt(5*x)/(5*x)"


def test_rationalized_radical_stops_before_following_variable():
    """Regression from the live y/sqrt(30) insertion.

    The compact string `√30y` was planned as sqrt(30y), even though SymPy's
    exact value was y*sqrt(30). The display must carry the radical boundary.
    """
    result = answer_symbolic_math(
        problem_text="Simplify by rationalizing the denominator.",
        expressions=[r"\frac{y}{\sqrt{30}}"],
    )

    assert result is not None
    final = extract_final_math(result.raw_response)
    assert final == r"\frac{y√30}{30}"
    assert keyboard_entry_for_math(final) == "y*sqrt(30)/30"


def test_rationalize_is_chosen_over_simplify_and_factor():
    for problem, expected in (
        ("Simplify by rationalizing the denominator.", "rationalize"),
        ("Rationalize the denominator.", "rationalize"),
        ("Simplify the expression.", "simplify"),
        ("Express your answer in simplified form.", "simplify"),
        ("Factor completely.", "factor"),
    ):
        assert _requested_operation(problem) == expected, problem


def test_hawkes_simplified_form_wording_evaluates_a_negative_radical():
    result = answer_symbolic_math(
        problem_text=(
            "Evaluate the radical expression. Express your answer in simplified form. "
            'If the expression does not represent a real number, indicate "Not a Real Number".'
        ),
        expressions=[r"-\sqrt{144}"],
    )

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: -12")


def test_rationalize_handles_a_conjugate_denominator():
    result = answer_symbolic_math(
        problem_text="Rationalize the denominator.",
        expressions=[r"\frac{3}{2+\sqrt{3}}"],
    )

    assert result is not None
    assert keyboard_entry_for_math(extract_final_math(result.raw_response)) == (
        "-3*sqrt(3)+6"
    )


def test_rationalize_handles_a_cube_root_denominator():
    result = answer_symbolic_math(
        problem_text="Rationalize the denominator.",
        expressions=[r"\frac{7}{\sqrt[3]{4}}"],
    )

    assert result is not None
    assert keyboard_entry_for_math(extract_final_math(result.raw_response)) == (
        "7*cbrt(2)/2"
    )


def test_an_already_rational_denominator_still_reports_the_tidied_form():
    # SymPy rationalizes 1/sqrt(2) while parsing, so comparing the answer
    # against the parsed form made this look like "nothing to do".
    result = answer_symbolic_math(
        problem_text="Rationalize the denominator.",
        expressions=[r"\frac{1}{\sqrt{2}}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == r"\frac{√2}{2}"


def test_radical_signs_survive_the_trip_to_keyboard_entry():
    # The display uses radical signs; homework entry needs function syntax.
    assert keyboard_entry_for_math("√2/2") == "sqrt(2)/2"
    assert keyboard_entry_for_math("9√5√x") == "9*sqrt(5)*sqrt(x)"
    assert keyboard_entry_for_math("∛2") == "cbrt(2)"
    assert keyboard_entry_for_math("√(5x)") == "sqrt(5*x)"


def test_radical_simplification_extracts_the_root():
    """Regression from live question 9 of lesson 1.2.

    "Simplify the following radical expression" over the fifth root of
    y^5 x^30 z^25 returned the question back as its own answer: SymPy will not
    extract a root without knowing the variables' signs, and this question --
    unlike the one before it -- does not say they are positive. Hawkes marks
    the extracted form correct, so the exercise convention is assumed.
    """
    result = answer_symbolic_math(
        problem_text="Simplify the following radical expression.",
        expressions=[r"\sqrt[5]{y^5 x^{30} z^{25}}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "x^6yz^5"


def test_the_positive_convention_is_limited_to_radical_simplification():
    # Factoring must not silently assume anything about signs.
    assert _assume_positive("Factor completely.", "x^2-4", "factor") is False
    # An even index keeps its absolute value: sqrt(9y^2) is 3|y|, not 3y, and
    # the two differ in sign for every negative y. Hawkes marked `y^5z^4/3`
    # wrong for the fourth root of y^20z^16/81 on lesson 1.2 question 7 for
    # exactly this reason.
    assert (
        _assume_positive(
            "Simplify the following radical expression.", r"\sqrt{9y^2}", "simplify"
        )
        is False
    )
    # An odd index needs no bars -- the fifth root of y^5 is y for every real
    # y -- and the assumption is what lets SymPy extract the root at all.
    assert (
        _assume_positive(
            "Simplify the following radical expression.", r"\sqrt[5]{y^5}", "simplify"
        )
        is True
    )
    # A question that says so licenses dropping the bars.
    assert (
        _assume_positive(
            "Simplify. Assume all variables represent positive real numbers.",
            r"\sqrt{9y^2}",
            "simplify",
        )
        is True
    )
    # A plain algebraic simplify with no radical gets no assumption either.
    assert _assume_positive("Simplify.", "x^2+2x", "simplify") is False


def test_rational_exponent_questions_get_exponents_not_radicals():
    """Regression from live question 12 of lesson 1.2.

    "Express your answer using rational exponents" is marked wrong for a
    radical, but SymPy prints `a**Rational(1, 2)` as `sqrt(a)` and will not
    rewrite it back, so the display has to invert it.
    """
    result = answer_symbolic_math(
        problem_text=(
            "Simplify the following expression. Assume all variables are "
            "positive. Express your answer using rational exponents."
        ),
        expressions=[r"a^{\frac{1}{6}} \cdot a^{\frac{1}{3}}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "a^(1/2)"


def test_a_braced_fraction_exponent_parses():
    # The parser only handled integer exponents in braces, so
    # "a^{\frac{1}{6}}" was rejected outright as unsupported characters.
    assert _python_expression(r"a^{\frac{1}{6}}") == "a**(((1)/(6)))"
    # Integer exponents keep the older, tighter path.
    assert _python_expression("x^{30}") == "x**30"
    assert _python_expression("x^{-2}") == "x**-2"


def test_rational_exponents_is_chosen_over_plain_simplify():
    assert (
        _requested_operation("Simplify. Express your answer using rational exponents.")
        == "rational_exponents"
    )
    assert _requested_operation("Simplify the expression.") == "simplify"


def test_converting_a_radical_gives_one_rational_exponent_not_a_nested_power():
    """Regression from live question 14 of lesson 1.2.

    "Convert the given radical expression to rational exponent notation" over
    the square root of y^3 produced `(y^3)^(1/2)` -- equivalent, but not the
    single rational exponent the question asks for. SymPy only collapses the
    nested power when the variable is known non-negative, and that assumption
    had been limited to simplification and rationalisation.
    """
    result = answer_symbolic_math(
        problem_text="Convert the given radical expression to rational exponent notation.",
        expressions=[r"\sqrt[2]{y^3}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "y^(3/2)"


def test_an_indexed_radical_converts_too():
    result = answer_symbolic_math(
        problem_text="Convert to rational exponent notation.",
        expressions=[r"\sqrt[3]{x^5}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "x^(5/3)"


def test_a_non_unit_rational_exponent_is_accepted():
    """Regression from live question 14 of lesson 1.2.

    `y^(3/4) * y^(3/5)` returned nothing at all: the exponent guard admitted
    only unit fractions, so `1/4` passed and `3/4` was rejected outright. A
    numerator of 1 never had anything to do with keeping the evaluation cheap
    -- the bounds do that -- and the restriction made "express your answer
    using rational exponents" unanswerable for most of its own questions.
    """
    result = answer_symbolic_math(
        problem_text=(
            "Simplify the following expression. Assume all variables are "
            "positive. Express your answer using rational exponents."
        ),
        expressions=[r"y^{\frac{3}{4}} \cdot y^{\frac{3}{5}}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "y^(27/20)"


def test_the_exponent_guard_still_refuses_absurd_powers():
    # The bound is the safety property, and it is still there.
    assert (
        solve_symbolic_operation(
            operation="simplify", problem_text="Simplify.", expressions=["2^999999"]
        )
        is None
    )
    assert (
        solve_symbolic_operation(
            operation="simplify", problem_text="Simplify.", expressions=["x^(1/500)"]
        )
        is None
    )


def test_an_even_root_keeps_its_absolute_value():
    """Regression from live question 7 of lesson 1.2, marked incorrect.

    The fourth root of y^20*z^16/81 was answered `y^5z^4/3`, which Hawkes
    marked wrong -- rightly, because it is wrong: at y = -2, z = 3 the radical
    is 864 and `y^5z^4/3` is -864. A fourth root cannot be negative. The
    answer is `|y|^5z^4/3`, and the question says nothing about the variables'
    signs, so the bars are part of it.
    """
    result = answer_symbolic_math(
        problem_text="Simplify the following radical expression.",
        expressions=[r"\sqrt[4]{\frac{y^{20}*z^{16}}{81}}"],
    )

    assert result is not None
    answer = extract_final_math(result.raw_response)
    # The bars wrap the power -- `|y^5|`, not `|y|^5` -- because that is the
    # form the editor can build. The two are equal for every real y.
    assert "|y^5|" in answer, f"the absolute value is part of the answer: {answer}"
    assert "z^4" in answer
    assert "3" in answer


def test_the_even_root_answer_is_numerically_right_for_negative_variables():
    """The bars are not cosmetic; they are the difference between +864 and -864."""
    import sympy

    y, z = sympy.symbols("y z", real=True)
    radical = ((y**20 * z**16) / 81) ** sympy.Rational(1, 4)
    with_bars = abs(y) ** 5 * z**4 / 3
    without = y**5 * z**4 / 3
    for point in ({y: -2, z: 3}, {y: 2, z: 3}, {y: -1, z: -2}):
        assert sympy.simplify(radical.subs(point) - with_bars.subs(point)) == 0
    assert (
        sympy.simplify(radical.subs({y: -2, z: 3}) - without.subs({y: -2, z: 3})) != 0
    )


def test_an_odd_root_needs_no_absolute_value():
    """The fifth root of y^5 is y for every real y, negative ones included."""
    result = answer_symbolic_math(
        problem_text="Simplify the following radical expression.",
        expressions=[r"\sqrt[5]{y^5 x^{30} z^{25}}"],
    )

    assert result is not None
    assert "|" not in extract_final_math(result.raw_response)


def test_descending_order_is_answered_exactly_rather_than_by_the_model():
    """Live regression: lesson 1.3 question 7, step 1 of 3.

    "Express the polynomial in descending order" matched no verb at all, so a
    pure rearrangement fell through to vision plus the math model and was still
    running after 74 seconds. SymPy has the answer in about a millisecond.
    """
    result = answer_symbolic_math(
        problem_text="Consider the following polynomial.\n"
        "Step 1 of 3: Express the polynomial in descending order.",
        expressions=["-3x^11 - x^13 + 5 + 2x^12"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "-x^13 + 2x^12 - 3x^11 + 5"


def test_ascending_order_runs_the_powers_the_other_way():
    result = answer_symbolic_math(
        problem_text="Write the polynomial in ascending order.",
        expressions=["-3x^11 - x^13 + 5 + 2x^12"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "5 - 3x^11 + 2x^12 - x^13"


def test_a_polynomial_already_in_order_is_answered_by_itself():
    """Every other operation returning its input has done nothing and falls
    through. An ordering question is answered by its own input, and rejecting
    that sent a finished answer down the minute-long fallback."""
    result = answer_symbolic_math(
        problem_text="Express the polynomial in descending order.",
        expressions=["x^3 + 2x^2 + 5"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "x^3 + 2x^2 + 5"


def test_ordering_declines_when_the_variable_to_order_by_is_ambiguous():
    """Two symbols means "descending" names no particular sequence, so this
    hands the question back rather than guessing at one."""
    assert (
        answer_symbolic_math(
            problem_text="Express the polynomial in descending order.",
            expressions=["a x^2 + b y^3"],
        )
        is None
    )


def test_a_rewriting_verb_beside_an_ordering_wins():
    """ "Factor completely, then write the answer in descending order" is a
    factoring question. Answering it by reordering the unfactored polynomial
    would be confidently wrong."""
    assert (
        _requested_operation(
            "Factor completely, then write the answer in descending order."
        )
        == "factor"
    )
    assert (
        _requested_operation("Simplify and express in descending order.") == "simplify"
    )
    assert _requested_operation("Express the polynomial in descending order.") == (
        "descending_order"
    )


def test_the_degree_and_leading_coefficient_are_read_not_guessed():
    """Live: lesson 1.3 question 7, steps 2 and 3 of 3.

    Both arrived at the host as an empty instruction, so no exact operation
    could match and a model inferred the task from a screenshot. The degree it
    returned (13) was right; the cost was 74 seconds and no way to check it.
    """
    poly = ["-3x^11 - x^13 + 5 + 2x^12"]

    degree = answer_symbolic_math(
        problem_text="Step 2 of 3 : Identify the degree of the polynomial.",
        expressions=poly,
    )
    leading = answer_symbolic_math(
        problem_text="Step 3 of 3 : Identify the leading coefficient.",
        expressions=poly,
    )

    assert degree is not None and extract_final_math(degree.raw_response) == "13"
    assert leading is not None and extract_final_math(leading.raw_response) == "-1"


def test_an_extraction_answer_is_allowed_to_differ_from_its_input():
    """The equivalence check guards rewritings: an answer that is not the same
    value as the input means the operation went wrong. A degree is a fact
    *about* the polynomial and is meant to differ, so that guard must not be
    applied to it -- doing so rejected every correct answer."""
    result = solve_symbolic_operation(
        operation="degree",
        problem_text="Identify the degree of the polynomial.",
        expressions=["x^4 + 1"],
    )

    assert result is not None
    assert result.answer == "4"


def test_extraction_declines_when_there_is_no_single_variable():
    assert (
        answer_symbolic_math(
            problem_text="Identify the leading coefficient.",
            expressions=["a x^2 + b y^3"],
        )
        is None
    )


def test_the_constant_term_is_the_coefficient_not_the_last_thing_written():
    """An ordered polynomial may have no constant term at all, so this asks
    what the polynomial is where the variable is zero rather than reading off
    whatever was written last."""
    result = answer_symbolic_math(
        problem_text="Identify the constant term of the polynomial.",
        expressions=["-3x^11 - x^13 + 5 + 2x^12"],
    )
    assert result is not None
    assert extract_final_math(result.raw_response) == "5"

    none_at_all = answer_symbolic_math(
        problem_text="Identify the constant term of the polynomial.",
        expressions=["x^2 + 3x"],
    )
    assert none_at_all is not None
    assert extract_final_math(none_at_all.raw_response) == "0"


def test_a_polynomial_is_classified_by_counting_its_terms():
    for expression, expected in (
        ("5x^3", "monomial"),
        ("x^2 - 9", "binomial"),
        ("x^2 + 3x + 2", "trinomial"),
    ):
        result = answer_symbolic_math(
            problem_text="Classify the polynomial as a monomial, binomial, or trinomial.",
            expressions=[expression],
        )
        assert result is not None, expression
        assert extract_final_math(result.raw_response) == expected


def test_naming_a_trinomial_is_not_asking_what_kind_it_is():
    """Caught by the coverage sweep before it shipped.

    "Factor the following trinomial completely" contains the word and is a
    factoring question. Matching on the word alone answered "trinomial" to a
    request to factor -- fast, confident, and wrong.
    """
    assert (
        _requested_operation("Factor the following trinomial completely.") == "factor"
    )
    assert _requested_operation("Factor the following binomial completely.") == "factor"
    assert (
        _requested_operation(
            "Classify the polynomial as a monomial, binomial, or trinomial."
        )
        == "classify"
    )


def test_evaluating_needs_a_value_to_evaluate_at():
    """Without one there is nothing to substitute, and claiming the question
    would mean answering it with the polynomial itself."""
    assert _requested_operation("Evaluate the polynomial for x = 2.") == "evaluate"
    assert _requested_operation("Evaluate the polynomial.") != "evaluate"

    result = answer_symbolic_math(
        problem_text="Evaluate the polynomial for x = 2.",
        expressions=["x^3 - 4x + 1"],
    )
    assert result is not None
    assert extract_final_math(result.raw_response) == "1"


def test_evaluation_declines_when_the_named_variable_is_not_the_one_present():
    """ "for t = 2" against a polynomial in x names nothing to substitute."""
    assert (
        answer_symbolic_math(
            problem_text="Evaluate the polynomial for t = 2.",
            expressions=["x^3 - 4x + 1"],
        )
        is None
    )


def test_plain_sqrt_syntax_is_a_root_not_four_implicit_variables():
    """H1: `sqrt(9)` was parsed as `s*q*r*t*(9)` and answered `9qrst`."""
    result = answer_symbolic_math(
        problem_text="Simplify the expression.", expressions=["2sqrt(9)"]
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "6"


def test_evaluation_consumes_signed_decimal_substitutions_completely():
    """H2: the old match stopped `-2.5` after `-2`, yielding 4, not 25/4."""
    for value, expected in (("-2.5", r"\frac{25}{4}"), ("+1.5", r"\frac{9}{4}")):
        result = answer_symbolic_math(
            problem_text=f"Evaluate the polynomial for x = {value}.",
            expressions=["x^2"],
        )

        assert result is not None, value
        assert extract_final_math(result.raw_response) == expected


def test_bare_polynomial_evaluate_declines_without_a_substitution():
    """H3: formatting changes must not disguise missing evaluation data."""
    assert _requested_operation("Evaluate the polynomial.") is None
    assert (
        answer_symbolic_math(
            problem_text="Evaluate the polynomial.",
            expressions=["x^2+2*x+1"],
        )
        is None
    )


def test_simplify_declines_cosmetic_no_ops():
    """M3: removing `*` or redundant parentheses is not a solved exercise."""
    for expression in ("x*y", "(x + 1)", "sqrt(x + 1)"):
        assert (
            answer_symbolic_math(
                problem_text="Simplify the expression.", expressions=[expression]
            )
            is None
        )


def test_prompt_prose_is_never_used_as_an_expression_candidate():
    """M4: prose letters must not become a product of one-letter variables."""
    assert answer_symbolic_math(problem_text="Simplify x + x.", expressions=[]) is None


def test_a_prime_polynomial_is_answered_when_the_question_offers_that_answer():
    """Live: lesson 1.3 question 9, `y^2 + y + 17`.

    Factoring is the one rewriting whose input can be its answer. Read as a
    failure -- output equals input, so nothing happened -- it cost seventy-six
    seconds of vision and model for a fact SymPy had at once.
    """
    offered = 'Factor the following trinomial. If it cannot be factored, indicate "Not Factorable".'
    result = answer_symbolic_math(problem_text=offered, expressions=["y^2 + y + 17"])

    assert result is not None
    assert extract_final_math(result.raw_response) == "Not Factorable"

    # And one that does factor is unaffected.
    ordinary = answer_symbolic_math(
        problem_text=offered, expressions=["y^2 + 13y + 40"]
    )
    assert extract_final_math(ordinary.raw_response) == "(y + 5)(y + 8)"


def test_an_unfactorable_polynomial_is_handed_back_when_no_escape_is_offered():
    """A question that just says "factor" has not licensed prose as an answer."""
    assert (
        answer_symbolic_math(
            problem_text="Factor completely.", expressions=["y^2 + y + 17"]
        )
        is None
    )


def test_a_named_product_beats_the_word_factor_appearing_in_a_noun():
    """Shipped wrong and caught in live use, twice over.

    "Find the product of the binomial factors using the appropriate special
    product (difference of two squares, square of a binomial sum, or square of
    a binomial difference)" says "binomial" three times, so a classification
    rule that counted mentions answered it `trinomial`. Tightened, it then said
    `factor` -- because "factor" is matched as a substring and sits inside
    "binomial factors" -- and declined. It is a multiplication.
    """
    prompt = (
        "Find the product of the binomial factors using the appropriate special "
        "product (difference of two squares, square of a binomial sum, or square "
        "of a binomial difference)."
    )
    assert _requested_operation(prompt) == "expand"

    result = answer_symbolic_math(problem_text=prompt, expressions=["(x + 9)^2"])
    assert result is not None
    assert extract_final_math(result.raw_response) == "x^2 + 18x + 81"


def test_classification_needs_all_three_names_or_the_verb():
    """Counting mentions is too loose: a question may name one of them in
    passing while asking something else entirely."""
    assert (
        _requested_operation(
            "Classify the polynomial as a monomial, binomial, or trinomial."
        )
        == "classify"
    )
    assert _requested_operation("Factor the following binomial completely.") == "factor"
    assert _requested_operation("Find the product of the binomial factors.") == "expand"


def test_evaluate_without_a_value_to_substitute_is_a_simplify():
    """Lesson 1.5 question 5, met live: `√-27` under "Evaluate the following
    square root expression."

    The substitution-gated `evaluate` branch declines it correctly -- there is
    no value to put in -- and nothing further used to match, so the question
    fell through to `None`. Its MathML had already been read exactly; the
    decline threw that away and spent a screenshot and the vision model on a
    question SymPy answers in milliseconds. What came back was
    `3i×sqrt(3)`, the escape text for a multiplication sign, which no
    answer box will accept.
    """
    assert _requested_operation("Evaluate the following square root expression.") == (
        "simplify"
    )
    # Still gated where a value really is given, so this stays the narrower
    # operation rather than being swallowed by the simplify branch.
    assert _requested_operation("Evaluate the polynomial for x = 2") == "evaluate"

    result = answer_symbolic_math(
        problem_text="Evaluate the following square root expression.",
        expressions=["\\sqrt{-27}"],
    )
    assert result is not None
    assert extract_final_math(result.raw_response) == "3i√3"


def test_the_imaginary_unit_is_written_the_way_the_question_writes_it():
    """SymPy prints `I`; every question that asks for one writes `i`.

    The number was right and the alphabet was wrong, which is worse than a
    decline: the editor publishes a character set holding the lowercase letter
    and not the capital, so `3I√3` is refused at the point of insertion having
    already been reported as a confident exact answer.
    """
    result = answer_symbolic_math(
        problem_text="Simplify the radical expression.",
        expressions=["\\sqrt{-27}"],
    )
    assert result is not None
    answer = extract_final_math(result.raw_response)
    assert answer == "3i√3"
    assert "I" not in answer


def test_a_question_that_names_one_positive_variable_is_believed():
    """Lesson 1.5 question 7, met live: "Assume x > 0."

    Only the phrase forms -- "assume all variables are positive" and its
    relatives -- were recognised, so this question was solved with no
    assumption at all. SymPy could not extract the root and returned
    `2sqrt(2(-x^9))`: unsimplified, missing its `i`, and refused by the editor.
    Hawkes marked the session's attempt "not in the simplest form".
    """
    from ethnos.symbolic_solver import _assume_positive, _named_positive_variables

    assert _named_positive_variables("Assume x > 0.") == {"x"}
    assert _named_positive_variables("Assume y >= 0 and z > 0") == {"y", "z"}
    assert _named_positive_variables("Simplify the expression.") == set()
    assert _assume_positive("Assume x > 0.", "\\sqrt{-8x^{9}}", "simplify")


def test_an_uncovered_variable_leaves_the_assumption_off():
    """The safe direction. Claiming positivity for a variable the question did
    not mention is how a confident wrong answer gets made; declining only costs
    the slow path."""
    from ethnos.symbolic_solver import _assume_positive, _candidate_variables

    # `sqrt` must not contribute an `s`, `q`, `r` or `t`.
    assert _candidate_variables("\\sqrt{-8x^{9}}") == {"x"}
    assert _candidate_variables("sqrt(9*y^2)*z") == {"y", "z"}
    # The question speaks for x only; y is not covered.
    assert not _assume_positive("Assume x > 0.", "\\sqrt{x^{3}y^{3}}", "simplify")


def test_a_half_integer_power_is_split_rather_than_rearranged():
    """`2·√2·i·x^(9/2)` was rendered `2ix√(2)^(9/2)` -- a different number.

    The radical machinery reordered the factors around an exponent it could not
    represent. Splitting the whole power off first both keeps the value and
    produces the single merged radical the question is marked against.
    """
    result = answer_symbolic_math(
        problem_text="Evaluate the following square root expression. Assume x > 0.",
        expressions=["\\sqrt{-8x^{9}}"],
    )
    assert result is not None
    assert extract_final_math(result.raw_response) == "2ix^4√(2x)"


def test_splitting_half_powers_does_not_disturb_whole_ones():
    """The split must fire only where SymPy actually produced a half power."""
    from ethnos.symbolic_solver import _display

    import sympy

    x = sympy.Symbol("x", positive=True)
    assert _display(sympy.Integer(2) * x**4) == "2x^4"
    assert _display(sympy.sqrt(2) * x) == "x√2"
    # A negative half power keeps its value: x**(-3/2) is x**-2 * sqrt(x).
    assert (
        sympy.simplify(
            sympy.Pow(x, sympy.Rational(-3, 2)) - sympy.Pow(x, -2) * sympy.sqrt(x)
        )
        == 0
    )


def test_powers_of_lowercase_i_reduce_in_complex_simplification():
    """Lesson 1.5 uses lowercase `i`; SymPy's imaginary unit is uppercase `I`."""
    for expression, expected in (("i^2", "-1"), ("i^3", "-i"), ("i^4", "1")):
        result = answer_symbolic_math(
            problem_text="Simplify the following expression.",
            expressions=[expression],
        )
        assert result is not None, expression
        assert extract_final_math(result.raw_response) == expected


def test_live_complex_sum_reduces_i_squared_before_collecting_terms():
    """Lesson 1.5 Q8: Hawkes rejected `11i^2 - 2i + 4` as unsimplified."""
    result = answer_symbolic_math(
        problem_text="Simplify the following expression.",
        expressions=["(11i^2 - 9i) + (4 + 7i)"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "-7 - 2i"


def test_live_complex_product_reduces_i_squared_and_collects_terms():
    """Lesson 1.5 Q11: Hawkes cannot accept an unexpanded product as simplest."""
    result = answer_symbolic_math(
        problem_text="Simplify the following expression.",
        expressions=["(5 - 4i)(6 + i)"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "34 - 19i"


def test_numeric_complex_arithmetic_is_recognized_without_a_bare_i_power():
    for expression, expected in (
        ("(3 + 2i)(3 - 2i)", "13"),
        ("(i + 2)(i - 2)", "-5"),
        ("(5 - 4i)/(6 + i)", r"\frac{26 - 29i}{37}"),
        ("(2 + i)^2", "3 + 4i"),
    ):
        result = answer_symbolic_math(
            problem_text="Simplify the following expression.", expressions=[expression]
        )
        assert result is not None, expression
        assert extract_final_math(result.raw_response) == expected


def test_live_negative_radical_binomial_power_expands_to_standard_complex_form():
    """Lesson 1.5 Q12: converting the root is not the end of simplification."""
    result = answer_symbolic_math(
        problem_text="Simplify the following square root expression.",
        expressions=[r"(6 + \sqrt{-2})^2"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "34 + 12i√2"


def test_numeric_negative_radicals_are_expanded_after_becoming_complex():
    for expression, expected in (
        (r"(4 + \sqrt{-9})^2", "7 + 24i"),
        (r"(3 + \sqrt{-5})(3 - \sqrt{-5})", "14"),
        (r"(\sqrt{-3})^4", "9"),
    ):
        result = answer_symbolic_math(
            problem_text="Simplify the following square root expression.",
            expressions=[expression],
        )
        assert result is not None, expression
        assert extract_final_math(result.raw_response) == expected


def test_parenthesized_negative_i_power_reduces_beside_a_negative_square_root():
    """Lesson 1.5 Q9: both input `i` values must be the same imaginary unit."""
    result = answer_symbolic_math(
        problem_text="Evaluate the following square root expression.",
        expressions=[r"(-i)^6\sqrt{-100}"],
    )

    assert result is not None
    assert extract_final_math(result.raw_response) == "-10i"


def test_signed_parenthesized_powers_of_i_are_fully_reduced():
    for expression, expected in (
        ("(-i)^2", "-1"),
        ("(-i)^3", "i"),
        ("(-i)^4", "1"),
        ("(-i)^6", "-1"),
    ):
        result = answer_symbolic_math(
            problem_text="Simplify the following expression.", expressions=[expression]
        )
        assert result is not None, expression
        assert extract_final_math(result.raw_response) == expected


def test_i_remains_an_ordinary_variable_outside_complex_simplification():
    """The contextual rule must not globally redefine a legitimate variable."""
    factored = answer_symbolic_math(
        problem_text="Factor completely.", expressions=["i^2 - 1"]
    )
    evaluated = answer_symbolic_math(
        problem_text="Evaluate the polynomial for i = 3.", expressions=["i^2 + 1"]
    )

    assert factored is not None
    assert extract_final_math(factored.raw_response) == "(i - 1)(i + 1)"
    assert evaluated is not None
    assert extract_final_math(evaluated.raw_response) == "10"

    # A generic simplify is not enough by itself. With no explicit power and
    # no numeric complex-number operands, this remains ordinary-variable
    # algebra and the no-op is declined.
    assert (
        answer_symbolic_math(
            problem_text="Simplify the following expression.",
            expressions=["i(i + x)"],
        )
        is None
    )


@pytest.mark.parametrize(
    ("expression", "classification", "solutions"),
    [
        ("|-14y + 5| + 8 = 7", "No Solution", ()),
        ("|2y - 6| = 0", "One Solution", ("3",)),
        ("|2y - 6| = 4", "Two Solutions", ("1", "5")),
    ],
)
def test_affine_absolute_value_equations_are_classified_exactly(
    expression, classification, solutions
):
    from ethnos.symbolic_solver import solve_absolute_value_equation

    result = solve_absolute_value_equation(expression)

    assert result is not None
    assert result.classification == classification
    assert result.solutions == solutions


@pytest.mark.parametrize(
    "expression",
    ["|y|+|y-1|=2", "|y^2-1|=3", "|y|+y=2", "||=1", "|y=1"],
)
def test_absolute_value_solver_declines_shapes_outside_its_exact_contract(expression):
    from ethnos.symbolic_solver import solve_absolute_value_equation

    assert solve_absolute_value_equation(expression) is None


def test_live_quadratic_equation_has_two_independently_verified_real_roots():
    from ethnos.symbolic_solver import solve_quadratic_equation

    result = solve_quadratic_equation("y^2 - 4y - 5 = 0")

    assert result is not None
    assert result.variable == "y"
    assert result.solutions == ("-1", "5")
    assert result.display_text == "y = -1 or y = 5"


def test_live_square_root_method_equation_has_two_exact_complex_roots():
    from ethnos.symbolic_solver import solve_quadratic_equation

    result = solve_quadratic_equation("(7z + 4)^2 + 36 = 0")

    assert result is not None
    assert result.variable == "z"
    assert result.solutions == (
        r"\frac{-4 - 6i}{7}",
        r"\frac{-4 + 6i}{7}",
    )
    assert result.display_text == (r"z = \frac{-4 - 6i}{7} or z = \frac{-4 + 6i}{7}")


@pytest.mark.parametrize(
    "expression",
    ["y+1=0", "y^3-1=0", "x^2+y=0"],
)
def test_quadratic_solver_declines_other_equation_contracts(expression):
    from ethnos.symbolic_solver import solve_quadratic_equation

    assert solve_quadratic_equation(expression) is None
