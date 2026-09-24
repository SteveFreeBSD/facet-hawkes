"""A labeled Cartesian point, from page-owned SVG to two Hawkes fields."""

from __future__ import annotations

import pytest

from facet_loopback import facet, reasoning

from ethnos.hawkes_host import handle


def request(**point):
    return {
        "operation": "solve_hawkes_problem",
        "request_id": "labeled-point-1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": "Identify the coordinates of the point Q on the graph.",
            "labeled_point": {
                "label": "Q",
                "x": "4",
                "y": "2",
                "reading": "svg",
                **point,
            },
            "answer_shape": {
                "kind": "multi",
                "count": 2,
                "representations": [
                    {"kind": "signed-integer", "maxLength": 6},
                    {"kind": "signed-integer", "maxLength": 6},
                ],
            },
        },
    }


def answering(monkeypatch):
    return facet(monkeypatch, **reasoning("FINAL ANSWER: a model guessed"))


def test_the_point_is_returned_as_a_typed_pair_with_two_preserved_components(
    monkeypatch,
):
    loopback = answering(monkeypatch)

    response = handle(request())

    assert response.status == "ready"
    assert response.answer.form == "ordered-pair"
    assert response.answer.display_text == "(4,2)"
    assert response.answer.keyboard_entry == ""
    assert response.answer.parts == ["4", "2"]
    assert loopback.prompts == [], "a model was asked about exact SVG geometry"


def test_the_route_reports_svg_exactness_and_zero_model_calls(monkeypatch):
    answering(monkeypatch)

    certainty = handle(request()).certainty

    assert certainty.source == "Facet Exact"
    assert certainty.answered_by == "exact"
    assert certainty.router == "solved"
    assert certainty.method == "Exact labeled Cartesian point"
    assert certainty.reading == "svg"
    assert certainty.model_calls == 0
    assert certainty.model is None
    assert certainty.actual_backend is None
    assert certainty.insertable is True


def test_page_model_provenance_survives_the_native_boundary(monkeypatch):
    answering(monkeypatch)

    certainty = handle(request(reading="page-model")).certainty

    assert certainty.reading == "page-model"
    assert certainty.model_calls == 0


def test_only_normalized_geometry_crosses_the_facet_boundary(monkeypatch):
    loopback = answering(monkeypatch)

    handle(request(x="-6", y="0"))

    assert loopback.problems == [
        {
            "instruction": "Identify the coordinates of the point Q on the graph.\n"
            "Each separate answer must use only digits and an optional leading "
            "minus sign, with at most 6 characters. Do not use a fraction, radical, "
            "exponent notation, parentheses, or any other characters.",
            "points": [{"x": "-6", "y": "0"}],
            "answer_parts": 2,
            "answer_representation": {"kind": "signed-integer", "max_length": 6},
        }
    ]


@pytest.mark.parametrize(("x", "y"), [("-8", "5"), ("0", "-4"), ("7", "0")])
def test_negative_positive_and_axis_points_remain_exact(monkeypatch, x, y):
    answering(monkeypatch)

    answer = handle(request(x=x, y=y)).answer

    assert answer.display_text == f"({x},{y})"
    assert answer.parts == [x, y]


def test_a_surface_without_two_coordinate_fields_is_refused_before_a_model(
    monkeypatch,
):
    loopback = answering(monkeypatch)
    malformed = request()
    malformed["problem"]["answer_shape"] = {
        "kind": "field",
        "representations": [{"kind": "signed-integer", "maxLength": 6}],
    }

    response = handle(malformed)

    assert response.status == "unsupported"
    assert "exactly two coordinate fields" in response.message
    assert loopback.prompts == []
