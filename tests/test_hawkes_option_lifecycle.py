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
        # Whether the page prints a subject in front of this box, which decides
        # whether an equation answer is entered whole or as its right side.
        # Reported even when there is none: measured-and-empty and never-looked
        # are different facts, and only one of them is safe to act on.
        "suppliedSubject": "",
    }


def test_the_isolated_prelude_leaves_the_revealed_box_to_the_page_world(option_page):
    """The box "One Solution" reveals is a Hawkes answer box, and this world no
    longer writes one.

    It used to, through the prototype setter and an `input` event, from a scope
    that can neither see nor select the control Hawkes routes that event
    through. The page's own model describes the revealed box as a textbox, so
    `hawkes-plain-box` writes it from the page's world and holds it until the
    page has kept it -- see
    `test_the_revealed_box_takes_only_its_value_from_the_page_world`. Reached
    here, it is refused and nothing is typed.
    """
    option_page.eval(
        "radios[1].checked = true; answer.visible = true; "
        "document.activeElement = radios[1]; globalThis.outcome = null; "
        "ethnosHawkes.insertAnswer('4').then(value => { outcome = value; })"
    )
    while option_page.execute_pending_job():
        pass

    assert option_page.eval("answer.value") == ""
    assert json.loads(option_page.eval("JSON.stringify(outcome)")) == {
        "ok": False,
        "code": "transport-unavailable",
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


# --- the transition a chosen option makes, in the same frame ----------------
#
# Live, on 2026-09-10, on every regenerated lesson 1.6 question. The owner
# selects "One Solution", Hawkes reveals the box that completes it, and the
# panel goes on offering the choice it had already answered while the box sits
# empty beside it. Insert stays disabled until the panel is reset or the add-on
# reloaded -- neither of which is part of answering a question.
#
# The watcher was written for exactly this ("selecting 'One Solution' replaces
# the option-only target with its aria-controlled text box") and could not see
# it. It re-prepared on a different *frame*, and this handoff happens inside
# one frame. It also re-prepares on a changed question, and the question does
# not change: `questionSignature` is the prompt and its MathML, and revealing a
# box touches neither. So both of its tests were false on every tick.
#
# The distinction that works is what kind of thing answers the question, not
# which box holds the caret -- a caret moving between two boxes is ready and
# not a choice both times, which is the regression the field-id comparison was
# removed for in the first place.

import pytest  # noqa: E402

from test_hawkes_insertion_ownership import make_page  # noqa: E402

#: The page before the choice is made: one radio group, nothing drawn.
GROUP_EDITOR = {
    "ok": True,
    "code": "described-option-group",
    "kind": "option",
    "name": "solution_kind",
    "enabled": True,
    "text": "",
    "allowedCharacters": "",
    "maxLength": None,
    "options": 3,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}
#: What the isolated sweep reports for it.
GROUP_INSPECT = {
    "ready": True,
    "code": "option-answer",
    "fieldId": "solution_kind",
    "choices": ["No Solution (∅)", "One Solution", "Infinite Solutions (ℝ)"],
}
#: The same page after the choice: the sweep has followed the radio to its box.
#: `via` is the page's own linkage, measured live rather than assumed.
REVEALED_INSPECT = {
    "ready": True,
    "code": "focused-answer-field",
    "via": "revealed-option",
    "fieldId": "QBase1_input",
    "fieldKind": "native",
    "suppliedSubject": "",
}
#: And what the page's own model then describes: the box, not the radio.
REVEALED_EDITOR = {
    "ok": True,
    "code": "described",
    "kind": "textbox",
    "name": "QBase1_input",
    "enabled": True,
    "text": "",
    "allowedCharacters": "[0-9.-]",
    "maxLength": 8,
    "pairedControl": False,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}
#: One lesson 1.6 question. Nothing below reads the equation or its answer --
#: Hawkes regenerates both on every Try Similar.
QUESTION = {
    "promptText": "Solve the following linear equation.",
    "expressions": ["<math><mi>t</mi></math>"],
}


def chose_an_option(page, answer="One Solution"):
    """The state a solved choice question leaves behind, before the click."""
    page.run(
        f"""
        settings.autoSolve = false;
        panels.set({{}}, {{windowId: 1}});   // the watcher only runs for a panel
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "solution_kind", editor: {json.dumps(GROUP_EDITOR)},
          answerChoices: {json.dumps(GROUP_INSPECT["choices"])},
          answer: {json.dumps(answer)}, displayText: {json.dumps(answer)},
          entryText: {json.dumps(answer)},
          signature: questionSignature({json.dumps(QUESTION)}),
        }};
        watchQuestion();
        """
    )
    page.pump()


def one_watch_tick(page, inspect_report, question=QUESTION):
    """Fire one watcher tick and settle the two reads it makes."""
    page.run("__H.tick();")
    page.pump()
    page.answer(inspect_report)  # the all-frame ownership read
    page.answer(question)  # the question it compares against the signature


@pytest.fixture
def solved_choice():
    page = make_page()
    chose_an_option(page)
    return page


def test_the_revealed_box_is_noticed_without_the_question_changing(solved_choice):
    """The whole defect. Same question, same frame, new answer surface."""
    one_watch_tick(solved_choice, REVEALED_INSPECT)
    # The re-prepare the tick started, answered as the live page answers it.
    solved_choice.answer(REVEALED_INSPECT)
    solved_choice.answer(REVEALED_EDITOR)
    solved_choice.answer(QUESTION)

    noticed = solved_choice.said("question-changed-while-open")
    assert noticed, "the surface transition went unnoticed"
    assert noticed[-1]["data"]["surfaceChanged"] is True
    # Not because the question moved on: it did not.
    assert noticed[-1]["data"]["targetChanged"] is False
    assert noticed[-1]["data"]["was"] == noticed[-1]["data"]["now"]


def test_the_state_becomes_the_revealed_textbox(solved_choice):
    one_watch_tick(solved_choice, REVEALED_INSPECT)
    solved_choice.answer(REVEALED_INSPECT)
    solved_choice.answer(REVEALED_EDITOR)
    solved_choice.answer(QUESTION)

    assert solved_choice.json("state.editor.kind") == "textbox"
    assert solved_choice.json("state.fieldId") == "QBase1_input"
    # The choice was an answer to the group, and the group is no longer what
    # this question is answered with. Carried across, it arrives on a numeric
    # box that cannot take it -- "solved", with Insert disabled.
    assert solved_choice.json("state.answer") == ""
    assert solved_choice.json("state.phase") == "ready"


#: What Facet answers the revealed box with. The value is whatever this
#: generated question's answer is; a reply has to carry something.
NUMERIC_REPLY = {
    "status": "ready",
    "problem_text": "Solve the following linear equation.",
    "answer": {
        "display_text": "One Solution (t = 3)",
        "keyboard_entry": "3",
        "parts": [],
    },
    "certainty": {
        "source": "Facet Exact",
        "answered_by": "exact",
        "facet_invoked": True,
        "insertable": True,
    },
}


def answer_the_revealed_box(page):
    """Choose, reveal, re-prepare onto the box, and take its numeric answer."""
    one_watch_tick(page, REVEALED_INSPECT)
    # The re-prepare the tick started, answered as the live page answers it.
    page.answer(REVEALED_INSPECT)
    page.answer(REVEALED_EDITOR)
    page.answer(QUESTION)
    page.run("acceptReply(%s);" % json.dumps(NUMERIC_REPLY))
    page.pump()


def test_the_numeric_answer_then_enables_insert(solved_choice):
    """What the owner is waiting for: the value, in the box that appeared."""
    answer_the_revealed_box(solved_choice)

    assert solved_choice.json("state.phase") == "solved"
    assert solved_choice.json("state.entryText") == "3"
    assert (
        solved_choice.json("answerFitsEditor(state.entryText, state.editor).insertable")
        is True
    )


def test_the_revealed_box_takes_only_its_value_from_the_page_world(solved_choice):
    """The last layer of the handoff: which writer, in which world, typing what.

    The value alone -- `3`, not the card's "One Solution (t = 3)" -- through
    the plain box's own writer in the page's world, which is the one route a
    Hawkes plain box has. The isolated prelude refuses this box outright; see
    `test_the_isolated_prelude_leaves_the_revealed_box_to_the_page_world`.
    """
    answer_the_revealed_box(solved_choice)

    solved_choice.run("insert();")
    solved_choice.pump()
    solved_choice.answer(REVEALED_EDITOR)  # describeEditor
    solved_choice.answer(QUESTION)  # the signature re-check

    [write] = solved_choice.writes
    assert write["func"] == "enterPlan"
    assert write["world"] == "MAIN"
    assert write["args"][0] == [{"op": "type", "text": "3"}]
    assert write["args"][3] == "hawkes-plain-box"


def test_a_caret_moving_between_boxes_is_not_a_transition():
    """The regression the field-id comparison was removed for. Two boxes in one
    frame are a surface with somewhere to type, both before and after."""
    page = make_page()
    page.run(
        f"""
        settings.autoSolve = false;
        panels.set({{}}, {{windowId: 1}});   // the watcher only runs for a panel
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input", editor: {json.dumps(REVEALED_EDITOR)},
          answer: "3", displayText: "3", entryText: "3",
          signature: questionSignature({json.dumps(QUESTION)}),
        }};
        watchQuestion();
        """
    )
    page.pump()

    one_watch_tick(page, {**REVEALED_INSPECT, "fieldId": "QBase2_input"})

    assert page.said("question-changed-while-open") == []
    assert page.json("state.answer") == "3", "a good answer was discarded"
    assert page.json("state.fieldId") == "QBase1_input"


def test_a_choice_question_still_at_its_group_is_left_alone(solved_choice):
    """Before the click there is nothing to notice, and the answer stays."""
    one_watch_tick(solved_choice, GROUP_INSPECT)

    assert solved_choice.said("question-changed-while-open") == []
    assert solved_choice.json("state.answer") == "One Solution"
    assert solved_choice.json("state.editor.kind") == "option"


def test_an_unreadable_frame_is_not_a_transition(solved_choice):
    """A tick that could not read the page says nothing about the surface."""
    one_watch_tick(solved_choice, {"ready": False, "code": "no-focused-answer-field"})

    assert solved_choice.said("question-changed-while-open") == []
    assert solved_choice.json("state.answer") == "One Solution"
