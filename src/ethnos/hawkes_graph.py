"""Strict Facet geometry, independently checked using exact page mathematics."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .hawkes_mathml import mathml_to_latex


class GraphPoint(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    x: str = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$", max_length=30)
    y: str = Field(pattern=r"^-?(?:0|[1-9][0-9]*)(?:/[1-9][0-9]*)?$", max_length=30)


class GraphPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["parabola"]
    orientation: Literal["vertical"]
    opening: Literal["up", "down"]
    vertex: GraphPoint
    points: list[GraphPoint] = Field(min_length=2, max_length=2)


def _strict_json(text: str):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate graph-plan key")
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique)


def parse_graph_plan(text: str) -> GraphPlan:
    return GraphPlan.model_validate(_strict_json(text))


def validate_graph_plan(plan: GraphPlan, mathml: list[str]) -> list[str]:
    """Prove vertex, opening, symmetric defining points and every coefficient."""
    import sympy

    expressions = [mathml_to_latex(item) for item in mathml]
    if len(expressions) != 1:
        raise ValueError("graph requires exactly one exact function")
    a, b, c = quadratic_coefficients(expressions[0])
    x = sympy.Symbol("x", real=True)
    expression = a * x**2 + b * x + c
    h, k = sympy.Rational(plan.vertex.x), sympy.Rational(plan.vertex.y)
    if h != -b / (2 * a) or k != expression.subs(x, h):
        raise ValueError("Facet vertex does not match the exact function")
    if plan.opening != ("up" if a > 0 else "down"):
        raise ValueError("Facet opening does not match the exact function")
    points = [(sympy.Rational(p.x), sympy.Rational(p.y)) for p in plan.points]
    if points[0][0] <= h or points[1][0] != 2 * h - points[0][0]:
        raise ValueError("defining points must be right then symmetric left of vertex")
    for px, py in points:
        if py != expression.subs(x, px) or (py - k) / (px - h) ** 2 != a:
            raise ValueError("Facet defining point does not match the exact function")
    return [str(value) for value in (a, b, c)]


def graph_prompt(instruction: str, mathml: list[str], context: dict) -> str:
    return (
        "Produce a graph plan for the exact function. Return ONLY one JSON object, "
        "no markdown, prose, code, or extra keys. Coordinates must be exact integer "
        'or rational STRINGS (for example "-3/2"). Required schema: '
        '{"kind":"parabola","orientation":"vertical","opening":"up or down",'
        '"vertex":{"x":"rational","y":"rational"},'
        '"points":[{"x":"rational","y":"rational"},'
        '{"x":"rational","y":"rational"}]}. '
        "Derive the vertex, opening and two symmetric defining points from the function. "
        "First point must be right of vertex, second left. Prefer one unit horizontal "
        "offset if it fits the bounds and snap grid. You have no browser actions.\n"
        + json.dumps(
            {
                "instruction": instruction,
                "exact_expression": [mathml_to_latex(m) for m in mathml],
                "graph_answer": context,
            }
        )
    )


def quadratic_coefficients(function: str):
    """Safely derive exact coefficients for any single-letter function of x."""
    import sympy

    from .symbolic_solver import _safe_sympy_expression

    match = re.fullmatch(r"\s*(?:[A-Za-z]\s*\(\s*x\s*\)|y)\s*=\s*(.+)", function)
    if not match:
        raise ValueError("graph requires an explicit function of x")
    expression = _safe_sympy_expression(match[1])
    x = sympy.Symbol("x", real=True)
    try:
        polynomial = sympy.Poly(expression, x)
    except sympy.PolynomialError as error:
        raise ValueError("graph requires a polynomial in x") from error
    if polynomial.degree() != 2 or any(
        not c.is_Rational for c in polynomial.all_coeffs()
    ):
        raise ValueError("graph requires a rational quadratic")
    a, b, c = polynomial.all_coeffs()
    return a, b, c


class RegressionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["quadratic-regression"]
    coefficients: list[str] = Field(min_length=3, max_length=3)


def validate_regression_plan(text: str, points: list[GraphPoint]):
    """Validate Facet's least-squares coefficients with exact normal equations."""
    import sympy

    plan = RegressionPlan.model_validate(_strict_json(text))
    coefficients = [sympy.Rational(GraphPoint(x=s, y="0").x) for s in plan.coefficients]
    if len(points) < 3:
        raise ValueError("regression requires at least three points")
    coordinates = [(sympy.Rational(p.x), sympy.Rational(p.y)) for p in points]
    design = sympy.Matrix([[x * x, x, 1] for x, _ in coordinates])
    values = sympy.Matrix([y for _, y in coordinates])
    if design.rank() != 3 or not coefficients[0]:
        raise ValueError("points do not define a unique quadratic regression")
    residuals = design * sympy.Matrix(coefficients) - values
    if design.T * residuals != sympy.zeros(3, 1):
        raise ValueError(
            "Facet coefficients fail the exact least-squares normal equations"
        )
    return coefficients


def regression_prompt(instruction: str, points: list[GraphPoint]) -> str:
    return (
        "Find the quadratic least-squares regression y=a*x^2+b*x+c for these exact "
        "SVG point coordinates. Return ONLY JSON with exactly this schema: "
        '{"kind":"quadratic-regression","coefficients":["a","b","c"]}. '
        "Coefficients must be exact integer or rational strings, NOT decimal "
        "approximations. Ethnos will independently verify and round them for display. "
        "No prose, markdown, browser commands, or extra keys.\n"
        + json.dumps(
            {"instruction": instruction, "points": [p.model_dump() for p in points]}
        )
    )
