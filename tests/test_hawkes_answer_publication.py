"""One rule: nothing is published as an answer unless it is one, for this shape.

Live, on a quadrant question, the answer card read:

    all answers as they would ordinarily be written

That is Facet's own description of the FINAL ANSWER line, echoed by a model
instead of answered -- and it reached a person because the two guards that were
supposed to stop it had a hole exactly between them. `acceptReply` validated the
machine form and, on the multi-part branch, took the *readable* form as the
reviewed identity without validating anything; the display guard beside it then
"fell back" to that same unvalidated string, so the fallback was a no-op and the
sentence was published twice over.

The fix is not a third check in `acceptReply`. It is one gate at `update()` --
the single place every state change passes through on its way to a card, to
`storage.session`, to a restored question and to a failure record -- asked of
the state that is about to become current, against the shape the question on
screen has right now.

These tests hold that gate for every shape and every route, and drive the real
`background.js` to do it, because a guard asserted in isolation is a guard the
production path can stop calling.
"""

from __future__ import annotations

import json

import pytest

from test_hawkes_insertion_ownership import (
    EDITOR_OK,
    FOUR_EDITOR,
    PAIR_EDITOR,
    QUESTION_A,
    make_page,
)

#: The sentence that reached a live card. Used as *data*: what the rule refuses
#: is that it is made of words, not that it is this particular sentence.
ECHOED = "all answers as they would ordinarily be written"

#: How the add-on joins the ids of several answer fields into one target name.
JOIN = "\u001f"

PAIR_FIELDS = ["QBase1_input", "QBase2_input"]
FOUR_FIELDS = [f"QBase{index}_input" for index in range(1, 5)]

OPTION_EDITOR = {
    "ok": True,
    "code": "described",
    "kind": "option",
    "name": "notReal",
    "enabled": True,
    "allowedCharacters": "",
    "maxLength": None,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}

GRAPH_EDITOR = {"ok": True, "kind": "graph", "context": {"family": "parabola"}}


@pytest.fixture
def page():
    return make_page()


def solving(page, editor, fields=None):
    """The state a solve is launched from, for the editor a question published."""
    field_ids = fields or []
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: {json.dumps(JOIN.join(field_ids) if field_ids else "txtAns1")},
          fieldIds: {json.dumps(field_ids)},
          editor: {json.dumps(editor)},
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        """
    )


def reply(page, answer, *, problem="Question A."):
    page.run(
        "acceptReply(%s);"
        % json.dumps(
            {
                "status": "ready",
                "problem_text": problem,
                "answer": answer,
                "certainty": {
                    "source": "Facet \u00b7 GPU",
                    "answered_by": "facet",
                    "facet_invoked": True,
                    "insertable": True,
                    "model": "gpt-oss:20b",
                    "runtime": "Ollama 0.33.2",
                },
            }
        )
    )
    page.pump()


def published(page):
    return {
        "phase": page.json("state.phase"),
        "answer": page.json("state.answer"),
        "displayText": page.json("state.displayText"),
        "entryText": page.json("state.entryText"),
        "answerParts": page.json("state.answerParts"),
    }


# --- the leak, exactly as it happened --------------------------------------


def test_an_echoed_instruction_never_reaches_the_card_on_a_multipart_answer(page):
    """The live defect. Parts checked, rendering not, and the fallback a no-op."""
    solving(page, PAIR_EDITOR, PAIR_FIELDS)

    reply(page, {"display_text": ECHOED, "keyboard_entry": "", "parts": ["-1", "5"]})

    shown = published(page)
    assert ECHOED not in json.dumps(shown)
    assert shown["phase"] != "solved"
    assert shown["answer"] == "" and shown["displayText"] == ""
    assert shown["answerParts"] == []


def test_the_same_prose_is_refused_on_a_single_value_answer(page):
    solving(page, EDITOR_OK)

    reply(page, {"display_text": ECHOED, "keyboard_entry": ECHOED, "parts": []})

    assert ECHOED not in json.dumps(published(page))
    assert page.json("state.phase") != "solved"


def test_prose_carrying_a_digit_is_refused_too(page):
    """A digit anywhere used to buy a pass, and most of a contract has one."""
    solving(page, PAIR_EDITOR, PAIR_FIELDS)

    reply(
        page,
        {
            "display_text": "Reply with exactly 3 labelled lines and nothing else",
            "keyboard_entry": "",
            "parts": ["-1", "5"],
        },
    )

    assert page.json("state.answer") == ""
    assert page.json("state.phase") != "solved"


def test_a_withheld_answer_says_so_rather_than_going_quiet(page):
    solving(page, PAIR_EDITOR, PAIR_FIELDS)

    reply(page, {"display_text": ECHOED, "keyboard_entry": "", "parts": ["-1", "5"]})

    assert page.json("state.errorKey") == "errorAnswerInvalid"
    withheld = page.said("answer-withheld")
    assert len(withheld) >= 1
    assert withheld[0]["data"]["code"] == "answer-not-an-answer"
    assert withheld[0]["data"]["shape"] == "multi"
    # The refused text is never written into the record: the reason is a code
    # this file authored, and its length, and nothing the model said.
    assert ECHOED not in json.dumps(withheld)


# --- the answers that must still come through ------------------------------


def test_a_real_multipart_answer_is_published_whole(page):
    """The rendering legitimately carries an equals sign no box would take."""
    solving(page, PAIR_EDITOR, PAIR_FIELDS)

    reply(
        page,
        {"display_text": "y = -1 or y = 5", "keyboard_entry": "", "parts": ["-1", "5"]},
    )

    assert page.json("state.phase") == "solved"
    assert page.json("state.displayText") == "y = -1 or y = 5"
    assert page.json("state.answerParts") == ["-1", "5"]


def test_a_real_single_answer_is_published(page):
    solving(page, EDITOR_OK)

    reply(page, {"display_text": "3y", "keyboard_entry": "3y", "parts": []})

    assert page.json("state.phase") == "solved"
    assert page.json("state.answer") == "3y"


def test_a_named_answer_is_short_enough_to_be_a_name(page):
    """A named answer is three words of English at most, because it is a name."""
    solving(page, EDITOR_OK)

    reply(
        page,
        {
            "display_text": "Not a Real Number",
            "keyboard_entry": "Not a Real Number",
            "parts": [],
        },
    )

    assert page.json("state.phase") == "solved"
    assert page.json("state.displayText") == "Not a Real Number"


# --- the shape has to be this question's shape -----------------------------


def test_a_four_part_answer_is_refused_by_a_two_control_question(page):
    """The page published its own count, and it is the authority on it."""
    solving(page, PAIR_EDITOR, PAIR_FIELDS)

    reply(
        page,
        {
            "display_text": "-2, 2, -3, 3",
            "keyboard_entry": "",
            "parts": ["-2", "2", "-3", "3"],
        },
    )

    assert page.json("state.answerParts") == []
    assert page.json("state.phase") != "solved"


def test_a_single_value_is_refused_by_a_four_control_question(page):
    solving(page, FOUR_EDITOR, FOUR_FIELDS)

    reply(page, {"display_text": "-2", "keyboard_entry": "-2", "parts": []})

    assert page.json("state.answer") == ""
    assert page.json("state.phase") != "solved"


def test_several_typed_values_are_refused_by_a_choice_question(page):
    """An option question is answered by choosing, not by typing two answers."""
    solving(page, OPTION_EDITOR)

    reply(page, {"display_text": "-1, 5", "keyboard_entry": "", "parts": ["-1", "5"]})

    assert page.json("state.answerParts") == []
    assert page.json("state.phase") != "solved"


def test_a_value_is_refused_by_a_graph_question(page):
    """A graph is answered by a proved plan. A typed value proved nothing."""
    solving(page, GRAPH_EDITOR)

    reply(page, {"display_text": "3y", "keyboard_entry": "3y", "parts": []})

    assert page.json("state.answer") == ""
    assert page.json("state.phase") != "solved"


# --- an unvalidated display may not stand in for a machine form ------------


def test_a_readable_form_alone_does_not_make_an_answer_publishable(page):
    """Something validated has to stand behind what the card shows.

    Interval notation reads perfectly well and is not typeable into anything:
    no answer box accepts an infinity sign. It is publishable as a *reading*
    and it is not an answer on its own, so a card carrying it and nothing else
    would be offering a solve with nothing behind it.
    """
    solving(page, EDITOR_OK)

    reply(
        page,
        {
            "display_text": "(-\u221e,-3)\u222a(3,\u221e)",
            "keyboard_entry": "",
            "parts": [],
        },
    )

    assert page.json("state.phase") != "solved"
    assert page.json("state.answer") == ""


# --- what was remembered is held to the rule that is current now -----------


def test_a_remembered_prose_answer_is_not_restored_onto_the_next_question(page):
    """A session store written under an older rule outlives the rule.

    `storage.session` survives the event page being unloaded, so the answer that
    comes back was published by whatever code was running when it was stored.
    It goes through the same gate as everything else.
    """
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "txtAns1", editor: {json.dumps(PAIR_EDITOR)},
          answer: {json.dumps(ECHOED)},
          displayText: {json.dumps(ECHOED)},
          entryText: "",
          answerParts: ["-1", "5"],
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        update({{}});
        """
    )
    page.pump()

    assert ECHOED not in json.dumps(published(page))
    assert page.json("state.phase") != "solved"


def test_a_completion_table_holds_its_answer_to_the_blanks_it_published(page):
    """The count survives the solve that produced it.

    `answerShapeOf` is told the question's table while the solve is being
    prepared, and the state does not keep the table -- only the mapping the
    reader built from it, one control per numbered blank. Without recovering
    the count from that mapping a table question falls back to "one box" here,
    and any number of parts would pass the one gate that is supposed to hold
    them to their contract.
    """
    targets = [
        {
            "blank": index,
            "id": f"cell{index}",
            "row": index,
            "column": 2,
            "maxLength": 4,
            "label": f"row {index}",
        }
        for index in range(1, 4)
    ]
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "cell1", editor: {json.dumps(EDITOR_OK)},
          tableTargets: {json.dumps(targets)},
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        """
    )

    reply(page, {"display_text": "1, 2", "keyboard_entry": "", "parts": ["1", "2"]})

    assert page.json("state.answerParts") == []
    assert page.json("state.phase") != "solved"

    reply(
        page,
        {"display_text": "1, 2, 3", "keyboard_entry": "", "parts": ["1", "2", "3"]},
    )

    assert page.json("state.answerParts") == ["1", "2", "3"]
    assert page.json("state.phase") == "solved"
