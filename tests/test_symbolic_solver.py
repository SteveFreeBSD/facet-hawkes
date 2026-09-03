from ethnos.answer_image import extract_final_math, keyboard_entry_for_math
from ethnos.symbolic_solver import (
    _assume_positive,
    _python_expression,
    _requested_operation,
    answer_symbolic_math,
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
    assert _assume_positive(
        "Simplify the following radical expression.", r"\sqrt{9y^2}", "simplify"
    ) is False
    # An odd index needs no bars -- the fifth root of y^5 is y for every real
    # y -- and the assumption is what lets SymPy extract the root at all.
    assert _assume_positive(
        "Simplify the following radical expression.", r"\sqrt[5]{y^5}", "simplify"
    ) is True
    # A question that says so licenses dropping the bars.
    assert _assume_positive(
        "Simplify. Assume all variables represent positive real numbers.",
        r"\sqrt{9y^2}",
        "simplify",
    ) is True
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
    assert _requested_operation(
        "Simplify. Express your answer using rational exponents."
    ) == "rational_exponents"
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
    assert solve_symbolic_operation(
        operation="simplify", problem_text="Simplify.", expressions=["2^999999"]
    ) is None
    assert solve_symbolic_operation(
        operation="simplify", problem_text="Simplify.", expressions=["x^(1/500)"]
    ) is None

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
    assert sympy.simplify(radical.subs({y: -2, z: 3}) - without.subs({y: -2, z: 3})) != 0


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
    assert answer_symbolic_math(
        problem_text="Express the polynomial in descending order.",
        expressions=["a x^2 + b y^3"],
    ) is None


def test_a_rewriting_verb_beside_an_ordering_wins():
    """"Factor completely, then write the answer in descending order" is a
    factoring question. Answering it by reordering the unfactored polynomial
    would be confidently wrong."""
    assert _requested_operation(
        "Factor completely, then write the answer in descending order."
    ) == "factor"
    assert _requested_operation("Simplify and express in descending order.") == "simplify"
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
    assert answer_symbolic_math(
        problem_text="Identify the leading coefficient.",
        expressions=["a x^2 + b y^3"],
    ) is None


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
        ("5x^3", "monomial"), ("x^2 - 9", "binomial"), ("x^2 + 3x + 2", "trinomial"),
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
    assert _requested_operation("Factor the following trinomial completely.") == "factor"
    assert _requested_operation("Factor the following binomial completely.") == "factor"
    assert _requested_operation(
        "Classify the polynomial as a monomial, binomial, or trinomial."
    ) == "classify"


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
    """"for t = 2" against a polynomial in x names nothing to substitute."""
    assert answer_symbolic_math(
        problem_text="Evaluate the polynomial for t = 2.",
        expressions=["x^3 - 4x + 1"],
    ) is None


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
    ordinary = answer_symbolic_math(problem_text=offered, expressions=["y^2 + 13y + 40"])
    assert extract_final_math(ordinary.raw_response) == "(y + 5)(y + 8)"


def test_an_unfactorable_polynomial_is_handed_back_when_no_escape_is_offered():
    """A question that just says "factor" has not licensed prose as an answer."""
    assert answer_symbolic_math(
        problem_text="Factor completely.", expressions=["y^2 + y + 17"]
    ) is None
