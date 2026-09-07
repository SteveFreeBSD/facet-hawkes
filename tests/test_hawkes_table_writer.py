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
    return this.tagName === "INPUT" && this.kind === "box"
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
globalThis.buildTable = (ids, {focused = 0, link = "cell", names = "id"} = {}) => {
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
    const opt = new HTMLInputElement({id: id.replace(/_num$/, "") + "_opt", kind: "opt"});
    cell.appendChild(box);
    cell.appendChild(opt);
    globalThis.fields.push(box, opt);

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
    // The option control beside it: enabled, published, and never an answer.
    const option = {enabled: true, objMyDiv: cell};
    Object.defineProperty(option, "field",
      {value: opt, enumerable: false, configurable: true});
    controls.push(option);
    rows.push({isQDy: false, boxValue: undefined, enableState: true,
               Name: opt.id});
  }
  globalThis.window.quant_wp_UI = {
    // The authoritative router: the element Hawkes edits through. The index
    // beside it is a mirror of the same selection, and only the page's own
    // focus handling moves the two together.
    focusedElement: controls[focused] ? controls[focused].field : null,
    focusedElementIndex: focused,
    controlsCollection: controls,
    controlsCollectionData: rows,
  };
  return globalThis.window.quant_wp_UI;
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
  control.buffer = event.target.value;
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
    r"^export ", "", (EXTENSION / "common" / "table-actions.js").read_text(encoding="utf-8"),
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


def write(context, parts=None, cells=None, writer="enterTableCells"):
    """Run one writer to completion and return what it reported."""
    parts = parts or LIVE_PARTS
    cells = cells or LIVE_CELLS
    call = (
        f"enterTableCells({json.dumps(parts)}, {json.dumps(cells)}, "
        f"{json.dumps(score(parts))})"
        if writer == "enterTableCells"
        else f"{writer}({json.dumps(parts)}, {json.dumps(cells)})"
    )
    context.eval(f"globalThis.outcome = null; {call}.then(v => {{ outcome = v; }});")
    for _ in range(20000):
        if not context.execute_pending_job():
            break
    return json.loads(context.eval("JSON.stringify(outcome)"))


def cellsNow(context):
    """What every visible box holds, by id -- the settled page, not a caret."""
    return dict(
        json.loads(
            context.eval(
                "JSON.stringify(fields.filter(f => f.kind === 'box')"
                ".map(f => [f.id, f._value]))"
            )
        )
    )


def buffers(context):
    """What every page-owned control holds in its own model."""
    return json.loads(
        context.eval(
            "JSON.stringify(window.quant_wp_UI.controlsCollection"
            ".filter(c => c.buffer !== undefined).map(c => [c.field.id, c.buffer]))"
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
        "ok", "code", "cells", "settled", "models", "ownership", "selected", "timing",
    }
    assert reported["selected"] == ["focus"] * 5
    assert reported["timing"]["notes"] == 5
