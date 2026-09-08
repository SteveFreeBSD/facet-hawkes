"""The panel, executed.

Every other extension test reads the add-on's JavaScript as text. That is
enough for the invariants -- which permissions, which tokens, which paths --
and it is not enough for behaviour: 0.22.0 shipped a panel whose `render()`
read a `const` declared thirty-eight lines below it, so every render threw
`ReferenceError`, the panel froze at "Checking…", and 428 passing tests said
nothing at all.

`common/panel-view.js` exists so that cannot happen again. It decides
everything the panel shows and returns it as plain data, with no DOM and no
`browser`, so it runs here under QuickJS against every phase the event page can
report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON = PROJECT_ROOT / "extension" / "common"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

# Dependency order; the modules are concatenated because QuickJS here has no
# module loader and these three are deliberately import-free apart from each
# other.
MODULES = ("config.js", "editor-rules.js", "editor-plan.js", "panel-view.js")

IMPORT_LINE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE | re.DOTALL)


@pytest.fixture(scope="module")
def view():
    """`describeView(state, now)`, running as the panel runs it."""
    source = "\n".join(
        IMPORT_LINE.sub("", (COMMON / name).read_text()).replace("export ", "")
        for name in MODULES
    )
    context = quickjs.Context()
    context.eval(source)

    def call(state, now=0, docked=False):
        argument = "null" if state is None else json.dumps(state)
        surface = json.dumps({"docked": docked})
        return json.loads(
            context.eval(f"JSON.stringify(describeView({argument}, {now}, {surface}))")
        )

    return call


# The editor description Hawkes publishes for a question answered by typing.
DYNAMIC_Y = {
    "ok": True,
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789y",
    "maxLength": 16,
    "templates": {"fraction": False, "radical": False, "exponent": True},
}

# One answered by choosing an option, which the add-on never does for you.
OPTION = {
    "ok": True,
    "kind": "option",
    "enabled": True,
    "allowedCharacters": "",
    "maxLength": None,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}

TWO_INTEGER_EDITORS = {
    "ok": True,
    "kind": "multi",
    "editors": [
        {
            "ok": True,
            "kind": "dynamic",
            "enabled": True,
            "allowedCharacters": "0123456789-",
            "maxLength": 16,
            "templates": {"fraction": False, "radical": False, "exponent": False},
        },
        {
            "ok": True,
            "kind": "dynamic",
            "enabled": True,
            "allowedCharacters": "0123456789-",
            "maxLength": 16,
            "templates": {"fraction": False, "radical": False, "exponent": False},
        },
    ],
}

TWO_FRACTION_EDITORS = {
    "ok": True,
    "kind": "multi",
    "editors": [
        {
            "ok": True,
            "kind": "dynamic",
            "enabled": True,
            "allowedCharacters": "+-0123456789i",
            "maxLength": 16,
            "slots": {
                "base": "+-0123456789i",
                "numerator": "+-0123456789i",
                "denominator": "0123456789",
            },
            "templates": {"fraction": True, "radical": False, "exponent": False},
        },
        {
            "ok": True,
            "kind": "dynamic",
            "enabled": True,
            "allowedCharacters": "+-0123456789i",
            "maxLength": 16,
            "slots": {
                "base": "+-0123456789i",
                "numerator": "+-0123456789i",
                "denominator": "0123456789",
            },
            "templates": {"fraction": True, "radical": False, "exponent": False},
        },
    ],
}

SINGLE_COMMA_EDITOR = {
    "ok": True,
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789-+,",
    "maxLength": 24,
    "slots": {
        "base": "0123456789-+,",
        "numerator": "0123456789-+",
        "denominator": "0123456789",
        "radicand": "0123456789",
    },
    "templates": {"fraction": True, "radical": True, "exponent": False},
}


def state(**overrides):
    """A state shaped exactly as `background.js` builds it."""
    base = {
        "phase": "idle",
        "tabId": None,
        "frameId": None,
        "editor": None,
        "problemText": "",
        "answer": "",
        "displayText": "",
        "entryText": "",
        "answerParts": [],
        "placedText": "",
        "promptSeen": True,
        "stage": "",
        "stageDetail": "",
        "signature": "",
        "source": "",
        "detail": "",
        "errorKey": "",
        "errorArgs": [],
        "startedAt": 0,
    }
    base.update(overrides)
    return base


PHASES = [
    "idle",
    "checking",
    "ready",
    "solving",
    "solved",
    "inserting",
    "inserted",
    "failed",
]


@pytest.mark.parametrize("phase", PHASES)
def test_every_phase_renders_without_throwing(view, phase):
    """The regression that started this file.

    A phase the panel cannot describe is a frozen panel, so each one is asked
    for directly rather than inferred from the source.
    """
    described = view(state(phase=phase, tabId=7, frameId=0, editor=DYNAMIC_Y))

    assert described["status"]["key"].startswith(("status", "error"))
    assert 0 <= described["progress"]["fraction"] <= 1
    assert isinstance(described["solve"]["disabled"], bool)


def test_a_state_that_never_arrived_says_so_rather_than_rendering_blank(view):
    described = view(None)

    assert described["status"] == {"key": "errorNoBridge", "args": [], "kind": "error"}
    assert described["solve"]["disabled"] is True
    assert described["insert"]["enabled"] is False


def test_insert_becomes_the_primary_action_once_there_is_an_answer(view):
    described = view(
        state(phase="solved", answer="3y", displayText="3y", editor=DYNAMIC_Y)
    )

    assert described["insert"] == {"enabled": True, "primary": True}
    # Solve stays available -- a doubted answer is re-solved from here -- but
    # stops carrying the emphasis.
    assert described["solve"]["primary"] is False
    assert described["status"]["kind"] == "ready"


def test_two_root_answer_keeps_friendly_display_and_enables_one_explicit_insert(view):
    described = view(
        state(
            phase="solved",
            answer="y = -1 or y = 5",
            displayText="y = -1 or y = 5",
            answerParts=["-1", "5"],
            editor=TWO_INTEGER_EDITORS,
        )
    )

    assert described["answer"]["text"] == "y = -1 or y = 5"
    assert described["insert"] == {"enabled": True, "primary": True}
    assert described["status"]["key"] == "statusSolved"


def test_two_fraction_roots_enable_one_explicit_structured_insert(view):
    display = "z = (-4 - 6i)/7 or z = (-4 + 6i)/7"
    described = view(
        state(
            phase="solved",
            answer=display,
            displayText=display,
            answerParts=["(-4-6*i)/7", "(-4+6*i)/7"],
            editor=TWO_FRACTION_EDITORS,
        )
    )

    assert described["answer"]["text"] == display
    assert described["insert"] == {"enabled": True, "primary": True}
    assert described["status"]["key"] == "statusSolved"


def test_two_roots_enable_one_comma_editor_only_when_the_prompt_requests_it(view):
    display = "y = (-3 + √17)/2 or y = (-√17 - 3)/2"
    described = view(
        state(
            phase="solved",
            problemText=(
                "Solve the following quadratic equation using the quadratic formula. "
                "Separate multiple answers with a comma if necessary."
            ),
            answer=display,
            displayText=display,
            answerParts=["(-3+sqrt(17))/2", "(-sqrt(17)-3)/2"],
            editor=SINGLE_COMMA_EDITOR,
        )
    )

    assert described["answer"]["text"] == display
    assert described["insert"] == {"enabled": True, "primary": True}
    assert described["status"]["key"] == "statusSolved"

    without_contract = view(
        state(
            phase="solved",
            problemText="Solve the equation.",
            answer=display,
            displayText=display,
            answerParts=["(-3+sqrt(17))/2", "(-sqrt(17)-3)/2"],
            editor=SINGLE_COMMA_EDITOR,
        )
    )
    assert without_contract["insert"]["enabled"] is False


def test_an_option_question_reads_as_your_turn_rather_than_a_failure(view):
    described = view(
        state(phase="solved", answer="3y", displayText="3y", editor=OPTION)
    )

    assert described["insert"]["enabled"] is False
    assert described["status"]["key"] == "errorOptionAnswer"
    # A note, not an error: the answer is right and only the selecting is yours.
    assert described["status"]["kind"] == "note"
    # And it can still be copied, which is the whole point of showing it.
    assert described["copy"] == {"enabled": True, "text": "3y"}


def test_linear_solution_classification_is_shown_without_selecting_the_option(view):
    described = view(
        state(
            phase="solved",
            answer="Infinite Solutions",
            displayText="Infinite Solutions",
            editor=OPTION,
        )
    )

    assert described["answer"]["text"] == "Infinite Solutions"
    assert described["insert"]["enabled"] is False
    assert described["status"] == {
        "key": "errorOptionAnswer",
        "args": [],
        "kind": "note",
    }


def test_selected_one_solution_can_insert_its_value_in_the_revealed_box(view):
    described = view(
        state(
            phase="solved",
            answer="6",
            entryText="6",
            displayText="One Solution (y = 6)",
            editor=DYNAMIC_Y,
        )
    )

    assert described["answer"]["text"] == "One Solution (y = 6)"
    assert described["insert"] == {"enabled": True, "primary": True}
    assert described["status"]["kind"] == "ready"


def test_prefixed_formula_shows_the_equality_but_inserts_only_the_rhs(view):
    editor = {
        "ok": True,
        "kind": "dynamic",
        "enabled": True,
        "allowedCharacters": "01234567892rCπ",
        "maxLength": 16,
        "templates": {"fraction": True, "radical": False, "exponent": True},
    }
    described = view(
        state(
            phase="solved",
            answer="C/(2π)",
            entryText="C/(2π)",
            displayText="r = C/(2π)",
            editor=editor,
        )
    )

    assert described["answer"]["text"] == "r = C/(2π)"
    assert described["insert"] == {"enabled": True, "primary": True}


def test_non_real_answer_in_numeric_box_reads_as_manual_choice(view):
    numeric = {
        "ok": True,
        "kind": "textbox",
        "enabled": True,
        "allowedCharacters": "[0-9.-]",
        "maxLength": 9,
        "templates": {"fraction": False, "radical": False, "exponent": False},
    }
    described = view(
        state(
            phase="solved",
            answer="Not a Real Number",
            displayText="Not a Real Number",
            editor=numeric,
        )
    )

    assert described["insert"]["enabled"] is False
    assert described["status"] == {
        "key": "errorOptionAnswer",
        "args": [],
        "kind": "note",
    }


def test_a_reported_error_wins_over_the_phase(view):
    described = view(
        state(
            phase="solved",
            answer="3y",
            editor=DYNAMIC_Y,
            errorKey="errorTranscriptionDisputed",
        )
    )

    assert described["status"]["key"] == "errorTranscriptionDisputed"
    assert described["status"]["kind"] == "error"
    assert described["insert"]["enabled"] is False
    assert described["progress"] == {"fraction": 1, "state": "error"}
    # The primary button offers the retry rather than repeating "Solve".
    assert described["solve"]["key"] == "popupRetryButton"


def test_a_withheld_site_permission_offers_the_scoped_grant(view):
    described = view(state(phase="failed", errorKey="errorTabAccessLost"))

    assert described["solve"]["key"] == "popupGrantAccessButton"
    assert described["insert"]["enabled"] is False


def test_a_running_solve_reports_its_stage_and_how_long_it_has_taken(view):
    described = view(
        state(phase="solving", stage="reading", startedAt=1_000_000, editor=DYNAMIC_Y),
        now=1_000_000 + 23_400,
    )

    assert described["solve"]["key"] == "popupCancelButton"
    assert described["status"]["key"] == "stageReading"
    assert described["status"]["elapsed"] == 23
    assert described["running"] is True
    assert described["resetDisabled"] is True
    assert 0 < described["progress"]["fraction"] < 1


def test_the_bar_advances_monotonically_through_the_stages(view):
    fractions = [
        view(state(phase="solving", stage=stage, startedAt=1, editor=DYNAMIC_Y))[
            "progress"
        ]["fraction"]
        for stage in ("checking-host", "capturing", "reading", "checking", "solving")
    ]

    assert fractions == sorted(fractions)
    assert fractions[0] > 0  # pressing Solve does something visible at once
    assert fractions[-1] < 1  # and the bar is never full while work remains


def test_a_finished_insertion_shows_what_it_placed_rather_than_an_em_dash(view):
    """0.38 emptied the card at the moment the add-on had succeeded.

    The reviewed answer is still gone from state -- `answer`, `displayText` and
    `entryText` are all cleared by `finishInsertion` -- so nothing here can be
    inserted a second time. `placedText` is a display-only copy, and this card
    is the largest thing in the panel: blanking it read as the answer having
    been lost rather than as the answer having been delivered.
    """
    described = view(state(phase="inserted", placedText="3y", source="symbolic"))

    assert described["answer"] == {"text": "3y", "empty": False, "placed": True}
    # Worth keeping copyable: this is the value to check against the screen.
    assert described["copy"] == {"enabled": True, "text": "3y"}
    assert described["insert"]["enabled"] is False
    assert described["progress"] == {"fraction": 1, "state": "done"}
    assert described["status"]["kind"] == "ready"
    # And it still says which stage produced it.
    assert described["badge"] == {"key": "popupSourceBadge", "args": ["symbolic"]}


def test_a_placed_answer_is_never_shown_outside_the_inserted_phase(view):
    """The phase gates the display copy as well as the event page clearing it.

    Belt and braces: no ordering of state updates may put a placed answer
    beside live work, in the way a stale answer once sat beside a running
    retry.
    """
    for phase in ("ready", "solving", "solved", "checking", "failed"):
        described = view(state(phase=phase, placedText="3y", editor=DYNAMIC_Y))

        assert described["answer"]["text"] == ""
        assert described["answer"]["placed"] is False


def test_nothing_is_bound_to_enter_once_the_answer_is_in_the_field(view):
    """The retry this release was opened to fix.

    Enter used to take its action from whichever button was not disabled, and
    Solve stays enabled after an insertion so a doubted answer can be
    re-solved. So the key -- and the footer hint naming it -- offered to solve
    the question that had just been answered.
    """
    described = view(state(phase="inserted", placedText="3y"))

    assert described["primary"] == "none"
    assert described["hint"] is None
    # Available, but no longer presenting itself as the next step.
    assert described["solve"]["disabled"] is False
    assert described["solve"]["primary"] is False
    assert described["solve"]["key"] == "popupSolveAgainButton"


def test_the_footer_hint_never_names_an_action_the_panel_would_refuse(view):
    """One rule: the hint is whatever Enter is actually bound to."""
    cases = [
        (state(phase="ready", editor=DYNAMIC_Y), "solve", "popupHintSolve"),
        (
            state(phase="solving", stage="reading", startedAt=1),
            "cancel",
            "popupHintCancel",
        ),
        (
            state(phase="solved", answer="3y", displayText="3y", editor=DYNAMIC_Y),
            "insert",
            "popupHintInsert",
        ),
        (state(phase="inserting"), "none", None),
        (state(phase="inserted", placedText="3y"), "none", None),
    ]
    for reported, primary, hint in cases:
        described = view(reported)

        assert described["primary"] == primary
        assert described["hint"] == hint

    assert view(None)["primary"] == "none"
    assert view(None)["hint"] is None


def test_only_the_docked_sidebar_claims_to_be_watching_for_the_next_question(view):
    """Same state, two surfaces, two different truths about what happens next.

    The event page's watcher runs only while a panel port is connected. The
    sidebar keeps one open; the toolbar popup is torn down the moment focus
    moves, which is exactly when the user goes to press Submit.
    """
    reported = state(phase="inserted", placedText="3y")

    assert view(reported, docked=True)["status"]["key"] == "statusInsertedWatching"
    assert view(reported)["status"]["key"] == "statusInserted"


def test_the_shown_answer_is_the_readable_form_not_the_typeable_one(view):
    """Regression from 0.19: the panel showed the keyboard form.

    `√(30yz)/(5z)` is what the answer is; `sqrt(30)*sqrt(y)...` is only how it
    would have to be typed. Gating the display on typeability showed the wrong
    one of the two.
    """
    described = view(
        state(
            phase="solved",
            answer="sqrt(30yz)/(5z)",
            displayText="√(30yz)/(5z)",
            editor=DYNAMIC_Y,
        )
    )

    assert described["answer"]["text"] == "√(30yz)/(5z)"
    assert described["copy"]["text"] == "√(30yz)/(5z)"


def test_the_recognized_problem_is_dimmed_rather_than_removed_when_absent(view):
    """The panel keeps one shape, so nothing may appear or vanish."""
    empty = view(state(phase="ready"))
    filled = view(
        state(phase="solved", problemText="Simplify √(9y²)", editor=DYNAMIC_Y)
    )

    assert empty["problem"] == {"text": "", "idle": True}
    assert filled["problem"]["idle"] is False


def test_the_source_badge_is_absent_rather_than_empty_until_something_answered(view):
    assert view(state(phase="ready"))["badge"] is None
    assert view(state(phase="solved", source="symbolic", editor=DYNAMIC_Y))[
        "badge"
    ] == {
        "key": "popupSourceBadge",
        "args": ["symbolic"],
    }


def test_an_answer_reached_without_the_question_says_so(view):
    """An empty prompt forces the least reliable path this add-on has.

    No exact operation can be selected without a verb, so the question reaches
    a model as a picture with nothing stating what to do about it. That answer
    is still offered -- it is often right, and nothing is inserted unreviewed
    -- but it must not read identically to one derived exactly.
    """
    unread = view(
        state(
            phase="solved",
            answer="13",
            displayText="13",
            editor=DYNAMIC_Y,
            promptSeen=False,
        )
    )
    read = view(state(phase="solved", answer="13", displayText="13", editor=DYNAMIC_Y))

    assert unread["status"] == {"key": "statusSolvedUnread", "args": [], "kind": "note"}
    assert read["status"]["key"] == "statusSolved"
    assert read["status"]["kind"] == "ready"
    # Cautioned, not withheld: the answer is still offered for review.
    assert unread["insert"] == {"enabled": True, "primary": True}
    assert unread["primary"] == "insert"


def test_the_caution_needs_an_explicit_denial_not_a_missing_field(view):
    """A host too old to report it must not make every answer look doubtful."""
    described = view(
        state(
            phase="solved",
            answer="13",
            displayText="13",
            editor=DYNAMIC_Y,
            promptSeen=None,
        )
    )

    assert described["status"]["key"] == "statusSolved"


# --- a multi-part answer, said against where its parts go ------------------

#: The live completion table's own editor: one plain box, digits and a minus.
TABLE_EDITOR = {
    "ok": True,
    "code": "described",
    "kind": "textbox",
    "enabled": True,
    "maxLength": 4,
    "allowedCharacters": "[0-9-]",
    "slots": None,
    "templates": {
        "fraction": False,
        "radical": False,
        "exponent": False,
        "parentheses": False,
        "absoluteValue": False,
    },
}

#: What Facet proves for that grid, in semantic blank order.
PARTS = ["0", "8", "8", "5", "3"]


def table_mapping():
    """The mapping the page reader states, read from the live fixture."""
    from hawkes_dom import read_fixture

    return read_fixture("table-completion.html")["answerTargets"]["blanks"]


def panel_state(**changes):
    state = {
        "phase": "solved",
        "editor": TABLE_EDITOR,
        "answer": "0, 8, 8, 5, 3",
        "displayText": "0, 8, 8, 5, 3",
        "answerParts": PARTS,
        "tableTargets": table_mapping(),
        "problemText": "Complete the table of values below.",
    }
    state.update(changes)
    return state


def test_the_panel_offers_a_table_answer_the_collection_could_not_place(view) -> None:
    """The live refusal: five correct values, Insert disabled, `answer-parts`."""
    shown = view(panel_state())

    assert shown["insert"]["enabled"] is True
    assert shown["status"]["key"] == "statusSolved"


def test_the_panel_names_the_cell_each_value_belongs_to(view) -> None:
    """Five numbers in a row would read as five boxes in a row. They are not."""
    shown = view(panel_state())

    assert shown["parts"]["kind"] == "cells"
    assert shown["parts"]["items"] == [
        {"label": "y #1", "text": "0"},
        {"label": "x #2", "text": "8"},
        {"label": "y #3", "text": "8"},
        {"label": "y #4", "text": "5"},
        {"label": "x #5", "text": "3"},
    ]
    assert not any(
        "MatrixTextBoxes" in item["label"] for item in shown["parts"]["items"]
    )


def test_a_multi_field_answer_is_numbered_rather_than_run_together(view) -> None:
    """Not a table: these boxes really are in visual order, and say so."""
    shown = view(
        panel_state(
            tableTargets=[],
            answerParts=["-1", "5"],
            answer="-1 or 5",
            displayText="-1 or 5",
            editor={
                "ok": True,
                "code": "described-multi",
                "kind": "multi",
                "editors": [TABLE_EDITOR, TABLE_EDITOR],
            },
        )
    )

    assert shown["parts"] == {
        "kind": "fields",
        "items": [{"label": "#1", "text": "-1"}, {"label": "#2", "text": "5"}],
    }


def test_a_running_solve_shows_no_breakdown_of_the_previous_answer(view) -> None:
    shown = view(panel_state(phase="solving"))

    assert shown["answer"]["text"] == ""
    assert shown["parts"] == {"kind": "none", "items": []}


def test_a_single_answer_has_no_breakdown_at_all(view) -> None:
    shown = view(
        panel_state(tableTargets=[], answerParts=[], answer="3y", displayText="3y")
    )

    assert shown["parts"] == {"kind": "none", "items": []}


def test_a_table_answer_with_no_mapping_is_not_offered(view) -> None:
    """Nothing places it, so nothing may claim it is ready to be placed."""
    shown = view(panel_state(tableTargets=[]))

    assert shown["insert"]["enabled"] is False
    assert shown["status"]["key"] == "errorEditorUnknown"


def test_a_value_too_long_for_its_own_cell_is_not_offered(view) -> None:
    """The box states its own bound in the markup; the panel applies it per cell."""
    targets = table_mapping()
    targets[2] = {**targets[2], "maxLength": 1}

    shown = view(
        panel_state(tableTargets=targets, answerParts=["0", "8", "88", "5", "3"])
    )

    assert shown["insert"]["enabled"] is False


def test_the_panel_offers_a_table_of_fractions(view) -> None:
    """The live refusal, at the control the owner actually sees.

    Lesson 2.1's four-blank table was answered exactly -- every value proved
    right by hand -- and Insert stayed disabled on all of it, because the rule
    behind that button judged `16/9` as one value against one box and named a
    keypad template the question does not publish. A cell holds a fraction
    across its own two boxes; the button has to know that too, or the answer
    goes nowhere.
    """
    shown = view(
        panel_state(
            answerParts=["16/9", "-8/3", "1/3", "34/9", "1/2"],
            answer="16/9, -8/3, 1/3, 34/9, 1/2",
            displayText="16/9, -8/3, 1/3, 34/9, 1/2",
        )
    )

    assert shown["insert"]["enabled"] is True
    assert shown["status"]["key"] == "statusSolved"


def test_the_panel_still_refuses_a_table_value_no_cell_can_hold(view) -> None:
    """Opening the fraction path must not open the door to everything."""
    shown = view(
        panel_state(
            answerParts=["sqrt(2)", "8", "8", "5", "3"],
            answer="sqrt(2), 8, 8, 5, 3",
            displayText="√2, 8, 8, 5, 3",
        )
    )

    assert shown["insert"]["enabled"] is False
    assert shown["status"]["kind"] == "error"


# --- a refusal belongs to the answer that produced it ------------------------
#
# Live, on 2026-09-07: the distance between (7,0) and (-3,-1), solved exactly,
# with the panel showing the answer and, beside it, "This question's answer box
# does not accept: s". The event page's state is merged rather than rebuilt, so
# an insertion refusal and its arguments outlive the answer they were raised
# for and land on the next one's card -- naming a character that answer does
# not contain, in a face where `s` reads as a 5.


#: The editor the distance question published, from the live log verbatim.
RADICAL_EDITOR = {
    "ok": True,
    "kind": "dynamic",
    "code": "described",
    "enabled": True,
    "maxLength": 16,
    "allowedCharacters": "0123456789-",
    "templates": {
        "fraction": False,
        "radical": True,
        "exponent": False,
        "parentheses": False,
        "absoluteValue": False,
    },
    "slots": {
        "base": "0123456789-",
        "numerator": "0123456789",
        "denominator": "0123456789",
        "exponent": "0123456789",
        "exponentBase": "0123456789xy",
        "radicand": "0123456789",
        "index": "23456789",
    },
}


def radical_state(**changes):
    """√101, as the event page now publishes it."""
    state = {
        "phase": "solved",
        "editor": RADICAL_EDITOR,
        "answer": "sqrt101",
        "displayText": "√101",
        "entryText": "sqrt101",
        "answerParts": [],
        "problemText": "Find the distance between the two points.",
    }
    state.update(changes)
    return state


def test_the_card_shows_the_radical_and_not_the_wire_spelling(view) -> None:
    """`sqrt101` is a transport encoding. `√101` is the answer."""
    shown = view(radical_state())

    assert shown["answer"]["text"] == "√101"
    assert "sqrt" not in shown["answer"]["text"]


def test_the_radical_is_offered_because_the_keypad_can_build_it(view) -> None:
    """The question publishes a Radical template and a numeric radicand."""
    shown = view(radical_state())

    assert shown["insert"]["enabled"] is True
    assert shown["status"]["key"] == "statusWillBuild"


def test_a_refusal_raised_for_another_answer_is_dropped(view) -> None:
    """The crossover: `does not accept: s` beside an answer with no `s`."""
    shown = view(
        radical_state(
            errorKey="errorAnswerRejected",
            errorArgs=["s"],
            errorAnswer="something the previous question was answered with",
        )
    )

    assert shown["status"]["key"] != "errorAnswerRejected"
    assert shown["status"]["args"] == []
    assert shown["status"]["key"] == "statusWillBuild"
    assert shown["insert"]["enabled"] is True


def test_a_refusal_about_this_very_answer_is_not_cleared_early(view) -> None:
    """The other half of the rule, and the one that must not regress."""
    shown = view(
        radical_state(
            errorKey="errorAnswerRejected", errorArgs=["s"], errorAnswer="sqrt101"
        )
    )

    assert shown["status"]["key"] == "errorAnswerRejected"
    assert shown["status"]["args"] == ["s"]
    assert shown["insert"]["enabled"] is False


def test_a_fault_that_is_not_about_an_answer_always_shows(view) -> None:
    """A lost tab is about the session. Clearing it early would hide it."""
    for key in ("errorTabAccessLost", "errorWrongSite", "errorNoFocusedField"):
        shown = view(radical_state(errorKey=key, errorArgs=[], errorAnswer=""))
        assert shown["status"]["key"] == key, key


def test_a_state_written_before_the_stamp_existed_still_shows_its_error(view):
    """An older event page publishes no `errorAnswer`. It is still believed."""
    shown = view(radical_state(errorKey="errorAnswerRejected", errorArgs=["s"]))

    assert shown["status"]["key"] == "errorAnswerRejected"


def test_the_solve_button_reads_as_retry_only_for_a_refusal_that_holds(view):
    """The stance follows the same rule, so the panel cannot half-clear one."""
    stale = view(
        radical_state(
            errorKey="errorAnswerRejected", errorArgs=["s"], errorAnswer="elsewhere"
        )
    )
    held = view(
        radical_state(
            errorKey="errorAnswerRejected", errorArgs=["s"], errorAnswer="sqrt101"
        )
    )

    assert stale["stance"] == "review"
    assert stale["progress"]["state"] == "done"
    assert held["stance"] == "solve"
    assert held["solve"]["key"] == "popupRetryButton"
    assert held["progress"]["state"] == "error"
