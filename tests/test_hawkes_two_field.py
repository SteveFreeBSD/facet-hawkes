"""Regressions for Hawkes questions with one structured multi-field answer."""

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


def test_both_roots_are_preflighted_then_written_to_their_pinned_fields(
    two_field_page,
):
    two_field_page.eval(
        "globalThis.outcome = null; "
        "ethnosHawkes.insertAnswerParts(['-1', '5'], "
        "['QBase1_input', 'QBase2_input']).then(value => { outcome = value; })"
    )
    settle(two_field_page)

    assert two_field_page.eval("fields[0].value") == "-1"
    assert two_field_page.eval("fields[1].value") == "5"
    assert result(two_field_page, "outcome") == {
        "ok": True,
        "code": "native-input-fields",
        "entered": ["-1", "5"],
    }


def test_second_editor_rejection_leaves_both_fields_untouched(two_field_page):
    two_field_page.eval(
        "fields[1].accept = false; globalThis.outcome = null; "
        "ethnosHawkes.insertAnswerParts(['-1', '5'], "
        "['QBase1_input', 'QBase2_input']).then(value => { outcome = value; })"
    )
    settle(two_field_page)

    assert two_field_page.eval("fields[0].value") == ""
    assert two_field_page.eval("fields[1].value") == ""
    assert result(two_field_page, "outcome") == {
        "ok": False,
        "code": "input-cancelled",
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


def test_four_parts_are_written_to_four_fields_in_visual_order(two_field_page):
    add_four_field_shape(two_field_page)
    assert result(two_field_page, "ethnosHawkes.inspectField()") == {
        "ready": True,
        "code": "multi-answer-fields",
        "fieldId": "\u001f".join(f"QBase{index}_input" for index in range(1, 5)),
        "fieldIds": [f"QBase{index}_input" for index in range(1, 5)],
    }

    two_field_page.eval(
        "globalThis.outcome = null; "
        "ethnosHawkes.insertAnswerParts(['-2*sqrt(5)', '2*sqrt(5)', "
        "'-2*i*sqrt(5)', '2*i*sqrt(5)'], "
        "['QBase1_input', 'QBase2_input', 'QBase3_input', 'QBase4_input'])"
        ".then(value => { outcome = value; })"
    )
    settle(two_field_page)

    assert result(two_field_page, "fields.map(field => field.value)") == [
        "-2*sqrt(5)",
        "2*sqrt(5)",
        "-2*i*sqrt(5)",
        "2*i*sqrt(5)",
    ]
    assert result(two_field_page, "outcome")["ok"] is True


def test_part_field_mismatch_refuses_before_mutation(two_field_page):
    add_four_field_shape(two_field_page)
    two_field_page.eval(
        "globalThis.outcome = null; "
        "ethnosHawkes.insertAnswerParts(['-1', '1'], "
        "['QBase1_input', 'QBase2_input']).then(value => { outcome = value; })"
    )
    settle(two_field_page)

    assert result(two_field_page, "outcome") == {
        "ok": False,
        "code": "answer-fields-changed",
    }
    assert result(two_field_page, "fields.map(field => field.value)") == [
        "",
        "",
        "",
        "",
    ]


def test_partial_multi_field_write_never_reports_success(two_field_page):
    add_four_field_shape(two_field_page)
    two_field_page.eval(
        "let plays = 0; afterPlay = () => { plays += 1; "
        "if (plays === 1) separators[0].textContent = 'and'; }; "
        "globalThis.outcome = null; "
        "ethnosHawkes.insertAnswerParts(['-2', '2', '-2*i', '2*i'], "
        "['QBase1_input', 'QBase2_input', 'QBase3_input', 'QBase4_input'])"
        ".then(value => { outcome = value; })"
    )
    settle(two_field_page)

    assert result(two_field_page, "outcome") == {
        "ok": False,
        "code": "answer-fields-changed",
        "written": 1,
    }
    assert two_field_page.eval("fields[0].value") == "-2"


@pytest.mark.parametrize(
    "change",
    [
        "separator.textContent = 'and'",
        "extras.push(new HTMLInputElement({id: 'third'}))",
    ],
)
def test_disappearing_or_ambiguous_pair_is_refused(two_field_page, change):
    two_field_page.eval(
        f"{change}; globalThis.outcome = null; "
        "ethnosHawkes.insertAnswerParts(['-1', '5'], "
        "['QBase1_input', 'QBase2_input']).then(value => { outcome = value; })"
    )
    settle(two_field_page)
    outcome = result(two_field_page, "outcome")

    assert outcome["ok"] is False
    assert outcome["code"] == "answer-fields-changed"
    assert two_field_page.eval("fields[0].value") == ""
    assert two_field_page.eval("fields[1].value") == ""
