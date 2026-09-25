"""Page identity decorates, but never changes, the exact point-plot route."""

from copy import deepcopy

import pytest

from facet_loopback import facet
from ethnos.hawkes_graph import PointPlotPlan
from ethnos.hawkes_host import handle


def request(points):
    return {
        "operation": "solve_hawkes_problem",
        "request_id": "labeled-plot",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": "Plot the given labeled points on the graph.",
            # Formula order deliberately differs from label-owner order.
            "mathml": [
                f"<math><mtext>({p['x']},{p['y']})</mtext></math>"
                for p in reversed(points)
            ],
            "answer_shape": {
                "kind": "graph",
                "graph": {
                    "family": "points",
                    "count": len(points),
                    "bounds": [-12.0, 8.0, -9.0, 11.0],
                    "snap": [0.5, 0.5],
                    "controls": "draggable-points",
                    "labeled_points": points,
                },
            },
        },
    }


@pytest.mark.parametrize(
    "points",
    [
        [{"label": "Z", "x": "0", "y": "0"}],
        [{"label": "R", "x": "4", "y": "-3"}, {"label": "K", "x": "-5", "y": "2"}],
        [{"label": "P_1", "x": "-3/2", "y": "0"}, {"label": "T", "x": "0", "y": "7/2"}],
        # Coincident coordinates do not make distinct, explicit labels ambiguous.
        [{"label": "U", "x": "2", "y": "3"}, {"label": "V", "x": "2", "y": "3"}],
    ],
)
def test_labels_survive_exact_plan_without_positional_assignment(monkeypatch, points):
    loopback = facet(monkeypatch)
    response = handle(request(points))
    assert response.status == "ready", response.message
    assert response.answer.graph_plan.model_dump() == {
        "kind": "points",
        "points": points,
    }
    assert response.certainty.model_calls == 0
    assert response.certainty.source == "Facet Exact"
    assert loopback.prompts == []
    assert loopback.problems[0]["result_kind"] == "point_plot_plan"
    assert all(p["label"] in response.answer.display_text for p in points)


def test_exact_coordinate_disagreement_refuses_without_a_model(monkeypatch):
    loopback = facet(monkeypatch)
    payload = request([{"label": "Z", "x": "1", "y": "2"}])
    payload["problem"]["mathml"] = ["<math><mtext>(1,3)</mtext></math>"]
    response = handle(payload)
    assert response.status != "ready"
    assert "disagree" in response.message
    assert loopback.prompts == []


@pytest.mark.parametrize("fault", ["duplicate", "missing", "empty"])
def test_invalid_label_plan_cannot_cross_the_host_contract(fault):
    points = [{"label": "R", "x": "1", "y": "2"}, {"label": "S", "x": "3", "y": "4"}]
    changed = deepcopy(points)
    if fault == "duplicate":
        changed[1]["label"] = "R"
    elif fault == "missing":
        del changed[1]["label"]
    else:
        changed[1]["label"] = ""
    with pytest.raises(ValueError):
        PointPlotPlan.model_validate({"kind": "points", "points": changed})


def test_unlabeled_route_remains_unlabeled(monkeypatch):
    loopback = facet(monkeypatch)
    payload = request([{"label": "Z", "x": "1", "y": "2"}])
    del payload["problem"]["answer_shape"]["graph"]["labeled_points"]
    response = handle(payload)
    assert response.status == "ready"
    assert response.answer.graph_plan.model_dump() == {
        "kind": "points",
        "points": [{"x": "1", "y": "2"}],
    }
    assert loopback.prompts == []
