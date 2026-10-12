"""Conditional ordered-pair proofs across the real runtime/host boundary."""

import json
from pathlib import Path
import pytest
from facet_loopback import facet
from ethnos.hawkes_host import handle

ROOT = Path(__file__).resolve().parents[1]
ASK = "Determine if the relation is a function. If it is not, identify two ordered pairs as proof."


def ask(monkeypatch, expression):
    loopback = facet(monkeypatch)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "function-proof",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": ASK,
                "mathml": [f"<math><mtext>{expression}</mtext></math>"],
                "answer_shape": {
                    "kind": "conditional",
                    "choices": ["yes", "no"],
                    "conditional_choice": "no",
                },
            },
        }
    )
    assert loopback.prompts == []
    return response


def test_host_preserves_pair_proof(monkeypatch):
    reply = ask(monkeypatch, "{(8,3),(2,4),(8,-7)}")
    assert reply.status == "ready", reply
    assert reply.certainty.model_calls == 0
    conditional = reply.answer.conditional_choice
    assert reply.answer.form == "conditional-choice"
    assert conditional.choice == "no"
    assert [(p.x, p.y) for p in conditional.proof_pairs] == [("8", "3"), ("8", "-7")]
    assert conditional.relation is None and not reply.answer.parts


def test_host_yes_has_no_proof(monkeypatch):
    reply = ask(monkeypatch, "{(8,3),(2,4),(8,3)}")
    assert reply.status == "ready" and reply.answer.keyboard_entry == "yes"
    assert reply.answer.conditional_choice is None


def test_js_accepts_atomic_pairs_and_rejects_wrong_proof():
    js = pytest.importorskip("quickjs").Context()
    source = (ROOT / "extension/background.js").read_text()
    js.eval(
        source[
            source.index("function conditionalPairProof(") : source.index(
                "function domainRangeParts("
            )
        ]
    )
    answer = {
        "form": "conditional-choice",
        "conditional_choice": {
            "choice": "no",
            "proof_pairs": [{"x": "8", "y": "3"}, {"x": "8", "y": "-7"}],
        },
    }

    def call(editor, fields):
        return json.loads(
            js.eval(
                f'JSON.stringify(conditionalPairProof({json.dumps(answer)},{json.dumps(editor)},{json.dumps(fields)},["yes","no"],"no"))'
            )
        )

    assert call({"kind": "option"}, [])["parts"] == []
    editor = {
        "kind": "multi",
        "conditionalProof": {
            "choice": "no",
            "rows": [
                {"fieldId": "z", "bracketed": False},
                {"fieldId": "a", "bracketed": True},
            ],
        },
    }
    assert call(editor, ["z", "a"])["parts"] == ["(8,3)", "8,-7"]
    assert call(editor, ["a", "z"]) is None
    answer["conditional_choice"]["proof_pairs"][1]["x"] = "9"
    assert call(editor, ["z", "a"]) is None


@pytest.mark.parametrize("reverse", [False, True])
def test_conditional_models_follow_radio_ownership_not_collection_order(reverse):
    from test_domain_range import context

    js = context(["", ""], ["", ""], reverse)
    js.eval("""
      const yes = {id:'yes-choice',name:'decision',checked:false, disabled:false,
        getBoundingClientRect:()=>({width:40,height:20}),
        getAttribute:name=>name==='aria-label'?'Yes':'', closest:()=>null};
      const no = {id:'no-choice',name:'decision',checked:true, disabled:false,
        getBoundingClientRect:()=>({width:40,height:20}),
        getAttribute:name=>name==='aria-label'?'No':name==='aria-controls'?'second first':'', closest:()=>null};
      const nodes = {'yes-choice':yes,'no-choice':no, alpha:fields[0], beta:fields[1],
        first:{contains:field=>field===fields[0]}, second:{contains:field=>field===fields[1]}};
      document.getElementById=id=>nodes[id]??null;
      document.querySelectorAll=selector=>selector.includes('input[type="radio"]')?[no,yes]
        :selector.includes('input.qbaseCSS')?fields:[];
    """)
    editor = json.loads(
        js.eval((ROOT / "extension/content/hawkes-describe.js").read_text()).json()
    )
    assert editor["kind"] == "multi"
    assert editor["conditionalProof"]["choice"] == "No"
    assert [
        (r["ownerId"], r["fieldId"]) for r in editor["conditionalProof"]["rows"]
    ] == [("first", "alpha"), ("second", "beta")]
    js.eval(
        "no.getAttribute=name=>name==='aria-label'?'No':name==='aria-controls'?'first first':'';"
    )
    assert not json.loads(
        js.eval((ROOT / "extension/content/hawkes-describe.js").read_text()).json()
    )["ok"]


@pytest.mark.parametrize("revealed", [False, True])
@pytest.mark.parametrize("continuous", [False, True])
def test_actual_reply_publishes_choice_and_whole_pair_parts(
    monkeypatch, revealed, continuous
):
    from test_hawkes_insertion_ownership import (
        make_page,
        QUESTION_A,
        STRUCTURED_PAIR_EDITOR,
    )

    if continuous:
        from test_continuous_function import ask as ask_continuous

        reply = ask_continuous(monkeypatch, vertical=True)
    else:
        reply = ask(monkeypatch, "{(8,3),(2,4),(8,-7)}")
    pairs = [p.model_dump() for p in reply.answer.conditional_choice.proof_pairs]
    entries = [f"({p['x']},{p['y']})" for p in pairs]
    page = make_page()
    editor = (
        json.loads(json.dumps(STRUCTURED_PAIR_EDITOR))
        if revealed
        else {"ok": True, "kind": "option"}
    )
    if revealed:
        for one in editor["editors"]:
            one["allowedCharacters"] += ","
            one["slots"]["base"] += ","
            one["templates"]["parentheses"] = True
        editor["conditionalProof"] = {
            "choice": "no",
            "group": "decision",
            "optionId": "no-choice",
            "rows": [
                {"fieldId": "QBase1_input", "ownerId": "first", "bracketed": False},
                {"fieldId": "QBase2_input", "ownerId": "second", "bracketed": False},
            ],
        }
    page.run(f"""state={{...blankState(),phase:'solving',windowId:1,tabId:11,frameId:0,
        fieldId:'QBase1_input\\u001fQBase2_input',fieldIds:['QBase1_input','QBase2_input'],
        fieldIdentity:'separated',editor:{json.dumps(editor)},answerChoices:['yes','no'],conditionalChoice:'no',
        signature:questionSignature({json.dumps(QUESTION_A)})}};
        acceptReply({reply.model_dump_json()});""")
    page.pump()
    assert page.json("state.phase") == "solved", page.json("__H.logged")
    assert page.json("state.answerProofPairs") == pairs
    assert page.json("state.answerParts") == (entries if revealed else [])
    assert page.json("state.displayText") == "no: " + " and ".join(entries)
    if revealed:
        from test_hawkes_insertion_ownership import PAIR_INSPECT

        page.run("insert();")
        page.pump()
        page.answer(editor)
        page.answer(QUESTION_A)
        page.answer(PAIR_INSPECT)
        assert len(page.writes) == 1, page.json("__H.logged")
        write = page.writes[0]
        assert write["func"] == "enterPlan"
        assert write["args"][2] == ["QBase1_input", "QBase2_input"]
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
                "entered": [p["x"] + p["y"] for p in pairs],
                "enteredFields": ["QBase1_input", "QBase2_input"],
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
    else:
        assert page.writes == []
