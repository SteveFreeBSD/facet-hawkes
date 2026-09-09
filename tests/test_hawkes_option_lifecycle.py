"""Focused regressions for Hawkes' radio-to-textbox answer lifecycle."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def option_page():
    quickjs = pytest.importorskip("quickjs")
    source = (PROJECT_ROOT / "extension" / "content" / "hawkes-editor.js").read_text(
        encoding="utf-8"
    )
    context = quickjs.Context()
    context.eval(
        r"""
        class Element {
          constructor({id = "", name = "", type = "", visible = true} = {}) {
            this.id = id;
            this.name = name;
            this.type = type;
            this.visible = visible;
            this.disabled = false;
            this.readOnly = false;
            this.checked = false;
            this.isConnected = true;
            this.value = "";
            this.selectionStart = 0;
            this.selectionEnd = 0;
            this.attributes = {};
          }
          getBoundingClientRect() {
            return {width: this.visible ? 20 : 0, height: this.visible ? 20 : 0};
          }
          getAttribute(name) { return this.attributes[name] ?? null; }
          matches(selector) {
            if (selector.includes("input.qbaseCSS")) return this === answer;
            return false;
          }
          closest() { return null; }
          dispatchEvent() { return true; }
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
        class InputEvent {}

        const body = new Element();
        const documentElement = new Element();
        const nextButton = new Element({id: "next"});
        const answer = new HTMLInputElement({id: "txt1_num", type: "text", visible: false});
        const radios = [1, 2, 3].map((number) => {
          const radio = new HTMLInputElement({
            id: `answer_opt${number}_opt`,
            name: "answer_opt",
            type: "radio",
          });
          if (number === 2) radio.attributes["aria-controls"] = "txt1_num";
          // What the page prints beside each button. These are the answer
          // contract for a choice question: the answer is one of them, and it
          // is matched by these exact words.
          radio.attributes["aria-label"] = `Quadrant ${"I".repeat(number)}`;
          return radio;
        });

        globalThis.window = {
          location: {origin: "https://learn.hawkeslearning.com"},
          getSelection() { return null; },
        };
        globalThis.document = {
          activeElement: nextButton,
          body,
          documentElement,
          baseURI: "https://learn.hawkeslearning.com/Portal/Lesson/lesson_practice",
          querySelectorAll(selector) {
            if (selector === 'input[type="radio"].opt') return radios;
            if (selector.includes('customMessageBox')) return [];
            if (selector.includes("input.qbaseCSS")) return [answer];
            return [];
          },
          getElementById(id) { return id === answer.id ? answer : null; },
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
            return {failure: null};
          },
        };
        """
    )
    context.eval(source)
    return context


def inspect(context):
    return json.loads(context.eval("JSON.stringify(ethnosHawkes.inspectField())"))


def test_new_radio_group_is_found_even_when_navigation_kept_button_focus(option_page):
    assert inspect(option_page) == {
        "ready": True,
        "code": "option-answer",
        "fieldId": "answer_opt",
        # One radio group, one answer, and the alternatives it is chosen from.
        "choices": ["Quadrant I", "Quadrant II", "Quadrant III"],
    }


def test_the_published_choices_are_the_words_the_page_prints(option_page):
    """A choice answer is selected by matching these, so they are the contract.

    Read through the ordinary accessible-name chain rather than through
    anything Hawkes-specific: the page is free to mark its radios up
    differently on the next question, and a reader that knew one layout would
    return nothing on the others.
    """
    assert inspect(option_page)["choices"] == [
        "Quadrant I",
        "Quadrant II",
        "Quadrant III",
    ]


def test_a_group_that_cannot_be_read_whole_offers_no_contract(option_page):
    """Four choices reported for a page showing five is worse than none: a
    solver would answer with one of the four."""
    option_page.eval('delete radios[1].attributes["aria-label"];')

    assert inspect(option_page)["choices"] == []


def test_two_choices_reading_the_same_offer_no_contract(option_page):
    """Two choices reading the same way: "the one that says X" names both."""
    option_page.eval('radios[2].attributes["aria-label"] = "Quadrant I";')

    assert inspect(option_page)["choices"] == []


def test_selected_one_solution_hands_off_to_its_controlled_textbox(option_page):
    option_page.eval(
        "radios[1].checked = true; answer.visible = true; "
        "document.activeElement = radios[1]"
    )

    assert inspect(option_page) == {
        "ready": True,
        "code": "focused-answer-field",
        # Which branch claimed the field. Insertion wants one field id per
        # answer part, so a single-field claim on a page with several is worth
        # telling apart from a genuinely single-field question.
        "via": "revealed-option",
        "fieldId": "txt1_num",
        # And what that field is, which is what decides whether the box writer
        # or the caret writer can reach it.
        "fieldKind": "native",
    }


def test_revealed_option_field_receives_only_the_explicit_rhs_value(option_page):
    option_page.eval(
        "radios[1].checked = true; answer.visible = true; "
        "document.activeElement = radios[1]; globalThis.outcome = null; "
        "ethnosHawkes.insertAnswer('4').then(value => { outcome = value; })"
    )
    while option_page.execute_pending_job():
        pass

    assert option_page.eval("answer.value") == "4"
    assert json.loads(option_page.eval("JSON.stringify(outcome)")) == {
        "ok": True,
        "code": "native-input",
    }


def test_multiple_visible_option_groups_still_fail_closed(option_page):
    option_page.eval("radios[2].name = 'another_group'")

    assert inspect(option_page) == {
        "ready": False,
        "code": "no-focused-answer-field",
    }


def test_question_watcher_reprepares_on_a_frame_handoff_and_not_on_a_click():
    """A different frame is a handoff. A different box is the owner typing.

    Watching the focused box re-prepared the panel every 1.5 seconds while the
    owner clicked into their own answer -- discarding a correct answer and
    solving the question again, live, on 2026-09-07.
    """
    source = (PROJECT_ROOT / "extension" / "background.js").read_text(encoding="utf-8")
    watcher = source.split("function watchQuestion()", 1)[1].split(
        "\nfunction stopWatchingQuestion", 1
    )[0]

    assert "allFrames: true" in watcher
    assert "selectAnswerFrame(reports)" in watcher
    assert "target.frameId !== state.frameId" in watcher
    assert "target.fieldId" not in watcher
    assert "targetChanged" in watcher
    assert "prepare(state.windowId)" in watcher


def test_question_watcher_does_not_treat_inserted_templates_as_a_new_question():
    source = (PROJECT_ROOT / "extension" / "background.js").read_text(encoding="utf-8")
    watcher = source.split("function watchQuestion()", 1)[1].split(
        "\nfunction stopWatchingQuestion", 1
    )[0]

    assert 'const targetChanged = state.phase !== "inserted"' in watcher
    assert "!sameQuestionSignature(now, state.signature)" in watcher
