"""The mixed coordinate/absence answer surface used by axis intercepts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


DOM = r"""
class Element {
  constructor(id, top, left, text = "") {
    this.id = id; this.top = top; this.left = left; this.textContent = text;
    this.disabled = false; this.readOnly = false; this.value = "";
  }
  getBoundingClientRect() {
    return {top: this.top, bottom: this.top + 20, left: this.left,
            right: this.left + 50, width: 50, height: 20};
  }
  getAttribute(name) {
    if (name === "aria-label") return this.ariaLabel || "";
    if (name === "aria-labelledby") return this.ariaLabelledby || "";
    return "";
  }
  matches(selector) { return selector.indexOf("input") >= 0; }
  closest() { return null; }
}
class HTMLInputElement extends Element {
  constructor(id, top, left, type = "text") {
    super(id, top, left); this.type = type; this.checked = false;
    this.classList = {contains: name => name === "opt" && type === "radio"};
  }
  dispatchEvent(event) {
    if (this.type === "radio" && event.type === "click") this.checked = true;
    return true;
  }
}
class HTMLTextAreaElement extends Element {}
class HTMLIFrameElement extends Element {}
class HTMLFrameElement extends Element {}
class MouseEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class InputEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class KeyboardEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class Event { constructor(type, options) { this.type = type; Object.assign(this, options); } }

var fields = [
  new HTMLInputElement("PracticeTxt11_num", 120, 160),
  new HTMLInputElement("PracticeTxt12_num", 120, 240),
  new HTMLInputElement("PracticeTxt21_num", 220, 160),
  new HTMLInputElement("PracticeTxt22_num", 220, 240),
];
var radios = [
  new HTMLInputElement("PracticeAbsent1", 120, 340, "radio"),
  new HTMLInputElement("PracticeAbsent2", 220, 340, "radio"),
];
var labels = [new Element("xLabel", 95, 20, "x-intercept:"),
              new Element("yLabel", 195, 20, "y-intercept:"),
              new Element("xAbsentLabel", 120, 390, "absent"),
              new Element("yAbsentLabel", 220, 390, "absent")];
radios[0].ariaLabelledby = "xAbsentLabel";
radios[1].ariaLabelledby = "yAbsentLabel";
var body = new Element("body", 0, 0);
var documentElement = new Element("html", 0, 0);
var futureGraph = null;
var all = [...fields, ...radios, ...labels];
var document = {
  activeElement: body, body, documentElement, baseURI: "https://learn.hawkeslearning.com/",
  getElementById: id => all.find(node => node.id === id) || null,
  querySelector: () => null,
  querySelectorAll(selector) {
    if (selector.indexOf("customMessageBox") >= 0) return [];
    if (selector.startsWith('#QGraph')) return futureGraph ? [futureGraph] : [];
    if (selector.indexOf('input[type="radio"].opt') >= 0) return radios;
    if (selector.indexOf("input.qbaseCSS") >= 0) return fields;
    if (selector === "*") return labels;
    return [];
  },
};
var window = {
  location: {origin: "https://learn.hawkeslearning.com"},
  getSelection: () => null,
};
var CSS = {escape: value => value};
var setTimeout = (fn, _ms) => { fn(); return 1; };
"""


def context() -> quickjs.Context:
    ctx = quickjs.Context()
    ctx.eval(DOM)
    return ctx


def test_isolated_reader_owns_two_coordinate_rows_and_their_absence_controls():
    ctx = context()
    ctx.eval((EXTENSION / "content" / "hawkes-editor.js").read_text())

    report = json.loads(ctx.eval("JSON.stringify(ethnosHawkes.inspectField())"))

    assert report == {
        "ready": True,
        "code": "axis-intercepts-answer",
        "fieldId": "\x1f".join(
            [
                "PracticeTxt11_num",
                "PracticeTxt12_num",
                "PracticeTxt21_num",
                "PracticeTxt22_num",
                "PracticeAbsent1",
                "PracticeAbsent2",
            ]
        ),
        "fieldIds": [
            "PracticeTxt11_num",
            "PracticeTxt12_num",
            "PracticeTxt21_num",
            "PracticeTxt22_num",
        ],
        "axisInterceptRows": [
            {
                "axis": "x",
                "fieldIds": ["PracticeTxt11_num", "PracticeTxt12_num"],
                "optionId": "PracticeAbsent1",
                "option": "absent",
            },
            {
                "axis": "y",
                "fieldIds": ["PracticeTxt21_num", "PracticeTxt22_num"],
                "optionId": "PracticeAbsent2",
                "option": "absent",
            },
        ],
    }


def test_future_graph_cannot_steal_the_current_intercept_step():
    """Step 2 may already be mounted while Step 1 owns the visible fields."""
    ctx = context()
    ctx.eval(
        "futureGraph={id:'QGraph',getBoundingClientRect:()=>"
        "({top:500,bottom:910,left:20,right:430,width:410,height:410}),"
        "querySelectorAll:()=>[{id:'point1'},{id:'point2'}]};"
    )
    ctx.eval((EXTENSION / "content" / "hawkes-editor.js").read_text())

    report = json.loads(ctx.eval("JSON.stringify(ethnosHawkes.inspectField())"))

    assert report["code"] == "axis-intercepts-answer"
    assert report["fieldIds"] == [
        "PracticeTxt11_num",
        "PracticeTxt12_num",
        "PracticeTxt21_num",
        "PracticeTxt22_num",
    ]
    assert [row["axis"] for row in report["axisInterceptRows"]] == ["x", "y"]


def test_page_model_describes_the_same_mixed_surface_without_flattening_it():
    ctx = context()
    controls = ",".join("{enabled:true}" for _ in range(10))
    option = '{Name:"absent",isQDy:false,enableState:true}'
    box = (
        '{Name:"coordinate",isQDy:false,boxValue:"",validString:"[0-9-]",'
        "maxLength:6,enableState:true}"
    )
    ctx.eval(
        "window.quant_wp_UI={focusedElementIndex:2,controlsCollection:["
        + controls
        + "],controlsCollectionData:["
        + ",".join([option, option] + [box] * 8)
        + "]};"
    )

    described = json.loads(
        ctx.eval((EXTENSION / "content" / "hawkes-describe.js").read_text()).json()
    )

    assert described["kind"] == "axis-intercepts"
    assert described["code"] == "described-axis-intercepts"
    assert described["collection"]["branch"] == "axis-intercepts"
    assert described["collection"]["usable"] == 10
    assert described["collection"]["drawn"] == 4
    assert described["coordinateEditor"]["pairedControl"] is True


def test_absence_selection_and_coordinate_readback_are_both_semantic():
    ctx = context()
    source = (
        (EXTENSION / "common" / "axis-actions.js").read_text().replace("export ", "")
    )
    ctx.eval(source)
    rows = [
        {
            "axis": "x",
            "fieldIds": ["PracticeTxt11_num", "PracticeTxt12_num"],
            "optionId": "PracticeAbsent1",
        },
        {
            "axis": "y",
            "fieldIds": ["PracticeTxt21_num", "PracticeTxt22_num"],
            "optionId": "PracticeAbsent2",
        },
    ]
    intercepts = {"x": None, "y": ["0", "2"]}
    ctx.eval(
        "var selected, verified; selectAxisAbsences("
        + json.dumps(rows)
        + ","
        + json.dumps(intercepts)
        + ").then(value => selected=value);"
    )
    while ctx.execute_pending_job():
        pass
    ctx.eval(
        'document.getElementById("PracticeTxt21_num").value="0";'
        'document.getElementById("PracticeTxt22_num").value="2";'
        "verifyAxisInterceptInsertion("
        + json.dumps(rows)
        + ","
        + json.dumps(intercepts)
        + ").then(value => verified=value);"
    )
    while ctx.execute_pending_job():
        pass

    assert json.loads(ctx.eval("JSON.stringify(selected)")) == {
        "ok": True,
        "code": "axis-options-settled",
        "selected": 1,
    }
    assert ctx.eval('document.getElementById("PracticeAbsent1").checked') is True
    assert ctx.eval('document.getElementById("PracticeAbsent2").checked') is False
    assert json.loads(ctx.eval("JSON.stringify(verified)")) == {
        "ok": True,
        "code": "axis-intercepts-verified",
        "fields": 2,
        "absent": 1,
    }


def test_duplicated_intercepts_fill_both_rows_and_neither_is_absent():
    ctx = context()
    source = (
        (EXTENSION / "common" / "axis-actions.js").read_text().replace("export ", "")
    )
    ctx.eval(source)
    rows = [
        {
            "axis": "x",
            "fieldIds": ["PracticeTxt11_num", "PracticeTxt12_num"],
            "optionId": "PracticeAbsent1",
        },
        {
            "axis": "y",
            "fieldIds": ["PracticeTxt21_num", "PracticeTxt22_num"],
            "optionId": "PracticeAbsent2",
        },
    ]
    intercepts = {"x": ["0", "0"], "y": ["0", "0"]}
    ctx.eval(
        "var selected, verified; selectAxisAbsences("
        + json.dumps(rows)
        + ","
        + json.dumps(intercepts)
        + ").then(value => selected=value);"
    )
    while ctx.execute_pending_job():
        pass
    for field_id in (
        "PracticeTxt11_num",
        "PracticeTxt12_num",
        "PracticeTxt21_num",
        "PracticeTxt22_num",
    ):
        ctx.eval(f'document.getElementById("{field_id}").value="0";')
    ctx.eval(
        "verifyAxisInterceptInsertion("
        + json.dumps(rows)
        + ","
        + json.dumps(intercepts)
        + ").then(value => verified=value);"
    )
    while ctx.execute_pending_job():
        pass

    assert json.loads(ctx.eval("JSON.stringify(selected)")) == {
        "ok": True,
        "code": "axis-options-settled",
        "selected": 0,
    }
    assert ctx.eval('document.getElementById("PracticeAbsent1").checked') is False
    assert ctx.eval('document.getElementById("PracticeAbsent2").checked') is False
    assert json.loads(ctx.eval("JSON.stringify(verified)")) == {
        "ok": True,
        "code": "axis-intercepts-verified",
        "fields": 4,
        "absent": 0,
    }
