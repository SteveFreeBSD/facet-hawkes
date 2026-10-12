"""Graph model geometry, labeled alternatives, and actual answer publication."""

import json
from pathlib import Path
import pytest
from facet_loopback import facet
from ethnos.hawkes_host import handle
from hawkes_dom import SHIM, _Tree, _place, _strip

ROOT = Path(__file__).resolve().parents[1]
ASK = "Determine the domain and range of the graph."


def dom(markup=""):
    js = pytest.importorskip("quickjs").Context()

    def parse(s):
        t = _Tree()
        t.feed(s)
        _place(t.root)
        return json.dumps(_strip(t.root))

    js.add_callable("__parse", parse)
    js.eval(SHIM)
    js.eval("""globalThis.DOMParser=class {parseFromString(s) {const root=new DomNode(JSON.parse(__parse(s)),null);root.body=root;return root;}};
      DomNode.prototype.getAttribute=function(k){return this.attributes[k]??null;};
      Object.defineProperty(DomNode.prototype,'tabIndex',{get(){return Number(this.getAttribute('tabindex')??0)}});
      Object.defineProperty(DomNode.prototype,'name',{get(){return this.getAttribute('name')??''}});
      Object.defineProperty(DomNode.prototype,'type',{get(){return this.getAttribute('type')??''}});
      globalThis.window={};""")
    js.eval(f"buildDocument(JSON.parse(__parse({json.dumps(markup)})));")
    return js


def graph(line, grid=("-9", "9", "-8", "8")):
    return (
        "<graph><isqagraph>true</isqagraph><grid><type>cartesian</type><cartesian>"
        + "".join(
            f"<{k}>{v}</{k}>"
            for k, v in zip(
                ("xmin", "xmax", "ymin", "ymax", "xinterval", "yinterval"),
                (*grid, "1", "1"),
            )
        )
        + f"</cartesian></grid><graphobjects>{line}</graphobjects></graph>"
    )


def line(a="2", b="3", c="7", extend="both"):
    return f"<line><type>line</type><visible>true</visible><definedby>equation</definedby><extend>{extend}</extend><equation><a>{a}</a><b>{b}</b><c>{c}</c></equation></line>"


def read_graph(source):
    js = dom()
    js.eval(
        f"window.questionPartViewModel={{partDescription:{json.dumps(ASK)},questionGraphHTML:{json.dumps(source)}}};"
    )
    return json.loads(
        js.eval((ROOT / "extension/content/hawkes-graph-model.js").read_text()).json()
    )


@pytest.mark.parametrize(
    ("a", "b", "c", "expected"),
    [
        ("2", "3", "7", [{"x": "0", "y": "-7/3"}, {"x": "1", "y": "-3"}]),
        ("0", "3", "-2", [{"x": "0", "y": "2/3"}, {"x": "1", "y": "2/3"}]),
        ("4", "0", "-7", [{"x": "7/4", "y": "0"}, {"x": "7/4", "y": "1"}]),
    ],
)
def test_equation_geometry_exact_and_viewport_independent(a, b, c, expected):
    for grid in (("-9", "9", "-8", "8"), ("-50", "20", "-30", "40")):
        result = read_graph(graph(line(a, b, c), grid))
        assert result["graphDecision"] == "accepted", result
        assert result["graphRelation"] == {
            "kind": "linear",
            "points": expected,
            "ends": ["infinite", "infinite"],
        }


def point(x, y, kind="endpoint", style="closed"):
    return f"<point><type>{kind}</type><x>{x}</x><y>{y}</y><coordinatestype>cartesian</coordinatestype><visible>true</visible><displaystyle>{style}</displaystyle></point>"


@pytest.mark.parametrize(
    ("types", "extend", "ends"),
    [
        (("endpoint", "endpoint"), "neither", ["open", "closed"]),
        (("point", "endpoint"), "negative", ["infinite", "closed"]),
        (("endpoint", "point"), "positive", ["open", "infinite"]),
        (("point", "point"), "both", ["infinite", "infinite"]),
    ],
)
def test_endpoints_and_arrows_survive_reordered_points(types, extend, ends):
    points = [
        point("-2", "3", types[0], "open" if types[0] == "endpoint" else "closed"),
        point("4", "-7", types[1]),
    ]
    for ordered in (points, points[::-1]):
        source = f"<line><type>line</type><visible>true</visible><definedby>twopoint</definedby><extend>{extend}</extend>{''.join(ordered)}</line>"
        result = read_graph(graph(source))
        assert result["graphDecision"] == "accepted", result
        assert result["graphRelation"]["ends"] == ends
        assert result["graphRelation"]["points"][0] == {"x": "-2", "y": "3"}


@pytest.mark.parametrize(
    "source",
    [
        line() + line(),
        line("0", "0"),
        line(extend="neither"),
        line().replace("</line>", "<domain/></line>"),
        "<curve><visible>true</visible></curve>",
        line().replace("<extend>both</extend>", ""),
    ],
)
def test_ambiguous_geometry_is_terminal(source):
    result = read_graph(graph(source))
    assert (
        result["graphQuestion"] == "domain-range"
        and result["graphDecision"] == "ambiguous"
    )
    assert "graphRelation" not in result


def test_real_host_preserves_named_typed_projections(monkeypatch):
    loopback = facet(monkeypatch)
    response = handle(
        {
            "operation": "solve_hawkes_problem",
            "request_id": "projections",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": ASK,
                "graph_relation": {
                    "kind": "linear",
                    "points": [{"x": "-2", "y": "3/4"}, {"x": "5", "y": "3/4"}],
                    "ends": ["infinite", "infinite"],
                },
                "answer_shape": {"kind": "multi", "count": 2},
            },
        }
    )
    assert response.status == "ready", response
    assert response.certainty.model_calls == 0 and not loopback.prompts
    assert response.answer.graph_domain_range == {
        "domain": {"kind": "all-real-numbers"},
        "range": {"kind": "singleton", "value": "3/4"},
    }


def surface(reverse=False, labels=("Range", "Domain")):
    markup = "".join(
        f'<fieldset><legend>{role}</legend><span id="owner{i}"><input class="qbaseCSS" id="field{i}"></span><input type="radio" class="opt" id="choice{i}" name="group{i}" aria-controls="owner{i}" aria-labelledby="label{i}"><label id="label{i}">All real numbers</label></fieldset>'
        for i, role in enumerate(labels)
    )
    js = dom(markup)
    js.eval("""const fields=[0,1].map(i=>document.getElementById('field'+i));
      const cs=[],ds=[];
      for(let i=0;i<2;i++) {
        cs.push({Type:'QDyText',enabled:true,qdyBase_AllowedChar:'0123456789-,∞',qdyBase_AllowedTemplates:['PBrace','SBrace','SPBrace','PSBrace','CBrace'],
          arrChildObjects:[{Type:'Base',objMyDiv:{querySelector:()=>fields[i]},arrChildObjects:[]}]});
        ds.push({Name:'value'+i,isQDy:true,enableState:true,prefix:'',suffix:''});
        cs.push({}); ds.push({Name:'group'+i,isOpt:true,enableState:true});
      }
      window.quant_wp_UI={focusedElementIndex:-1,controlsCollection:cs,controlsCollectionData:ds};""")
    if reverse:
        js.eval("cs.reverse();ds.reverse();")
    editor = json.loads(
        js.eval((ROOT / "extension/content/hawkes-describe.js").read_text()).json()
    )
    return js, editor


@pytest.mark.parametrize("reverse", [False, True])
def test_fieldset_roles_and_explicit_alternatives_override_model_order(reverse):
    js, e = surface(reverse)
    assert e["ok"], e
    assert [r["role"] for r in e["graphDomainRangeRows"]] == ["range", "domain"]
    assert [r["fieldId"] for r in e["graphDomainRangeRows"]] == ["field0", "field1"]
    assert e["editors"][0]["name"] == "value0"


def test_duplicate_roles_refuse_surface():
    _, e = surface(labels=("Domain", "Domain"))
    assert not e["ok"]


def test_publish_and_insert_semantic_choices_without_typing_them():
    from test_hawkes_insertion_ownership import make_page, QUESTION_A

    _, editor = surface()
    page = make_page()
    page.own_window_a()
    page.run(
        f'state={{...state,phase:"solving",editor:{json.dumps(editor)},fieldIds:["field0","field1"],fieldId:"field0\\u001ffield1",answerChoices:[],conditionalChoice:""}};'
    )
    reply = {
        "status": "ready",
        "problem_text": ASK,
        "answer": {
            "form": "graph-domain-range",
            "graph_domain_range": {
                "domain": {"kind": "all-real-numbers"},
                "range": {"kind": "all-real-numbers"},
            },
        },
        "certainty": {
            "answered_by": "exact",
            "facet_invoked": True,
            "model_calls": 0,
            "source": "Facet Exact",
            "insertable": True,
        },
    }
    page.run(f"acceptReply({json.dumps(reply)});")
    page.pump()
    assert (
        page.json("state.answer") == "Range: All real numbers; Domain: All real numbers"
    )
    assert page.json("state.answerParts") == []
    assert page.json("state.errorKey") == ""
    page.run("insert();")
    page.pump()
    page.answer(editor)
    page.answer(QUESTION_A)
    page.answer(
        {"ok": True, "code": "axis-options-settled", "selected": 2, "events": 2}
    )
    page.answer({"ok": True, "code": "axis-options-settled", "selected": 2})
    page.answer(QUESTION_A)
    assert not any(w["func"] == "enterPlan" for w in page.writes)
    assert (
        len([w for w in page.json("__H.calls") if w["func"] == "selectAxisAbsences"])
        == 2
    ), json.dumps(page.json("__H.logged"))
    inserted = page.said("inserted")[-1]["data"]
    assert inserted["characterWrites"] == 0
    assert inserted["structuralActions"] == 2


@pytest.mark.parametrize("mixed", [False, True])
def test_value_plans_keep_interval_and_singleton_structure(mixed):
    from test_hawkes_insertion_ownership import make_page, QUESTION_A

    _, editor = surface()
    page = make_page()
    page.own_window_a()
    parts = {
        "domain": {"kind": "all-real-numbers"}
        if mixed
        else {"kind": "singleton", "value": "4"},
        "range": {
            "kind": "interval",
            "lower": "-3",
            "upper": None,
            "lower_closed": True,
            "upper_closed": False,
        },
    }
    page.run(
        f'state={{...state,phase:"solving",editor:{json.dumps(editor)},fieldIds:["field0","field1"],fieldId:"field0\\u001ffield1",answerChoices:[]}};'
    )
    reply = {
        "status": "ready",
        "answer": {"form": "graph-domain-range", "graph_domain_range": parts},
        "certainty": {
            "model_calls": 0,
            "answered_by": "exact",
            "facet_invoked": True,
            "insertable": True,
        },
    }
    page.run(f"acceptReply({json.dumps(reply)});")
    page.pump()
    assert page.json("state.phase") == "solved"
    page.run("insert();")
    page.pump()
    page.answer(editor)
    page.answer(QUESTION_A)
    page.answer({"ok": True, "selected": int(mixed), "events": int(mixed)})
    writes = page.writes
    assert len(writes) == 1, json.dumps(page.json("__H.logged"))
    assert writes[0]["func"] == "enterPlan"
    assert writes[0]["args"][2] == (["field0"] if mixed else ["field0", "field1"])
    assert writes[0]["args"][3] == "hawkes-dynamic-keypad"
    typed = sum(
        len(step.get("text", ""))
        for plan in writes[0]["args"][0]
        for step in plan
        if step["op"] == "type"
    )
    assert len(writes[0]["args"][1]["score"]["offsets"]) == typed
    assert writes[0]["args"][0][0][0] == {"op": "template", "name": "SPBrace"}
    if not mixed:
        assert writes[0]["args"][0][1][0] == {"op": "template", "name": "CBrace"}
    ids = writes[0]["args"][2]
    page.answer(
        {
            "ok": True,
            "code": "entered-fields",
            "enteredFields": ids,
            "completed": len(ids),
            "timing": {
                "transport": "hawkes-dynamic-keypad",
                "notes": typed,
                "keypadWrites": typed,
                "nativeWrites": 0,
            },
        }
    )
    page.answer({"ok": True, "selected": int(mixed)})
    page.answer(QUESTION_A)
    inserted = page.said("inserted")[-1]["data"]
    assert inserted["characterTransport"] == "hawkes-dynamic-keypad"
    assert inserted["characterWrites"] == typed
    assert inserted["structuralActions"] == int(mixed)


def test_one_value_plain_surface_uses_owned_field_writer_with_shared_cadence():
    """A conditional row count does not turn a plain field into a keypad target."""
    from test_hawkes_insertion_ownership import make_page, QUESTION_A

    _, editor = surface()
    editor["editors"] = [
        {
            "ok": True,
            "kind": "textbox",
            "enabled": True,
            "allowedCharacters": "[0-9,()\\[\\]∞-]",
            "maxLength": 40,
            "templates": {},
        }
        for _ in editor["editors"]
    ]
    parts = {
        "domain": {"kind": "all-real-numbers"},
        "range": {
            "kind": "interval",
            "lower": "-3",
            "upper": None,
            "lower_closed": True,
            "upper_closed": False,
        },
    }
    page = make_page()
    page.own_window_a()
    page.run(
        f'state={{...state,phase:"solving",editor:{json.dumps(editor)},fieldIds:["field0","field1"],fieldId:"field0\\u001ffield1",answerChoices:[]}};'
    )
    page.run(
        "acceptReply("
        + json.dumps(
            {
                "status": "ready",
                "answer": {
                    "form": "graph-domain-range",
                    "graph_domain_range": parts,
                },
                "certainty": {
                    "model_calls": 0,
                    "answered_by": "exact",
                    "facet_invoked": True,
                    "insertable": True,
                },
            }
        )
        + ");"
    )
    page.pump()
    page.run("insert();")
    page.pump()
    page.answer(editor)
    page.answer(QUESTION_A)
    page.answer({"ok": True, "selected": 1, "events": 1})

    assert len(page.writes) == 1, page.json("__H.logged")
    write = page.writes[0]
    assert write["func"] == "enterOwnedFields"
    assert write["world"] == "MAIN"
    assert write["args"][0] == ["[-3,∞)"]
    assert write["args"][1] == ["field0"]
    assert write["args"][3] == "fields"
    assert len(write["args"][2]["score"]["offsets"]) == len("[-3,∞)")
    page.answer(
        {
            "ok": True,
            "code": "entered-answer-fields",
            "fields": ["field0"],
            "settled": 1,
            "timing": {
                "transport": "hawkes-plain-fields",
                "notes": len("[-3,∞)"),
                "keypadWrites": 0,
                "nativeWrites": len("[-3,∞)"),
            },
        }
    )
    page.answer({"ok": True, "selected": 1})
    page.answer(QUESTION_A)
    inserted = page.said("inserted")[-1]["data"]
    assert inserted["characterTransport"] == "hawkes-plain-fields"
    assert inserted["characterWrites"] == len("[-3,∞)")
    assert inserted["structuralActions"] == 1


@pytest.mark.parametrize("fault", ["label", "owner", "duplicate", "group", "role"])
def test_actual_choice_writer_preflights_both_rows_before_any_click(fault):
    js, editor = surface()
    js.eval("""globalThis.HTMLInputElement=DomNode;window.location={origin:'https://learn.hawkeslearning.com'};
      globalThis.MouseEvent=class{constructor(type){this.type=type;}};
      globalThis.setTimeout=(fn)=>fn(); globalThis.clicked=[];
      DomNode.prototype.getClientRects=function(){return [this.getBoundingClientRect()]};
      DomNode.prototype.dispatchEvent=function(e){clicked.push(this.id);this.checked=!this.checked;};
      for(const el of document.querySelectorAll('input')) {el.checked=false;el.value='';el.classList.contains=el.classList.includes;}
    """)
    rows = editor["graphDomainRangeRows"]
    if fault == "label":
        js.eval(
            "document.getElementById('label1').childNodes[0].data='Something else';"
        )
    if fault == "owner":
        rows[1]["ownerId"] = "owner0"
    if fault == "duplicate":
        rows[1]["optionId"] = rows[0]["optionId"]
    if fault == "group":
        rows[1]["group"] = rows[0]["group"]
    if fault == "role":
        rows[1]["role"] = rows[0]["role"]
    js.eval(
        (ROOT / "extension/common/axis-actions.js").read_text().replace("export ", "")
    )
    js.eval(
        f'selectAxisAbsences({json.dumps(rows)},{{domain:{{kind:"all-real-numbers"}},range:{{kind:"all-real-numbers"}}}},"graph-domain-range").then(r=>globalThis.outcome=r);'
    )
    while js.execute_pending_job():
        pass
    assert json.loads(js.eval("JSON.stringify(outcome)"))["ok"] is False
    assert js.eval("clicked.length") == 0


def test_actual_choice_writer_selects_only_the_named_row_choices():
    js, editor = surface(True)
    js.eval("""globalThis.HTMLInputElement=DomNode;window.location={origin:'https://learn.hawkeslearning.com'};
      globalThis.MouseEvent=class{constructor(type){this.type=type;}};globalThis.setTimeout=(fn)=>fn();globalThis.clicked=[];
      DomNode.prototype.getClientRects=function(){return [this.getBoundingClientRect()]};
      DomNode.prototype.dispatchEvent=function(e){clicked.push(this.id);this.checked=!this.checked;};
      for(const el of document.querySelectorAll('input')) {el.checked=false;el.value='';el.classList.contains=el.classList.includes;}
    """)
    js.eval(
        (ROOT / "extension/common/axis-actions.js").read_text().replace("export ", "")
    )
    js.eval(
        f'selectAxisAbsences({json.dumps(editor["graphDomainRangeRows"])},{{domain:{{kind:"all-real-numbers"}},range:{{kind:"singleton",value:"4"}}}},"graph-domain-range").then(r=>globalThis.outcome=r);'
    )
    while js.execute_pending_job():
        pass
    assert json.loads(js.eval("JSON.stringify(outcome)"))["ok"]
    assert json.loads(js.eval("JSON.stringify(clicked)")) == ["choice1"]
