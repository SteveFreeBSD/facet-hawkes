"""A two-box question that labels its boxes rather than separating them.

Lesson 3.3's "find two points on the parabola" step publishes two coordinate
boxes labelled **A:** and **B:**. It was solved correctly and then refused at
insertion, every time, with "the answer editor could not be read".

The page said two different things about itself. Its published editor model
reported two enabled controls, which is what `answerShapeOf` reads to ask Facet
for two parts. Its DOM sweep found the same two boxes and then discarded them,
because `solutionFields()` recognises several boxes as one answer only when the
word "or" sits between them -- the shape `x = ___ or x = ___`. With no field
ids, insertion's "one field id per answer part" rule could never be satisfied.

These tests pin the live shape: two boxes, no separator anywhere on the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

#: How many separate values one answer may have, as the add-on declares it.
MAX_ANSWER_PARTS = int(
    re.search(
        r"\bMAX_ANSWER_PARTS = (\d+);",
        (EXTENSION / "common" / "config.js").read_text(encoding="utf-8"),
    ).group(1)
)


def _lift(source: str, name: str) -> str:
    """Lift one brace-balanced function out of `background.js`."""
    start = source.index(f"function {name}(")
    depth = 0
    for cursor in range(source.index("{", start), len(source)):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return source[start : cursor + 1]
    raise AssertionError(f"{name} is not brace-balanced")


@pytest.fixture
def labelled_pair_page():
    """Two visible, editable boxes and no separator element anywhere."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    source = (EXTENSION / "content" / "hawkes-editor.js").read_text()
    context = quickjs.Context()
    context.eval(
        r"""
        class Element {
          constructor({id = "", left = 0, top = 0, width = 20, height = 20} = {}) {
            this.id = id;
            this.left = left;
            this.top = top;
            this.width = width;
            this.height = height;
            this.disabled = false;
            this.readOnly = false;
            this.isConnected = true;
            this.value = "";
            this.selectionStart = 0;
            this.selectionEnd = 0;
            this.accept = true;
            this.textContent = "";
          }
          getBoundingClientRect() {
            return {
              left: this.left, right: this.left + this.width,
              top: this.top, bottom: this.top + this.height,
              width: this.width, height: this.height,
            };
          }
          dispatchEvent(event) {
            return event.type !== "beforeinput" || this.accept;
          }
          matches(selector) { return selector.includes("input"); }
          closest() { return null; }
          focus() { document.activeElement = this; }
          setSelectionRange(start, end) {
            this.selectionStart = start;
            this.selectionEnd = end;
          }
        }
        class HTMLInputElement extends Element {}
        class HTMLTextAreaElement extends Element {}
        class HTMLIFrameElement extends Element {}
        class HTMLFrameElement extends Element {}
        class InputEvent { constructor(type) { this.type = type; } }

        const body = new Element();
        const documentElement = new Element();
        const fields = [
          new HTMLInputElement({id: "QBase1_input", left: 100, top: 200, width: 80}),
          new HTMLInputElement({id: "QBase2_input", left: 220, top: 200, width: 80}),
        ];
        // "A:" and "B:" -- labels, not separators. Nothing on this page says
        // "or", which is the entire reason the boxes were being discarded.
        const labelA = new Element({left: 70, top: 200, width: 20});
        labelA.textContent = "A:";
        const labelB = new Element({left: 190, top: 200, width: 20});
        labelB.textContent = "B:";
        const everything = [labelA, labelB];
        const extras = [];
        globalThis.afterPlay = null;
        globalThis.window = {
          location: {origin: "https://learn.hawkeslearning.com"},
          getSelection() { return null; },
        };
        globalThis.document = {
          activeElement: fields[0], body, documentElement,
          querySelectorAll(selector) {
            if (selector.includes('input[type="radio"].opt')) return [];
            if (selector.includes('customMessageBox')) return [];
            if (selector === "*") return everything;
            if (selector.includes("input.qbaseCSS")) return [...fields, ...extras];
            return [];
          },
        };
        globalThis.ethnosCadence = {
          normalize(value) { return value; },
          planCharacters() { return {offsets: []}; },
          async playCharacters(characters, write) {
            for (const character of characters) {
              const failure = write(character);
              if (failure) return {failure};
            }
            return {failure: null};
          },
        };
        """
    )
    context.eval(source)
    return context


def result(context, expression):
    return json.loads(context.eval(f"JSON.stringify({expression})"))


def adopt(choice, evidence, editor):
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    context = quickjs.Context()
    # The bound on how many parts one answer may have, read from the module the
    # event page imports it from rather than repeated here.
    context.eval(
        (EXTENSION / "common" / "config.js")
        .read_text(encoding="utf-8")
        .replace("export ", "")
    )
    context.eval(_lift(source, "answerFieldIds"))
    return json.loads(
        context.eval(
            "JSON.stringify(answerFieldIds("
            f"{json.dumps(choice)}, {json.dumps(evidence)}, {json.dumps(editor)}))"
        )
    )


# --- what the page reports -------------------------------------------------


def test_labelled_boxes_are_still_discarded_as_a_decision(labelled_pair_page):
    """The "or" rule is unchanged: with no separator these are not adopted here.

    The sweep must not start calling two boxes one answer on its own evidence.
    It falls through to the focused box, exactly as before.
    """
    reported = result(labelled_pair_page, "ethnosHawkes.inspectField()")

    assert reported["code"] == "focused-answer-field"
    assert reported["via"] == "focused-field"
    assert "fieldIds" not in reported


def test_the_discarded_boxes_are_still_reported_as_candidates(labelled_pair_page):
    """The ids survive as evidence, which is the whole fix.

    Live, this report carried `{fields: 2, separatorCandidates: 0,
    separators: 0}` and no ids at all, so the event page had a count and
    nothing it could type into.
    """
    evidence = result(labelled_pair_page, "ethnosHawkes.inspectField()")[
        "multiFieldEvidence"
    ]

    assert evidence["fields"] == 2
    assert evidence["separators"] == 0
    assert evidence["separatorCandidates"] == 0
    assert evidence["fieldIds"] == ["QBase1_input", "QBase2_input"]


def test_a_single_box_offers_no_candidates(labelled_pair_page):
    """One field is not a pair, and must not be reported as one."""
    labelled_pair_page.eval("fields.pop();")
    evidence = result(labelled_pair_page, "ethnosHawkes.inspectField()")[
        "multiFieldEvidence"
    ]

    assert evidence["fields"] == 1
    assert evidence["fieldIds"] == []


def test_a_disabled_box_is_not_a_candidate(labelled_pair_page):
    """The same rule that stopped a disabled control being counted.

    A control nobody can type into is not one of the question's answers, and
    it must not become one by arriving through the candidate route instead.
    """
    labelled_pair_page.eval("fields[1].disabled = true;")
    evidence = result(labelled_pair_page, "ethnosHawkes.inspectField()")[
        "multiFieldEvidence"
    ]

    assert evidence["fields"] == 1
    assert evidence["fieldIds"] == []


# --- what the event page does with them ------------------------------------


def test_two_agreeing_readings_place_the_answer() -> None:
    """The live shape: two boxes found, two enabled editors published."""
    assert adopt(
        {"fieldId": "QBase1_input"},
        {"fields": 2, "separators": 0, "fieldIds": ["QBase1_input", "QBase2_input"]},
        {"kind": "multi", "editors": [{"name": "A"}, {"name": "B"}]},
    ) == ["QBase1_input", "QBase2_input"]


def test_a_model_that_says_one_box_is_believed_over_the_sweep() -> None:
    """Disagreement falls back to the single focused box, as before.

    A question with one answer beside some other visible field must keep
    working; adopting on the DOM's word alone would refuse it instead.
    """
    assert (
        adopt(
            {"fieldId": "QBase1_input"},
            {"fields": 2, "fieldIds": ["QBase1_input", "QBase2_input"]},
            {"kind": "dynamic"},
        )
        == []
    )


def test_a_model_counting_differently_is_not_adopted() -> None:
    """Three published editors against two boxes is the disagreement itself."""
    assert (
        adopt(
            {"fieldId": "QBase1_input"},
            {"fields": 2, "fieldIds": ["QBase1_input", "QBase2_input"]},
            {"kind": "multi", "editors": [{}, {}, {}]},
        )
        == []
    )


def test_an_accepted_pair_passes_through_untouched() -> None:
    """The "or" path already decided; nothing here may second-guess it."""
    assert adopt(
        {"fieldIds": ["QBase1_input", "QBase2_input"]},
        {"fields": 2, "fieldIds": ["other1", "other2"]},
        {"kind": "multi", "editors": [{}, {}]},
    ) == ["QBase1_input", "QBase2_input"]


@pytest.mark.parametrize(
    "candidates",
    [
        ["QBase1_input", "QBase1_input"],  # ids it cannot tell apart
        ["QBase1_input", ""],  # a box with no id to aim at
        # One past the bound, whatever the bound is; five is now a table of
        # values completed cell by cell, and no longer "too many".
        [f"box{index}" for index in range(MAX_ANSWER_PARTS + 1)],
        ["QBase1_input"],  # not a pair
    ],
    ids=["duplicate", "empty-id", "too-many", "single"],
)
def test_an_unusable_candidate_set_is_never_adopted(candidates) -> None:
    editors = [{} for _ in candidates]
    assert (
        adopt(
            {"fieldId": "QBase1_input"},
            {"fields": len(candidates), "fieldIds": candidates},
            {"kind": "multi", "editors": editors},
        )
        == []
    )
