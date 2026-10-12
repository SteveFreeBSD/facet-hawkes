"""Named finite sets through the actual host, page probe, and semantic adapter."""

import json
from pathlib import Path

import pytest
from facet_loopback import facet

from ethnos.hawkes_host import handle

ROOT = Path(__file__).resolve().parents[1]


def test_host_keeps_named_sets_without_model(monkeypatch):
    loopback = facet(monkeypatch)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "sets",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": "Determine the domain and range for the relation.",
                "mathml": ["<math><mtext>S={(7,-3),(7,4),(-2,4)}</mtext></math>"],
                "answer_shape": {"kind": "multi", "count": 2},
            },
        }
    )
    assert response.status == "ready", response
    assert loopback.prompts == []
    assert response.certainty.model_calls == 0
    assert response.answer.form == "domain-range"
    assert response.answer.domain_range == {"domain": ["-2", "7"], "range": ["-3", "4"]}
    assert response.answer.parts == []


def graph_evidence_problem(question):
    quickjs = pytest.importorskip("quickjs")
    source = (ROOT / "extension/background.js").read_text()
    start = source.index("function graphEvidenceProblem(")
    end = source.index("\n}\n", start) + 2
    js = quickjs.Context()
    js.eval(source[start:end])
    return js.eval(f"graphEvidenceProblem({json.dumps(question)})")


@pytest.mark.parametrize("graph_question", ["domain-range", "function-test"])
@pytest.mark.parametrize("decision", ["unavailable", "ambiguous"])
def test_listed_finite_relation_does_not_require_graph_model_verification(
    graph_question, decision
):
    question = {
        "evidence": {
            "graphQuestion": graph_question,
            "graphDecision": decision,
            "listedFiniteRelation": True,
        }
    }
    assert graph_evidence_problem(question) == ""


@pytest.mark.parametrize("graph_question", ["domain-range", "function-test"])
def test_accepted_continuous_graph_conflicting_with_finite_relation_fails_closed(
    graph_question,
):
    question = {
        "evidence": {
            "graphQuestion": graph_question,
            "graphDecision": "accepted",
            "listedFiniteRelation": True,
        },
        "graphRelation": {"kind": "linear", "topology": "line"},
    }
    assert graph_evidence_problem(question) == "finite-relation-graph-conflict"


def test_continuous_domain_range_still_requires_verified_graph_evidence():
    question = {
        "evidence": {
            "graphQuestion": "domain-range",
            "graphDecision": "ambiguous",
            "listedFiniteRelation": False,
        }
    }
    assert graph_evidence_problem(question) == "graph-facts-unverified"


def context(prefixes, suffixes, reverse=False):
    js = pytest.importorskip("quickjs").Context()
    js.eval(
        "const prefixes="
        + json.dumps(prefixes)
        + "; const suffixes="
        + json.dumps(suffixes)
        + ";"
    )
    js.eval("""
      const fields = ["alpha", "beta"].map(id => ({id, tabIndex: 0,
        getBoundingClientRect: () => ({width: 50, height: 20})}));
      const controls = fields.map(field => ({Type: "QDyText", enabled: true,
        qdyBase_AllowedChar: "0123456789-,", qdyBaseMaxChars: 50,
        arrChildObjects: [{Type: "Base", objMyDiv: {querySelector: () => field}, arrChildObjects: []}]}));
      const data = fields.map((_, i) => ({Name: "set", isQDy: true, enableState: true,
        prefix: prefixes[i], suffix: suffixes[i]}));
      globalThis.window = {quant_wp_UI: {focusedElementIndex: -1,
        controlsCollection: controls, controlsCollectionData: data}};
      globalThis.document = {querySelectorAll: selector => selector.includes('input.qbaseCSS') ? fields : [],
        getElementById: () => null, querySelector: () => null};
    """)
    if reverse:
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
            source.index("function domainRangeParts(") : source.index(
                "function answerForSurface("
            )
        ]
    )
    answer = {
        "form": "domain-range",
        "domain_range": {"domain": ["-2", "7"], "range": ["-3", "4"]},
        **changes,
    }
    return json.loads(
        js.eval(
            f"JSON.stringify(domainRangeParts({json.dumps(answer)}, {json.dumps(editor)}, ['alpha','beta']))"
        )
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("braces", [False, True])
def test_labels_and_owner_ids_override_both_orders(reverse, braces):
    prefixes = ["Range:", "Domain:"]
    if braces:
        prefixes = [p + '<math><mo stretchy="false">{</mo></math>' for p in prefixes]
    js = context(prefixes, ["<math><mo>}</mo></math>" if braces else ""] * 2, reverse)
    editor = describe(js)
    assert editor["ok"] is True
    assert [row["role"] for row in editor["domainRangeRows"]] == ["range", "domain"]
    assert adapt(js, editor) == (["-3,4", "-2,7"] if braces else ["{-3,4}", "{-2,7}"])


@pytest.mark.parametrize(
    ("prefixes", "suffixes"),
    [
        (["Domain:{", "Domain:{"], ["}", "}"]),
        (["Domain:{", "Range:"], ["}", "}"]),
        (["Domain:{", "Answer:{"], ["}", "}"]),
        (["Domain:{", "Domain and Range:{"], ["}", "}"]),
        (["First:", "Second:"], ["", ""]),
    ],
)
def test_ambiguous_surfaces_never_adapt(prefixes, suffixes):
    js = context(prefixes, suffixes)
    assert adapt(js, describe(js)) is None


def test_ambiguous_payloads_and_changed_mapping_refuse():
    js = context(["Domain:{", "Range:{"], ["}", "}"])
    editor = describe(js)
    assert adapt(js, editor, form="parts") is None
    assert adapt(js, editor, parts=["7", "4"]) is None
    assert (
        adapt(js, editor, domain_range={"domain": ["1", "1"], "range": ["2"]}) is None
    )
    editor["domainRangeRows"].reverse()
    assert adapt(js, editor) is None


def test_published_sets_keep_semantic_labels_and_gate_insertion():
    from test_hawkes_insertion_ownership import EDITOR_OK, QUESTION_A, make_page

    page = make_page()
    page.own_window_a()
    rows = [
        {"fieldId": "alpha", "role": "range", "braces": True},
        {"fieldId": "beta", "role": "domain", "braces": True},
    ]
    value_editor = {
        **EDITOR_OK,
        "allowedCharacters": "0123456789-,",
        "slots": {"base": "0123456789-,"},
    }
    editor = {
        "ok": True,
        "kind": "multi",
        "editors": [value_editor, value_editor],
        "domainRangeRows": rows,
    }
    page.run(f"""state = {{...state, fieldIds: ["alpha","beta"], fieldId: "alpha\\u001fbeta",
      editor: {json.dumps(editor)}, entryText: "", answerParts: ["-3,4","-2,7"],
      answer: "Range: {{-3,4}}; Domain: {{-2,7}}", displayText: "Range: {{-3,4}}; Domain: {{-2,7}}"}};
      update({{}});""")
    page.pump()
    assert page.json("state.phase") == "solved"
    page.run("insert();")
    page.pump()
    changed = json.loads(json.dumps(editor))
    changed["domainRangeRows"][0]["role"] = "domain"
    changed["domainRangeRows"][1]["role"] = "range"
    page.answer(changed)
    page.answer(QUESTION_A)
    assert page.writes == []
    assert page.json("state.errorKey") == "errorQuestionChanged"


def test_finite_sets_use_dynamic_keypad_and_one_shared_cadence_score():
    from test_hawkes_insertion_ownership import EDITOR_OK, QUESTION_A, make_page

    rows = [
        {"fieldId": "alpha", "role": "range", "braces": True},
        {"fieldId": "beta", "role": "domain", "braces": True},
    ]
    value_editor = {
        **EDITOR_OK,
        "allowedCharacters": "0123456789-,",
        "slots": {"base": "0123456789-,"},
    }
    editor = {
        "ok": True,
        "kind": "multi",
        "editors": [value_editor, value_editor],
        "domainRangeRows": rows,
    }
    reply = {
        "status": "ready",
        "answer": {
            "form": "domain-range",
            "domain_range": {"domain": ["-2", "7"], "range": ["-3", "4"]},
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
    assert len(page.writes) == 1, page.json("__H.logged")
    write = page.writes[0]
    assert write["func"] == "enterPlan"
    assert write["args"][2] == ["alpha", "beta"]
    assert write["args"][3] == "hawkes-dynamic-keypad"
    typed = sum(
        len(step.get("text", ""))
        for plan in write["args"][0]
        for step in plan
        if step["op"] == "type"
    )
    assert len(write["args"][1]["score"]["offsets"]) == typed
    page.answer(
        {
            "ok": True,
            "code": "entered-fields",
            "enteredFields": ["alpha", "beta"],
            "completed": 2,
            "timing": {
                "transport": "hawkes-dynamic-keypad",
                "notes": typed,
                "keypadWrites": typed,
                "nativeWrites": 0,
            },
        }
    )
    page.answer(QUESTION_A)
    assert page.json("state.phase") == "inserted", page.json("__H.logged")


def test_set_plans_preserve_fraction_boundaries_and_literal_braces():
    import re

    js = pytest.importorskip("quickjs").Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js"):
        source = (ROOT / "extension/common" / name).read_text()
        js.eval(
            re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M).replace(
                "export ", ""
            )
        )
    editor = {
        "kind": "dynamic",
        "allowedCharacters": "0123456789-,{}",
        "slots": {
            "base": "0123456789-,{}",
            "numerator": "0123456789-",
            "denominator": "0123456789",
        },
        "templates": {"fraction": True},
        "limits": {"fractions": 2},
    }
    result = json.loads(
        js.eval(f'JSON.stringify(planEntry("{{-2/5,7/3}}", {json.dumps(editor)}))')
    )
    assert result["ok"]
    steps = result["steps"]
    assert steps[0] == {"op": "type", "text": "{"}
    assert steps[-2:] == [{"op": "base"}, {"op": "type", "text": "}"}]
    assert steps.count({"op": "template", "name": "Fraction"}) == 2
    comma = steps.index({"op": "type", "text": ","})
    assert steps[comma - 1] == {"op": "base"}
    editor["limits"]["fractions"] = 1
    assert (
        json.loads(
            js.eval(f'JSON.stringify(planEntry("-2/5,7/3", {json.dumps(editor)}))')
        )["ok"]
        is False
    )
    assert js.eval('validateAnswer("{alert(1)}").ok') is False
