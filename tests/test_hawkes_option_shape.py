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
    """A question with an option *and* a field the page is drawing is not a
    choice question, and guessing which of them holds the answer is not this
    reader's to do."""
    mixed = {
        "ok": True,
        "kind": "multi",
        "editors": [{**OPTION_EDITOR, "kind": "option"}, EDITOR_OK],
    }

    assert shape(page, mixed)["kind"] == "multi"


# --- a group beside a box the page is not drawing ---------------------------
#
# Live, on 2026-09-10, four runs on build 1d0e21b6b1d3: "No Solution (∅) / One
# Solution / Infinite Solutions (ℝ)", where "One Solution" reveals a box for
# the value. Three options and the two controls behind that one box are five
# usable controls, and none of them is drawn until the choice is made. The
# probe now reads that as the group it is; this is the same rule at the reader,
# so an older build still sending five cannot ask for five values again.


#: What such a build sends: the group, plus the undrawn box behind one of its
#: alternatives, with the probe's own count of what the page is drawing.
UNDRAWN_BOX_CONTROLS = {
    "ok": True,
    "code": "described-multi",
    "kind": "multi",
    "editors": [
        *({**OPTION_EDITOR, "code": "described", "options": None} for _ in range(3)),
        *(EDITOR_OK for _ in range(2)),
    ],
    "collection": {"controls": 5, "usable": 5, "drawn": 0, "branch": "multi"},
}

#: The three phrases the page prints beside its radios.
SOLUTION_KINDS = ["No Solution (∅)", "One Solution", "Infinite Solutions (ℝ)"]


def test_an_undrawn_box_behind_a_choice_is_not_a_second_answer(page):
    """The live defect: five controls, one question, one answer."""
    assert shape(page, UNDRAWN_BOX_CONTROLS, SOLUTION_KINDS) == {
        "kind": "option",
        "count": 1,
        "choices": SOLUTION_KINDS,
    }


def test_the_same_controls_beside_a_drawn_box_stay_several_answers(page):
    """What the page is drawing is the whole of the difference."""
    drawn = {
        **UNDRAWN_BOX_CONTROLS,
        "collection": {**UNDRAWN_BOX_CONTROLS["collection"], "drawn": 1},
    }

    assert shape(page, drawn, SOLUTION_KINDS)["kind"] == "multi"


def test_an_unknown_drawn_count_is_not_a_zero(page):
    """`-1` is the probe saying it could not tell, and it overrules nothing."""
    unknown = {
        **UNDRAWN_BOX_CONTROLS,
        "collection": {**UNDRAWN_BOX_CONTROLS["collection"], "drawn": -1},
    }

    assert shape(page, unknown, SOLUTION_KINDS)["kind"] == "multi"
    # And a build too old to publish a collection at all says nothing either.
    assert (
        shape(
            page,
            {k: v for k, v in UNDRAWN_BOX_CONTROLS.items() if k != "collection"},
            SOLUTION_KINDS,
        )["kind"]
        == "multi"
    )


def test_the_probe_and_the_reader_agree_on_the_live_model(page):
    """The two boundaries, chained, on the page's own control collection.

    Every other test here hands the reader a description written by hand, which
    cannot catch the two halves drifting apart -- and drifting apart is exactly
    what happened live: the probe published five controls and the reader was
    asked to make one contract out of them. This runs the real probe over the
    real model and gives the reader whatever it says, so a change to either
    that leaves them disagreeing fails here rather than on Steve's screen.
    """
    from test_hawkes_editor_collection import describe, solution_kind_model

    described = describe(solution_kind_model(), drawn=0)

    assert shape(page, described, SOLUTION_KINDS) == {
        "kind": "option",
        "count": 1,
        "choices": SOLUTION_KINDS,
    }


def test_one_option_beside_undrawn_boxes_is_not_a_group(page):
    """Two alternatives at least, or there is nothing to choose between."""
    single = {
        **UNDRAWN_BOX_CONTROLS,
        "editors": [
            {**OPTION_EDITOR, "code": "described", "kind": "option"},
            EDITOR_OK,
            EDITOR_OK,
        ],
    }

    assert shape(page, single, SOLUTION_KINDS)["kind"] == "multi"


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


# --- a choice is selected, not typed ----------------------------------------
#
# Live, on 2026-09-10, after the count and the wording were both right. Facet
# answered lesson 1.6's question with the page's own `Infinite Solutions (ℝ)`
# and the panel said:
#
#     The saved answer is not a supported plain-text answer. Fix it in Settings.
#
# `validateAnswer` is the alphabet an answer may be *typed* in -- digits,
# letters, the operators, `√` and `π`. It has no set-theoretic notation in it
# and should not: nobody types `ℝ` into a Hawkes box. The answer to a choice
# question is not keystrokes. It is the page's own string, matched exactly so
# that the right radio is the one selected, and holding it to the typing
# alphabet is a category error that recurs for whatever notation the next page
# prints in a label.

#: The live group, with the notation Hawkes sets beside two of its three.
NOTATED = ["No Solution (∅)", "One Solution", "Infinite Solutions (ℝ)"]


def choice_reply(page, answer):
    page.run(
        "acceptReply(%s);"
        % json.dumps(
            {
                "status": "ready",
                "problem_text": "Solve the following linear equation.",
                "answer": {
                    "display_text": answer,
                    "keyboard_entry": answer,
                    "parts": [],
                },
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


def test_a_published_choice_carrying_set_notation_reaches_the_card(page):
    """The live defect, at the filter that dropped it."""
    solving(page, OPTION_EDITOR, NOTATED)

    choice_reply(page, "Infinite Solutions (ℝ)")

    assert page.json("state.phase") == "solved"
    assert page.json("state.answer") == "Infinite Solutions (ℝ)"
    assert page.json("state.displayText") == "Infinite Solutions (ℝ)"


def test_the_empty_set_notation_reaches_the_card_too(page):
    solving(page, OPTION_EDITOR, NOTATED)

    choice_reply(page, "No Solution (∅)")

    assert page.json("state.phase") == "solved"
    assert page.json("state.answer") == "No Solution (∅)"


def test_notation_that_the_page_did_not_publish_is_still_refused(page):
    """Narrower than the character rule, not weaker: what buys a choice its way
    past the alphabet is that this question printed it, and nothing else."""
    solving(page, OPTION_EDITOR, NOTATED)

    choice_reply(page, "Infinite Solutions (ℤ)")

    assert page.json("state.phase") != "solved"
    assert page.json("state.answer") == ""


def test_a_question_publishing_no_choices_still_holds_the_alphabet(page):
    """A field question is typed into, so its answer is held to what can be
    typed. Nothing about that path may have moved."""
    solving(page, EDITOR_OK, [])

    choice_reply(page, "Infinite Solutions (ℝ)")

    assert page.json("state.phase") != "solved"
    assert page.json("state.answer") == ""


def test_selecting_is_still_the_readers_own_action(page):
    """Publishable is not insertable. The add-on never clicks a radio."""
    solving(page, OPTION_EDITOR, NOTATED)

    choice_reply(page, "Infinite Solutions (ℝ)")

    assert page.json("state.phase") == "solved"
    assert page.writes == [], "a choice question must never be written into"
