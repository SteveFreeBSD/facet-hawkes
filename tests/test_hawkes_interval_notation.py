"""Interval notation, entered through Hawkes' own bracket templates.

Live, on 2026-09-12, lesson 1.7: "solve the inequality and express your answer
in interval notation". Facet answered `(-8,7]`, correctly, and the add-on
refused it before the page was asked:

    editor   kind=dynamic maxLength=16 templates=parentheses
    allowed  '0123456789-.,∞∅'
    FAILURE  answer-shape (errorAnswerInvalid)

Two losses, one after the other. `validateAnswer` refused `]` outright, so the
answer never reached the editor that publishes `∞` and `∅` for exactly this
question. And had it got there, the probe had already reduced Hawkes' bracket
family to one `parentheses` boolean -- by a substring test that also read
`SPBrace` as `PBrace` -- so there was nothing left to say which end was closed.

What each bracket template draws is Hawkes' own statement, read from the lesson
bundle rather than from the names: `PSBrace` is labelled "left parenthesis,
right square bracket" and bound to Ctrl+]; `SPBrace` is "left square bracket,
right parenthesis" and bound to Ctrl+[. Its SVG paths draw the same.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ethnos.answer_capabilities import composition, load, notation_of

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON = PROJECT_ROOT / "extension" / "common"
PROBE = PROJECT_ROOT / "extension" / "content" / "hawkes-describe.js"
IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)

BRACKETS = ("PBrace", "SBrace", "PSBrace", "SPBrace")

#: The live lesson 1.7 control, as the page described it, with the bracket
#: family published under Hawkes' own names.
INTERVAL_BOX = {
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789-.,∞∅",
    "maxLength": 16,
    "templates": {
        "fraction": False,
        "radical": False,
        "exponent": False,
        "parentheses": True,
        "absoluteValue": False,
        **{name: True for name in BRACKETS},
    },
    "slots": {"base": "0123456789-.,∞∅"},
}


def offering(*names: str, characters: str = "0123456789-.,∞∅") -> dict:
    """The same box, publishing only these bracket templates."""
    return {
        **INTERVAL_BOX,
        "allowedCharacters": characters,
        "slots": {"base": characters},
        "templates": {
            **INTERVAL_BOX["templates"],
            "parentheses": "PBrace" in names,
            **{name: name in names for name in BRACKETS},
        },
    }


@pytest.fixture(scope="module")
def js():
    context = quickjs.Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js"):
        source = (COMMON / name).read_text(encoding="utf-8")
        context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))

    def call(name, *arguments):
        rendered = ", ".join(json.dumps(argument) for argument in arguments)
        return json.loads(context.eval(f"JSON.stringify({name}({rendered}))"))

    return call


def typed(result) -> str:
    return "".join(step["text"] for step in result["steps"] if step["op"] == "type")


def templates(result) -> list[str]:
    return [step["name"] for step in result["steps"] if step["op"] == "template"]


# --- the planner picks the template the two ends call for -------------------


@pytest.mark.parametrize(
    ("answer", "template"),
    [
        ("(-8,7)", "PBrace"),
        ("[-8,7]", "SBrace"),
        ("(-8,7]", "PSBrace"),
        ("[-8,7)", "SPBrace"),
    ],
)
def test_each_pairing_of_ends_loads_its_own_bracket_template(js, answer, template):
    result = js("planEntry", answer, INTERVAL_BOX)

    assert result["ok"] is True, result
    assert result["steps"] == [
        {"op": "template", "name": template},
        {"op": "type", "text": "-8,7"},
    ]


def test_decimal_ends_are_typed_inside_the_template(js):
    result = js("planEntry", "(-8.5,7.25]", INTERVAL_BOX)

    assert result["ok"] is True
    assert templates(result) == ["PSBrace"]
    assert typed(result) == "-8.5,7.25"


@pytest.mark.parametrize(
    ("answer", "template", "interior"),
    [
        ("(-∞,3]", "PSBrace", "-∞,3"),
        ("[2.5,∞)", "SPBrace", "2.5,∞"),
        ("(-∞,∞)", "PBrace", "-∞,∞"),
    ],
)
def test_infinity_is_a_character_the_box_publishes(js, answer, template, interior):
    result = js("planEntry", answer, INTERVAL_BOX)

    assert result["ok"] is True
    assert templates(result) == [template]
    assert typed(result) == interior


def test_the_empty_set_is_typed_where_the_box_publishes_it(js):
    assert js("planEntry", "∅", INTERVAL_BOX) == {
        "ok": True,
        "steps": [{"op": "type", "text": "∅"}],
    }


def test_spacing_from_a_readable_answer_is_not_typed(js):
    result = js("planEntry", "(-8.0, 7.0]", INTERVAL_BOX)

    assert result["ok"] is True
    assert typed(result) == "-8.0,7.0"


# --- and refuses, before writing, what the page does not publish -------------


@pytest.mark.parametrize(
    ("answer", "missing"),
    [
        ("(-8,7]", "PSBrace"),
        ("[-8,7)", "SPBrace"),
        ("[-8,7]", "SBrace"),
    ],
)
def test_an_end_the_question_offers_no_template_for_is_refused(js, answer, missing):
    """Never approximated by a bracket the page does offer."""
    result = js("planEntry", answer, offering("PBrace"))

    assert result == {
        "ok": False,
        "code": "template-refused-by-question",
        "detail": missing,
    }


def test_open_ends_are_refused_where_only_closed_brackets_are_offered(js):
    """`SPBrace` alone does not make `(-∞,3)` a pair the page drew brackets for."""
    result = js("planEntry", "(-∞,3)", offering("SPBrace"))

    assert result == {
        "ok": False,
        "code": "template-refused-by-question",
        "detail": "parentheses",
    }


def test_a_box_offering_no_bracket_takes_no_interval(js):
    result = js("planEntry", "[2,5)", offering(characters="0123456789-,"))

    assert result["ok"] is False
    assert result["code"] == "template-refused-by-question"


def test_infinity_is_refused_where_the_box_does_not_publish_it(js):
    result = js("planEntry", "(-∞,3]", offering(*BRACKETS, characters="0123456789-,"))

    assert result == {
        "ok": False,
        "code": "answer-has-rejected-characters",
        "detail": "∞",
    }


def test_a_union_is_refused_by_a_box_that_does_not_publish_it(js):
    result = js("planEntry", "(-∞,-3)∪(3,∞)", INTERVAL_BOX)

    assert result == {
        "ok": False,
        "code": "answer-has-rejected-characters",
        "detail": "∪",
    }


def test_a_union_is_built_between_templates_where_a_box_publishes_it(js):
    """Hawkes' own source types `∪` as a character between two enclosures."""
    result = js(
        "planEntry", "(-∞,-3]∪[3,∞)", offering(*BRACKETS, characters="0123456789-.,∞∪")
    )

    assert result["ok"] is True
    assert result["steps"] == [
        {"op": "template", "name": "PSBrace"},
        {"op": "type", "text": "-∞,-3"},
        {"op": "base"},
        {"op": "type", "text": "∪"},
        {"op": "template", "name": "SPBrace"},
        {"op": "type", "text": "3,∞"},
    ]


def test_a_mismatched_bracket_is_not_understood(js):
    assert (
        js("planEntry", "(-8,7", INTERVAL_BOX)["code"] == "parentheses-not-understood"
    )


def test_the_character_check_names_brackets_as_structure(js):
    verdict = js("answerFitsEditor", "(-8,7]", INTERVAL_BOX)

    assert verdict["insertable"] is False
    assert verdict["code"] == "answer-needs-template"
    assert "brackets" in verdict["detail"]


# --- the global boundary widens by intervals and nothing else ---------------


@pytest.mark.parametrize(
    "answer",
    [
        "(-8,7]",
        "[-8,7)",
        "[-8,7]",
        "(-8.5,7.25]",
        "(-∞,3]",
        "[2.5,∞)",
        "∅",
        "(-∞,-3)∪(3,∞)",
    ],
)
def test_interval_notation_is_a_valid_answer(js, answer):
    assert js("validateAnswer", answer) == {"ok": True, "value": answer}


@pytest.mark.parametrize(
    "answer",
    [
        "[1,2,3]",  # a square bracket holding three values is no interval
        "[x]",  # nor holding one
        "]1,2[",  # closed before it opens
        "[1,2",  # never closed
        "(1,2]]",
        "<b>[1,2]</b>",
        "[1,2];",
        "{1,2}",
        "'[1,2]'",
        "\\[1,2]",
    ],
)
def test_square_brackets_that_are_not_an_interval_stay_invalid(js, answer):
    assert js("validateAnswer", answer) == {"ok": False, "code": "answer-invalid"}


def test_answers_that_were_valid_before_still_are(js):
    for answer in (
        "(x+3)*(x+4)",
        "y=-2*x+5",
        "sqrt(101)",
        "(17/2,-1/2)",
        "Not a Real Number",
    ):
        assert js("validateAnswer", answer)["ok"] is True, answer


# --- the probe publishes the family exactly ---------------------------------


def describe(published_templates: str) -> dict:
    context = quickjs.Context()
    context.eval(
        "globalThis.window = {quant_wp_UI: {focusedElementIndex: 0,"
        " controlsCollection: [{Type: 'Base', qdyBase_AllowedChar: '0123456789-.,∞∅',"
        f" qdyBase_AllowedTemplates: {published_templates}, qdyBaseMaxChars: 16}}],"
        " controlsCollectionData: [{isQDy: true, Name: 'QBase'}]}};"
    )
    return json.loads(context.eval(PROBE.read_text(encoding="utf-8")).json())


def test_the_probe_publishes_each_bracket_under_hawkes_own_name():
    described = describe("['PBrace', 'PSBrace', 'SPBrace', 'SBrace']")

    assert {name: described["templates"][name] for name in BRACKETS} == {
        name: True for name in BRACKETS
    }
    assert described["templates"]["parentheses"] is True


def test_a_mixed_bracket_is_not_mistaken_for_parentheses():
    """`"SPBrace".includes("PBrace")` is true, and was the whole test."""
    described = describe("['SPBrace']")

    assert described["templates"]["parentheses"] is False
    assert described["templates"]["PBrace"] is False
    assert described["templates"]["SPBrace"] is True
    assert described["templates"]["PSBrace"] is False


# --- the MAIN-world writer loads the template through Hawkes' own guard -----

#: A dynamic editor modelled on `addElement`: a bracket name is guarded by
#: `qualifyLoadParenthesis(name)` against the published template array, loaded
#: by `loadParenthesis(name, fromKeypad)` into an interior box it focuses and a
#: continuation after it; anything else is a character validated against the
#: published set. A refused key raises the dialog, as Hawkes does.
EDITOR = """
var now = 0, timers = [];
var performance = {now: () => now};
Date.now = () => now;
var setTimeout = (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t; };
var completed = null, dialog = false, serial = 1;
class InputEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class KeyboardEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class Event { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class FocusEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class CustomEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class HTMLInputElement {
  constructor(id) { this.id = id; this.held = ''; this.className = 'qbaseCSS'; }
  get value() { return this.held; }
  set value(v) { this.held = v; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return {width: 100, height: 20}; }
  dispatchEvent() { return true; }
}
var everyBox = [];
var document = {
  activeElement: null,
  getElementById: id => everyBox.find(box => box.id === id) ?? null,
  querySelectorAll: selector => selector.indexOf('customMessageBox') >= 0
    ? (dialog ? [{getBoundingClientRect: () => ({height: 40})}] : [])
    : everyBox.slice(),
  dispatchEvent: () => true,
};
var BRACKETS = ['PBrace', 'SBrace', 'PSBrace', 'SPBrace', 'Mod'];
var control = {
  enabled: true, arrChildObjects: [], CurrentBase: null, loaded: [], guarded: [],
  qdyBase_AllowedTemplates: PUBLISHED,
  qdyBase_AllowedChar: CHARACTERS,
  keyPadButtonClick(name) { this.addElement(name, true); },
  addElement(name) {
    if (name === 'Clear') {
      everyBox.splice(1); everyBox[0].held = '';
      control.arrChildObjects.splice(1); control.CurrentBase = control.arrChildObjects[0];
      return;
    }
    const base = control.CurrentBase;
    if (BRACKETS.includes(name)) {
      if (base.qualifyLoadParenthesis(name)) { base.loadParenthesis(name, true); }
      else { dialog = true; }
      return;
    }
    if (control.qdyBase_AllowedChar.indexOf(name) < 0) { dialog = true; return; }
    base.box.held += name;
  },
};
function makeBase(id) {
  const box = new HTMLInputElement(id);
  const base = {
    Type: 'Base', box, arrChildObjects: [],
    objMyDiv: {querySelector: () => box},
    loadExponent() {},
    setFocus() { control.CurrentBase = base; },
    qualifyLoadParenthesis(name) {
      control.guarded.push(name);
      return control.qdyBase_AllowedTemplates.indexOf(name) !== -1;
    },
    loadParenthesis(name) {
      control.loaded.push(name);
      setTimeout(() => {
        const inner = makeBase('QBase' + (++serial) + '_input');
        makeBase('QBase' + (++serial) + '_input');
        inner.box.drawnBy = name;
        document.activeElement = inner.box;
        control.CurrentBase = inner;
      }, 120);
    },
  };
  everyBox.push(box);
  control.arrChildObjects.push(base);
  return base;
}
control.CurrentBase = makeBase('QBase1_input');
var window = {quant_wp_UI: {controlsCollection: [control], focusedElementIndex: 0}};
"""


def editor(published: list[str], characters: str = "0123456789-.,∞∅"):
    context = quickjs.Context()
    context.eval(
        EDITOR.replace("PUBLISHED", json.dumps(published)).replace(
            "CHARACTERS", json.dumps(characters)
        )
    )
    for name in ("cadence.js", "page-actions.js"):
        source = (COMMON / name).read_text(encoding="utf-8")
        context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))
    return context


def pump(context):
    for _ in range(20000):
        while context.execute_pending_job():
            pass
        if not context.eval("timers.length"):
            return
        context.eval(
            "timers.sort((a,b) => a.at-b.at); var t = timers.shift();"
            " now = Math.max(now, t.at); t.fn();"
        )
    pytest.fail("the writer did not terminate")


def perform(context, steps):
    context.eval(
        f"var steps = {json.dumps(steps)};"
        " var phrase = ethnosCadence.planSemanticPhrase(steps,"
        " {durationMinMs: 200, durationMaxMs: 200});"
        " enterPlan(steps, {score: phrase}, [], 'hawkes-dynamic-keypad')"
        ".then(r => completed = r, e => completed = {ok: false, code: 'threw',"
        " detail: String(e)});"
    )
    pump(context)
    return json.loads(context.eval("JSON.stringify(completed)"))


def drawn(context) -> list[tuple[str, str]]:
    return json.loads(
        context.eval(
            "JSON.stringify(everyBox.map(box => [box.drawnBy ?? '', box.value]))"
        )
    )


@pytest.mark.parametrize(
    ("answer", "template"),
    [
        ("(-8,7)", "PBrace"),
        ("[-8,7]", "SBrace"),
        ("(-8,7]", "PSBrace"),
        ("[-8,7)", "SPBrace"),
        ("[2.5,∞)", "SPBrace"),
    ],
)
def test_the_writer_loads_the_planned_bracket_through_hawkes_guard(
    js, answer, template
):
    page = editor(list(BRACKETS))
    steps = js("planEntry", answer, INTERVAL_BOX)["steps"]

    reported = perform(page, steps)

    assert reported["ok"] is True, reported
    assert reported["transport"] == "hawkes-dynamic-keypad"
    # Asked by the writer before pressing, and again by `addElement` itself;
    # only ever about the one template the plan named.
    assert set(json.loads(page.eval("JSON.stringify(control.guarded)"))) == {template}
    assert page.eval("JSON.stringify(control.loaded)") == json.dumps([template])
    interior = answer[1:-1]
    assert [box for box in drawn(page) if box[1]] == [[template, interior]]
    assert reported["timing"]["keypadWrites"] == len(interior)
    assert reported["timing"]["nativeWrites"] == 0

    # Nothing Hawkes does afterwards undoes it: the page settles holding it.
    page.eval("setTimeout(() => {}, 2000);")
    pump(page)
    assert page.eval("dialog") is False
    assert "".join(value for _, value in drawn(page)) == interior


def test_a_union_is_built_through_the_keypad_where_the_box_publishes_it(js):
    """Hawkes types `∪` as an ordinary special character between two enclosures."""
    characters = "0123456789-.,∞∪"
    page = editor(list(BRACKETS), characters)
    steps = js("planEntry", "(-∞,1]∪[4,∞)", offering(*BRACKETS, characters=characters))[
        "steps"
    ]

    reported = perform(page, steps)

    assert reported["ok"] is True, reported
    assert json.loads(page.eval("JSON.stringify(control.loaded)")) == [
        "PSBrace",
        "SPBrace",
    ]
    held = [box for box in drawn(page) if box[1]]
    assert held == [["PSBrace", "-∞,1"], ["", "∪"], ["SPBrace", "4,∞"]]
    assert reported["timing"]["nativeWrites"] == 0
    page.eval("setTimeout(() => {}, 2000);")
    pump(page)
    assert page.eval("dialog") is False


def test_a_union_is_never_typed_into_a_box_that_does_not_publish_it(js):
    """Hawkes' own editor would refuse the `∪` key with its dialog."""
    result = js("planEntry", "(-∞,1]∪[4,∞)", INTERVAL_BOX)

    assert result == {
        "ok": False,
        "code": "answer-has-rejected-characters",
        "detail": "∪",
    }


def test_the_writer_refuses_a_bracket_the_page_does_not_publish(js):
    """A plan made against a stale description meets Hawkes' own guard."""
    page = editor(["PBrace"])
    steps = js("planEntry", "(-8,7]", INTERVAL_BOX)["steps"]

    reported = perform(page, steps)

    assert reported["ok"] is False
    assert reported["code"] == "template-unavailable"
    assert reported["detail"] == "PSBrace"
    assert page.eval("JSON.stringify(control.loaded)") == "[]"
    assert page.eval("dialog") is False
    assert "".join(value for _, value in drawn(page)) == ""


# --- the map, the planner, the writer and the probe name the same family -----


def test_every_bracket_the_planner_can_press_is_guarded_loaded_and_described():
    plan = (COMMON / "editor-plan.js").read_text(encoding="utf-8")
    writer = (COMMON / "page-actions.js").read_text(encoding="utf-8")
    probe = PROBE.read_text(encoding="utf-8")
    table = re.search(r"const BRACKET_TEMPLATES = \{([^}]*)\}", plan).group(1)
    planned = re.findall(r'"([()\[\]]{2})": "(\w+)"', table)

    assert dict(planned) == {
        "()": "PBrace",
        "[]": "SBrace",
        "(]": "PSBrace",
        "[)": "SPBrace",
    }
    for _, name in planned:
        assert f'{name}: [base.qualifyLoadParenthesis, ["{name}"]]' in writer
        assert f'{name}: [base.loadParenthesis, ["{name}", true]]' in writer
        assert f'{name}: baseTemplates.has("{name}")' in probe


def test_every_interval_row_plans_the_template_its_ends_call_for(js):
    authority = load()
    # A number line is drawn rather than typed, and is proved in
    # `test_hawkes_number_line.py`.
    rows = [
        entry
        for entry in authority.entries
        if "interval" in entry.notation
        and authority.editor_for(entry)["kind"] != "graph"
    ]
    marks = {"()": "PBrace", "[]": "SBrace", "(]": "PSBrace", "[)": "SPBrace"}

    assert {entry.id for entry in rows if entry.supported} >= {
        "scalar-interval",
        "scalar-interval-decimal",
        "scalar-interval-empty",
    }
    for entry in rows:
        assert composition(entry.form, notation_of(entry.example)) == entry.composition
        result = js("planEntry", entry.example, authority.editor_for(entry))
        if not entry.supported:
            assert result["ok"] is False and result["code"] == entry.refusal, entry.id
            continue
        assert result["ok"] is True, (entry.id, result)
        groups = re.findall(r"([(\[])[^()\[\]]*([)\]])", entry.example)
        assert templates(result) == [marks[a + b] for a, b in groups], entry.id
        assert "enterPlan" in entry.mechanism, entry.id
