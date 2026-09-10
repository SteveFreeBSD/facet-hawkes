"""Which writer places an answer, and why it cannot be decided from the answer.

The policy this pins replaced one sentence in `background.js`:

    const typeable = reviewed && answerFitsEditor(reviewed, editor).insertable;
    if (!typeable) { buildStructured(...); } else { enterPlainAnswer(...); }

-- "if the characters happen to be directly typeable, write them through the
DOM; otherwise ask the Hawkes editor to build them". One question's editor
therefore had two writers, and the answer picked between them: `5` and `1/5`
went into the same box by different machinery, with different failure modes,
and the log recorded the shape of the answer rather than the route it took.

It is also wrong about the editor. A digit is not merely *acceptable* to a
Hawkes dynamic editor -- it is one of that editor's own operations.
`keyPadButtonClick(name)` delegates to `addElement(name, true, callback)`,
whose ordinary-character branch validates the character against the slot the
editor is in, updates the page-owned `Base`, focuses it, and runs Hawkes' own
change handler. The DOM setter reaches the same box and bypasses all of it.

So: **the page's own answer model chooses the transport, and the answer is
then checked against the transport it chose.** The tests below are in three
groups -- the policy itself, the writer performing each transport, and the
event page routing to them -- and the first group is the one that makes the old
policy unrepresentable rather than merely absent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from test_hawkes_insertion_ownership import (  # noqa: F401  (page is a fixture)
    EDITOR_OK,
    QUESTION_A,
    make_page,
    page,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"
COMMON = EXTENSION / "common"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


def load(ctx, *names):
    for name in names:
        source = (COMMON / name).read_text()
        source = re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M)
        ctx.eval(re.sub(r"^export ", "", source, flags=re.M))


def value(ctx, expression):
    return json.loads(ctx.eval(f"JSON.stringify({expression})"))


# --- the policy ------------------------------------------------------------


@pytest.fixture
def policy():
    ctx = quickjs.Context()
    load(ctx, "transport.js")
    return ctx


def chosen(ctx, editor, **page_facts):
    return value(
        ctx,
        f"chooseTransport({json.dumps(editor)}, {json.dumps(page_facts)})",
    )


DYNAMIC = {"ok": True, "kind": "dynamic", "allowedCharacters": "0123456789xy"}
TEXTBOX = {"ok": True, "kind": "textbox", "allowedCharacters": "[0-9-]"}


def test_the_policy_cannot_see_the_answer_at_all(policy):
    """The strongest form of "it cannot drift back": there is nothing to drift.

    `chooseTransport` takes the editor the page published and the facts the
    page stated about itself. It is handed no answer, no plan and no character
    set, so "if directly typeable" is not a sentence that can be written in it.
    """
    source = (COMMON / "transport.js").read_text()
    assert "export function chooseTransport(editor, page = {}) {" in source
    # One required argument, and it is the editor the page published.
    assert value(policy, "chooseTransport.length") == 1

    # Nothing that could tell it what the answer is, anywhere in the code --
    # not as an argument, not as an import, not as a check it makes itself.
    # Its prose quotes the policy it replaced, so the prose is removed first.
    code = re.sub(r"/\*[\s\S]*?\*/|//.*", "", source)
    for forbidden in (
        "answerFitsEditor",
        "insertable",
        "planEntry",
        "allowedCharacters",
        "validateAnswer",
        "import ",
    ):
        assert forbidden not in code, f"the policy can reach {forbidden!r}"


@pytest.mark.parametrize(
    "answer", ["5", "1/5", "x^6yz^5", "-3/2", "sqrt(30)*y/30", "1,-4"]
)
def test_one_editor_has_one_transport_whatever_the_answer_is(policy, answer):
    """The defect, stated as a test: these six answers used to take two routes."""
    first = chosen(policy, DYNAMIC)
    assert first == {
        "ok": True,
        "transport": "hawkes-dynamic-keypad",
        "world": "MAIN",
        "writer": "enterPlan",
    }
    # The answer is not an argument, so it cannot change the decision. Asked
    # again with it in hand, and it still cannot.
    assert chosen(policy, DYNAMIC, answer=answer) == first


def test_the_policy_table_is_the_page_model_and_nothing_else(policy):
    assert chosen(policy, DYNAMIC)["transport"] == "hawkes-dynamic-keypad"
    assert chosen(policy, TEXTBOX)["transport"] == "hawkes-plain-box"
    # The one page fact outside the editor model that changes the route: a
    # MathQuill-style editor is a contenteditable element, and the box writer
    # has no box to write into.
    assert (
        chosen(policy, TEXTBOX, fieldKind="contenteditable")["transport"]
        == "native-contenteditable"
    )
    # A completion table's cells are plain boxes; what differs is that each is
    # routed through a control the page has selected.
    assert (
        chosen(policy, TEXTBOX, tableTargets=[{"blank": 1}, {"blank": 2}])["transport"]
        == "hawkes-table-cells"
    )
    assert chosen(policy, {"ok": True, "kind": "graph"})["transport"] == "hawkes-graph"


def test_several_fields_are_routed_by_what_kind_of_fields_they_are(policy):
    dynamic_pair = {"ok": True, "kind": "multi", "editors": [DYNAMIC, DYNAMIC]}
    plain_pair = {"ok": True, "kind": "multi", "editors": [TEXTBOX, TEXTBOX]}
    assert chosen(policy, dynamic_pair)["transport"] == "hawkes-dynamic-keypad"
    # Several plain boxes are several page-owned controls, routed by the one
    # Hawkes has selected -- so they are written from the page's own world, by
    # the writer a completion table's cells take. An isolated writer can focus
    # a box and cannot select it, and live its parts arrived cumulative and
    # crossed between the boxes.
    assert chosen(policy, plain_pair) == {
        "ok": True,
        "transport": "hawkes-plain-fields",
        "world": "MAIN",
        "writer": "enterOwnedFields",
    }
    # Two editors of different kinds need two writers for one answer, and there
    # is no route that is both. Refused by name rather than resolved by
    # whichever half the answer happened to suit.
    mixed = {"ok": True, "kind": "multi", "editors": [DYNAMIC, TEXTBOX]}
    assert chosen(policy, mixed) == {"ok": False, "code": "editor-mixed-transports"}


def test_a_question_answered_by_choosing_has_no_transport(policy):
    """Selecting an option is answering, not filling a field in."""
    assert chosen(policy, {"ok": True, "kind": "option"})["code"] == (
        "editor-option-answer"
    )
    group = {
        "ok": True,
        "kind": "multi",
        "editors": [{"ok": True, "kind": "option"}, TEXTBOX],
    }
    assert chosen(policy, group)["code"] == "editor-option-answer"


def test_an_unreadable_editor_names_its_own_reason(policy):
    assert chosen(policy, None) == {"ok": False, "code": "editor-unknown"}
    assert chosen(policy, {"ok": False, "code": "editor-model-missing"}) == {
        "ok": False,
        "code": "editor-model-missing",
    }
    assert chosen(policy, {"ok": True, "kind": "something-new"})["code"] == (
        "editor-unknown"
    )


def test_the_old_policy_is_gone_from_the_event_page(policy):
    """It is not enough that a new one exists; the old sentence must be absent."""
    background = (EXTENSION / "background.js").read_text()
    assert "answerFitsEditor(reviewed, editor).insertable" not in background
    assert "const typeable = " not in background
    # `multiEntryPlans` used to return `plain`, read as a router by its caller.
    assert "plain: direct.every(Boolean)" not in background
    assert "directlyTypeable: direct.every(Boolean)" in background
    # Every branch that writes states which transport it is, and every
    # transport the policy names is stated by one -- so no writer is reached by
    # falling through to whichever branch happens to be written next, and no
    # transport is named that nothing performs.
    checked = set(re.findall(r'transportMatches\(routed, "([\w-]+)"\)', background))
    assert checked == set(value(policy, "Object.keys(TRANSPORTS)"))


# --- the writer ------------------------------------------------------------

#: One Hawkes editor, with the same entry point for characters and templates.
#:
#: `keyPadButtonClick` writes an ordinary character into the slot its own
#: `CurrentBase` owns, and refuses one outside the question's set, which is what
#: makes "the character landed in the box the plan meant" a real assertion here.
EDITOR_PAGE = """
var now = 0, timers = [];
var performance = {now: () => now};
Date.now = () => now;
var setTimeout = (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t; };
var clearTimeout = t => { timers = timers.filter(item => item !== t); };
var completed = null;
var pressed = [];      // every keyPadButtonClick, in order
var assigned = [];     // every value written through the prototype setter
var dispatched = [];   // every event delivered to a box
var serial = 0;
var allowed = '0123456789xy-+,';

class InputEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class KeyboardEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class Event { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class FocusEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class CustomEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }

class HTMLInputElement {
  constructor(id) { this.id = id; this.held = ''; this.className = 'qbaseCSS'; }
  get value() { return this.held; }
  set value(v) { assigned.push([this.id, v]); this.held = v; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return {width: 100, height: 20}; }
  dispatchEvent(event) { dispatched.push([this.id, event.type]); return true; }
}

var boxes = {}, bases = {}, order = [];
var control = {
  enabled: true,
  arrChildObjects: [],
  keyPadButtonClick(name) {
    pressed.push(name);
    if (name === 'Exponent' || name === 'Fraction') {
      const slot = addBox('slot' + (++serial));
      addBox('slot' + (++serial));
      setTimeout(() => {
        document.activeElement = slot;
        if (globalThis.__aims !== false) { control.CurrentBase = bases[slot.id]; }
      }, 60);
      return;
    }
    if (name === 'Clear') { for (const id of order) { boxes[id].held = ''; } return; }
    const base = control.CurrentBase;
    const box = base && base.objMyDiv.querySelector('input.qbaseCSS');
    // The editor's own validation, in the slot the editor is actually in.
    if (box && allowed.indexOf(name) >= 0) { box.held += name; }
  },
};

function addBox(id) {
  boxes[id] = new HTMLInputElement(id);
  order.push(id);
  bases[id] = {
    Type: 'Base',
    loadExponent() {}, loadFraction() {},
    qualifyLoadExponent: () => boxes[id].held.length > 0,
    qualifyLoadFraction: () => true,
    objMyDiv: {querySelector: () => boxes[id]},
    // A page that does not move its own editor is the fixture's `aims` flag:
    // the characters then land wherever the editor still was.
    setFocus() { if (globalThis.__aims !== false) { control.CurrentBase = bases[id]; } },
    arrChildObjects: [],
  };
  control.arrChildObjects.push(bases[id]);
  return boxes[id];
}

var document = {
  activeElement: null,
  getElementById: id => boxes[id] ?? null,
  querySelectorAll: selector => selector.indexOf('customMessageBox') >= 0
    ? [] : order.map(id => boxes[id]),
  dispatchEvent: () => true,
};
var window = {quant_wp_UI: {controlsCollection: [control], focusedElementIndex: 0}};
addBox('QBase1_input');
control.CurrentBase = bases.QBase1_input;
"""


def editor_page(**flags):
    ctx = quickjs.Context()
    ctx.eval(EDITOR_PAGE)
    for key, flag in flags.items():
        ctx.eval(f"globalThis.__{key} = {json.dumps(flag)};")
    load(ctx, "cadence.js", "page-actions.js")
    return ctx


def perform(ctx, steps, transport):
    ctx.eval(
        f"var steps = {json.dumps(steps)};"
        " var phrase = ethnosCadence.planSemanticPhrase(steps,"
        " {durationMinMs: 200, durationMaxMs: 200});"
        f" enterPlan(steps, {{score: phrase}}, [], {json.dumps(transport)})"
        " .then(r => completed = r,"
        " e => completed = {ok: false, code: 'threw', detail: String(e)});"
    )
    for _ in range(20000):
        while ctx.execute_pending_job():
            pass
        if not ctx.eval("timers.length"):
            break
        ctx.eval(
            "timers.sort((a,b) => a.at-b.at); var t = timers.shift();"
            " now = Math.max(now, t.at); t.fn();"
        )
    else:
        pytest.fail("the writer did not terminate")
    return value(ctx, "completed")


def test_a_writer_told_no_transport_refuses_before_touching_the_page():
    """A caller that forgot to say cannot inherit whichever branch is first."""
    for transport in ("", "hawkes-plain-fields", "made-up"):
        live = editor_page()
        outcome = perform(live, [{"op": "type", "text": "12"}], transport)
        assert outcome["ok"] is False
        assert outcome["code"] == "transport-unavailable"
        assert value(live, "pressed") == []
        assert value(live, "assigned") == []


def test_every_dynamic_character_is_an_editor_operation():
    """Digits included -- the whole point. Nothing is assigned into the box."""
    live = editor_page()
    outcome = perform(live, [{"op": "type", "text": "12xy"}], "hawkes-dynamic-keypad")
    assert outcome["ok"] is True
    assert outcome["transport"] == "hawkes-dynamic-keypad"
    assert value(live, "pressed") == ["1", "2", "x", "y"]
    # Not one character reached the box any other way.
    assert value(live, "assigned") == []
    assert [event for _id, event in value(live, "dispatched") if event == "input"] == []
    assert value(live, "boxes.QBase1_input.held") == "12xy"
    assert outcome["timing"]["keypadWrites"] == 4
    assert outcome["timing"]["nativeWrites"] == 0


def test_a_plain_box_is_written_by_its_own_input_handling():
    """The other half of the policy: no keypad is pressed at a plain box."""
    live = editor_page()
    outcome = perform(live, [{"op": "type", "text": "12xy"}], "hawkes-plain-box")
    assert outcome["ok"] is True
    assert outcome["transport"] == "hawkes-plain-box"
    assert value(live, "pressed") == []
    assert [box for box, _value in value(live, "assigned")] == ["QBase1_input"] * 4
    assert value(live, "boxes.QBase1_input.held") == "12xy"
    # The box's own preflight is asked once for the run, then each character is
    # delivered as a whole key press -- `keydown`, the assignment, the `input`
    # its sanitiser runs inside, `keyup` -- and the box is committed with the
    # `change` that leaving it produces.
    #
    # The key events are not decoration. Live, on 2026-09-10, a value written
    # with `input` alone read back correctly and was then discarded by Hawkes,
    # which raised its own "Your answer seems incomplete" dialog and emptied
    # the box: the DOM held a value the page never owned.
    assert [event for _id, event in value(live, "dispatched")] == [
        "beforeinput",
        *["keydown", "input", "keyup"] * 4,
        "change",
    ]
    assert outcome["timing"]["nativeWrites"] == 4
    assert outcome["timing"]["keypadWrites"] == 0


def test_characters_and_templates_take_the_same_entry_point():
    """A structured answer is one sequence of editor operations, not two kinds."""
    live = editor_page()
    outcome = perform(
        live,
        [
            {"op": "type", "text": "x"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "12"},
        ],
        "hawkes-dynamic-keypad",
    )
    assert outcome["ok"] is True
    assert value(live, "pressed") == ["x", "Exponent", "1", "2"]
    assert value(live, "assigned") == []
    assert value(live, "boxes.QBase1_input.held") == "x"
    assert value(live, "boxes.slot1.held") == "12"


def test_a_character_the_editor_refuses_names_itself_and_leaves_nothing():
    live = editor_page()
    outcome = perform(live, [{"op": "type", "text": "1z"}], "hawkes-dynamic-keypad")
    assert outcome["ok"] is False
    assert outcome["code"] == "answer-has-rejected-characters"
    assert outcome["detail"] == "z"
    # Cleared through the editor's own Clear, so no half-answer is left behind.
    assert value(live, "boxes.QBase1_input.held") == ""
    assert outcome.get("leftBehind") is None


def test_a_character_that_lands_in_another_box_is_a_refusal_not_a_success():
    """The keypad writes where the *editor's* cursor is, not where focus is.

    `setFocus` doing nothing is a page that will not move its own editor, so
    the exponent's digits land back in the base. The read-back asks the box the
    plan meant, which is what turns a wrong answer into a refusal.
    """
    live = editor_page(aims=False)
    outcome = perform(
        live,
        [
            {"op": "type", "text": "x"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "12"},
        ],
        "hawkes-dynamic-keypad",
    )
    assert outcome["ok"] is False
    assert outcome["code"] == "answer-has-rejected-characters"
    assert outcome["detail"] == "1"
    assert value(live, "boxes.slot1.held") == ""


def test_a_step_belonging_to_the_other_editor_is_refused_by_name():
    """A plan and a transport that disagree about which editor this is."""
    live = editor_page()
    outcome = perform(
        live,
        [{"op": "type", "text": "x"}, {"op": "template", "name": "Exponent"}],
        "hawkes-plain-box",
    )
    assert outcome["ok"] is False and outcome["code"] == "transport-step-mismatch"

    live = editor_page()
    outcome = perform(
        live,
        [{"op": "type", "text": "3"}, {"op": "slash"}, {"op": "type", "text": "2"}],
        "hawkes-dynamic-keypad",
    )
    assert outcome["ok"] is False and outcome["code"] == "transport-step-mismatch"


def test_a_page_showing_two_answers_is_refused_before_anything_is_written():
    """The guard the isolated writer had, asked of the boxes themselves."""
    live = editor_page()
    live.eval("addBox('QBase2_input');")
    outcome = perform(live, [{"op": "type", "text": "12"}], "hawkes-dynamic-keypad")
    assert outcome["ok"] is False and outcome["code"] == "editor-multiple-answer"
    assert value(live, "pressed") == []


# --- the event page routing to them ----------------------------------------

PLAIN_BOX_EDITOR = {**EDITOR_OK, "kind": "textbox", "allowedCharacters": "0123456789y"}


def route(page, editor, answer="3y", field_kind="native"):  # noqa: F811
    """Run one insertion to the point of its write, and report how it went."""
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved",
          windowId: 1, tabId: 11, frameId: 0, fieldId: "txtAns1",
          fieldKind: {json.dumps(field_kind)},
          editor: {json.dumps(editor)},
          answer: {json.dumps(answer)},
          displayText: {json.dumps(answer)},
          entryText: {json.dumps(answer)},
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        insert();
        """
    )
    page.pump()
    page.answer(editor)  # describeEditor
    page.answer(QUESTION_A)  # the signature re-check
    return page


def test_a_directly_typeable_answer_still_goes_through_the_dynamic_editor(page):  # noqa: F811
    """`3y` fits the box exactly, and still takes the editor's own keypad."""
    route(page, EDITOR_OK)
    written = page.writes
    assert [call["func"] for call in written] == ["enterPlan"]
    assert written[0]["args"][0] == [{"op": "type", "text": "3y"}]
    assert written[0]["args"][3] == "hawkes-dynamic-keypad"
    chose = page.said("transport-chosen")
    assert chose[-1]["data"]["transport"] == "hawkes-dynamic-keypad"
    assert chose[-1]["data"]["world"] == "MAIN"


def test_a_plain_box_takes_the_box_writer_for_the_same_answer(page):  # noqa: F811
    route(page, PLAIN_BOX_EDITOR)
    written = page.writes
    assert [call["func"] for call in written] == ["enterPlan"]
    assert written[0]["args"][3] == "hawkes-plain-box"


def test_a_contenteditable_field_keeps_the_caret_writer(page):  # noqa: F811
    route(page, PLAIN_BOX_EDITOR, field_kind="contenteditable")
    # The caret writer runs in the add-on's own world, so its prelude is
    # refreshed immediately beforehand.
    page.answer({"ready": True, "code": "focused-answer-field", "fieldId": "txtAns1"})
    written = page.writes
    assert [call["func"] for call in written] == ["enterPlainAnswer"]
    assert page.said("transport-chosen")[-1]["data"]["world"] == "isolated"


def test_an_insertion_records_the_route_its_characters_actually_took(page):  # noqa: F811
    """Diagnostics name the mechanism, not the shape of the answer."""
    route(page, EDITOR_OK)
    page.answer(
        {
            "ok": True,
            "code": "entered",
            "entered": "3y",
            "transport": "hawkes-dynamic-keypad",
            "timing": {"keypadWrites": 2, "nativeWrites": 0, "notes": 2},
        }
    )
    page.answer(QUESTION_A)
    inserted = page.said("inserted")[-1]["data"]
    assert inserted["transport"] == "hawkes-dynamic-keypad"
    assert inserted["routedTo"] == "hawkes-dynamic-keypad"
    assert inserted["timing"]["keypadWrites"] == 2
    assert page.json("state.phase") == "inserted"


def test_a_question_with_no_route_is_refused_before_the_page_is_touched(page):  # noqa: F811
    """A control this add-on has no writer for is a refusal, not a best guess.

    The old policy had no such state: an editor it did not recognise published
    no character set, the answer therefore "did not fit", and the answer went
    to the structured builder to be refused there -- one step further into the
    page than it needed to go.
    """
    unknown = {**EDITOR_OK, "kind": "controlled-canvas"}
    route(page, unknown)
    assert page.writes == []
    assert page.said("transport-unavailable")[-1]["data"] == {
        "code": "editor-unknown",
        "editorKind": "controlled-canvas",
        "editors": 0,
        "fieldKind": "native",
        "blanks": 0,
    }
    assert page.json("state.phase") == "failed"
    assert page.json("state.errorKey") == "errorEditorUnknown"


# --- an entry the page discards is a failed insertion -----------------------
#
# Live, on 2026-09-10, on the box "One Solution" reveals. The character went
# in, the writer read it back from the box in the same turn, and the panel said
# the answer had been placed. Hawkes then raised its own modal --
#
#     Your answer seems incomplete.  Please try again.
#
# -- and emptied the box, while the log showed nothing after `inserted`,
# because the add-on had nothing more to do. Reading a box back in the turn
# that wrote it proves the assignment happened and nothing else; the page
# decides afterwards, from its own copy of the answer.
#
# These hold the writer to the page's verdict rather than to its own.


def discards_the_entry_on_commit(live):
    """Make the page take the entry back when the box is committed.

    This is the live shape: every character is accepted and reads back, and the
    page discards the lot when the box is finished with -- which is where a
    page that keeps its own copy of the answer decides whether it has one. A
    stub that emptied the box mid-typing would model something else entirely,
    and the per-character read-back already catches that.
    """
    live.eval(
        """
        var __box = boxes.QBase1_input;
        var __dispatch = __box.dispatchEvent.bind(__box);
        __box.dispatchEvent = event => {
          const result = __dispatch(event);
          if (event.type === 'change') { __box.held = ''; }
          return result;
        };
        """
    )


def test_a_value_the_page_takes_back_is_not_a_successful_insertion():
    """The live defect, at the writer that reported success for it."""
    live = editor_page()
    discards_the_entry_on_commit(live)

    outcome = perform(live, [{"op": "type", "text": "12xy"}], "hawkes-plain-box")

    assert outcome["ok"] is False
    assert outcome["code"] == "answer-did-not-persist"
    # Every character was accepted on the way in, which is exactly why the
    # same-turn read-back could not see this.
    assert outcome["timing"]["nativeWrites"] == 4


def test_a_value_the_page_keeps_still_succeeds():
    """The check must not refuse an entry that survived. Same writer, same
    characters, a page that leaves them alone."""
    live = editor_page()

    outcome = perform(live, [{"op": "type", "text": "12xy"}], "hawkes-plain-box")

    assert outcome["ok"] is True
    assert outcome["code"] == "entered"
    assert value(live, "boxes.QBase1_input.held") == "12xy"


def test_the_pages_own_dialog_is_a_refusal_however_the_box_reads():
    """Hawkes' modal is its verdict on the entry. A box that still shows the
    characters underneath an "incomplete" dialog has not been accepted."""
    live = editor_page()
    live.eval(
        "document.querySelectorAll = selector =>"
        " selector.indexOf('customMessageBox') >= 0"
        "   ? [{getBoundingClientRect: () => ({width: 300, height: 120})}]"
        "   : order.map(id => boxes[id]);"
    )

    outcome = perform(live, [{"op": "type", "text": "12xy"}], "hawkes-plain-box")

    assert outcome["ok"] is False
    assert outcome["code"] == "editor-dialog-open"


def test_the_keypad_transport_is_not_held_to_this():
    """It writes through the editor's own API, so what it entered is the
    editor's by construction. Unchanged, and not slowed by a settle it has no
    use for."""
    live = editor_page()

    outcome = perform(live, [{"op": "type", "text": "12xy"}], "hawkes-dynamic-keypad")

    assert outcome["ok"] is True
    assert outcome["timing"]["keypadWrites"] == 4
