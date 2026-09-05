"""The exact symbolic solvers, which now live on the Facet side.

Facet owns solver routing: a Hawkes question is handed to Facet as a question,
and Facet decides between deterministic exact mathematics and a reasoning
model. That decision cannot be made where the solver is not, so the solver
moved to `facet_runtime.exact.symbolic` and this module re-exports it.

It is re-exported rather than reimplemented because two copies of an exact
solver do not stay exact for long: they drift, and the drift shows up as one
side answering a question the other declines. Ethnos still calls these directly
for its own local paths -- the screenshot pipeline, the coverage sweep, the CLI
-- and every one of those calls now reaches the same implementation Facet runs.
"""

from __future__ import annotations

from facet_runtime.exact.symbolic import (
    EXTRACTION,
    ORDERING,
    AbsoluteValueEquationResult,
    LinearEquationResult,
    PolynomialEquationResult,
    RationalEquationResult,
    SymbolicResult,
    _assume_positive,
    _candidate_variables,
    _display,
    _named_positive_variables,
    _python_expression,
    _requested_operation,
    _requested_variable,
    _safe_sympy_expression,
    answer_symbolic_math,
    quadratic_coefficients,
    solve_absolute_value_equation,
    solve_equation,
    solve_linear_equation,
    solve_polynomial_equation,
    solve_quadratic_equation,
    solve_rational_equation,
    solve_symbolic_operation,
)

__all__ = [
    "EXTRACTION",
    "ORDERING",
    "AbsoluteValueEquationResult",
    "LinearEquationResult",
    "PolynomialEquationResult",
    "RationalEquationResult",
    "SymbolicResult",
    "_assume_positive",
    "_candidate_variables",
    "_display",
    "_named_positive_variables",
    "_python_expression",
    "_requested_operation",
    "_requested_variable",
    "_safe_sympy_expression",
    "answer_symbolic_math",
    "quadratic_coefficients",
    "solve_absolute_value_equation",
    "solve_equation",
    "solve_linear_equation",
    "solve_polynomial_equation",
    "solve_quadratic_equation",
    "solve_rational_equation",
    "solve_symbolic_operation",
]
