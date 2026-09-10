"""Discovering the "or"-separated solution set, from the DOM alone.

This file models what an isolated content script can see: several visible
answer boxes, and the wording between them. That is what decides whether the
page is showing one answer in several places, and it is all `inspectField`
and `solutionFields` are allowed to decide from.

It used to exercise the insertion as well, through `insertAnswerParts`, and
it modelled the boxes as independent inputs -- so a write to one could not
touch another and every insertion test passed while the live page was being
corrupted. A Hawkes answer box is a page-owned control, `input` is routed
through the one the page has selected, and none of that exists here. The
insertion moved to `common/table-actions.js` and is proven against the
controlled editor in `test_hawkes_owned_fields.py`; the pinned identity this
file discovers is revalidated by the event page, in
`test_hawkes_insertion_ownership.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def two_field_page():
    quickjs = pytest.importorskip("quickjs")
    source = (PROJECT_ROOT / "extension" / "content" / "hawkes-editor.js").read_text()
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
        class KeyboardEvent { constructor(type) { this.type = type; } }

        const body = new Element();
        const documentElement = new Element();
        const fields = [
          new HTMLInputElement({id: "QBase1_input", left: 100, top: 200, width: 80}),
          new HTMLInputElement({id: "QBase2_input", left: 220, top: 200, width: 80}),
        ];
        const separator = new Element({left: 190, top: 200, width: 20});
        separator.textContent = "or";
        const separators = [separator];
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
            if (selector === "*") return separators;
            if (selector.includes("input.qbaseCSS")) return [...fields, ...extras];
            return [];
          },
        };
        globalThis.performance = { now: () => 0 };
        globalThis.ethnosCadence = {
          normalize(value) { return value; },
          planCharacters() { return {offsets: []}; },
          async playCharacters(characters, write) {
            for (const character of characters) {
              const failure = write(character);
              if (failure) return {failure};
            }
            if (afterPlay) afterPlay();
            return {failure: null};
          },
        };
        """
    )
    context.eval(source)
    return context


def result(context, expression):
    return json.loads(context.eval(f"JSON.stringify({expression})"))


def settle(context):
    while context.execute_pending_job():
        pass


def test_exact_pair_is_discovered_in_left_to_right_order(two_field_page):
    assert result(two_field_page, "ethnosHawkes.inspectField()") == {
        "ready": True,
        "code": "multi-answer-fields",
        "fieldId": "QBase1_input\u001fQBase2_input",
        "fieldIds": ["QBase1_input", "QBase2_input"],
    }


def add_four_field_shape(context):
    context.eval(
        """
        fields.push(
          new HTMLInputElement({id: "QBase3_input", left: 100, top: 260, width: 80}),
          new HTMLInputElement({id: "QBase4_input", left: 220, top: 260, width: 80})
        );
        const lowerOr = new Element({left: 190, top: 260, width: 20});
        lowerOr.textContent = "or";
        const rowOr = new Element({left: 60, top: 260, width: 20});
        rowOr.textContent = "or";
        separators.push(lowerOr, rowOr);
        """
    )


def test_four_fields_are_discovered_in_visual_order(two_field_page):
    add_four_field_shape(two_field_page)

    assert result(two_field_page, "ethnosHawkes.inspectField()") == {
        "ready": True,
        "code": "multi-answer-fields",
        "fieldId": "\u001f".join(f"QBase{index}_input" for index in range(1, 5)),
        "fieldIds": [f"QBase{index}_input" for index in range(1, 5)],
    }


@pytest.mark.parametrize(
    "change",
    [
        "separator.textContent = 'and'",
        "extras.push(new HTMLInputElement({id: 'third'}))",
    ],
)
def test_a_pair_that_stops_saying_or_is_no_longer_one_answer(two_field_page, change):
    """The wording is the whole of the proof, so losing it loses the shape.

    An extra box is the same fact from the other side: three boxes joined by
    one "or" are not three parts of one answer, and this reader will not say
    they are. The event page may still adopt boxes with no separator at all,
    but only when the page's own editor model publishes exactly that many
    editors -- which is a different proof, made somewhere else, and pinned as
    `editor-corroborated`.
    """
    two_field_page.eval(change)

    found = result(two_field_page, "ethnosHawkes.inspectField()")

    assert found.get("fieldIds", []) == []
    assert found.get("code") != "multi-answer-fields"
