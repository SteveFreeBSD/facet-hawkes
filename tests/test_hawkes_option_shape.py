"""A radio group is one answer, and its choices are what that answer may be.

Live, on 2026-09-08, this failed eleven times in an hour on one question. The
page publishes one radio group of five choices. The editor probe counted five
*controls* and reported `kind: "multi", editors: 5`; `answerShapeOf` turned that
into a five-part contract; the host asked Facet for five separate values to a
question that has one; a reasoning model on a GPU produced five, and the guard
that refuses prose caught the last of them -- "reasoning route answered part 4
with prose" -- which is the symptom, not the fault.

The fault is the count. Five alternatives are the things to choose *between*;
a choice is one answer by construction, whatever the size of the group.

These hold the browser half: one group is one answer, the page's own words for
its alternatives are the contract, and the count never comes from how many
backing controls the page happens to publish.
"""

from __future__ import annotations

import json

import pytest

from test_hawkes_insertion_ownership import EDITOR_OK, QUESTION_A, make_page

#: The live question's group: four quadrants and one axis choice, five radios.
CHOICES = [
    "Quadrant I",
    "Quadrant II",
    "Quadrant III",
    "Quadrant IV",
    "The point is on an axis",
]

#: What the editor probe now reports for that group: one control, not five.
OPTION_EDITOR = {
    "ok": True,
    "code": "described-option-group",
    "kind": "option",
    "name": "answer_opt",
    "enabled": True,
    "text": "",
    "allowedCharacters": "",
    "maxLength": None,
    "options": 5,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}

#: What it reported before, and what any older build still sends: five option
#: controls under one `multi`. The shape reader must not read five answers out
#: of it either.
FIVE_OPTION_CONTROLS = {
    "ok": True,
    "code": "described-multi",
    "kind": "multi",
    "editors": [
        {**OPTION_EDITOR, "code": "described", "options": None} for _ in range(5)
    ],
}


@pytest.fixture
def page():
    return make_page()


def shape(page, editor, choices=()):
    return json.loads(
        page.context.eval(
            "JSON.stringify(answerShapeOf(%s, null, [], %s))"
            % (json.dumps(editor), json.dumps(list(choices)))
        )
    )


def solving(page, editor, choices=()):
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "answer_opt", editor: {json.dumps(editor)},
          answerChoices: {json.dumps(list(choices))},
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        """
    )


def reply(page, answer):
    page.run(
        "acceptReply(%s);"
        % json.dumps(
            {
                "status": "ready",
                "problem_text": "In which quadrant does the point lie?",
                "answer": answer,
                "certainty": {
                    "source": "Facet Exact",
                    "answered_by": "exact",
                    "facet_invoked": True,
                    "insertable": True,
                },
            }
        )
    )
    page.pump()


# --- one group is one answer -----------------------------------------------


def test_a_radio_group_is_one_answer_however_many_buttons_it_has(page):
    assert shape(page, OPTION_EDITOR, CHOICES) == {
        "kind": "option",
        "count": 1,
        "choices": CHOICES,
    }


def test_backing_option_controls_are_never_read_as_separate_answers(page):
    """The live defect, at the reader that made it.

    Five controls of kind `option` are one question's alternatives. Counting
    them is what asked Facet for five answers to a question with one.
    """
    assert shape(page, FIVE_OPTION_CONTROLS, CHOICES)["kind"] == "option"
    assert shape(page, FIVE_OPTION_CONTROLS, CHOICES)["count"] == 1


def test_a_group_of_two_is_still_one_answer(page):
    """A two-option question is the same shape as a five-option one."""
    two = {**FIVE_OPTION_CONTROLS, "editors": FIVE_OPTION_CONTROLS["editors"][:2]}

    assert shape(page, two, ["Real Number", "Not a Real Number"])["count"] == 1


def test_typed_boxes_are_still_several_answers(page):
    """The rule is about what the controls are, not about how many."""
    typed = {
        "ok": True,
        "kind": "multi",
        "editors": [
            {**EDITOR_OK, "allowedCharacters": "0123456789-"} for _ in range(2)
        ],
    }

    assert shape(page, typed)["kind"] == "multi"
    assert shape(page, typed)["count"] == 2


def test_a_group_mixing_options_with_a_typed_box_is_left_alone(page):
    """A question with an option *and* a field is not a choice question, and
    guessing which of them holds the answer is not this reader's to do."""
    mixed = {
        "ok": True,
        "kind": "multi",
        "editors": [{**OPTION_EDITOR, "kind": "option"}, EDITOR_OK],
    }

    assert shape(page, mixed)["kind"] == "multi"


# --- the choices are the contract ------------------------------------------


def test_a_published_choice_is_publishable_even_though_it_is_a_sentence(page):
    """A choice is prose by every shape test there is. What makes it
    publishable is that the question offered it."""
    solving(page, OPTION_EDITOR, CHOICES)

    reply(
        page,
        {
            "display_text": "The point is on an axis",
            "keyboard_entry": "The point is on an axis",
            "parts": [],
        },
    )

    assert page.json("state.phase") == "solved"
    assert page.json("state.displayText") == "The point is on an axis"


def test_an_answer_that_is_not_one_of_the_choices_is_withheld(page):
    """It selects nothing: a control is chosen by the words the page printed."""
    solving(page, OPTION_EDITOR, CHOICES)

    reply(
        page,
        {
            "display_text": "the fourth quadrant",
            "keyboard_entry": "the fourth quadrant",
            "parts": [],
        },
    )

    assert page.json("state.phase") != "solved"
    assert page.json("state.answer") == ""
    assert page.said("answer-withheld")[0]["data"]["code"] == (
        "answer-not-a-published-choice"
    )


def test_several_values_are_never_an_answer_to_a_choice_question(page):
    solving(page, OPTION_EDITOR, CHOICES)

    reply(
        page,
        {
            "display_text": "Quadrant I, Quadrant II",
            "keyboard_entry": "",
            "parts": ["Quadrant I", "Quadrant II"],
        },
    )

    assert page.json("state.answerParts") == []
    assert page.json("state.phase") != "solved"


def test_a_group_that_could_not_be_read_publishes_no_contract(page):
    """No choices means the ordinary rules apply, not an invented contract."""
    assert "choices" not in shape(page, OPTION_EDITOR)
    assert "choices" not in shape(page, OPTION_EDITOR, ["only one"])
