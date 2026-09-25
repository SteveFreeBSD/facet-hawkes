"""Plural coordinate answers retain identity while reusing exact pair solves."""

from copy import deepcopy

import pytest

from facet_loopback import facet, reasoning
from ethnos.hawkes_host import handle


def request(points):
    return {
        "operation": "solve_hawkes_problem",
        "request_id": "labeled-coordinates",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": "Identify the coordinates of the labeled points on the graph.",
            "labeled_points": [{**point, "reading": "page-model"} for point in points],
            "answer_shape": {"kind": "labeled-coordinates"},
        },
    }


@pytest.mark.parametrize(
    "points",
    [
        [{"label": "U", "x": "-4", "y": "0"}, {"label": "P", "x": "0", "y": "7"}],
        [
            {"label": "K", "x": "-3/2", "y": "1/2"},
            {"label": "R", "x": "5/2", "y": "-7/2"},
        ],
        [
            {"label": label, "x": str(index - 3), "y": str(3 - index)}
            for index, label in enumerate(["Z", "T", "Q", "R"])
        ],
    ],
)
def test_instruction_and_graph_are_complete_content_with_no_equation(
    monkeypatch, points
):
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: must not run"))
    response = handle(request(points))
    assert response.status == "ready", response.message
    assert response.answer.form == "labeled-coordinates"
    assert response.answer.parts == []
    assert response.answer.keyboard_entry == ""
    assert [
        point.model_dump(exclude={"reading"})
        for point in response.answer.labeled_coordinates
    ] == points
    assert response.certainty.model_calls == 0
    assert response.certainty.source == "Facet Exact"
    assert loopback.prompts == []
    assert len(loopback.problems) == len(points)


@pytest.mark.parametrize("fault", ["duplicate", "one", "wrong-surface"])
def test_ambiguous_collection_fails_before_any_solver(monkeypatch, fault):
    loopback = facet(monkeypatch)
    payload = request(
        [{"label": "U", "x": "-4", "y": "0"}, {"label": "P", "x": "0", "y": "7"}]
    )
    if fault == "duplicate":
        payload["problem"]["labeled_points"][1] = deepcopy(
            payload["problem"]["labeled_points"][0]
        )
    elif fault == "one":
        payload["problem"]["labeled_points"].pop()
    else:
        payload["problem"]["answer_shape"] = {"kind": "multi", "count": 2}
    assert handle(payload).status != "ready"
    assert loopback.problems == []
    assert loopback.prompts == []
