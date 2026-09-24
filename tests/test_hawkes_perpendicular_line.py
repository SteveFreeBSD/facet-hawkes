"""Page math reaches Facet's sibling line constructors and the native planner."""

import pytest

from facet_loopback import facet, reasoning
from test_hawkes_plan import SLOPE_INTERCEPT_EDITOR, plan as plan
from ethnos.hawkes_host import handle


def request(relationship="perpendicular"):
    return {
        "operation": "solve_hawkes_problem",
        "request_id": "related-line-proof",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": f"Find the equation of the line passing through the stated point and {relationship} to the given line. Express your answer in slope-intercept form.",
            "mathml": [
                "<math><mn>3</mn><mi>x</mi><mo>-</mo><mn>2</mn><mi>y</mi><mo>=</mo><mn>7</mn></math>",
                "<math><mo>(</mo><mo>-</mo><mn>2</mn><mo>,</mo><mn>1</mn><mo>)</mo></math>",
            ],
            "answer_shape": {"kind": "field"},
        },
    }


@pytest.mark.parametrize(
    ("relationship", "entry"),
    [
        ("perpendicular", "y=-2/3*x-1/3"),
        ("parallel", "y=3/2*x+4"),
    ],
)
def test_related_line_is_exact_typed_and_uses_existing_fraction_planner(
    monkeypatch, plan, relationship, entry
):
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: y=999x"))
    response = handle(request(relationship))
    assert response.status == "ready"
    assert response.answer.form == "relation"
    assert response.answer.keyboard_entry == entry
    assert response.answer.relation.subject == "y"
    assert response.certainty.source == "Facet Exact"
    assert response.certainty.method == f"Exact {relationship} line through a point"
    assert response.certainty.model_calls == 0
    assert loopback.prompts == []
    native = plan(response.answer.keyboard_entry, SLOPE_INTERCEPT_EDITOR)
    assert native["ok"] is True
    assert any(step.get("name") == "Fraction" for step in native["steps"])
    assert all("/" not in step.get("text", "") for step in native["steps"])


def test_unrepresentable_vertical_result_is_refused_without_a_model(monkeypatch):
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: y=999x"))
    payload = request()
    payload["problem"]["mathml"][0] = "<math><mi>y</mi><mo>=</mo><mn>4</mn></math>"
    response = handle(payload)
    assert response.status == "ambiguous"
    assert "vertical line" in response.message
    assert loopback.prompts == []
