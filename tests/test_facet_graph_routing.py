"""Graph plans across the boundary: Facet proposes, Ethnos proves.

The parabola and quadratic-regression paths were the last two places where
Ethnos wrote a model prompt. They built one here, called `generate_text`, and
parsed the reply themselves -- so for those two families the consumer still
decided how the question would be answered, and Facet only executed.

They go through `solve_math` now, as a *question*: an instruction, the exact
expressions, and normalised geometry or normalised coordinates. Facet picks the
specialist, writes the prompt, and parses the reply strictly.

What did not move is the proof. A plan is a proposal, and it becomes insertable
only after this side re-validates its schema and then checks its mathematics
against the page's own markup. These tests are mostly about that: a plan Facet
was perfectly happy with must still be refused here when it is wrong.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from facet_loopback import facet, reasoning

from ethnos.facet_client import FacetProtocolError, _solution
from ethnos.hawkes_host import handle

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: f(x) = (x-3)^2 - 1, as MathJax leaves it in the page.
MATH = (
    "<math><mi>f</mi><mo>(</mo><mi>x</mi><mo>)</mo><mo>=</mo><msup><mrow><mo>(</mo>"
    "<mi>x</mi><mo>-</mo><mn>3</mn><mo>)</mo></mrow><mn>2</mn></msup><mo>-</mo>"
    "<mn>1</mn></math>"
)
PLAN = {
    "kind": "parabola",
    "orientation": "vertical",
    "opening": "up",
    "vertex": {"x": "3", "y": "-1"},
    "points": [{"x": "4", "y": "0"}, {"x": "2", "y": "0"}],
}
CONTEXT = {
    "family": "parabola",
    "orientation": "vertical",
    "bounds": [-10.0, 10.0, -10.0, 10.0],
    "snap": [0.5, 0.5],
    "controls": "vertex-and-symmetric-points",
}
POINTS = [("-5", "5"), ("-2", "-4"), ("-1", "5")]
REGRESSION = '{"kind":"quadratic-regression","coefficients":["3","18","20"]}'
REGRESSION_INSTRUCTION = "Use quadratic regression. Round to three decimal places."


def graph_request(**changes) -> dict:
    request = {
        "operation": "solve_hawkes_problem",
        "request_id": "graph-1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": "Graph the parabola.",
            "mathml": [MATH],
            "answer_shape": {"kind": "graph", "graph": CONTEXT},
        },
    }
    request.update(changes)
    return request


def regression_request(**changes) -> dict:
    request = {
        "operation": "solve_hawkes_problem",
        "request_id": "scatter-1",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": REGRESSION_INSTRUCTION,
            "graph_points": [{"x": x, "y": y} for x, y in POINTS],
        },
    }
    request.update(changes)
    return request


def answering(monkeypatch, text: str):
    """A real Facet whose model answers with `text`, and no other way across."""
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("a graph path still writes its own prompt"),
    )
    return facet(monkeypatch, **reasoning(text))


# --- both families now ask a question rather than send a prompt -------------


def test_a_parabola_request_goes_through_solve_math(monkeypatch) -> None:
    loopback = answering(monkeypatch, json.dumps(PLAN))

    response = handle(graph_request())

    crossed = loopback.requests[0]
    assert crossed["operation"] == "solve_math"
    assert crossed["problem"]["result_kind"] == "parabola_plan"
    assert crossed["problem"]["instruction"] == "Graph the parabola."
    # The mathematics, not the markup: converting MathJax stays on this side.
    assert crossed["problem"]["expressions"] == ["f(x)=(x-3)^2-1"]
    assert crossed["problem"]["graph"] == CONTEXT
    assert response.status == "ready"


def test_a_regression_request_goes_through_solve_math(monkeypatch) -> None:
    loopback = answering(monkeypatch, REGRESSION)

    response = handle(regression_request())

    crossed = loopback.requests[0]
    assert crossed["operation"] == "solve_math"
    assert crossed["problem"]["result_kind"] == "quadratic_regression"
    assert crossed["problem"]["points"] == [{"x": x, "y": y} for x, y in POINTS]
    # A regression is fitted to coordinates; there is no expression to send.
    assert "expressions" not in crossed["problem"]
    assert response.status == "ready"
    assert response.answer.keyboard_entry == "3x^2+18x+20"


def test_no_hawkes_path_writes_a_model_prompt_any_more() -> None:
    """The last two prompts written here are gone, and nothing replaced them."""
    for name in ("hawkes_host.py", "hawkes_graph.py"):
        source = (PROJECT_ROOT / "src" / "ethnos" / name).read_text()
        assert "generate_text" not in source, f"{name} still calls a model directly"
        for prompting in (
            "Return ONLY",
            "FINAL ANSWER",
            "Reply with",
            "Do not explain",
        ):
            assert prompting not in source, f"{name} still writes a prompt"


# --- the structured plans survive the protocol exactly ----------------------


def test_a_parabola_plan_survives_serialisation_exactly(monkeypatch) -> None:
    answering(monkeypatch, json.dumps(PLAN))

    response = handle(graph_request())

    assert response.answer.graph_plan.model_dump() == PLAN
    # The coefficients are this host's own reading of the page, not Facet's.
    assert response.answer.graph_coefficients == ["1", "-6", "8"]


def test_exact_regression_coefficients_survive_serialisation_exactly(
    monkeypatch,
) -> None:
    """A rational coefficient must not become a decimal on the way through."""
    answering(
        monkeypatch,
        '{"kind":"quadratic-regression","coefficients":["5/4","-9/20","1/20"]}',
    )

    response = handle(
        regression_request(
            problem={
                "prompt_text": REGRESSION_INSTRUCTION,
                "graph_points": [
                    {"x": str(x), "y": str(y)}
                    for x, y in [(0, 0), (1, 1), (2, 4), (3, 10)]
                ],
            }
        )
    )

    assert response.status == "ready"
    # Rounded for display only after the exact fit was proved.
    assert response.answer.keyboard_entry == "1.25x^2-0.45x+0.05"


# --- Ethnos is still the authority that proves a plan -----------------------


@pytest.mark.parametrize(
    ("change", "why"),
    [
        ({"vertex": {"x": "0", "y": "0"}}, "a vertex the function does not have"),
        ({"opening": "down"}, "an opening the leading coefficient contradicts"),
        (
            {"points": [{"x": "4", "y": "1"}, {"x": "2", "y": "1"}]},
            "points that are not on the curve",
        ),
        (
            {"points": [{"x": "3", "y": "-1"}, {"x": "3", "y": "-1"}]},
            "points that are not symmetric about the vertex",
        ),
        (
            {"points": [{"x": "2", "y": "0"}, {"x": "4", "y": "0"}]},
            "the defining points the wrong way round",
        ),
    ],
)
def test_a_schema_valid_plan_that_is_wrong_is_refused_here(
    monkeypatch, change, why
) -> None:
    """Facet was happy with every one of these. That is the point.

    A plan parses on the Facet side because it is well-formed; whether it is
    *true* of the function on the page is a question only this side can answer,
    and it answers it before the graph actuator sees anything.
    """
    answering(monkeypatch, json.dumps({**PLAN, **change}))

    response = handle(graph_request())

    assert response.status == "unsupported", why
    assert response.answer is None
    assert response.certainty is None
    assert "Graph plan refused" in response.message


def test_a_schema_valid_regression_that_is_wrong_is_refused_here(monkeypatch) -> None:
    """Coefficients that parse, and fail the exact normal equations."""
    answering(monkeypatch, REGRESSION.replace('"20"', '"21"'))

    response = handle(regression_request())

    assert response.status == "unsupported"
    assert response.answer is None
    assert "normal equations" in response.message


def test_points_that_do_not_determine_a_fit_are_refused(monkeypatch) -> None:
    answering(monkeypatch, REGRESSION)

    response = handle(
        regression_request(
            problem={
                "prompt_text": REGRESSION_INSTRUCTION,
                "graph_points": [{"x": "-5", "y": "5"}] * 3,
            }
        )
    )

    assert response.status == "unsupported"
    assert "unique" in response.message


def test_a_fractional_fit_without_the_supported_rounding_is_refused(
    monkeypatch,
) -> None:
    """Rounding behaviour did not move either: only the instruction we support."""
    answering(
        monkeypatch,
        '{"kind":"quadratic-regression","coefficients":["5/4","-9/20","1/20"]}',
    )

    response = handle(
        regression_request(
            problem={
                "prompt_text": "Use quadratic regression.",
                "graph_points": [
                    {"x": str(x), "y": str(y)}
                    for x, y in [(0, 0), (1, 1), (2, 4), (3, 10)]
                ],
            }
        )
    )

    assert response.status == "unsupported"
    assert "three-decimal" in response.message


# --- a reply that is not a plan reaches nothing -----------------------------


@pytest.mark.parametrize(
    ("reply", "why"),
    [
        ("```json\n" + json.dumps(PLAN) + "\n```", "a fenced code block"),
        (json.dumps(PLAN) + " prose", "trailing prose"),
        (json.dumps({**PLAN, "click": "Submit"}), "an extra key"),
        (json.dumps(PLAN).replace('"x": "3"', '"x": 3'), "a bare number"),
        (json.dumps(PLAN).replace('"3"', '"3.0"'), "a decimal approximation"),
        (json.dumps(PLAN).replace('"x": "3"', '"x": "3", "x": "4"'), "a repeated key"),
        ("I would put the vertex at (3, -1).", "prose instead of a plan"),
        ("", "no reply at all"),
    ],
)
def test_a_malformed_graph_reply_fails_closed(monkeypatch, reply, why) -> None:
    answering(monkeypatch, reply)

    response = handle(graph_request())

    assert response.status == "unsupported", why
    assert response.answer is None
    assert response.certainty is None


# --- what the protocol will and will not carry ------------------------------


#: Everything a Hawkes page is made of. A graph question is the one most able
#: to leak it, because the thing being asked about is a picture.
PAGE_DETAIL = (
    "screenshot",
    "png",
    "base64",
    "mathml",
    "<math",
    "origin",
    "hawkeslearning",
    "tab_id",
    "frame",
    "window",
    "field",
    "editor",
    "selector",
    "keyboard",
    "answer_shape",
    "graph_points",
    "solve_engine",
    "qgraph",
    "svg",
    "element",
    "node",
)


@pytest.mark.parametrize(
    ("build", "reply"),
    [(graph_request, json.dumps(PLAN)), (regression_request, REGRESSION)],
    ids=["parabola", "regression"],
)
def test_no_browser_detail_reaches_facet(monkeypatch, build, reply) -> None:
    loopback = answering(monkeypatch, reply)

    handle(build())

    crossed = json.dumps(
        [
            {key: value for key, value in request.items() if key != "request_id"}
            for request in loopback.requests
        ]
    ).lower()
    for detail in PAGE_DETAIL:
        assert detail not in crossed, f"{detail} crossed to Facet"


# --- provenance names the specialist that ran -------------------------------


def test_a_parabola_plan_is_identifiable_as_the_specialist_it_was(
    monkeypatch,
) -> None:
    answering(monkeypatch, json.dumps(PLAN))

    certainty = handle(graph_request()).certainty

    assert certainty.source == "Facet Parabola Plan · GPU"
    assert certainty.answered_by == "facet"
    assert certainty.facet_invoked is True
    # The exact solvers answer expressions, not geometry, so they were not
    # asked -- which is a different claim from having tried and declined.
    assert certainty.router == "not-run"
    assert certainty.router_detail == "a graph plan has no deterministic route"
    assert certainty.model == "gpt-oss:20b"
    assert certainty.runtime == "Ollama 0.33.2"
    assert certainty.actual_backend == "gpu"
    assert certainty.device == "AMD Radeon 890M Graphics (RADV STRIX1)"
    assert certainty.fallback is False
    assert certainty.elapsed_ms >= 0
    assert certainty.reading == "mathml"
    # The one claim that is not Facet's: what this host checked for itself.
    assert certainty.issues == [
        "Graph plan mathematically validated against exact MathML"
    ]


def test_a_regression_is_identifiable_as_the_specialist_it_was(monkeypatch) -> None:
    answering(monkeypatch, REGRESSION)

    certainty = handle(regression_request()).certainty

    assert certainty.source == "Facet Quadratic Regression · GPU"
    assert certainty.router == "not-run"
    assert certainty.reading == "svg"
    assert certainty.issues == [
        "Facet coefficients validated with exact least-squares normal equations"
    ]


# --- the client refuses a result of the wrong shape -------------------------


def plan_result(**changes) -> dict:
    made = {
        "route": "reasoning",
        "answer": {"kind": "parabola_plan", "plan": PLAN},
        "provenance": {
            "source": "Facet Parabola Plan · GPU",
            "method": "gpt-oss:20b",
            "router": "not-run",
            "router_detail": "a graph plan has no deterministic route",
            "runtime": "Ollama 0.33.2",
            "model": "gpt-oss:20b",
            "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
            "requested_backend": "auto",
            "actual_backend": "gpu",
            "elapsed_ms": 910.0,
            "fallback": False,
            "metrics": {},
            "evidence": {},
        },
    }
    made.update(changes)
    return made


def test_a_well_formed_plan_result_is_accepted() -> None:
    """The refusals below must be refusing something, not everything."""
    solution = _solution(
        plan_result(), allow_fallback=False, expected_kind="parabola_plan"
    )

    assert solution.answer.kind == "parabola_plan"
    assert solution.answer.plan == PLAN
    assert solution.route == "reasoning"


@pytest.mark.parametrize(
    ("payload", "kind", "why"),
    [
        (plan_result(), "value", "a plan where a value was asked for"),
        (
            plan_result(
                answer={
                    "kind": "value",
                    "display": "3",
                    "entry": "3",
                    "parts": [],
                    "entry_mode": "auto",
                }
            ),
            "parabola_plan",
            "a value where a plan was asked for",
        ),
        (
            plan_result(answer={"kind": "quadratic_regression", "plan": PLAN}),
            "parabola_plan",
            "the other specialist's result",
        ),
        (
            plan_result(answer={"kind": "parabola_plan", "plan": PLAN, "entry": "3"}),
            "parabola_plan",
            "a plan smuggling a writable value",
        ),
        (
            plan_result(
                answer={
                    "kind": "parabola_plan",
                    "plan": PLAN,
                    "display": "Vertex (3,-1)",
                }
            ),
            "parabola_plan",
            "a plan smuggling something to display",
        ),
        (
            plan_result(answer={"kind": "parabola_plan", "plan": {}}),
            "parabola_plan",
            "an empty plan",
        ),
        (
            plan_result(answer={"kind": "parabola_plan", "plan": "up"}),
            "parabola_plan",
            "a plan that is not structured",
        ),
        (
            plan_result(route="exact"),
            "parabola_plan",
            "geometry claimed as an exact solve",
        ),
        (
            plan_result(
                provenance={**plan_result()["provenance"], "router": "declined"}
            ),
            "parabola_plan",
            "a router that says it tried",
        ),
        (
            plan_result(provenance={**plan_result()["provenance"], "model": None}),
            "parabola_plan",
            "a reasoned plan naming nothing that reasoned",
        ),
    ],
)
def test_a_plan_result_that_contradicts_itself_is_refused(payload, kind, why) -> None:
    with pytest.raises(FacetProtocolError):
        _solution(payload, allow_fallback=False, expected_kind=kind)
    assert why


def test_a_repeated_key_anywhere_in_a_reply_is_refused() -> None:
    """`json.loads` keeps the last silently; a vertex may not be chosen that way."""
    from ethnos.facet_client import _envelope

    with pytest.raises(FacetProtocolError, match="more than once"):
        _envelope('{"facet_protocol_version": 2, "status": "ok", "status": "error"}')
