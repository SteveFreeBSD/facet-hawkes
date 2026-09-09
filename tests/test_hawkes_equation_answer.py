"""An answer that is an equation, and the two ways a Hawkes page takes one.

The live failure, on 2026-09-09, lesson 2.4 question 4 of 9: "Find the equation
of the line in slope-intercept form that passes through the following point
with the given slope", `Point (0,5); Slope = -2`, and a **bare** answer box.
Facet derived the line correctly and the add-on inserted `-2x+5`, which Hawkes
refused -- "Your answer is in an incorrect format." It is not an equation.

The half that was missing had never been anybody's to supply. The runtime
returned the right-hand side of `y = mx + b` as the whole answer, which is an
answer only on a page that prints the left side beside its box, and the runtime
cannot know whether a page does -- it is never told there is a page at all.

So the answer is the equation, both of its sides cross, and this side chooses
between them from what its own page publishes. Two facts decide it and either
is enough: the subject the page prints in front of the box, and whether the
box's own character rules accept an equals sign.

Everything below is driven end to end. The payload comes from the real native
host answering the real question; the choice, the review and the insertion are
the shipped event page running under QuickJS.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ethnos.hawkes_host import handle
from facet_loopback import facet
from test_hawkes_insertion_ownership import QUESTION_A, make_page

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

#: Lesson 2.4 question 4, as the page states it. The instruction carries its own
#: step marker, the way the question reader joins them, and the point and the
#: slope are two separate MathJax elements -- "Point" and the semicolon between
#: them are ordinary text and never reach a solver.
LESSON_2_4_INSTRUCTION = (
    "Step 1 of 1 Find the equation of the line in slope-intercept form that "
    "passes through the following point with the given slope. Simplify your "
    "answer."
)
LESSON_2_4_POINT = (
    "<math><mrow><mo>(</mo><mn>0</mn><mo>,</mo><mn>5</mn><mo>)</mo></mrow></math>"
)
LESSON_2_4_SLOPE = (
    "<math><mrow><mtext>Slope</mtext><mo>=</mo><mo>&#x2212;</mo><mn>2</mn>"
    "</mrow></math>"
)

#: Lesson 3.2, the question with the same mathematics and a different page: it
#: prints `f(x) =` in front of its box, so the box takes the right side alone.
LESSON_3_2_INSTRUCTION = "Find the linear function with the given properties."
LESSON_3_2_VALUE = (
    "<math><mrow><mi>f</mi><mo>&#x2061;</mo><mo>(</mo><mn>0</mn><mo>)</mo>"
    "<mo>=</mo><mo>&#x2212;</mo><mn>3</mn></mrow></math>"
)
LESSON_3_2_SLOPE = (
    "<math><mrow><mtext>slope</mtext><mo>=</mo><mo>&#x2212;</mo><mn>5</mn>"
    "</mrow></math>"
)

#: The live lesson 2.4 control, exactly as the add-on's own probe described it
#: on 2026-09-09 (field `QBase12_input`). Its keypad publishes `y` and `=`,
#: which is the page saying an equation is what goes in it.
EQUATION_BOX = {
    "ok": True,
    "code": "described",
    "kind": "dynamic",
    "enabled": True,
    "maxLength": 16,
    "allowedCharacters": "0123456789xy=+-",
    "templates": {
        "fraction": True,
        "radical": False,
        "exponent": False,
        "parentheses": False,
        "absoluteValue": False,
    },
    "slots": {
        "base": "0123456789xy=+-",
        "numerator": "0123456789xy+-",
        "denominator": "0123456789xy",
        "exponent": "0123456789",
        "exponentBase": "0123456789xy",
        "radicand": "0123456789",
        "index": "23456789",
    },
}

#: The counterpart control: a box on a page that states the subject itself, so
#: its keypad has no equals sign on it and the right side is all it can hold.
SIDE_BOX = {
    **EQUATION_BOX,
    "allowedCharacters": "0123456789x+-",
    "slots": {**EQUATION_BOX["slots"], "base": "0123456789x+-"},
}


def solved(monkeypatch, instruction, markup):
    """The native host's own reply to one question, as the browser receives it.

    Through a real in-process Facet rather than a stub, so what is asserted
    below is what the shipped runtime actually returns. Nothing here reaches a
    model: every question in this file is answered exactly.
    """
    loopback = facet(monkeypatch)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "equation-answer",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {"prompt_text": instruction, "mathml": list(markup)},
        }
    )
    assert response.status == "ready", response.message
    assert loopback.prompts == [], "an exactly derivable question reached a model"
    return json.loads(response.model_dump_json())


def reviewed(reply, editor, supplied_subject):
    """Drive the shipped event page through one solve, and read what it holds."""
    page = make_page()
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase12_input",
          editor: {json.dumps(editor)},
          suppliedSubject: {json.dumps(supplied_subject)},
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        acceptReply({json.dumps(reply)});
        """
    )
    page.pump()
    return page


# --- the live question -----------------------------------------------------


def test_the_bare_box_receives_the_whole_equation(monkeypatch):
    """The live failure, end to end: `y=-2x+5` reaches the box, not `-2x+5`.

    Every stage is the shipped one. The reply is the native host's own answer
    to the question the page states; the editor is the description the add-on's
    probe returned from the live control; and the page prints nothing in front
    of the box, which is what the screenshot of it shows.
    """
    reply = solved(
        monkeypatch, LESSON_2_4_INSTRUCTION, [LESSON_2_4_POINT, LESSON_2_4_SLOPE]
    )

    assert reply["answer"]["display_text"] == "y=-2x+5"
    assert reply["answer"]["relation"] == {
        "subject": "y",
        "display_text": "-2x+5",
        "keyboard_entry": "-2*x+5",
    }

    page = reviewed(reply, EQUATION_BOX, "")

    assert page.json("state.phase") == "solved"
    # What the card shows for review, and what the keypad is driven from.
    assert page.json("state.answer") == "y=-2x+5"
    assert page.json("state.displayText") == "y=-2x+5"
    assert page.json("state.entryText") == "y=-2*x+5"
    assert page.json("state.errorKey") == ""


def test_the_live_question_is_typed_into_the_live_control(monkeypatch):
    """The keystrokes themselves, planned against the box's own published rules."""
    reply = solved(
        monkeypatch, LESSON_2_4_INSTRUCTION, [LESSON_2_4_POINT, LESSON_2_4_SLOPE]
    )
    page = reviewed(reply, EQUATION_BOX, "")

    assert page.json("planEntry(state.entryText, state.editor)") == {
        "ok": True,
        "steps": [{"op": "type", "text": "y=-2x+5"}],
    }
    # And the same answer passes the editor's own character rules, so nothing
    # downstream has to choose between a plan that fits and a check that does
    # not. `=` and `y` are both on this question's keypad.
    assert page.json("answerFitsEditor(state.answer, state.editor)") == {
        "insertable": True
    }


def test_the_whole_equation_reaches_the_page_through_the_editors_own_keypad(
    monkeypatch,
):
    """Insertion, run for real: one write, through the transport the page chose."""
    reply = solved(
        monkeypatch, LESSON_2_4_INSTRUCTION, [LESSON_2_4_POINT, LESSON_2_4_SLOPE]
    )
    page = reviewed(reply, EQUATION_BOX, "")

    page.run("insert();")
    page.pump()
    page.answer(EQUATION_BOX)  # describeEditor
    page.answer(QUESTION_A)  # the signature re-check
    page.answer(  # the entry itself, in the page's own world
        {
            "ok": True,
            "code": "entered",
            "entered": "y=-2x+5",
            "transport": "hawkes-dynamic-keypad",
        }
    )
    page.answer(QUESTION_A)  # finishInsertion's rebase read

    writes = [call for call in page.writes if call["func"] == "enterPlan"]
    assert len(writes) == 1
    assert writes[0]["args"][0] == [{"op": "type", "text": "y=-2x+5"}]
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == "y=-2x+5"
    # The page's own answer model chose the writer, as it does for every
    # answer. Nothing about this one changed that.
    chosen = page.said("transport-chosen")
    assert [row["data"]["transport"] for row in chosen] == ["hawkes-dynamic-keypad"]


# --- the counterpart: a page that states the subject itself ----------------


@pytest.mark.parametrize(
    ("subject", "editor", "why"),
    [
        pytest.param("y", EQUATION_BOX, "printed", id="a-page-that-prints-y"),
        pytest.param("f(x)", EQUATION_BOX, "printed", id="a-page-that-prints-f-of-x"),
        pytest.param("", SIDE_BOX, "no equals sign on the keypad", id="by-the-keypad"),
    ],
)
def test_a_page_that_states_the_subject_receives_only_the_right_side(
    monkeypatch, subject, editor, why
):
    """The same answer, the other half of it, on the page that asks for that.

    Three pages, one rule. Two print the subject and one does not print
    anything but publishes a keypad with no equals sign on it, which says the
    same thing in the page's own machine-readable terms. None of them is a
    special case for `y=`: what is read is the page, and the answer is the same
    equation in all three.
    """
    reply = solved(
        monkeypatch, LESSON_2_4_INSTRUCTION, [LESSON_2_4_POINT, LESSON_2_4_SLOPE]
    )
    page = reviewed(reply, editor, subject)

    assert page.json("state.answer") == "-2x+5", why
    assert page.json("state.displayText") == "-2x+5"
    assert page.json("state.entryText") == "-2*x+5"
    assert page.json("planEntry(state.entryText, state.editor)") == {
        "ok": True,
        "steps": [{"op": "type", "text": "-2x+5"}],
    }


def test_the_named_function_page_is_unchanged_by_any_of_this(monkeypatch):
    """Lesson 3.2, which was answered correctly before and still is.

    It prints `f(x) =` in front of its box, so the box takes `-5x-3` -- which
    is exactly what it received before an equation had two sides. The reply now
    carries both, and this page still gets the one it asked for.
    """
    reply = solved(
        monkeypatch, LESSON_3_2_INSTRUCTION, [LESSON_3_2_VALUE, LESSON_3_2_SLOPE]
    )

    assert reply["answer"]["display_text"] == "f(x)=-5x-3"
    assert reply["answer"]["relation"]["subject"] == "f(x)"

    page = reviewed(reply, SIDE_BOX, "f(x)")

    assert page.json("state.answer") == "-5x-3"
    assert page.json("state.entryText") == "-5*x-3"
    assert page.json("answerFitsEditor(state.answer, state.editor)") == {
        "insertable": True
    }


def test_an_answer_that_is_not_an_equation_is_untouched_by_the_choice(monkeypatch):
    """The rule reaches one family and cannot reach any other.

    A scalar carries no relation, so there is nothing to choose between and the
    answer arrives as it always did -- on a page printing a subject as much as
    on one that does not.
    """
    reply = solved(
        monkeypatch,
        "Determine the degree of the polynomial.",
        [
            "<math><mrow><mo>&#x2212;</mo><mn>3</mn><msup><mi>x</mi><mn>11</mn>"
            "</msup><mo>+</mo><mn>5</mn></mrow></math>"
        ],
    )

    assert reply["answer"]["relation"] is None

    page = reviewed(reply, {**EQUATION_BOX, "allowedCharacters": "0123456789-"}, "y")

    assert page.json("state.answer") == "11"


# --- the rule itself -------------------------------------------------------


@pytest.fixture(scope="module")
def rules():
    """The shipped rules module, beside the one bound it imports."""
    context = quickjs.Context()
    for name in ("config.js", "editor-rules.js"):
        source = (EXTENSION / "common" / name).read_text(encoding="utf-8")
        context.eval(
            re.sub(
                r"^export ",
                "",
                re.sub(r"^import .*\n", "", source, flags=re.MULTILINE),
                flags=re.MULTILINE,
            )
        )

    def call(editor, page):
        return context.eval(
            f"surfaceStatesSubject({json.dumps(editor)}, {json.dumps(page)})"
        )

    return call


@pytest.mark.parametrize(
    ("editor", "page", "expected", "id"),
    [
        (EQUATION_BOX, {"suppliedSubject": ""}, False, "bare-box-takes-the-equation"),
        (EQUATION_BOX, {"suppliedSubject": "y"}, True, "printed-y"),
        (EQUATION_BOX, {"suppliedSubject": "f(x)"}, True, "printed-f-of-x"),
        (SIDE_BOX, {"suppliedSubject": ""}, True, "no-equals-on-the-keypad"),
        (SIDE_BOX, {"suppliedSubject": "f(x)"}, True, "both-signals-agree"),
        (EQUATION_BOX, {}, False, "nothing-reported"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_the_surface_decides_and_the_answer_never_does(
    rules, editor, page, expected, id
):
    assert rules(editor, page) is expected


def test_an_unreadable_character_rule_states_nothing_either_way(rules):
    """A page whose rules could not be read has not said the subject is there.

    The whole equation is then held to that same unreadable rule and refused by
    name, which is one refusal with one reason -- rather than a quiet guess
    that half the answer is what the page wanted.
    """
    assert rules({**EQUATION_BOX, "allowedCharacters": ""}, {}) is False


# --- what the page prints in front of the box ------------------------------


ANSWER_PAGE = r"""
class Element {
  constructor({id = "", text = "", left = 0, top = 0, width = 40, height = 20} = {}) {
    this.id = id;
    this.textContent = text;
    this.left = left;
    this.top = top;
    this.width = width;
    this.height = height;
    this.disabled = false;
    this.readOnly = false;
    this.isConnected = true;
    this.value = "";
  }
  getBoundingClientRect() {
    return {
      left: this.left, right: this.left + this.width,
      top: this.top, bottom: this.top + this.height,
      width: this.width, height: this.height,
    };
  }
  matches(selector) { return selector.includes("input"); }
  closest() { return null; }
}
class HTMLInputElement extends Element {}
class HTMLTextAreaElement extends Element {}
class HTMLIFrameElement extends Element {}
class HTMLFrameElement extends Element {}

// One answer box, drawn where the live one is drawn.
const box = new HTMLInputElement({id: "QBase12_input", left: 400, top: 200,
                                  width: 200, height: 100});
globalThis.__printed = [];
globalThis.window = {
  location: {origin: "https://learn.hawkeslearning.com"},
  getSelection() { return null; },
};
globalThis.document = {
  activeElement: box,
  body: new Element(),
  documentElement: new Element(),
  querySelectorAll(selector) {
    if (selector.includes('input[type="radio"].opt')) return [];
    if (selector.includes("customMessageBox")) return [];
    if (selector.includes('#QGraph')) return [];
    if (selector === "*") return [...globalThis.__printed, box];
    if (selector.includes("input.qbaseCSS")) return [box];
    return [];
  },
};
globalThis.performance = { now: () => 0 };
globalThis.ethnosCadence = {
  normalize(value) { return value; },
  planCharacters() { return {offsets: []}; },
  async playCharacters() { return {failure: null}; },
};
globalThis.print = (fields) => {
  globalThis.__printed = [new Element(fields)];
};
"""


@pytest.fixture
def answer_page():
    context = quickjs.Context()
    context.eval(ANSWER_PAGE)
    context.eval((EXTENSION / "content" / "hawkes-editor.js").read_text())
    return context


def subject_of(context, **fields):
    if fields:
        context.eval(f"print({json.dumps(fields)});")
    else:
        context.eval("globalThis.__printed = [];")
    return json.loads(context.eval("JSON.stringify(ethnosHawkes.inspectField())"))[
        "suppliedSubject"
    ]


@pytest.mark.parametrize(
    ("fields", "expected"),
    [
        pytest.param({}, "", id="a-bare-box-prints-nothing"),
        pytest.param(
            {"text": "y =", "left": 340, "top": 240, "width": 50},
            "y",
            id="a-page-that-prints-y",
        ),
        pytest.param(
            {"text": "f(x) =", "left": 320, "top": 240, "width": 70},
            "f(x)",
            id="a-page-that-prints-f-of-x",
        ),
        pytest.param(
            {"text": "g(t) =", "left": 320, "top": 240, "width": 70},
            "g(t)",
            id="the-name-is-the-pages-and-not-a-fixed-letter",
        ),
        pytest.param(
            {"text": "Slope =", "left": 320, "top": 240, "width": 70},
            "",
            id="a-property-the-question-states-is-not-a-label",
        ),
        pytest.param(
            {"text": "Answer", "left": 320, "top": 240, "width": 70},
            "",
            id="the-answer-heading-is-not-a-subject",
        ),
        pytest.param(
            {"text": "y =", "left": 340, "top": 60, "width": 50},
            "",
            id="text-above-the-box-is-not-in-front-of-it",
        ),
        pytest.param(
            {"text": "y =", "left": 100, "top": 240, "width": 50},
            "",
            id="text-too-far-to-the-left-belongs-to-something-else",
        ),
        pytest.param(
            {"text": "y =", "left": 620, "top": 240, "width": 50},
            "",
            id="text-after-the-box-is-not-in-front-of-it",
        ),
        pytest.param(
            {"text": "f(x)=", "left": 320, "top": 190, "width": 300, "height": 120},
            "",
            id="a-wrapper-around-the-box-is-not-a-label-on-it",
        ),
    ],
)
def test_the_reader_reports_what_the_page_prints_in_front_of_the_box(
    answer_page, fields, expected
):
    """Read off the DOM where the box is, and only what is printed beside it.

    The two that matter are the first three rows: a bare box says nothing, and
    a page that prints a subject says so whichever name it uses. The rest are
    the ways a generic reader goes wrong -- a property stated in the question,
    the section heading, text above or after or far away from the box, and the
    container the box sits inside, whose own text reads the same and whose box
    is the whole row.
    """
    assert subject_of(answer_page, **fields) == expected
