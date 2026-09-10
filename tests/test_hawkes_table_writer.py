"""Writing a completion table into a controlled editor, not into five boxes.

Live, on 2026-09-07, lesson 2.1's five-blank grid was read correctly, mapped
correctly, solved exactly, and inserted wrongly -- twice, and both runs logged
success:

    inserted {"via":"table-cells","fields":5,"parts":5,
              "held":[0,0,0,0,0],"placed":[1,1,1,1,1]}

Writing the fifth part into `MatrixTextBoxes6_num` also changed
`MatrixTextBoxes3_num`, which is the second part's cell. Nothing about the
mapping, the mathematics or the targets was wrong; what was wrong is that a
Hawkes answer cell is not an ordinary text box.

The old harness could not have caught it, because it modelled five independent
inputs: a write to one of them could not touch another, so the writer passed
every test it had while corrupting the page. What this file models instead is
the editor Hawkes actually publishes:

*   `controlsCollection`, one control per cell, each with its own text buffer,
    and twice as many controls as blanks -- the hidden option control beside
    every box, which is why the page's model reported ten for a five-blank grid.
*   `focusedElementIndex`, the one control the page believes is being edited.
*   Delegated `input` handling: the event updates the *selected* control's
    buffer, whichever box it was dispatched on.
*   A rerender: a control that takes a value writes it back into the box it
    owns.
*   And the fact the whole failure turns on -- `focus()` moves
    `document.activeElement` and does **not** move `focusedElementIndex`.

`test_the_writer_this_replaced_corrupts_the_table` runs the old algorithm
against that page and reproduces the live corruption exactly, which is what
makes the rest of this file evidence rather than decoration.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

#: The live case, in the order the mathematics numbers the cells. Reading order
#: is `3, 6, 8, 10, 11`; nothing below is in it.
LIVE_CELLS = [
    "MatrixTextBoxes8_num",
    "MatrixTextBoxes3_num",
    "MatrixTextBoxes10_num",
    "MatrixTextBoxes11_num",
    "MatrixTextBoxes6_num",
]
#: The five values Facet proves for `x = y²` on that grid.
LIVE_PARTS = ["0", "8", "8", "5", "3"]
#: The order the *markup* writes those boxes in, which is what Hawkes numbers
#: its own controls by. Nothing above is in it, and that is the point.
DOM_CELLS = [
    "MatrixTextBoxes3_num",
    "MatrixTextBoxes6_num",
    "MatrixTextBoxes8_num",
    "MatrixTextBoxes10_num",
    "MatrixTextBoxes11_num",
]

PAGE = r"""
// --- a clock that moves ----------------------------------------------------
globalThis.__clock = 0;
globalThis.Date = {now: () => (__clock += 5)};
globalThis.performance = {now: () => (__clock += 1)};
// Timers resolve on the microtask queue so `execute_pending_job` drives them.
globalThis.setTimeout = (fn) => { Promise.resolve().then(fn); return 0; };
globalThis.clearTimeout = () => {};

class InputEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.data = init.data;
    this.inputType = init.inputType;
    this.cancelable = init.cancelable === true;
    this.target = null;
  }
}
class CustomEvent {
  constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
}
class FocusEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = init.bubbles === true;
    this.target = null;
  }
}
globalThis.InputEvent = InputEvent;
globalThis.CustomEvent = CustomEvent;
globalThis.FocusEvent = FocusEvent;

// --- the page's elements ---------------------------------------------------
class Element {
  constructor({id = "", tag = "SPAN", visible = true} = {}) {
    this.id = id;
    this.tagName = tag;
    this.nodeType = 1;
    this.isConnected = true;
    this.visible = visible;
    this.childNodes = [];
    this.parentElement = null;
  }
  getAttribute(name) { return name === "id" ? this.id : null; }
  appendChild(child) { child.parentElement = this; this.childNodes.push(child); return child; }
  contains(other) {
    for (let at = other; at; at = at.parentElement) { if (at === this) return true; }
    return false;
  }
  getBoundingClientRect() {
    const size = this.visible ? 60 : 0;
    return {top: 0, left: 0, width: size, height: this.visible ? 20 : 0,
            right: size, bottom: this.visible ? 20 : 0};
  }
  focus() { globalThis.document.activeElement = this; }
  matches(selector) {
    return this.tagName === "INPUT" && this.kind !== "opt"
      && String(selector).includes("input.qbaseCSS");
  }
  dispatchEvent(event) {
    event.target = this;
    if (event.type === "beforeinput") { return this.accept !== false; }
    if (event.type === "input") { globalThis.__hawkesInput(event); }
    // A bubbling focus event reaches the handler Hawkes binds at document
    // level. `focus()` alone does not, which is the whole of the live case:
    // the panel holds system focus, so the browser fires nothing.
    if (event.type === "focusin") { globalThis.__hawkesFocus(event); }
    return true;
  }
  setSelectionRange(start, end) {
    const length = this._value.length;
    this.selectionStart = Math.min(start, length);
    this.selectionEnd = Math.min(end, length);
  }
}
class HTMLInputElement extends Element {
  constructor(options = {}) {
    super({...options, tag: "INPUT"});
    this.kind = options.kind ?? "box";
    this.visible = this.kind === "box";
    this.maxLength = options.maxLength ?? 4;
    this.disabled = false;
    this.readOnly = false;
    this.accept = true;
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this._value = "";
  }
  // The editor's own rerender: the control writes its buffer back into the box
  // it owns, without going through the setter the add-on writes with.
  render(text) { this._value = text; }
}
Object.defineProperty(HTMLInputElement.prototype, "value", {
  get() { return this._value; },
  set(next) { this._value = next; },
  configurable: true,
});
globalThis.HTMLInputElement = HTMLInputElement;

globalThis.fields = [];
globalThis.document = {
  activeElement: null,
  getElementById(id) {
    return globalThis.fields.find((one) => one.id === id && one.isConnected) ?? null;
  },
  querySelectorAll(selector) {
    if (String(selector).includes("customMessageBox")) return globalThis.dialogs ?? [];
    return [];
  },
  dispatchEvent() { return true; },
};
globalThis.window = {location: {origin: "https://learn.hawkeslearning.com"}};

// --- the editor Hawkes publishes -------------------------------------------
//
// One control per value cell, and one hidden option control beside it -- which
// is why the live collection held ten entries for five blanks. Only the text
// controls carry a buffer; the option ones publish no `boxValue`, which is the
// same thing the read-only probe classifies them by.
globalThis.buildTable = (  ids,
  {focused = 0, link = "cell", names = "id", showing = [], router = "element"} = {}
) => {
  // `ids` is markup order, because that is the order Hawkes numbers its own
  // controls in. The answers arrive in the order the mathematics numbers the
  // cells, and the two are not the same list.
  globalThis.fields = [];
  globalThis.dialogs = [];
  const controls = [];
  const rows = [];
  for (const id of ids) {
    const cell = new Element({id: id + "_cell"});
    const box = new HTMLInputElement({id});
    // The other half of this one cell. Hawkes' control collection carries it
    // from the start -- eight controls for a four-blank table -- and its box
    // is not drawn until a `/` is typed into the numerator.
    const den = new HTMLInputElement({id: id.replace(/_num$/, "") + "_den", kind: "den"});
    den.visible = false;
    cell.appendChild(box);
    cell.appendChild(den);
    globalThis.fields.push(box, den);

    const control = {enabled: true, buffer: "",
                     boxValue: function () { return this.buffer; }};
    // The harness's own wiring, hidden from anything that enumerates the
    // control: which box a control rerenders is the editor's business, not a
    // link the add-on may resolve ownership from.
    Object.defineProperty(control, "field",
      {value: box, enumerable: false, configurable: true});
    if (link === "cell") { control.objMyDiv = cell; }
    if (link === "element") { control.objMyInput = box; }
    controls.push(control);
    rows.push({
      isQDy: false, boxValue: "", enableState: true,
      validString: "[0-9-]", maxLength: 4,
      Name: names === "base" ? id.replace(/_num$/, "") : (names === "none" ? "" : id),
    });
    // The denominator's own control, published beside the numerator's.
    const half = {enabled: true, buffer: "",
                  boxValue: function () { return this.buffer; }};
    Object.defineProperty(half, "field",
      {value: den, enumerable: false, configurable: true});
    Object.defineProperty(control, "half",
      {value: half, enumerable: false, configurable: true});
    controls.push(half);
    rows.push({isQDy: false, boxValue: "", enableState: true,
               validString: "[0-9/-]", maxLength: 4, Name: den.id});
  }
  globalThis.window.quant_wp_UI = {
    // The authoritative router: the element Hawkes edits through. The index
    // beside it is a mirror of the same selection, and only the page's own
    // focus handling moves the two together.
    focusedElement: controls[focused] ? controls[focused].field : null,
    focusedElementIndex: focused,
    controlsCollection: controls,
    controlsCollectionData: rows,
    // The halves of whichever cell is showing a fraction. Hawkes keeps these
    // for as long as the fraction is drawn -- they are not a selection, and
    // they do not move when one cell is left for another. Reading every
    // element-valued property here as though it named the cell being edited
    // is what made a table with one fraction in it unwritable.
    fractionNumerator: null,
    fractionDenominator: null,
  };
  const ui = globalThis.window.quant_wp_UI;
  // A cell the owner already typed a fraction into before the add-on ran.
  // Live, on 2026-09-07, this was the state on screen: one semantic cell
  // expanded into two boxes, the other three still single boxes, and every
  // one of the four still asking for exactly one value -- with the editor
  // sitting in the expanded cell's *denominator*, which is where typing a
  // fraction leaves it and where the caret still was.
  for (const id of showing) {
    const control = controls[globalThis.controlFor(id)];
    control.half.field.visible = true;
    ui.fractionNumerator = control.field;
    ui.fractionDenominator = control.half.field;
    ui.focusedElement = control.half.field;
    ui.focusedElementIndex = controls.indexOf(control.half);
  }
  // Some Hawkes pages publish no element-valued property this add-on can
  // enumerate at all: live the router read back as `routed: []`, and the
  // mirror was the only evidence there was. A proof that depends on the
  // router has to survive its absence.
  if (router === "none") {
    const held = ui.focusedElement;
    delete ui.focusedElement;
    Object.defineProperty(ui, "focusedElement",
      {value: held, writable: true, enumerable: false, configurable: true});
    for (const key of ["fractionNumerator", "fractionDenominator"]) {
      const value = ui[key];
      delete ui[key];
      Object.defineProperty(ui, key,
        {value, writable: true, enumerable: false, configurable: true});
    }
  }
  return ui;
};

/** Which published control owns one visible box. */
globalThis.controlFor = (id) =>
  globalThis.window.quant_wp_UI.controlsCollection.findIndex(
    (control) => control.field && control.field.id === id && control.buffer !== undefined
  );

// The page's own delegated input handling, and the whole of the defect: the
// event updates the control the page has *selected*, not the one that owns the
// box it was dispatched on, and that control then rerenders its own box.
globalThis.__hawkesInput = (event) => {
  const ui = globalThis.window.quant_wp_UI;
  if (!ui) return;
  // Routed through `focusedElement`, never through the index. Setting the
  // index is what 674329b did, and it changed nothing about where this goes.
  const control = ui.controlsCollection.find(
    (one) => one.field === ui.focusedElement && one.buffer !== undefined
  );
  if (!control) return;
  const written = event.target.value;
  // A plain answer box turns `/` into its own fraction: the numerator keeps
  // what came before it, the cell's second box is drawn, and the editor moves
  // there. One logical cell showing two inputs, not a second blank.
  const cut = written.indexOf("/");
  if (cut >= 0 && control.half && !control.half.field.visible) {
    control.buffer = written.slice(0, cut);
    control.field.render(control.buffer);
    control.half.buffer = written.slice(cut + 1);
    control.half.field.visible = true;
    control.half.field.render(control.half.buffer);
    ui.focusedElement = control.half.field;
    ui.focusedElementIndex = ui.controlsCollection.indexOf(control.half);
    // Kept for as long as the fraction is on screen, and left behind when the
    // editor moves on to the next cell.
    ui.fractionNumerator = control.field;
    ui.fractionDenominator = control.half.field;
    return;
  }
  control.buffer = written;
  control.field.render(control.buffer);
  // A page that crosses two cells even when the right control is selected.
  if (control.alsoRenders) { control.alsoRenders.render(control.buffer); }
};

// Hawkes' own focus handling, which is what a click on a cell delivers: it
// selects the control that owns the box and moves the router and the mirror
// together. Nothing else in this page moves the router.
globalThis.__hawkesFocus = (event) => {
  const ui = globalThis.window.quant_wp_UI;
  if (!ui) return;
  const at = ui.controlsCollection.findIndex((one) => one.field === event.target);
  if (at < 0) return;
  ui.focusedElement = event.target;
  ui.focusedElementIndex = at;
};

// --- the writer this replaced ----------------------------------------------
//
// Focus the box, set its value through the prototype setter, dispatch `input`.
// Kept here, and only here, so the harness above has to keep reproducing the
// failure it was built to reproduce.
globalThis.oldSelectionWriter = async (parts, ids) => {
  const ui = globalThis.window.quant_wp_UI;
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  const put = (field, text, character) => {
    setter.call(field, text);
    field.dispatchEvent(new InputEvent("input", {data: character, inputType: "insertText"}));
  };
  const mirrorAgreed = [];
  for (let at = 0; at < ids.length; at += 1) {
    const field = document.getElementById(ids[at]);
    const index = controlFor(ids[at]);
    field.focus();
    ui.focusedElementIndex = index;                     // 674329b's selection
    mirrorAgreed.push(ui.focusedElementIndex === index);  // and its read-back
    put(field, "", "");
    let placed = "";
    for (const character of parts[at]) { placed += character; put(field, placed, character); }
  }
  return {ok: true, code: "index-mirror-only", mirrorAgreed,
          router: ui.focusedElement ? ui.focusedElement.id : null};
};

globalThis.oldWriter = async (parts, ids) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
  const put = (field, text, character) => {
    setter.call(field, text);
    field.setSelectionRange(text.length, text.length);
    field.dispatchEvent(new InputEvent("input", {data: character, inputType: "insertText"}));
  };
  for (let at = 0; at < ids.length; at += 1) {
    const field = document.getElementById(ids[at]);
    field.focus();
    put(field, "", "");
    let placed = "";
    for (const character of parts[at]) { placed += character; put(field, placed, character); }
  }
  return {ok: true, code: "native-input-cells", cells: [...ids], placed: ids.map(() => 1)};
};
"""

WRITER = re.sub(
    r"^export ",
    "",
    (EXTENSION / "common" / "table-actions.js").read_text(encoding="utf-8"),
    flags=re.MULTILINE,
)


def page(**options):
    """One completion table, drawn and numbered as the live page draws it."""
    context = quickjs.Context()
    context.eval(PAGE)
    context.eval(WRITER)
    context.eval(f"buildTable({json.dumps(DOM_CELLS)}, {json.dumps(options)});")
    return context


def score(parts):
    return {"score": {"offsets": [0] * len("".join(parts))}}


def write(context, parts=None, cells=None, writer="enterOwnedFields"):
    """Run one writer to completion and return what it reported."""
    parts = parts or LIVE_PARTS
    cells = cells or LIVE_CELLS
    call = (
        f"enterOwnedFields({json.dumps(parts)}, {json.dumps(cells)}, "
        f"{json.dumps(score(parts))}, 'table')"
        if writer == "enterOwnedFields"
        else f"{writer}({json.dumps(parts)}, {json.dumps(cells)})"
    )
    context.eval(f"globalThis.outcome = null; {call}.then(v => {{ outcome = v; }});")
    for _ in range(20000):
        if not context.execute_pending_job():
            break
    return json.loads(context.eval("JSON.stringify(outcome)"))


def cellsNow(context):
    """Each mapped cell's *logical* value, by numerator id.

    A cell showing a fraction holds `16/9` across two inputs and is still one
    blank; reading its boxes separately would make the same four-blank table
    four answers or eight depending on what had been typed into it.
    """
    return dict(
        json.loads(
            context.eval(
                "JSON.stringify(fields.filter(f => f.kind === 'box').map(f => {"
                " const den = fields.find(o => o.kind === 'den'"
                "   && o.id === f.id.replace(/_num$/, '') + '_den' && o.visible);"
                " return [f.id, den ? f._value + '/' + den._value : f._value]; }))"
            )
        )
    )


def inputsNow(context):
    """Every physical text input the page is showing, in document order."""
    return json.loads(
        context.eval("JSON.stringify(fields.filter(f => f.visible).map(f => f.id))")
    )


def buffers(context):
    """What every page-owned control holds in its own model."""
    return json.loads(
        context.eval(
            "JSON.stringify(window.quant_wp_UI.controlsCollection"
            ".filter(c => c.buffer !== undefined && c.field.kind === 'box')"
            ".map(c => [c.field.id, c.buffer]))"
        )
    )


# --- the harness reproduces the live failure --------------------------------


def test_dom_focus_moves_neither_the_router_nor_the_mirror() -> None:
    """The one fact the old harness did not have, stated on its own."""
    live = page()
    live.eval("document.getElementById('MatrixTextBoxes6_num').focus();")

    assert live.eval("document.activeElement.id") == "MatrixTextBoxes6_num"
    assert live.eval("window.quant_wp_UI.focusedElementIndex") == 0
    assert live.eval("window.quant_wp_UI.focusedElement.id") == "MatrixTextBoxes3_num"


def test_the_index_is_a_mirror_and_the_element_is_the_router() -> None:
    """Assigning the mirror moves nothing the editor edits through."""
    live = page()
    live.eval("window.quant_wp_UI.focusedElementIndex = 4;")

    assert live.eval("window.quant_wp_UI.focusedElementIndex") == 4
    assert live.eval("window.quant_wp_UI.focusedElement.id") == "MatrixTextBoxes3_num"


def test_the_pages_own_focus_handling_moves_both_together() -> None:
    """And it is the only thing that does, which is what a click delivers."""
    live = page()
    live.eval(
        "document.getElementById('MatrixTextBoxes8_num')"
        ".dispatchEvent(new FocusEvent('focusin', {bubbles: true}));"
    )

    assert live.eval("window.quant_wp_UI.focusedElementIndex") == 4
    assert live.eval("window.quant_wp_UI.focusedElement.id") == "MatrixTextBoxes8_num"


def test_the_selection_this_replaced_crosses_two_cells_either_way() -> None:
    """674329b's selection, and the matched pair of live failures it produced.

    It assigned `focusedElementIndex` and read it back, and the read-back
    always agreed -- that is all a mirror can tell you. The router stayed where
    Hawkes had left it before the panel opened, so every write went there:
    pre-focused on blank 1's control the first write lands and the second
    crosses into blank 1, and pre-focused on blank 2's the very first write
    crosses into blank 2.
    """
    on_blank_two = page(focused=0)  # MatrixTextBoxes3_num, blank 2
    reported = write(on_blank_two, writer="oldSelectionWriter")

    assert reported["mirrorAgreed"] == [True] * 5
    assert reported["router"] == "MatrixTextBoxes3_num"
    # Blank 1's value went into blank 2's cell, on the very first write.
    assert cellsNow(on_blank_two)["MatrixTextBoxes3_num"] == LIVE_PARTS[4]
    assert cellsNow(on_blank_two)["MatrixTextBoxes8_num"] == LIVE_PARTS[0]

    on_blank_one = page(focused=4)  # MatrixTextBoxes8_num, blank 1
    reported = write(on_blank_one, writer="oldSelectionWriter")

    assert reported["mirrorAgreed"] == [True] * 5
    assert reported["router"] == "MatrixTextBoxes8_num"
    assert cellsNow(on_blank_one)["MatrixTextBoxes8_num"] == LIVE_PARTS[4]
    assert cellsNow(on_blank_one)["MatrixTextBoxes3_num"] == LIVE_PARTS[1]


def test_the_new_selection_fixes_both_of_those_starting_states() -> None:
    """Same two pages, same five parts, through the page's own focus path."""
    for focused in (0, 4):
        live = page(focused=focused)

        reported = write(live)

        assert reported["ok"] is True, focused
        assert cellsNow(live) == dict(zip(LIVE_CELLS, LIVE_PARTS)), focused


def test_a_page_that_cannot_be_proven_focused_refuses() -> None:
    """No selection Hawkes made is no selection: nothing is written."""
    live = page()
    live.eval("globalThis.__hawkesFocus = () => {};")

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-not-selected"
    assert reported["blank"] == 1
    assert reported["written"] == 0
    assert set(cellsNow(live).values()) == {""}


def test_a_router_left_on_another_cell_refuses_even_when_the_mirror_agrees() -> None:
    """The confirmation that 674329b did not make: the router, not the index."""
    live = page()
    live.eval(
        "globalThis.__hawkesFocus = (event) => {"
        " const ui = window.quant_wp_UI;"
        " ui.focusedElementIndex = ui.controlsCollection"
        "   .findIndex((one) => one.field === event.target); };"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-not-selected"
    assert set(cellsNow(live).values()) == {""}


def test_the_writer_this_replaced_corrupts_the_table() -> None:
    """The live run, reproduced: five writes reported, one cell wrong.

    `focusedElementIndex` is 0 throughout -- the first cell, which is where the
    page's own selection was left before the panel was ever opened -- so every
    write updates that control and rerenders its box. Four cells keep what the
    DOM setter left in them; `MatrixTextBoxes3_num`, which holds the second
    part, ends up holding the fifth.
    """
    live = page()

    reported = write(live, writer="oldWriter")
    settled = cellsNow(live)

    assert reported["ok"] is True
    assert reported["placed"] == [1, 1, 1, 1, 1]
    assert settled["MatrixTextBoxes3_num"] == "3"
    assert settled["MatrixTextBoxes3_num"] != LIVE_PARTS[1]
    # The other four are right, which is exactly why it read as success.
    assert [settled[cell] for cell in LIVE_CELLS] == ["0", "3", "8", "5", "3"]


# --- the writer that replaced it --------------------------------------------


def test_every_part_settles_in_its_own_cell() -> None:
    """The whole fix, against the page that broke the old one."""
    live = page()

    reported = write(live)

    assert reported["ok"] is True
    assert reported["code"] == "entered-table-cells"
    assert reported["cells"] == LIVE_CELLS
    assert cellsNow(live) == {
        "MatrixTextBoxes8_num": "0",
        "MatrixTextBoxes3_num": "8",
        "MatrixTextBoxes10_num": "8",
        "MatrixTextBoxes11_num": "5",
        "MatrixTextBoxes6_num": "3",
    }


def test_the_pages_own_models_settle_with_the_same_five_parts() -> None:
    """Success is five page-owned states, not five write calls that returned."""
    live = page()

    reported = write(live)

    assert reported["settled"] == 5
    assert reported["models"] == 5
    assert dict(buffers(live)) == dict(zip(LIVE_CELLS, LIVE_PARTS))


def test_a_stale_selection_pointing_at_the_wrong_model_is_corrected() -> None:
    """The live starting state, and every wrong one: the writer selects.

    `focusedElementIndex` begins on some other cell's control -- or on the
    hidden option control beside one, or nowhere at all -- and none of that may
    reach the answers.
    """
    for focused in (0, 3, 8, -1):
        live = page(focused=focused)

        reported = write(live)

        assert reported["ok"] is True, focused
        assert cellsNow(live)["MatrixTextBoxes3_num"] == "8", focused
        assert reported["selected"] == ["focus"] * 5, focused


def test_writing_a_later_part_cannot_overwrite_an_earlier_cell() -> None:
    """The regression, stated as the thing that must not happen.

    Semantic order is not DOM order here -- the fifth part goes to the box the
    page writes second -- so a writer that has lost its place has every chance
    to put the last value in the first cell, which is what the old one did.
    """
    live = page()

    write(live)
    settled = cellsNow(live)

    for cell, part in zip(LIVE_CELLS, LIVE_PARTS):
        assert settled[cell] == part
    assert len({*LIVE_CELLS}) == 5
    assert LIVE_CELLS != sorted(LIVE_CELLS)


def test_a_cell_the_editor_moves_after_a_write_is_a_refusal() -> None:
    """If the page still crosses two cells, nothing is reported as inserted.

    The right control is selected and the page still rerenders a second cell
    from it: whatever is written into the fourth cell also lands in the first.
    That must end as a named refusal with the table put back, not as four parts
    and a shrug.
    """
    live = page()
    live.eval(
        "const controls = window.quant_wp_UI.controlsCollection;"
        "Object.defineProperty(controls[controlFor('MatrixTextBoxes11_num')],"
        " 'alsoRenders', {value: controls[controlFor('MatrixTextBoxes8_num')].field,"
        " enumerable: false, configurable: true});"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-crossed"
    assert reported["blank"] == 4
    assert reported["moved"] == 1
    assert reported.get("leftBehind") is None
    assert set(cellsNow(live).values()) == {""}


def test_a_cell_that_does_not_keep_its_part_is_a_refusal() -> None:
    """The page takes the write and settles on something else."""
    live = page()
    live.eval(
        "const box = document.getElementById('MatrixTextBoxes10_num');"
        "box.render = () => { box._value = '7'; };"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-not-settled"
    assert reported["where"] == "cell"
    assert reported["blank"] == 3


def test_a_model_that_settles_on_something_else_is_a_refusal() -> None:
    """The box agrees and the control does not: the two readings disagree."""
    live = page()
    live.eval(
        "const control = window.quant_wp_UI.controlsCollection"
        "[controlFor('MatrixTextBoxes3_num')];"
        "control.boxValue = function () { return 'x'; };"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-not-settled"
    assert reported["where"] == "model"
    assert reported["blank"] == 2


# --- resolving a cell to exactly one page-owned control ---------------------


def test_a_cell_is_tied_to_a_control_by_the_element_it_owns() -> None:
    live = page(link="element")

    reported = write(live)

    assert reported["ownership"] == ["element"] * 5


def test_a_cell_is_tied_to_a_control_by_the_cell_around_it() -> None:
    """The live shape: the control publishes the cell, which holds one box."""
    live = page(link="cell")

    reported = write(live)

    assert reported["ownership"] == ["cell"] * 5


def test_a_cell_with_no_element_link_is_tied_by_the_name_it_publishes() -> None:
    for names, expected in (("id", "id"), ("base", "name")):
        live = page(link="none", names=names)

        reported = write(live)

        assert reported["ownership"] == [expected] * 5, names


def test_a_cell_with_no_control_at_all_refuses_before_writing() -> None:
    """No unique model is not a reason to write by position."""
    live = page(link="none", names="none")

    reported = write(live)

    assert reported == {"ok": False, "code": "table-cell-model-missing", "blank": 1}
    assert set(cellsNow(live).values()) == {""}


def test_two_cells_resolving_to_one_control_refuse_before_writing() -> None:
    live = page(link="none")
    live.eval(
        "const rows = window.quant_wp_UI.controlsCollectionData;"
        "rows[controlFor('MatrixTextBoxes6_num')].Name ="
        " rows[controlFor('MatrixTextBoxes3_num')].Name;"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] in {"table-cell-model-ambiguous", "table-cell-model-shared"}
    assert set(cellsNow(live).values()) == {""}


def test_a_control_that_claims_another_cell_more_strongly_refuses() -> None:
    """Ownership is checked in both directions, and a disagreement refuses."""
    live = page(link="none")
    live.eval(
        # The second cell's control publishes the first cell's exact id as well
        # as its own base name, and claims the first more strongly than the one
        # it was matched on.
        "const rows = window.quant_wp_UI.controlsCollectionData;"
        "const row = rows[controlFor('MatrixTextBoxes3_num')];"
        "row.Name = 'MatrixTextBoxes3';"
        "row.Other = 'MatrixTextBoxes8_num';"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] in {
        "table-cell-model-ambiguous",
        "table-cell-model-disagrees",
        "table-cell-model-shared",
    }
    assert set(cellsNow(live).values()) == {""}


def test_the_hidden_option_control_beside_every_cell_is_never_an_answer() -> None:
    """Ten published controls, five answers: the other five are selections."""
    live = page()

    assert live.eval("window.quant_wp_UI.controlsCollection.length") == 10
    assert write(live)["ok"] is True


# --- the mapping still has to describe the page -----------------------------


def test_a_replaced_cell_refuses_before_anything_is_written() -> None:
    live = page()
    live.eval("fields.find(f => f.id === 'MatrixTextBoxes10_num').isConnected = false;")

    reported = write(live)

    assert reported == {"ok": False, "code": "table-target-missing", "blank": 3}
    assert set(cellsNow(live).values()) == {""}


def test_a_disabled_cell_refuses_before_anything_is_written() -> None:
    live = page()
    live.eval("fields.find(f => f.id === 'MatrixTextBoxes6_num').disabled = true;")

    reported = write(live)

    assert reported == {"ok": False, "code": "table-target-not-editable", "blank": 5}
    assert set(cellsNow(live).values()) == {""}


def test_a_hidden_internal_control_is_never_written_to() -> None:
    live = page()
    cells = [*LIVE_CELLS]
    cells[1] = "MatrixTextBoxes3_opt"

    reported = write(live, cells=cells)

    assert reported == {"ok": False, "code": "table-target-missing", "blank": 2}


def test_a_part_longer_than_its_own_cell_refuses() -> None:
    live = page()
    live.eval("fields.find(f => f.id === 'MatrixTextBoxes3_num').maxLength = 1;")

    reported = write(live, parts=["0", "88", "8", "5", "3"])

    assert reported == {"ok": False, "code": "answer-invalid", "blank": 2}


def test_one_cell_refusing_the_characters_stops_all_of_them() -> None:
    """The page's own objection, asked of every cell before any is changed."""
    live = page()
    live.eval("fields.find(f => f.id === 'MatrixTextBoxes6_num').accept = false;")

    reported = write(live)

    assert reported == {"ok": False, "code": "input-cancelled"}
    assert set(cellsNow(live).values()) == {""}


def test_a_cell_lost_between_two_writes_puts_the_others_back() -> None:
    """Paced entry runs for seconds; a cell can go while another is typed."""
    live = page()
    live.eval(
        "const watched = fields.find(f => f.id === 'MatrixTextBoxes8_num');"
        "const render = watched.render.bind(watched);"
        "watched.render = (text) => { render(text);"
        " fields.find(f => f.id === 'MatrixTextBoxes3_num').isConnected = false; };"
    )

    reported = write(live)

    assert reported["ok"] is False
    assert reported["code"] == "table-target-missing"
    assert reported["blank"] == 2
    assert reported["written"] == 1
    # And the cell that had already taken its part is put back as it was.
    assert cellsNow(live)["MatrixTextBoxes8_num"] == ""


def test_a_dialog_over_the_page_refuses_without_writing() -> None:
    live = page()
    live.eval("globalThis.dialogs = [new Element({id: 'customMessageBox'})];")

    assert write(live) == {"ok": False, "code": "editor-dialog-open"}


def test_a_page_with_no_editor_model_refuses() -> None:
    live = page()
    live.eval("delete window.quant_wp_UI;")

    assert write(live) == {"ok": False, "code": "editor-model-missing"}


def test_two_blanks_naming_one_control_are_refused() -> None:
    live = page()
    cells = [*LIVE_CELLS]
    cells[4] = cells[0]

    assert write(live, cells=cells) == {"ok": False, "code": "answer-invalid"}


def test_a_write_off_the_allowed_origin_never_happens() -> None:
    live = page()
    live.eval("window.location.origin = 'https://example.com';")

    assert write(live) == {"ok": False, "code": "wrong-site"}


# --- what a report may carry ------------------------------------------------


def test_no_cell_text_ever_leaves_the_page() -> None:
    """The reads are comparisons made in the page's own world, and stay there.

    The old writer was forbidden from reading a cell at all; this one reads one
    back to prove it settled. What replaces that rule is this: names, counts,
    booleans and reason codes cross, and no cell's contents do -- neither the
    parts it just wrote nor whatever a control was carrying before.
    """
    live = page()
    live.eval("fields.find(f => f.id === 'MatrixTextBoxes3_num')._value = 'kept41';")

    reported = json.dumps(write(live))

    assert "kept41" not in reported
    for part in {*LIVE_PARTS}:
        assert f'"{part}"' not in reported
    assert json.loads(reported)["ok"] is True


def test_the_writer_reports_how_it_reached_the_page() -> None:
    """A live refusal has to be diagnosable without a screenshot of coursework."""
    live = page()

    reported = write(live)

    assert set(reported) == {
        "ok",
        "code",
        "cells",
        "settled",
        "models",
        "expanded",
        "ownership",
        "selected",
        "timing",
    }
    assert reported["selected"] == ["focus"] * 5
    assert reported["timing"]["notes"] == 5


# --- one logical cell, two physical inputs ----------------------------------
#
# Facet solved a four-blank table exactly -- 16/9, -8/3, 1/3, 34/9 -- and every
# answer was proved right by hand. Hawkes draws one box per blank; typing `/`
# turns that one box into a numerator and a denominator, so the finished table
# has four semantic blanks and eight physical inputs. Read as eight answers it
# renumbers everything after the first fraction; refused as "two controls in a
# cell" it made the whole table unreadable and took Insert with it.

#: The four cells of the live fraction table, in semantic blank order.
FRACTION_CELLS = [
    "MatrixTextBoxes2_num",
    "MatrixTextBoxes8_num",
    "MatrixTextBoxes9_num",
    "MatrixTextBoxes5_num",
]
#: Its exact answers.
FRACTION_PARTS = ["16/9", "-8/3", "1/3", "34/9"]
#: Markup order, which is what Hawkes numbers its controls by.
FRACTION_DOM = [
    "MatrixTextBoxes2_num",
    "MatrixTextBoxes5_num",
    "MatrixTextBoxes8_num",
    "MatrixTextBoxes9_num",
]


def fraction_page(**options):
    context = quickjs.Context()
    context.eval(PAGE)
    context.eval(WRITER)
    context.eval(f"buildTable({json.dumps(FRACTION_DOM)}, {json.dumps(options)});")
    return context


def test_a_four_blank_table_starts_as_four_inputs() -> None:
    """The cells' second boxes exist in the model and are not drawn."""
    live = fraction_page()

    assert inputsNow(live) == FRACTION_DOM
    assert live.eval("window.quant_wp_UI.controlsCollection.length") == 8


def test_every_fraction_settles_in_the_cell_it_belongs_to() -> None:
    """Four blanks in, four blanks out, eight inputs on the page."""
    live = fraction_page()

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert reported["settled"] == 4
    assert reported["expanded"] == 4
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, FRACTION_PARTS))
    assert len(inputsNow(live)) == 8, "four cells, showing both halves each"


def test_the_slash_opens_the_cell_and_the_rest_is_typed_in_the_other_half() -> None:
    """The transition, box by box: `16` then `/` then `9`."""
    live = fraction_page()

    write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert live.eval("document.getElementById('MatrixTextBoxes2_num')._value") == "16"
    assert live.eval("document.getElementById('MatrixTextBoxes2_den')._value") == "9"
    assert live.eval("document.getElementById('MatrixTextBoxes2_den').visible") is True


def test_the_pages_own_models_hold_both_halves() -> None:
    """Each half is its own control's buffer, and each cell is still one blank."""
    live = fraction_page()

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["models"] == 4, "the mapped control holds the numerator"
    assert dict(buffers(live)) == {
        "MatrixTextBoxes2_num": "16",
        "MatrixTextBoxes8_num": "-8",
        "MatrixTextBoxes9_num": "1",
        "MatrixTextBoxes5_num": "34",
    }
    halves = json.loads(
        live.eval(
            "JSON.stringify(window.quant_wp_UI.controlsCollection"
            ".filter(c => c.buffer !== undefined && c.field.kind === 'den')"
            ".map(c => [c.field.id, c.buffer]))"
        )
    )
    assert dict(halves) == {
        "MatrixTextBoxes2_den": "9",
        "MatrixTextBoxes8_den": "3",
        "MatrixTextBoxes9_den": "3",
        "MatrixTextBoxes5_den": "9",
    }


def test_a_later_fraction_never_disturbs_an_earlier_cell() -> None:
    """Semantic order is not markup order, and the last cell is the second box."""
    live = fraction_page()

    write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)
    settled = cellsNow(live)

    assert FRACTION_CELLS != FRACTION_DOM
    for cell, part in zip(FRACTION_CELLS, FRACTION_PARTS):
        assert settled[cell] == part


def test_a_cell_already_showing_a_fraction_is_written_whole() -> None:
    """Someone typed one in by hand, or a previous run left one there."""
    live = fraction_page()
    live.eval(
        "const box = document.getElementById('MatrixTextBoxes8_num');"
        "const den = document.getElementById('MatrixTextBoxes8_den');"
        "den.visible = true; box._value = '7'; den._value = '2';"
        "const controls = window.quant_wp_UI.controlsCollection;"
        "controls[controlFor('MatrixTextBoxes8_num')].buffer = '7';"
        "controls[controlFor('MatrixTextBoxes8_num')].half.buffer = '2';"
    )

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, FRACTION_PARTS))


def test_a_plain_integer_table_is_written_exactly_as_before() -> None:
    """The path that works must not have changed."""
    live = page()

    reported = write(live)

    assert reported["ok"] is True
    assert reported["expanded"] == 0
    assert cellsNow(live) == dict(zip(LIVE_CELLS, LIVE_PARTS))
    assert len(inputsNow(live)) == 5, "no cell was opened"


def test_a_cell_that_will_not_open_its_other_half_refuses() -> None:
    """Unexpected topology is still a refusal, with the table put back."""
    live = fraction_page()
    live.eval("globalThis.__hawkesInput = (event) => { event.target.render(''); };")

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is False
    assert reported["code"] in {
        "table-cell-not-expandable",
        "table-cell-not-selected",
        "table-cell-not-settled",
    }
    assert set(cellsNow(live).values()) == {""}


def test_a_part_whose_halves_cannot_fit_their_boxes_refuses() -> None:
    """Each half is bounded by its own box, not the part by one of them."""
    live = fraction_page()
    live.eval("document.getElementById('MatrixTextBoxes9_num').maxLength = 2;")

    reported = write(
        live, parts=["16/9", "-8/3", "100/3", "34/9"], cells=FRACTION_CELLS
    )

    assert reported == {"ok": False, "code": "answer-invalid", "blank": 3}
    assert set(cellsNow(live).values()) == {""}


def test_a_five_character_fraction_fits_two_four_character_boxes() -> None:
    """`100/9` never fits one box and fits these two exactly."""
    live = fraction_page()

    reported = write(live, parts=["100/9", "-8/3", "1/3", "34/9"], cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert cellsNow(live)["MatrixTextBoxes2_num"] == "100/9"


# --- the mixed table, which is what the page actually shows ------------------
#
# Live, on 2026-09-07, with the answers `8/5, -2, 7/4, 12/5` on screen: one
# semantic cell already expanded into a numerator and a denominator by hand,
# the other three still single boxes, and four values to place. Three runs
# refused with nothing written at all --
#
#     table-answer-not-placed {"code":"table-cell-not-selected","blank":1,
#                              "written":0,"leftBehind":true,"cells":4}
#
# -- and a fourth got two cells in before refusing at blank 3, which is the
# same failure arriving one fraction later. Hawkes keeps element references to
# a drawn fraction's two halves; the selection proof required *every* element
# the model published to name the cell it was about, so one fraction anywhere
# in the table made every cell of it unselectable.


def test_a_cell_expanded_before_the_run_does_not_block_the_first_blank() -> None:
    """The exact live state: written=0, blank 1, three runs running."""
    live = fraction_page(showing=["MatrixTextBoxes5_num"])

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert reported["settled"] == 4
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, FRACTION_PARTS))


def test_the_page_still_holds_the_expanded_cells_halves_throughout() -> None:
    """The references are furniture. They are not a selection and never were."""
    live = fraction_page(showing=["MatrixTextBoxes5_num"])

    assert (
        live.eval("window.quant_wp_UI.fractionNumerator.id") == "MatrixTextBoxes5_num"
    )
    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    # Left behind by the page, pointing at a cell that is not the last one
    # written -- which is precisely the state that used to refuse everything.
    assert live.eval("window.quant_wp_UI.fractionDenominator.id").endswith("_den")


def test_a_mixed_table_of_fractions_and_whole_numbers_is_placed() -> None:
    """`8/5, -2, 7/4, 12/5`: the answers that were on screen."""
    live = fraction_page(showing=["MatrixTextBoxes5_num"])
    parts = ["8/5", "-2", "7/4", "12/5"]

    reported = write(live, parts=parts, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, parts))
    # One of the four is a whole number and must not have opened a pair.
    assert live.eval("document.getElementById('MatrixTextBoxes8_den').visible") is False


def test_every_cell_expanded_before_the_run_is_still_four_blanks() -> None:
    """The finished table, re-answered: eight inputs, four values."""
    live = fraction_page(showing=FRACTION_DOM)

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, FRACTION_PARTS))


def test_a_stale_reference_still_never_excuses_writing_the_wrong_cell() -> None:
    """Presence is weaker than unanimity, and must not be weaker than this.

    The failure the selection proof exists to catch: the page is editing some
    other cell, and this writer must not accept that as editing the one it
    means. A leftover fraction reference does not change that -- the page
    never names the intended cell at all.
    """
    live = fraction_page(showing=["MatrixTextBoxes5_num"])
    # The page is editing blank 2's cell, holds an expanded cell's halves
    # elsewhere, and nothing this writer does will move it: Hawkes' own focus
    # handling never runs, which is the live condition the panel creates.
    live.eval(
        "const ui = window.quant_wp_UI;"
        "globalThis.__hawkesFocus = () => {};"
        "ui.focusedElement = document.getElementById('MatrixTextBoxes8_num');"
        "ui.focusedElementIndex = controlFor('MatrixTextBoxes8_num');"
    )

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-not-selected"
    # And it says which half of the proof failed, rather than only that one did.
    assert reported["why"] in {"mirror", "router"}
    assert reported["routed"]


# --- the state the page was actually in --------------------------------------
#
# Reloaded onto the fix above, the live refusal named its own gate:
#
#     table-answer-not-placed {"code":"table-cell-not-selected","blank":1,
#       "written":0,"expanded":true,"why":"mirror",
#       "mirrorIndex":1,"wantedIndex":0,"routed":[]}
#
# Two facts the harness did not have. The page publishes no element-valued
# property this add-on can enumerate -- the router half of the proof reads back
# empty and the mirror is the whole of the evidence. And a cell already showing
# a fraction is being edited through its *denominator's* control, so demanding
# the cell's own control by name refused a table nobody had touched yet.


def live_page(**options):
    """The exact shape of the live grid: one expanded cell, no router."""
    return fraction_page(showing=["MatrixTextBoxes2_num"], router="none", **options)


def test_the_page_publishes_no_router_and_the_mirror_is_on_the_denominator():
    """Both halves of what the live refusal reported."""
    live = live_page()

    assert (
        live.eval(
            "Object.keys(window.quant_wp_UI).filter("
            " k => window.quant_wp_UI[k] && window.quant_wp_UI[k].nodeType === 1).length"
        )
        == 0
    )
    assert live.eval("window.quant_wp_UI.focusedElement.id") == "MatrixTextBoxes2_den"
    assert live.eval("window.quant_wp_UI.focusedElementIndex") == 1


def test_the_expanded_first_blank_no_longer_refuses_the_whole_table() -> None:
    """`blank 1, written 0` -- the refusal this state produced, three runs."""
    live = live_page()

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert reported["settled"] == 4
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, FRACTION_PARTS))


def test_the_answers_that_were_on_the_owners_screen_go_in() -> None:
    """`9/4, -9/2, 3/2, 17/4`, into a grid whose first blank is expanded."""
    live = live_page()
    parts = ["9/4", "-9/2", "3/2", "17/4"]

    reported = write(live, parts=parts, cells=FRACTION_CELLS)

    assert reported["ok"] is True
    assert cellsNow(live) == dict(zip(FRACTION_CELLS, parts))


def test_a_cell_is_never_written_through_the_half_the_page_happens_to_be_in():
    """Accepting either half as "this cell" typed the numerator into the den.

    The proof is asked of one exact box, because every write is aimed at one:
    the denominator is cleared through the denominator, and the value is then
    typed through the cell's own box, each one proven separately.
    """
    live = live_page()

    write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    halves = json.loads(
        live.eval(
            "JSON.stringify(window.quant_wp_UI.controlsCollection"
            ".filter(c => c.buffer !== undefined)"
            ".map(c => c.buffer))"
        )
    )
    # Every half holds its own digits, and none holds the other's.
    assert "16" in halves and "9" in halves
    assert not any("/" in half for half in halves)


def test_the_mirror_alone_still_refuses_a_page_editing_another_cell() -> None:
    """With no router to read, the mirror carries the whole proof."""
    live = live_page()
    live.eval(
        "globalThis.__hawkesFocus = () => {};"
        "window.quant_wp_UI.focusedElementIndex = controlFor('MatrixTextBoxes8_num');"
    )

    reported = write(live, parts=FRACTION_PARTS, cells=FRACTION_CELLS)

    assert reported["ok"] is False
    assert reported["code"] == "table-cell-not-selected"
    assert reported["why"] == "mirror"
    assert reported["routed"] == []
