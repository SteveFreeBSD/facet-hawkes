"""Named slope and y-intercept through Facet, Hawkes labels, and insertion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from facet_loopback import facet

from ethnos.hawkes_host import handle

ROOT = Path(__file__).resolve().parents[1]
ASK = "Find the slope and the y-intercept. Express the intercept as an ordered pair."


def test_host_keeps_exact_named_properties_without_a_model(monkeypatch):
    loopback = facet(monkeypatch)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "linear-properties",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": ASK,
                "mathml": [
                    "<math><mi>r</mi><mo>(</mo><mi>x</mi><mo>)</mo><mo>=</mo>"
                    "<mn>4</mn><mo>-</mo><mfrac><mn>3</mn><mn>2</mn></mfrac>"
                    "<mi>x</mi></math>"
                ],
                "answer_shape": {"kind": "multi", "count": 2},
            },
        }
    )

    assert response.status == "ready", response
    assert loopback.prompts == []
    assert response.certainty.model_calls == 0
    assert response.answer.form == "linear-properties"
    assert response.answer.linear_properties.slope == "-3/2"
    assert response.answer.linear_properties.y_intercept.x == "0"
    assert response.answer.linear_properties.y_intercept.y == "4"
    assert response.answer.parts == []


def context(prefixes, suffixes=("", ""), reverse_models=False):
    js = pytest.importorskip("quickjs").Context()
    js.eval(
        f"const prefixes={json.dumps(prefixes)}; const suffixes={json.dumps(suffixes)};"
    )
    js.eval("""
      const fields = ["alpha", "beta"].map(id => ({id, tabIndex: 0,
        getBoundingClientRect: () => ({width: 50, height: 20})}));
      const controls = fields.map((field, i) => ({Type: "QDyText", enabled: true,
        qdyBase_AllowedChar: i ? "0123456789-," : "0123456789-+",
        qdyBase_AllowedTemplates: "PBrace Fraction", qdyFractionAllowed: true,
        qdyBaseMaxChars: 50, arrChildObjects: [{Type: "Base",
          objMyDiv: {querySelector: () => field}, arrChildObjects: []}]}));
      const data = fields.map((_, i) => ({Name: "answer", isQDy: true,
        enableState: true, prefix: prefixes[i], suffix: suffixes[i]}));
      globalThis.window = {quant_wp_UI: {focusedElementIndex: -1,
        controlsCollection: controls, controlsCollectionData: data}};
      globalThis.document = {querySelectorAll: selector => selector.includes('input.qbaseCSS') ? fields : [],
        getElementById: () => null, querySelector: () => null};
    """)
    if reverse_models:
        js.eval("controls.reverse(); data.reverse();")
    return js


def describe(js):
    return json.loads(
        js.eval((ROOT / "extension/content/hawkes-describe.js").read_text()).json()
    )


def adapt(js, editor, **changes):
    source = (ROOT / "extension/background.js").read_text()
    js.eval(
        source[
            source.index("function linearPropertyParts(") : source.index(
                "function answerForSurface("
            )
        ]
    )
    answer = {
        "form": "linear-properties",
        "linear_properties": {
            "slope": "-3/2",
            "y_intercept": {"x": "0", "y": "4"},
        },
        **changes,
    }
    return json.loads(
        js.eval(
            f"JSON.stringify(linearPropertyParts({json.dumps(answer)}, "
            f"{json.dumps(editor)}, ['alpha','beta']))"
        )
    )


@pytest.mark.parametrize("reverse_models", [False, True])
def test_semantic_labels_override_model_and_field_order(reverse_models):
    js = context(
        [
            '<span class="noWrap"><var>y</var>-intercept: </span>',
            '<span class="noWrap">Slope: </span>',
        ],
        reverse_models=reverse_models,
    )
    editor = describe(js)

    assert editor["ok"] is True
    assert editor["code"] == "described-linear-properties"
    assert [row["role"] for row in editor["linearPropertyRows"]] == [
        "y-intercept",
        "slope",
    ]
    assert adapt(js, editor) == ["(0,4)", "-3/2"]


def test_page_owned_pair_parentheses_are_not_duplicated():
    js = context(["Slope:", "y-intercept: ("], ["", ")"])
    editor = describe(js)
    assert editor["linearPropertyRows"][1]["ownsPair"] is True
    assert adapt(js, editor) == ["-3/2", "0,4"]


@pytest.mark.parametrize(
    ("prefixes", "suffixes"),
    [
        (["Slope:", "Slope:"], ["", ""]),
        (["Slope:", "Answer:"], ["", ""]),
        (["Slope: (", "y-intercept:"], [")", ""]),
        (["Slope:", "y-intercept: ("], ["", ""]),
    ],
)
def test_ambiguous_surfaces_never_adapt(prefixes, suffixes):
    js = context(prefixes, suffixes)
    assert adapt(js, describe(js)) is None


def test_competing_or_malformed_payloads_never_adapt():
    js = context(["Slope:", "y-intercept:"])
    editor = describe(js)
    assert adapt(js, editor, form="parts") is None
    assert adapt(js, editor, parts=["-3/2", "(0,4)"]) is None
    assert (
        adapt(
            js,
            editor,
            linear_properties={"slope": "-3/2", "y_intercept": {"x": "1", "y": "4"}},
        )
        is None
    )
    editor["linearPropertyRows"].reverse()
    assert adapt(js, editor) is None


def test_equation_only_slope_request_does_not_claim_a_future_graph():
    from test_graph_domain_range import ROOT as GRAPH_ROOT, dom

    js = dom()
    js.eval(
        f"window.questionPartViewModel={{partDescription:{json.dumps(ASK)},questionGraphHTML:''}};"
    )
    model = json.loads(
        js.eval(
            (GRAPH_ROOT / "extension/content/hawkes-graph-model.js").read_text()
        ).json()
    )
    assert model == {
        "graphReason": "line-slope-no-graph",
        "graphQuestion": "",
        "graphDecision": "unavailable",
    }


def test_typed_reply_reaches_owned_fields_in_semantic_order():
    from test_hawkes_insertion_ownership import QUESTION_A, make_page

    editor = describe(context(["Slope:", "y-intercept:"]))
    reply = {
        "status": "ready",
        "problem_text": ASK,
        "answer": {
            "form": "linear-properties",
            "linear_properties": {
                "slope": "-3/2",
                "y_intercept": {"x": "0", "y": "4"},
            },
        },
        "certainty": {
            "source": "Facet Exact",
            "answered_by": "exact",
            "facet_invoked": True,
            "model_calls": 0,
            "insertable": True,
        },
    }
    page = make_page()
    page.run(
        f"""state={{...blankState(),phase:'solving',windowId:1,tabId:11,frameId:0,
          fieldId:'alpha\\u001fbeta',fieldIds:['alpha','beta'],fieldIdentity:'separated',
          editor:{json.dumps(editor)},signature:questionSignature({json.dumps(QUESTION_A)})}};
          acceptReply({json.dumps(reply)});"""
    )
    page.pump()

    assert page.json("state.phase") == "solved", page.json("__H.logged")
    assert page.json("state.answerParts") == ["-3/2", "(0,4)"]
    assert page.json("state.answer") == "Slope: -3/2; y-intercept: (0,4)"
    assert page.writes == []

    page.run("insert();")
    page.pump()
    page.answer(editor)
    page.answer(QUESTION_A)
    page.answer(
        {
            "ready": True,
            "code": "multi-answer-fields",
            "fieldId": "alpha\u001fbeta",
            "fieldIds": ["alpha", "beta"],
        }
    )
    page.answer(
        {
            "ok": True,
            "code": "entered-fields",
            "entered": ["-32", "04"],
            "enteredFields": ["alpha", "beta"],
            "completed": 2,
        }
    )
    page.answer(QUESTION_A)

    writes = [call for call in page.writes if call["func"] == "enterPlan"]
    assert len(writes) == 1
    assert writes[0]["args"][0] == [
        [
            {"op": "template", "name": "Fraction"},
            {"op": "type", "text": "-3"},
            {"op": "slot", "name": "denominator"},
            {"op": "type", "text": "2"},
        ],
        [
            {"op": "template", "name": "PBrace"},
            {"op": "type", "text": "0,4"},
        ],
    ]
    assert writes[0]["args"][2] == ["alpha", "beta"]
    assert writes[0]["args"][3] == "hawkes-dynamic-keypad"
    typed = sum(
        len(step.get("text", ""))
        for plan in writes[0]["args"][0]
        for step in plan
        if step["op"] == "type"
    )
    assert len(writes[0]["args"][1]["score"]["offsets"]) == typed
    assert page.json("state.phase") == "inserted"
