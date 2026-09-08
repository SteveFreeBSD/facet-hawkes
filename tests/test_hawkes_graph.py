"""Graph plans cross the Facet boundary only as strictly validated geometry."""

import json
import pathlib

import pytest

from ethnos.hawkes_graph import parse_graph_plan, validate_graph_plan
from ethnos.hawkes_host import handle
from facet_loopback import facet, reasoning
from test_hawkes_provenance import FACET_RUN
from test_hawkes_insertion_ownership import page, QUESTION_A  # noqa: F401

MATH = "<math><mi>f</mi><mo>(</mo><mi>x</mi><mo>)</mo><mo>=</mo><msup><mrow><mo>(</mo><mi>x</mi><mo>-</mo><mn>3</mn><mo>)</mo></mrow><mn>2</mn></msup><mo>-</mo><mn>1</mn></math>"
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


def test_correct_exact_parabola_plan():
    assert validate_graph_plan(parse_graph_plan(json.dumps(PLAN)), [MATH]) == [
        "1",
        "-6",
        "8",
    ]
    # Translation is derived from the function, not from this live example.
    other = json.loads(
        json.dumps(PLAN)
        .replace('"3"', '"5"')
        .replace('"4"', '"6"')
        .replace('"2"', '"4"')
    )
    assert validate_graph_plan(
        parse_graph_plan(json.dumps(other)), [MATH.replace("<mn>3</mn>", "<mn>5</mn>")]
    ) == ["1", "-10", "24"]


@pytest.mark.parametrize(
    "text",
    [
        "```json\n" + json.dumps(PLAN) + "\n```",
        json.dumps(PLAN) + " prose",
        json.dumps({**PLAN, "click": "Submit"}),
        json.dumps(PLAN).replace('"x": "3"', '"x": 3'),
        json.dumps(PLAN).replace('"x": "3"', '"x": "3", "x": "4"'),
        json.dumps(PLAN).replace('"3"', '"NaN"'),
    ],
)
def test_strict_parser_rejects_non_plan(text):
    with pytest.raises(ValueError):
        parse_graph_plan(text)


@pytest.mark.parametrize(
    "change",
    [
        {"vertex": {"x": "0", "y": "0"}},
        {"opening": "down"},
        {"points": [{"x": "4", "y": "1"}, {"x": "2", "y": "1"}]},
        {"points": [{"x": "3", "y": "-1"}, {"x": "3", "y": "-1"}]},
    ],
)
def test_invalid_facet_geometry_rejected(change):
    with pytest.raises(ValueError):
        validate_graph_plan(parse_graph_plan(json.dumps({**PLAN, **change})), [MATH])


def test_graph_invokes_facet_and_reports_real_provenance(monkeypatch):
    loopback = facet(monkeypatch, **reasoning(json.dumps(PLAN)))
    result = handle(
        {
            "operation": "solve_hawkes_problem",
            "request_id": "graph-test",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Graph the parabola.",
                "mathml": [MATH],
                "answer_shape": {"kind": "graph", "graph": CONTEXT},
            },
        }
    )
    assert result.status == "ready"
    assert len(loopback.prompts) == 1
    # Facet builds the prompt now, from the question Ethnos sent it.
    assert "f(x)=(x-3)^2-1" in loopback.prompts[0]
    assert "vertex-and-symmetric-points" in loopback.prompts[0]
    assert loopback.requests[0]["constraints"]["accelerator_required"] is False
    assert result.certainty.facet_invoked
    assert result.certainty.answered_by == "facet"
    assert result.certainty.model == FACET_RUN.model
    assert result.certainty.device == FACET_RUN.device
    assert result.answer.graph_plan.model_dump() == PLAN


def test_stale_graph_snapshot_refuses_before_actuation(page):  # noqa: F811
    page.run("function graphOperation() {}")
    editor = {
        "ok": True,
        "kind": "graph",
        "context": CONTEXT,
        "snapshot": {"question": "original"},
    }
    page.own_window_a()
    # As a graph solve actually publishes it. A plan carries no writable value,
    # so `acceptReply` clears the typed fields when it puts one up, and the
    # publication guard refuses a state holding both -- a plan is proved
    # geometry and a typed answer is not, and nothing downstream picks between
    # them. Seeding the value fields and then overlaying a plan was a state the
    # event page never reaches.
    page.run(
        f"update({{editor: {json.dumps(editor)}, graphPlan: {json.dumps(PLAN)}, "
        f'graphCoefficients: ["1","-6","8"], answer: "", displayText: "", '
        f'entryText: "", answerParts: []}}); insert();'
    )
    page.pump()
    page.answer({**editor, "snapshot": {"question": "replacement"}})
    page.answer(QUESTION_A)
    assert page.json("state.phase") == "failed"
    assert page.json("state.detail") == "graph-target-stale"
    assert all(
        not call["args"]
        for call in page.json("__H.calls")
        if call["func"] == "graphOperation"
    )


def test_graph_shape_and_truthful_panel_provenance(page):  # noqa: F811
    page.run(
        "update("
        + json.dumps({"editor": {"ok": True, "kind": "graph", "context": CONTEXT}})
        + ")"
    )
    assert page.json("answerShapeOf(state.editor)") == {
        "kind": "graph",
        "graph": CONTEXT,
    }
    reply = {
        "status": "ready",
        "answer": {
            "graph_plan": PLAN,
            "graph_coefficients": ["1", "-6", "8"],
            "display_text": "Vertex (3,-1)",
        },
        "certainty": {
            "answered_by": "exact",
            "facet_invoked": False,
            "insertable": True,
        },
    }
    page.run(f"acceptReply({json.dumps(reply)})")
    assert page.json("state.phase") == "failed"


def test_graph_dom_is_detected_without_a_text_box():
    from pathlib import Path
    import quickjs

    context = quickjs.Context()
    context.eval("""
      globalThis.HTMLIFrameElement = class {};
      globalThis.HTMLFrameElement = class {};
      globalThis.window = {location: {origin: 'https://learn.hawkeslearning.com'}};
      const graph = {getBoundingClientRect:()=>({width:410}), querySelectorAll:()=>[{id:'a0'},{id:'a1'},{id:'a2'}]};
      globalThis.document = {activeElement:null, querySelectorAll:s=>s.startsWith('#QGraph')?[graph]:[]};
    """)
    context.eval(
        (Path(__file__).parents[1] / "extension/content/hawkes-editor.js").read_text()
    )
    result = json.loads(context.eval("JSON.stringify(ethnosHawkes.inspectField())"))
    assert result == {
        "ready": True,
        "code": "graph-answer",
        # Which reading claimed it: the three parabola controls this add-on
        # can move, rather than the graph merely being the only surface there.
        "via": "parabola-controls",
        "fieldId": "a0\u001fa1\u001fa2",
    }


# --- a graph that is the answer, and is not a parabola -----------------------
#
# Live, on 2026-09-07: "plot the following points in the Cartesian plane", four
# ordered pairs written into the prompt, and no answer box anywhere. The panel
# said `no-focused-answer-field` and offered the editor recovery -- "click the
# answer box and reopen this panel" -- which cannot be followed on a question
# that has no box to click.
#
# The graph gate looked for exactly three draggable parabola controls, so any
# other graph question fell past it into the text-field sweep and out the far
# side as "nothing is focused".


def graph_page(*, anchors: int, fields: str = "[]", width: int = 410):
    """A page drawing one graph, with however many controls it offers."""
    import quickjs

    context = quickjs.Context()
    context.eval(f"""
      globalThis.HTMLIFrameElement = class {{}};
      globalThis.HTMLFrameElement = class {{}};
      globalThis.window = {{location: {{origin: 'https://learn.hawkeslearning.com'}}}};
      const controls = Array.from({{length: {anchors}}}, (_, i) => ({{id: 'a' + i}}));
      const graph = {{
        id: 'QGraph',
        getBoundingClientRect: () => ({{width: {width}}}),
        querySelectorAll: () => controls,
      }};
      globalThis.document = {{
        activeElement: null,
        querySelectorAll: s => s.startsWith('#QGraph') ? [graph] : {fields},
      }};
    """)
    context.eval(
        (
            pathlib.Path(__file__).parents[1] / "extension/content/hawkes-editor.js"
        ).read_text()
    )
    return json.loads(context.eval("JSON.stringify(ethnosHawkes.inspectField())"))


def test_a_graph_with_no_parabola_controls_is_still_the_answer_surface():
    """The live case: four points to plot, no box, and no three controls."""
    result = graph_page(anchors=0)

    assert result["ready"] is True
    assert result["code"] == "graph-answer"
    assert result["via"] == "graph-surface"
    assert result["fieldId"] == "QGraph"


def test_a_graph_offering_some_other_number_of_controls_is_claimed_too():
    """Four points to place is four controls, and not a parabola's three."""
    result = graph_page(anchors=4)

    assert result["code"] == "graph-answer"
    assert result["via"] == "graph-surface"


def test_a_graph_beside_a_text_box_never_takes_that_questions_answer():
    """A scatter plot drawn beside a box is that question's data, not its
    answer surface, and the box is still where the answer goes."""
    result = graph_page(
        anchors=0,
        fields="[{id:'txtAns1_num', getBoundingClientRect:()=>({width:60,height:20}),"
        " disabled:false, readOnly:false, type:'text', value:''}]",
    )

    assert result.get("via") != "graph-surface"


def test_a_graph_the_page_is_not_drawing_is_not_an_answer_surface():
    """Zero width is a graph that is not on screen."""
    result = graph_page(anchors=0, width=0)

    assert result.get("code") != "graph-answer"


def test_the_graph_recovery_never_tells_anyone_to_click_a_box():
    """`errorEditorUnknown` ends "click the answer box and reopen this panel".

    On a graph question there is no box, so that instruction is impossible to
    follow. The graph refusal has its own words.
    """
    messages = json.loads(
        (
            pathlib.Path(__file__).parents[1] / "extension/_locales/en/messages.json"
        ).read_text()
    )
    background = (
        pathlib.Path(__file__).parents[1] / "extension/background.js"
    ).read_text()

    assert "errorGraphUnsupported" in messages
    said = messages["errorGraphUnsupported"]["message"]
    assert "answer box" not in said
    assert "graph" in said.lower()
    # And it is what a refused graph describe actually raises.
    assert '"errorWrongSite" : "errorGraphUnsupported"' in background
    assert 'log.warn("graph-unsupported"' in background


def test_graph_writer_has_no_grading_or_navigation_capability():
    from pathlib import Path

    source = (
        Path(__file__).parents[1] / "extension/common/graph-actions.js"
    ).read_text()
    for forbidden in [
        ".click(",
        ".submit(",
        '"Enter"',
        '"Tab"',
        "Submit",
        "Check",
        "Next",
        "Skip",
        "dispatchUserAnswer(",
    ]:
        assert forbidden not in source
    assert "new KeyboardEvent" in source
    assert "graph-rendered-curve-mismatch" in source


def test_factored_vertex_is_exact_and_keeps_ordered_pair_parentheses(monkeypatch):
    from ethnos.hawkes_host import _solve_from_markup

    markup = "<math><mi>p</mi><mo>(</mo><mi>x</mi><mo>)</mo><mo>=</mo><mrow><mo>(</mo><mi>x</mi><mo>-</mo><mn>6</mn><mo>)</mo></mrow><mrow><mo>(</mo><mi>x</mi><mo>+</mo><mn>2</mn><mo>)</mo></mrow><mo>+</mo><mn>16</mn></math>"
    answer, reason = _solve_from_markup("Find the vertex.", [markup])
    assert not reason
    assert answer.keyboard_entry == "(2,0)"
    assert answer.display_text == "(2,0)"
    assert answer.parts == []
    loopback = facet(monkeypatch)
    result = handle(
        {
            "operation": "solve_hawkes_problem",
            "request_id": "vertex-exact",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {"mathml": [markup], "prompt_text": "Find the vertex."},
        }
    )
    assert loopback.prompts == [], "a model guessed an exactly derivable vertex"
    assert result.certainty.answered_by == "exact"
    assert result.certainty.source == "Facet Exact"
    assert result.answer.keyboard_entry == "(2,0)"


def test_vertex_pair_uses_hawkes_parenthesis_template():
    import quickjs
    from pathlib import Path
    import re

    root = Path(__file__).parents[1] / "extension/common"
    context = quickjs.Context()
    for name in ["config.js", "editor-rules.js", "editor-plan.js"]:
        source = re.sub(
            r"^import\s[\s\S]*?;\s*$", "", (root / name).read_text(), flags=re.M
        ).replace("export ", "")
        context.eval(source)
    editor = {
        "kind": "dynamic",
        "allowedCharacters": "0123456789-,",
        "templates": {"parentheses": True},
    }
    result = json.loads(
        context.eval('JSON.stringify(planEntry("(2,0)",' + json.dumps(editor) + "))")
    )
    assert result == {
        "ok": True,
        "steps": [{"op": "template", "name": "PBrace"}, {"op": "type", "text": "2,0"}],
    }


def test_regression_coefficients_are_checked_exactly():
    from ethnos.hawkes_graph import GraphPoint, validate_regression_plan

    points = [GraphPoint(x=x, y=y) for x, y in [("-5", "5"), ("-2", "-4"), ("-1", "5")]]
    text = '{"kind":"quadratic-regression","coefficients":["3","18","20"]}'
    assert list(map(str, validate_regression_plan(text, points))) == ["3", "18", "20"]
    with pytest.raises(ValueError, match="normal equations"):
        validate_regression_plan(text.replace('"20"', '"21"'), points)
    with pytest.raises(ValueError):
        validate_regression_plan(text + " prose", points)
    with pytest.raises(ValueError):
        validate_regression_plan(text.replace('"3"', '"3.0"'), points)
    with pytest.raises(ValueError, match="unique"):
        validate_regression_plan(text, [points[0]] * 3)


def test_svg_regression_reaches_facet_without_a_screenshot(monkeypatch):
    loopback = facet(
        monkeypatch,
        **reasoning('{"kind":"quadratic-regression","coefficients":["3","18","20"]}'),
    )
    result = handle(
        {
            "operation": "solve_hawkes_problem",
            "request_id": "scatter-test",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": "Use quadratic regression. Round to three decimal places.",
                "graph_points": [
                    {"x": x, "y": y}
                    for x, y in [("-5", "5"), ("-2", "-4"), ("-1", "5")]
                ],
            },
        }
    )
    assert len(loopback.prompts) == 1
    assert result.status == "ready"
    assert result.answer.keyboard_entry == "3x^2+18x+20"
    assert result.certainty.reading == "svg"
    assert result.certainty.answered_by == "facet"
    assert result.certainty.facet_invoked


def test_regression_accepts_least_squares_without_exact_interpolation():
    from ethnos.hawkes_graph import GraphPoint, validate_regression_plan

    points = [
        GraphPoint(x=str(x), y=str(y)) for x, y in [(0, 0), (1, 1), (2, 4), (3, 10)]
    ]
    plan = '{"kind":"quadratic-regression","coefficients":["5/4","-9/20","1/20"]}'
    assert list(map(str, validate_regression_plan(plan, points))) == [
        "5/4",
        "-9/20",
        "1/20",
    ]
