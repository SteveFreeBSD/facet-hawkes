"""A line's two page-owned points become one exact scalar slope."""

from __future__ import annotations

import pytest

from facet_loopback import facet, reasoning

from ethnos.hawkes_host import handle


PROMPT = (
    "Find the slope of the line in the following graph using the points on the "
    "graph. Write the exact answer. Do not round. If the slope does not exist, "
    "write DNE for your answer."
)


def request(points=None, prompt=PROMPT):
    return {
        "operation": "solve_hawkes_problem",
        "request_id": "line-slope-1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": prompt,
            "line_points": points
            if points is not None
            else [
                {"label": "M", "x": "-8", "y": "6", "reading": "page-model"},
                {"label": "N", "x": "4", "y": "-3", "reading": "page-model"},
            ],
            "answer_shape": {"kind": "field"},
        },
    }


def answering(monkeypatch):
    return facet(monkeypatch, **reasoning("FINAL ANSWER: a model guessed"))


def test_reduced_slope_is_a_typed_scalar_and_no_model_is_called(monkeypatch):
    loopback = answering(monkeypatch)

    response = handle(request())

    assert response.status == "ready"
    assert response.answer.form == "scalar"
    assert response.answer.display_text == "-3/4"
    assert response.answer.keyboard_entry == "-3/4"
    assert response.answer.parts == []
    assert response.certainty.source == "Facet Exact"
    assert response.certainty.answered_by == "exact"
    assert response.certainty.router == "solved"
    assert response.certainty.method == "Exact slope from two Cartesian points"
    assert response.certainty.reading == "page-model"
    assert response.certainty.model_calls == 0
    assert response.certainty.insertable is True
    assert loopback.prompts == []


def test_only_normalized_owned_points_cross_the_facet_boundary(monkeypatch):
    loopback = answering(monkeypatch)

    handle(request())

    assert loopback.problems == [
        {
            "instruction": PROMPT,
            "points": [{"x": "-8", "y": "6"}, {"x": "4", "y": "-3"}],
            "answer_parts": 1,
        }
    ]


@pytest.mark.parametrize(
    ("points", "expected"),
    [
        ([(-3, 0), (0, 6)], "2"),
        ([(0, -4), (5, -4)], "0"),
        ([(6, -2), (-2, 2)], "-1/2"),
    ],
)
def test_positive_negative_axis_and_horizontal_geometry_stays_exact(
    monkeypatch, points, expected
):
    answering(monkeypatch)
    payload = [
        {
            "label": label,
            "x": str(x),
            "y": str(y),
            "reading": "page-model",
        }
        for label, (x, y) in zip(("A", "B"), points, strict=True)
    ]

    response = handle(request(payload))

    assert response.status == "ready"
    assert response.answer.keyboard_entry == expected


def test_vertical_line_uses_dne_only_under_the_prompts_convention(monkeypatch):
    loopback = answering(monkeypatch)
    points = [
        {"label": "C", "x": "2", "y": "-5", "reading": "page-model"},
        {"label": "D", "x": "2", "y": "7", "reading": "page-model"},
    ]

    accepted = handle(request(points))
    refused = handle(request(points, "Find the slope of the line using the points."))

    assert accepted.status == "ready"
    assert accepted.answer.form == "scalar"
    assert accepted.answer.keyboard_entry == "DNE"
    assert refused.status == "unsupported"
    assert "does not specify DNE" in refused.message
    assert loopback.prompts == []


@pytest.mark.parametrize(
    ("points", "reason"),
    [
        (
            [{"label": "A", "x": "0", "y": "0", "reading": "page-model"}],
            "exactly two labeled points",
        ),
        (
            [
                {"label": "A", "x": "0", "y": "0", "reading": "page-model"},
                {"label": "A", "x": "2", "y": "2", "reading": "page-model"},
            ],
            "labels are not unique",
        ),
        (
            [
                {"label": "A", "x": "1", "y": "1", "reading": "page-model"},
                {"label": "B", "x": "1", "y": "1", "reading": "page-model"},
            ],
            "identical coordinates",
        ),
    ],
)
def test_ambiguous_point_identity_and_geometry_fail_closed(monkeypatch, points, reason):
    loopback = answering(monkeypatch)

    response = handle(request(points))

    assert response.status == "unsupported"
    assert response.message.startswith("Graph slope refused:")
    assert reason in response.message
    assert loopback.prompts == []


def test_a_non_scalar_surface_is_refused_before_facet_or_a_model(monkeypatch):
    loopback = answering(monkeypatch)
    malformed = request()
    malformed["problem"]["answer_shape"] = {"kind": "multi", "count": 2}

    response = handle(malformed)

    assert response.status == "unsupported"
    assert "exactly one scalar answer field" in response.message
    assert loopback.requests == []
    assert loopback.prompts == []
