"""Counted intercepts through the real reader, runtime and conditional writer."""

import json
from pathlib import Path
import pytest
from facet_loopback import facet
from ethnos.hawkes_host import handle
from test_domain_range import context, describe

ROOT = Path(__file__).resolve().parents[1]
ASK = "Find the x-intercepts, if any. Express the intercept(s) as ordered pair(s)."


def ask(monkeypatch, equation):
    loop = facet(monkeypatch)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "counted-intercepts",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": ASK,
                "mathml": [f"<math><mtext>{equation}</mtext></math>"],
                "answer_shape": {"kind": "option", "choices": ["Two", "None", "One"]},
            },
        }
    )
    assert not loop.prompts
    assert response.status == "ready", response
    assert response.certainty.model_calls == 0
    return response


@pytest.mark.parametrize(
    ("equation", "count"), [("y=x^2-7", 2), ("f(x)=3x-2", 1), ("y=x^2+2", 0)]
)
def test_host_carries_count_and_exact_whole_pairs(monkeypatch, equation, count):
    response = ask(monkeypatch, equation)
    conditional = response.answer.conditional_choice
    assert conditional.choice == ("None", "One", "Two")[count]
    assert conditional.x_intercepts["count"] == count
    assert all(p["y"] == "0" for p in conditional.x_intercepts["points"])
    assert not response.answer.keyboard_entry and not response.answer.parts
    if count == 2:
        assert all("sqrt(7)" in p["x"] for p in conditional.x_intercepts["points"])


def reader(selected=2, reverse=False):
    js = context(
        ["<math><mo>(</mo></math>", ", <math><mo>(</mo></math>"],
        ["<math><mo>)</mo></math>"] * 2,
        reverse,
    )
    js.eval("const selected=" + json.dumps(selected) + ";")
    js.eval("""
      const radios=[['two-choice','Two',2,'second first'],['zero-choice','None',0,''],['one-choice','One',1,'first']].map(([id,label,count,owners])=>({id,name:'cardinality',checked:count===selected,disabled:false,
        getBoundingClientRect:()=>({width:40,height:20}),getAttribute:n=>n==='aria-label'?label:n==='aria-controls'?owners:'',closest:()=>null}));
      fields.forEach((f,i)=>f.getBoundingClientRect=()=>({width:selected!==null && i<selected?50:0,height:20}));
      const nodes={alpha:fields[0],beta:fields[1],first:{contains:f=>f===fields[0]},second:{contains:f=>f===fields[1]},...Object.fromEntries(radios.map(r=>[r.id,r]))};
      document.getElementById=id=>nodes[id]??null;
      document.querySelectorAll=s=>s.includes('input[type="radio"]')?radios:s.includes('input.qbaseCSS')?fields:[];
    """)
    return js


@pytest.mark.parametrize("selected", [None, 0, 1, 2])
@pytest.mark.parametrize("reverse", [False, True])
def test_reader_follows_semantic_choice_and_owners_without_focus(selected, reverse):
    editor = describe(reader(selected, reverse))
    assert editor["ok"], editor
    assert editor["countedCoordinates"]["selected"] == selected
    if selected:
        assert [r["fieldId"] for r in editor["conditionalProof"]["rows"]] == [
            "alpha",
            "beta",
        ][:selected]
        assert all(r["bracketed"] for r in editor["conditionalProof"]["rows"])
    else:
        assert editor["kind"] == "option"


@pytest.mark.parametrize(
    "fault", ["duplicate-owner", "wrong-count", "wrong-bracket", "duplicate-label"]
)
def test_reader_refuses_ambiguous_coordinate_ownership(fault):
    js = reader()
    if fault in {"duplicate-owner", "wrong-count"}:
        owners = "first first" if fault == "duplicate-owner" else "first"
        js.eval(
            f"radios[0].getAttribute=n=>n==='aria-label'?'Two':n==='aria-controls'?'{owners}':'';"
        )
    if fault == "wrong-bracket":
        js.eval("data[1].suffix=']';")
    if fault == "duplicate-label":
        js.eval("radios[1].getAttribute=n=>n==='aria-label'?'Two':'';")
    assert not describe(js)["ok"]


@pytest.mark.parametrize(
    ("equation", "count"), [("y=x^2-9", 2), ("y=x-4", 1), ("y=x^2+1", 0)]
)
@pytest.mark.parametrize("selected", [None, 0, 1, 2])
def test_real_reply_publishes_typed_count_on_every_choice_state(
    monkeypatch, equation, count, selected
):
    from test_hawkes_insertion_ownership import make_page, QUESTION_A

    reply = ask(monkeypatch, equation)
    editor = describe(reader(selected))
    fields = ["alpha", "beta"][:selected] if selected else []
    page = make_page()
    page.run(f"""state={{...blankState(),phase:'solving',windowId:1,tabId:11,frameId:0,
      fieldId:{json.dumps(chr(31).join(fields))},fieldIds:{json.dumps(fields)},fieldIdentity:'separated',
      editor:{json.dumps(editor)},answerChoices:['Two','None','One'],
      conditionalChoice:{json.dumps(("None", "One", "Two")[selected] if selected is not None else "")},
      signature:questionSignature({json.dumps(QUESTION_A)})}};
      acceptReply({reply.model_dump_json()});""")
    page.pump()
    assert page.json("state.phase") == "solved", page.json("__H.logged")
    assert page.json("state.answerXIntercepts.count") == count
    assert page.json("state.displayText").startswith(("None", "One", "Two")[count])
    if count == selected and count:
        assert page.json("state.answerParts") == (["-3,0", "3,0"] if count == 2 else [])
        if count == 1:
            assert page.json("state.entryText") == "4,0"
    else:
        assert page.json("state.answerParts") == []
        assert page.json("state.answer") == ("None", "One", "Two")[count]
    assert page.writes == []


def one_editor_surface():
    """The One branch, with the field identity Hawkes publishes live."""
    editor = describe(reader(1))
    editor["conditionalProof"]["rows"][0]["fieldId"] = "QBase1_input"
    return editor


def test_one_owned_coordinate_field_passes_the_real_prepare_gate():
    from test_hawkes_insertion_ownership import make_page, QUESTION_A

    editor = one_editor_surface()
    report = {
        "ready": True,
        "code": "focused-answer-field",
        "via": "revealed-option",
        "fieldId": "QBase1_input",
        "fieldIds": ["QBase1_input"],
        "fieldKind": "native",
        "choices": ["None", "One", "Two"],
        "conditionalChoice": "One",
    }
    page = make_page()
    page.run("settingsReady.then(() => { settings.autoSolve = false; });")
    page.pump()
    page.run("prepare(1);")
    page.pump()
    page.answer(report)
    page.answer(editor)
    page.answer(QUESTION_A)

    assert page.json("state.phase") == "ready", page.json("__H.logged")
    assert page.json("state.fieldIds") == ["QBase1_input"]
    assert page.json("state.editor.countedCoordinates.selected") == 1
    assert page.json("state.errorKey") == ""
    assert page.writes == []


def test_one_intercept_uses_the_existing_single_coordinate_writer(monkeypatch):
    from test_hawkes_insertion_ownership import make_page, QUESTION_A

    reply = ask(monkeypatch, "y=x-4")
    editor = one_editor_surface()
    fields = ["QBase1_input"]
    page = make_page()
    page.run(f"""state={{...blankState(),phase:'solving',windowId:1,tabId:11,frameId:0,
      fieldId:'QBase1_input',fieldKind:'native',fieldIds:{json.dumps(fields)},fieldIdentity:'',
      editor:{json.dumps(editor)},answerChoices:['None','One','Two'],conditionalChoice:'One',
      signature:questionSignature({json.dumps(QUESTION_A)})}};acceptReply({reply.model_dump_json()});""")
    page.pump()
    assert page.json("state.phase") == "solved", page.json("__H.logged")
    assert page.json("state.entryText") == "4,0"
    assert page.json("state.answerParts") == []

    page.run("insert();")
    page.pump()
    page.answer(editor)
    page.answer(QUESTION_A)
    page.answer(
        {
            "ok": True,
            "code": "entered",
            "entered": "4,0",
            "transport": "hawkes-dynamic-keypad",
            "timing": {
                "transport": "hawkes-dynamic-keypad",
                "notes": 3,
                "keypadWrites": 3,
                "nativeWrites": 0,
            },
        }
    )
    page.answer(QUESTION_A)

    assert len(page.writes) == 1, page.json("__H.logged")
    assert page.writes[0]["func"] == "enterPlan"
    assert page.writes[0]["args"][2] == []
    assert page.writes[0]["args"][3] == "hawkes-dynamic-keypad"
    assert len(page.writes[0]["args"][1]["score"]["offsets"]) == 3
    assert page.json("state.phase") == "inserted", page.json("__H.logged")
    assert page.json("state.placedText") == "One: (4,0)"


@pytest.mark.parametrize("changed", [False, True])
def test_counted_pairs_use_existing_writer_and_refuse_changed_choice(
    monkeypatch, changed
):
    from test_hawkes_insertion_ownership import make_page, QUESTION_A, PAIR_INSPECT

    reply = ask(monkeypatch, "y=x^2-9")
    editor = describe(reader(2))
    fields = ["QBase1_input", "QBase2_input"]
    for row, field in zip(editor["conditionalProof"]["rows"], fields):
        row["fieldId"] = field
    page = make_page()
    page.run(f"""state={{...blankState(),phase:'solving',windowId:1,tabId:11,frameId:0,
      fieldId:'QBase1_input\\u001fQBase2_input',fieldIds:{json.dumps(fields)},fieldIdentity:'separated',
      editor:{json.dumps(editor)},answerChoices:['Two','None','One'],conditionalChoice:'Two',
      signature:questionSignature({json.dumps(QUESTION_A)})}};acceptReply({reply.model_dump_json()});""")
    page.pump()
    assert page.json("state.phase") == "solved", page.json("__H.logged")
    page.run("insert();")
    page.pump()
    if changed:
        import copy

        altered = copy.deepcopy(editor)
        altered["countedCoordinates"]["selected"] = 1
        page.answer(altered)
        assert page.writes == []
        assert page.json("state.errorKey") == "errorQuestionChanged"
        return
    page.answer(editor)
    page.answer(QUESTION_A)
    page.answer(PAIR_INSPECT)
    assert len(page.writes) == 1, page.json("__H.logged")
    write = page.writes[0]
    assert write["func"] == "enterPlan"
    assert write["args"][2] == fields
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
            "entered": ["-30", "30"],
            "enteredFields": fields,
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


@pytest.mark.parametrize("equation", ["y=x^2-7", "y=x^2+x-1", "y=(3x-2)*(5x+1)"])
def test_exact_radical_and_rational_pairs_use_existing_templates(monkeypatch, equation):
    import re

    response = ask(monkeypatch, equation)
    value = response.answer.conditional_choice.x_intercepts
    js = pytest.importorskip("quickjs").Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js"):
        source = (ROOT / "extension/common" / name).read_text()
        js.eval(
            re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M).replace(
                "export ", ""
            )
        )
    editor = json.loads((ROOT / "docs/answer-capabilities.json").read_text())[
        "editors"
    ]["fraction-box"]["description"]
    editor["templates"]["radical"] = True
    editor["maxLength"] = 80
    editor["allowedCharacters"] += "+"
    editor["slots"]["base"] += "+"
    editor["slots"]["numerator"] += "+"
    for pair in value["points"]:
        entry = f"{pair['x']},0"
        result = json.loads(
            js.eval(
                f"JSON.stringify(planEntry({json.dumps(entry)},{json.dumps(editor)}))"
            )
        )
        assert result["ok"], result
    editor["templates"]["radical"] = False
    if "sqrt" in str(value):
        result = json.loads(
            js.eval(
                f"JSON.stringify(planEntry({json.dumps(entry)},{json.dumps(editor)}))"
            )
        )
        assert not result["ok"]
