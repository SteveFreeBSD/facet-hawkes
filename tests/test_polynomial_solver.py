from ethnos.polynomial_solver import (
    answer_polynomial_product,
    expand_first_polynomial_expression,
)


def test_expands_square_of_binomial_sum_exactly():
    expansion = expand_first_polynomial_expression("Find the product.\n$(x + 8)^2$")

    assert expansion is not None
    assert expansion.original == "(x+8)^2"
    assert expansion.expanded == "x^2 + 16x + 64"


def test_expands_square_of_binomial_difference_and_difference_of_squares():
    difference = expand_first_polynomial_expression("Expand (2x - 3)^2")
    squares = expand_first_polynomial_expression("Find the product.\n(x+5)(x-5)")

    assert difference is not None
    assert difference.expanded == "4x^2 - 12x + 9"
    assert squares is not None
    assert squares.expanded == "x^2 - 25"


def test_product_answer_uses_deterministic_fast_path():
    result = answer_polynomial_product("Find the product.\n(x + 8)^2")

    assert result is not None
    assert result.raw_response.endswith("FINAL ANSWER: x^2 + 16x + 64")
    assert result.debug_info is not None
    assert result.debug_info.format_kind == "deterministic_polynomial"
    assert result.debug_info.response_summary["eval_count"] == 0


def test_non_product_question_falls_back_to_model():
    assert answer_polynomial_product("Solve x^2 = 9") is None
