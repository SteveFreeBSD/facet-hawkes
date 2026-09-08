"""A rational typed into an ordinary answer box that offers no template.

Live, on 2026-09-07: Facet Exact answered a question with a rational, Hawkes
presented one ordinary box publishing `[0-9-]` and not one keypad template, and
the add-on refused --

    editor   kind=textbox count=1 enabled=True maxLength=6  allowed '[0-9-]'
    refused  editor=answer-needs-template plan=template-refused-by-question
    route    source=Facet Exact router=solved

-- on the assumption that a question offering no Fraction template cannot take
a fraction. That is not what the page does. An ordinary Hawkes answer box turns
into a numerator and a denominator when a `/` is typed into it, which is how a
student enters one, and the same run said the box had a second control behind
it all along:

    collection {"branch":"one-drawn-box","controls":2,"usable":2,"drawn":1}

This is the generic single-answer editor, modelled as it really behaves: one
drawn box that splits when a `/` reaches it, a hidden denominator that becomes
real at that moment, and a page that moves its own editor there.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

quickjs = pytest.importorskip("quickjs")
COMMON = Path(__file__).resolve().parents[1] / "extension" / "common"

#: A Hawkes answer box, and the half a `/` opens behind it.
PAGE = """
var now = 0, timers = [];
var performance = {now: () => now};
Date.now = () => now;
var setTimeout = (fn, ms) => { const t = {fn, at: now + ms}; timers.push(t); return t; };
var clearTimeout = t => { timers = timers.filter(item => item !== t); };
var completed = null;
class InputEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class FocusEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }
class CustomEvent { constructor(type, options) { this.type = type; Object.assign(this, options); } }

class HTMLInputElement {
  constructor(id, shown) { this.id = id; this.held = ''; this.shown = shown; }
  get value() { return this.held; }
  set value(v) { this.held = v; }
  focus() { document.activeElement = this; }
  getBoundingClientRect() { return {width: this.shown ? 100 : 0, height: this.shown ? 20 : 0}; }
  dispatchEvent(event) {
    if (event.type === 'input') { globalThis.__pageInput(this); }
    if (event.type === 'focusin') { globalThis.__pageFocus(this); }
    return true;
  }
}

var numerator = new HTMLInputElement('txtAns1_num', true);
var denominator = new HTMLInputElement('txtAns1_den', false);
var everyBox = [numerator, denominator];

var document = {
  activeElement: null,
  getElementById: id => everyBox.find(box => box.id === id) ?? null,
  // Honours the selector, because which boxes a writer can see is exactly
  // what was wrong: a plain answer box is `txtAns1_num` and matches
  // `input[id^="txtAns"]`, not `input.qbaseCSS`.
  querySelectorAll: selector => {
    if (selector.indexOf('customMessageBox') >= 0) { return []; }
    return everyBox.filter(box =>
      (selector.indexOf('qbaseCSS') >= 0 && box.className === 'qbaseCSS')
      || (selector.indexOf('txtAns') >= 0 && box.id.indexOf('txtAns') === 0)
      || (selector.indexOf('boxStyle') >= 0 && box.className === 'boxStyle'));
  },
  dispatchEvent: () => true,
};

// The page's own input handling. A `/` reaching the numerator splits the box:
// the numerator keeps what came before it, the denominator becomes real, and
// the editor moves there -- which is exactly what it does for a table cell.
globalThis.__splits = true;
globalThis.__opensId = 'txtAns1_den';
globalThis.__movesItself = true;
globalThis.__pageInput = (box) => {
  const cut = box.held.indexOf('/');
  if (cut < 0 || box !== numerator) { return; }
  box.held = box.held.slice(0, cut);
  if (!globalThis.__splits) { return; }
  denominator.id = globalThis.__opensId;
  denominator.shown = true;
  if (globalThis.__movesItself) {
    document.activeElement = denominator;
    window.quant_wp_UI.focusedElementIndex = 1;
  }
};
globalThis.__pageFocus = (box) => {
  window.quant_wp_UI.focusedElementIndex = everyBox.indexOf(box);
};

var control = {
  enabled: true,
  keyPadButtonClick: () => { numerator.held = ''; denominator.held = ''; },
};
var window = {
  quant_wp_UI: {
    controlsCollection: [control, {enabled: true}],
    focusedElementIndex: 0,
  },
};
"""


def page(**options):
    ctx = quickjs.Context()
    ctx.eval(PAGE)
    for name in ("cadence.js", "page-actions.js"):
        source = (COMMON / name).read_text()
        source = re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M)
        ctx.eval(re.sub(r"^export ", "", source, flags=re.M))
    for key, value in options.items():
        ctx.eval(f"globalThis.__{key} = {json.dumps(value)};")
    return ctx


def pump(ctx):
    for _ in range(20000):
        while ctx.execute_pending_job():
            pass
        if not ctx.eval("timers.length"):
            return
        ctx.eval(
            "timers.sort((a,b) => a.at-b.at); var t = timers.shift();"
            " now = Math.max(now, t.at); t.fn();"
        )
    pytest.fail("the writer did not terminate")


def run(ctx, steps):
    ctx.eval(
        f"var steps = {json.dumps(steps)};"
        " var phrase = ethnosCadence.planSemanticPhrase(steps,"
        " {durationMinMs: 200, durationMaxMs: 200});"
        " enterPlan(steps, {score: phrase}).then(r => completed = r,"
        " e => completed = {ok: false, code: 'threw', detail: String(e)});"
    )
    pump(ctx)
    return json.loads(ctx.eval("JSON.stringify(completed)"))


def held(ctx) -> tuple[str, str]:
    return (
        ctx.eval("document.getElementById('txtAns1_num').value"),
        ctx.eval("denominator.value"),
    )


#: The plan the planner makes for a rational in a box with no Fraction template.
SLASH_PLAN = [
    {"op": "type", "text": "-3"},
    {"op": "slash"},
    {"op": "type", "text": "2"},
]


def test_a_rational_is_entered_through_the_pages_own_slash() -> None:
    """The live refusal, performed instead: `-3/2` into one ordinary box."""
    live = page()

    reported = run(live, SLASH_PLAN)

    assert reported["ok"] is True
    assert held(live) == ("-3", "2")


def test_the_denominator_box_is_the_one_the_page_opened() -> None:
    """Not a box found by position: the half named for this same answer."""
    live = page()

    run(live, SLASH_PLAN)

    assert live.eval("denominator.shown") is True
    assert live.eval("document.activeElement.id") == "txtAns1_den"


def test_a_box_that_does_not_split_is_refused_and_left_clean() -> None:
    """A page that takes the `/` and does nothing has not opened anything."""
    live = page(splits=False)

    reported = run(live, SLASH_PLAN)

    assert reported["ok"] is False
    assert reported["code"] == "fraction-not-expandable"
    assert held(live) == ("", "")


def test_a_box_that_opens_something_else_is_refused() -> None:
    """Ambiguous ownership fails closed rather than typing into a stranger."""
    live = page(opensId="txtAns9_den")

    reported = run(live, SLASH_PLAN)

    assert reported["ok"] is False
    assert reported["code"] == "fraction-not-expandable"


def test_a_half_that_is_not_a_denominator_is_refused() -> None:
    """The page has to say it opened a denominator, not merely a box."""
    live = page(opensId="txtAns1_num2")

    reported = run(live, SLASH_PLAN)

    assert reported["ok"] is False
    assert reported["code"] == "fraction-not-expandable"


def test_the_editor_is_moved_when_the_page_does_not_move_itself() -> None:
    """Hawkes usually moves into the new box; this runs its own handling."""
    live = page(movesItself=False)

    reported = run(live, SLASH_PLAN)

    assert reported["ok"] is True
    assert held(live) == ("-3", "2")


def test_a_whole_number_still_takes_the_plain_path() -> None:
    """Nothing about ordinary entry changes, and no box is split."""
    live = page()

    reported = run(live, [{"op": "type", "text": "-6"}])

    assert reported["ok"] is True
    assert held(live) == ("-6", "")
    assert live.eval("denominator.shown") is False


def test_the_settled_value_is_read_back_from_both_boxes() -> None:
    """A denominator that went elsewhere is caught, not reported as placed.

    The page here takes the digit and quietly drops it, which is what a
    misrouted write looks like from outside: every call returned, and the
    logical value is not in the boxes.
    """
    live = page()
    live.eval(
        "const drop = denominator.dispatchEvent.bind(denominator);"
        " denominator.dispatchEvent = (event) => {"
        "   if (event.type === 'input') { denominator.held = ''; return true; }"
        "   return drop(event); };"
    )

    reported = run(live, SLASH_PLAN)

    assert reported["ok"] is False
    assert reported["code"] in {
        "fraction-not-settled",
        "answer-has-rejected-characters",
    }


#: The same box, with the Fraction template this question does not publish.
PLAIN_EDITOR = {
    "ok": True,
    "kind": "textbox",
    "enabled": True,
    "allowedCharacters": "[0-9-]",
    "maxLength": 6,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}


def planner():
    ctx = quickjs.Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js"):
        source = (COMMON / name).read_text()
        source = re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M)
        ctx.eval(re.sub(r"^export ", "", source, flags=re.M))

    def call(answer, editor):
        return json.loads(
            ctx.eval(
                f"JSON.stringify(planEntry({json.dumps(answer)}, {json.dumps(editor)}))"
            )
        )

    return call


def test_a_published_fraction_template_is_still_the_route_when_there_is_one():
    """The template path is preserved exactly; the slash is the other case."""
    plan = planner()
    offered = {
        **PLAIN_EDITOR,
        "pairedControl": True,
        "templates": {"fraction": True, "radical": False, "exponent": False},
    }

    assert plan("-3/2", offered)["steps"] == [
        {"op": "template", "name": "Fraction"},
        {"op": "type", "text": "-3"},
        {"op": "slot", "name": "denominator"},
        {"op": "type", "text": "2"},
    ]


def test_the_slash_is_planned_only_where_the_box_has_a_second_control():
    """The live topology allows it; a lone box still cannot take a fraction."""
    plan = planner()

    assert plan("-3/2", {**PLAIN_EDITOR, "pairedControl": True})["steps"] == SLASH_PLAN
    assert plan("-3/2", PLAIN_EDITOR) == {
        "ok": False,
        "code": "template-refused-by-question",
        "detail": "fraction",
    }


def test_each_half_is_bounded_by_the_box_it_is_typed_into() -> None:
    """`100/9` fits a six-character box twice and would never fit it once."""
    plan = planner()
    paired = {**PLAIN_EDITOR, "pairedControl": True}

    assert plan("100/9", paired)["ok"] is True
    assert plan("1234567/9", paired) == {"ok": False, "code": "answer-too-long"}


def test_the_questions_character_set_still_governs_both_halves() -> None:
    """Opening this route does not open the character rule with it."""
    plan = planner()

    assert plan("x/2", {**PLAIN_EDITOR, "pairedControl": True}) == {
        "ok": False,
        "code": "answer-has-rejected-characters",
        "detail": "x",
    }
