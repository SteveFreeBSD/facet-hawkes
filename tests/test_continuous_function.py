"""Shared graph reading and conditional host contract for continuous functions."""

import json

import pytest
from facet_loopback import facet
from hawkes_dom import read_question
from test_graph_domain_range import dom, graph, line, ROOT
from ethnos.hawkes_host import handle

ASK = "Determine if the relation is a function. If it is not, identify two ordered pairs as proof."


@pytest.mark.parametrize(
    "instruction",
    [
        ASK,
        "Does the graph represent a function?",
        "Is this relation a function?",
    ],
)
def test_semantic_function_prompts_select_the_page_owned_graph_route(instruction):
    result = read_question(
        f'<div id="partInformation">{instruction}</div><input type="radio">'
    )
    assert result["evidence"]["graphQuestion"] == "function-test"
    assert result["evidence"]["graphDecision"] == "unavailable"

    js = dom()
    source = graph(line("3", "5", "-7"), ("2", "9", "3", "11"))
    js.eval(
        "window.questionPartViewModel="
        + json.dumps({"partDescription": instruction, "questionGraphHTML": source})
        + ";"
    )
    model = json.loads(
        js.eval((ROOT / "extension/content/hawkes-graph-model.js").read_text()).json()
    )
    assert model["graphQuestion"] == "function-test"
    assert model["graphDecision"] == "accepted"


@pytest.mark.parametrize(
    "instruction",
    [
        "Does the graph represent a linear equation?",
        "Is the function represented by the graph linear?",
        "Does this expression define a function?",
    ],
)
def test_nearby_prompts_do_not_claim_the_function_test_route(instruction):
    result = read_question(
        f'<div id="partInformation">{instruction}</div><input type="radio">'
    )
    assert result["evidence"]["graphQuestion"] == ""


def read_model(source):
    js = dom()
    js.eval(
        f"window.questionPartViewModel={{partDescription:{json.dumps(ASK)},questionGraphHTML:{json.dumps(source)}}};"
    )
    return json.loads(
        js.eval((ROOT / "extension/content/hawkes-graph-model.js").read_text()).json()
    )


@pytest.mark.parametrize("vertical", [False, True])
def test_function_prompt_uses_shared_line_reader_and_exact_bounds(vertical):
    result = read_question(
        f'<div id="partInformation">Step 2 of 2 {ASK}</div><div id="questionString"><math><mi>x</mi><mo>=</mo><mn>2</mn></math></div><input type="radio">'
    )
    assert result["evidence"]["graphQuestion"] == "function-test"
    model = read_model(
        graph(line("3", "0" if vertical else "5", "-7"), ("2", "9", "3", "11"))
    )
    assert model["graphDecision"] == "accepted", model
    assert model["graphRelation"]["bounds"] == ["2", "9", "3", "11"]
    assert model["graphRelation"]["ends"] == ["infinite", "infinite"]


def test_confirmed_graph_absence_leaves_finite_route_available():
    model = read_model("")
    assert (
        model["graphQuestion"] == ""
        and model["graphReason"] == "function-test-no-graph"
    )


@pytest.mark.parametrize("bad", ["missing-end", "two-lines", "curve"])
def test_ambiguous_geometry_never_becomes_equation_only(bad):
    src = line()
    if bad == "missing-end":
        src = src.replace("<extend>both</extend>", "")
    if bad == "two-lines":
        src += line("1", "2", "3")
    if bad == "curve":
        src = src.replace("<line>", "<parabola>").replace("</line>", "</parabola>")
    model = read_model(graph(src))
    assert (
        model["graphQuestion"] == "function-test"
        and model["graphDecision"] != "accepted"
    )


def ask(monkeypatch, vertical, proof=True):
    loop = facet(monkeypatch)
    g = {
        "kind": "linear",
        "points": [{"x": "2", "y": "3"}, {"x": "2" if vertical else "4", "y": "7"}],
        "ends": ["infinite", "infinite"],
        "bounds": ["-5", "8", "-7", "9"],
    }
    reply = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "continuous-function",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": ASK
                if proof
                else "Determine whether the relation is a function.",
                "graph_relation": g,
                "mathml": [
                    f"<math><mtext>{'x=2' if vertical else 'y=2x-1'}</mtext></math>"
                ],
                "answer_shape": {
                    "kind": "conditional" if proof else "option",
                    "choices": ["yes", "no"],
                    **({"conditional_choice": "no"} if proof else {}),
                },
            },
        }
    )
    assert not loop.prompts
    return reply


@pytest.mark.parametrize("vertical", [False, True])
@pytest.mark.parametrize("proof", [False, True])
def test_host_reuses_semantic_choice_and_proof_carrier(monkeypatch, vertical, proof):
    reply = ask(monkeypatch, vertical, proof)
    assert reply.status == "ready", reply
    assert reply.certainty.model_calls == 0
    if vertical and proof:
        assert reply.answer.form == "conditional-choice"
        assert reply.answer.conditional_choice.choice == "no"
        assert [(p.x, p.y) for p in reply.answer.conditional_choice.proof_pairs] == [
            ("2", "-7"),
            ("2", "-6"),
        ]
    else:
        assert reply.answer.form == "choice"
        assert reply.answer.keyboard_entry == ("no" if vertical else "yes")
        assert reply.answer.conditional_choice is None
