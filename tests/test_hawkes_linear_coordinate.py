"""Page-owned coordinate constraints cross the boundary as mathematics."""

from facet_loopback import facet, reasoning
from ethnos.hawkes_host import handle


def request(given="2", axis="y"):
    return {
        "operation": "solve_hawkes_problem",
        "request_id": "coordinate-step",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": f"Given x = {given}, determine the value for {axis}.",
            "mathml": [
                "<math><mn>3</mn><mi>x</mi><mo>+</mo><mn>2</mn><mi>y</mi><mo>=</mo><mn>8</mn></math>"
            ],
            "coordinate_task": {
                "axis": axis,
                "given": given,
                "bounds": ["-4", "6", "-3", "5"],
                "steps": ["1", "1"],
                "allow_rational": False,
            },
            "answer_shape": {"kind": "field"},
        },
    }


def test_exact_typed_coordinate_and_normalized_bounds(monkeypatch):
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: 99"))
    response = handle(request())
    assert response.status == "ready"
    assert response.answer.form == "scalar"
    assert response.answer.keyboard_entry == "1"
    assert response.certainty.model_calls == 0
    assert response.certainty.source == "Facet Exact"
    assert response.certainty.insertable
    assert loopback.prompts == []
    assert (
        loopback.problems[0]["coordinate_task"]
        == request()["problem"]["coordinate_task"]
    )


def test_out_of_bounds_dependent_coordinate_is_not_sent_to_reasoning(monkeypatch):
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: 99"))
    response = handle(request("6"))
    assert response.status != "ready"
    assert loopback.prompts == []


def test_free_coordinate_is_safe_for_the_next_dependent_step(monkeypatch):
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: 99"))
    payload = request(None, "x")
    payload["problem"]["prompt_text"] = "Choose a value for x."
    response = handle(payload)
    assert response.status == "ready"
    assert response.answer.keyboard_entry == "2"
    assert response.certainty.model_calls == 0
    assert loopback.prompts == []
