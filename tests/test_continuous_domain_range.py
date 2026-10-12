"""Continuous projections reuse labeled rows and the existing multipart writer."""

import json

import pytest
from facet_loopback import facet
from hawkes_dom import read_question
from test_domain_range import context, describe
from test_graph_domain_range import dom, graph, line, ROOT
from test_hawkes_insertion_ownership import QUESTION_A, make_page
from ethnos.hawkes_host import handle

ASK = "Determine the domain and range for the relation in interval notation."


def test_relation_prompt_probes_graph_without_a_graph_keyword():
    result = read_question(
        f'<div id="partInformation">Step 1 of 2 {ASK}</div><div id="questionString"><math><mi>y</mi><mo>=</mo><mi>x</mi></math></div><input class="qbaseCSS">'
    )
    assert result["evidence"]["graphQuestion"] == "domain-range"
    js = dom()
    js.eval(
        f"window.questionPartViewModel={{partDescription:{json.dumps(ASK)},questionGraphHTML:{json.dumps(graph(line()))}}};"
    )
    model = json.loads(
        js.eval((ROOT / "extension/content/hawkes-graph-model.js").read_text()).json()
    )
    assert model["graphDecision"] == "accepted"
    assert model["graphRelation"]["ends"] == ["infinite", "infinite"]


def test_absent_graph_leaves_finite_and_equation_routes_available():
    js = dom()
    js.eval(
        f'window.questionPartViewModel={{partDescription:{json.dumps(ASK)},questionGraphHTML:""}};'
    )
    model = json.loads(
        js.eval((ROOT / "extension/content/hawkes-graph-model.js").read_text()).json()
    )
    assert model["graphQuestion"] == ""
    assert model["graphReason"] == "domain-range-no-graph"


def request(equation, geometry=None):
    return {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "continuous-test",
        "origin": "https://learn.hawkeslearning.com",
        "solve_engine": "facet",
        "problem": {
            "prompt_text": ASK,
            "mathml": [f"<math><mtext>{equation}</mtext></math>"],
            "answer_shape": {"kind": "multi", "count": 2},
            **({"graph_relation": geometry} if geometry else {}),
        },
    }


@pytest.mark.parametrize("with_graph", [False, True])
def test_host_carries_continuous_parts_with_no_model(monkeypatch, with_graph):
    loop = facet(monkeypatch)
    g = {
        "kind": "linear",
        "points": [{"x": "0", "y": "5"}, {"x": "1", "y": "3"}],
        "ends": ["infinite", "infinite"],
    }
    response = handle(request("y=-2x+5", g if with_graph else None))
    assert response.status == "ready", response
    assert response.answer.graph_domain_range == {
        r: {"kind": "all-real-numbers"} for r in ("domain", "range")
    }
    assert response.certainty.model_calls == 0 and not loop.prompts


def test_host_refuses_equation_graph_conflict(monkeypatch):
    loop = facet(monkeypatch)
    response = handle(
        request(
            "y=-2x+5",
            {
                "kind": "linear",
                "points": [{"x": "0", "y": "4"}, {"x": "1", "y": "3"}],
                "ends": ["infinite", "infinite"],
            },
        )
    )
    assert response.status == "unsupported" and response.answer is None
    assert not loop.prompts


def interval_editor(reverse=False):
    js = context(["Range:", "Domain:"], ["", ""], reverse)
    js.eval(
        "controls.forEach(c=>{c.qdyBase_AllowedChar='0123456789-,∞';c.qdyBase_AllowedTemplates=['PBrace','SBrace','SPBrace','PSBrace'];});"
    )
    return describe(js)


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("axis", [None, "domain", "range"])
def test_continuous_parts_use_semantic_rows_and_existing_writer(reverse, axis):
    editor = interval_editor(reverse)
    assert editor["ok"]
    rows = editor["domainRangeRows"]
    ids = [r["fieldId"] for r in rows]
    parts = {r: {"kind": "all-real-numbers"} for r in ("domain", "range")}
    if axis:
        parts[axis] = {"kind": "singleton", "value": "7"}
    page = make_page()
    page.own_window_a()
    page.run(
        f'state={{...state,phase:"solving",editor:{json.dumps(editor)},fieldIds:{json.dumps(ids)},fieldId:{json.dumps(chr(31).join(ids))},answerChoices:[]}};'
    )
    reply = {
        "status": "ready",
        "answer": {"form": "graph-domain-range", "graph_domain_range": parts},
        "certainty": {
            "answered_by": "exact",
            "facet_invoked": True,
            "model_calls": 0,
            "insertable": True,
        },
    }
    page.run(f"acceptReply({json.dumps(reply)});")
    page.pump()
    assert page.json("state.phase") == "solved", page.json("__H.logged")
    page.run("insert();")
    page.pump()
    page.answer(editor)
    page.answer(QUESTION_A)
    assert len(page.writes) == 1, page.json("__H.logged")
    write = page.writes[0]
    assert write["func"] == "enterPlan" and write["args"][2] == ids
    assert write["args"][3] == "hawkes-dynamic-keypad"
    typed = sum(
        len(step.get("text", ""))
        for plan in write["args"][0]
        for step in plan
        if step["op"] == "type"
    )
    assert len(write["args"][1]["score"]["offsets"]) == typed
    for row, steps in zip(rows, write["args"][0]):
        assert steps[0] == {
            "op": "template",
            "name": "SBrace" if row["role"] == axis else "PBrace",
        }
    assert not any(c["func"] == "selectAxisAbsences" for c in page.json("__H.calls"))


@pytest.mark.parametrize("bad", ["duplicate", "braces", "partial-option"])
def test_interval_row_ambiguity_refuses_before_any_write(bad):
    editor = interval_editor()
    rows = editor["domainRangeRows"]
    if bad == "duplicate":
        rows[1]["role"] = rows[0]["role"]
    if bad == "braces":
        rows[1]["braces"] = True
    if bad == "partial-option":
        rows[1]["optionId"] = "unowned"
    page = make_page()
    page.own_window_a()
    page.run(
        f'state={{...state,phase:"solving",editor:{json.dumps(editor)}}};acceptReply({json.dumps({"status": "ready", "answer": {"form": "graph-domain-range", "graph_domain_range": {r: {"kind": "all-real-numbers"} for r in ("domain", "range")}}, "certainty": {"answered_by": "exact", "facet_invoked": True, "model_calls": 0, "insertable": True}})});'
    )
    page.pump()
    assert page.json("state.errorKey") == "errorAnswerInvalid"
    assert not page.writes
