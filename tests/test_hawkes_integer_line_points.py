"""The consumer re-proves every derived point, independent of Facet's claim."""

import pytest

from ethnos.hawkes_graph import PointPlotPlan, validate_integer_line_points
from ethnos.hawkes_protocol import GraphContext

MATH = ["<math><mi>y</mi><mo>=</mo><mn>2</mn></math>"]


def context(**changes):
    return GraphContext.model_validate(
        {
            "family": "points",
            "count": 2,
            "bounds": [-4.0, 7.0, -3.0, 5.0],
            "snap": [1.0, 1.0],
            "controls": "draggable-points",
            **changes,
        }
    )


def plan(points):
    return PointPlotPlan.model_validate(
        {"kind": "points", "points": [{"x": x, "y": y} for x, y in points]}
    )


def test_independent_coefficients():
    assert validate_integer_line_points(
        plan([("0", "2"), ("1", "2")]), MATH, context()
    ) == ["0", "1", "-2"]


@pytest.mark.parametrize(
    "points,changes",
    [
        ([("0", "2"), ("1", "3")], {}),
        ([("0", "2"), ("1/2", "2")], {}),
        ([("0", "2"), ("0", "2")], {}),
        ([("0", "2"), ("8", "2")], {}),
        ([("0", "2"), ("1", "2")], {"snap": [2.0, 1.0]}),
        ([("0", "2"), ("1", "2")], {"count": 3}),
    ],
)
def test_invalid_proposals_refused(points, changes):
    with pytest.raises(ValueError):
        validate_integer_line_points(plan(points), MATH, context(**changes))
