"""Strict Facet geometry, independently checked using exact page mathematics."""

from __future__ import annotations

import json
import re
from fractions import Fraction
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


#: The four interval shapes a number line draws, named by their two ends.
IntervalShape = Literal["open", "closed", "open-closed", "closed-open"]

#: A finite end as the page's own tick spells it, or one of the two infinities.
_END_VALUE = r"^(?:-inf|inf|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?)$"


class NumberLineEnd(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str = Field(pattern=_END_VALUE, max_length=30)
    closed: bool


class NumberLineInterval(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    left: NumberLineEnd
    right: NumberLineEnd


class NumberLinePlan(BaseModel):
    """The intervals to draw on a number line, and nothing derived about them.

    The set itself is Facet's, solved exactly. What this carries is where the
    ends of each of its intervals go and whether each is included -- the only
    things a number line can be told -- in values already checked against the
    page's own ticks, one interval per piece of a union.
    """

    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["numberline"]
    intervals: list[NumberLineInterval] = Field(min_length=1, max_length=12)


#: A solution set written in interval notation, as Facet writes one.
_INTERVAL = re.compile(
    r"^(?P<open>[(\[])(?P<left>-∞|-?\d+(?:\.\d+)?(?:/\d+)?),"
    r"(?P<right>∞|-?\d+(?:\.\d+)?(?:/\d+)?)(?P<close>[)\]])$"
)


def _shape(left_closed: bool, right_closed: bool) -> str:
    return {
        (False, False): "open",
        (True, True): "closed",
        (False, True): "open-closed",
        (True, False): "closed-open",
    }[(left_closed, right_closed)]


def number_line_plan(solution_set: str, context) -> NumberLinePlan:
    """The number-line plan for an exactly solved solution set, or a named refusal.

    Every check is against the page's own number line, as its probe reported
    it: each interval's shape has to be one the page publishes a button for, a
    finite end has to be one of its ticks, and an infinite end is always open --
    Hawkes draws it by dragging an open end to the arrow.

    A union is one interval per piece, as many as the line says it will take,
    left to right and apart from each other -- which is what the solution of
    `|u| > c` is. The empty set and a single point are not intervals, and are
    refused by name rather than drawn as something near them.
    """
    text = re.sub(r"\s+", "", solution_set or "")
    if text == "∅":
        raise ValueError("the empty set is not an interval to draw")
    if context is None or context.family != "numberline":
        raise ValueError("a number-line plan needs the page's number line")
    pieces = text.split("∪")
    limit = context.count or 1
    if len(pieces) > limit:
        raise ValueError(
            f"the number line takes at most {limit} interval"
            + ("s" if limit != 1 else "")
            + f", and the solution set has {len(pieces)}"
        )
    planned = [_plan_interval(piece, context) for piece in pieces]
    for before, after in zip(planned, planned[1:], strict=False):
        right, right_closed = before[2]
        left, left_closed = after[1]
        if right is None or left is None or right > left:
            raise ValueError("the intervals of the union are not in order")
        if right == left and right_closed and left_closed:
            raise ValueError("the intervals of the union overlap")
    return NumberLinePlan(
        kind="numberline", intervals=[interval[0] for interval in planned]
    )


def _plan_interval(piece: str, context):
    """One interval of the set: its plan, and its two ends as numbers.

    The ends come back as `(value, closed)`, with None for an infinite end, so
    that the pieces of a union can be put in order against each other.
    """
    match = _INTERVAL.fullmatch(piece)
    if match is None:
        raise ValueError("the solution set is not intervals in interval notation")
    left_closed = match.group("open") == "["
    right_closed = match.group("close") == "]"
    ends = []
    for raw, closed, infinity in (
        (match.group("left"), left_closed, "-∞"),
        (match.group("right"), right_closed, "∞"),
    ):
        if raw == infinity:
            if closed:
                raise ValueError("an infinite end is never included")
            ends.append((None, "-inf" if raw == "-∞" else "inf", closed))
            continue
        value = Fraction(raw)
        low, high = (Fraction(str(bound)) for bound in context.bounds)
        step = Fraction(str(context.snap[0]))
        if not low <= value <= high:
            raise ValueError("an end of the interval is off the number line")
        if (value - low) % step != 0:
            raise ValueError(
                "an end of the interval is not one of the number line's ticks"
            )
        ends.append((value, _tick_spelling(value), closed))
    if ends[0][0] is not None and ends[1][0] is not None and ends[0][0] >= ends[1][0]:
        raise ValueError("the interval's ends are not in order")
    shape = _shape(left_closed, right_closed)
    if shape not in (context.intervals or []):
        raise ValueError(f"the number line publishes no {shape} interval")
    interval = NumberLineInterval(
        left=NumberLineEnd(value=ends[0][1], closed=left_closed),
        right=NumberLineEnd(value=ends[1][1], closed=right_closed),
    )
    return interval, (ends[0][0], left_closed), (ends[1][0], right_closed)


def _tick_spelling(value: Fraction) -> str:
    """A tick value as a terminating decimal, which is how a tick is labelled."""
    if value.denominator == 1:
        return str(value.numerator)
    denominator = value.denominator
    for prime in (2, 5):
        while denominator % prime == 0:
            denominator //= prime
    if denominator != 1:
        raise ValueError("an end of the interval is not one of the number line's ticks")
    places = 0
    while (value * 10**places).denominator != 1:
        places += 1
    return f"{value:.{places}f}"


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
