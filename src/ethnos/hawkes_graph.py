"""Strict Facet geometry, independently checked using exact page mathematics."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .hawkes_mathml import mathml_to_latex

# Facet's exact vertex route reads these same coefficients, so there is one
# implementation and this module uses it. Re-exported: `quadratic_coefficients`
# has always been part of this module's surface.
from .symbolic_solver import quadratic_coefficients


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


class PointPlotPlan(BaseModel):
    """Where each stated point goes. No curve, and no coefficients to prove.

    The question writes its own answer down, so this carries the points it
    named and nothing derived: what proves it is the browser, against the live
    graph's own bounds and snap, before a key is pressed.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["points"]
    points: list[GraphPoint] = Field(min_length=1, max_length=12)


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


class RegressionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["quadratic-regression"]
    coefficients: list[str] = Field(min_length=3, max_length=3)


def validate_regression_plan(text: str, points: list[GraphPoint]):
    """Read a regression plan out of one JSON reply and prove it exactly."""
    return regression_coefficients(
        RegressionPlan.model_validate(_strict_json(text)), points
    )


def regression_coefficients(plan: RegressionPlan, points: list[GraphPoint]):
    """Validate least-squares coefficients with exact normal equations.

    The proof is this host's, not Facet's. Facet proposes three coefficients;
    what makes them insertable is that they satisfy the exact normal equations
    against the coordinates the add-on measured, and a fit that merely looks
    right does not.
    """
    import sympy

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
