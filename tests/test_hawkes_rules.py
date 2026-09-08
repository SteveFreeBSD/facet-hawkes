"""Insertability decided from the editor's own published rules.

Hawkes states, per question, exactly which characters its answer box accepts.
Typing anything else raises a modal that holds focus until dismissed, so the
add-on has to refuse first. These cases are the real descriptions observed on a
live lesson, run against the shipped module under QuickJS.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_JS = PROJECT_ROOT / "extension" / "common" / "editor-rules.js"
CONFIG_JS = PROJECT_ROOT / "extension" / "common" / "config.js"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


def rules_context():
    """The shipped rules module, beside the one bound it imports."""
    context = quickjs.Context()
    context.eval(re.sub(r"^export ", "", CONFIG_JS.read_text(), flags=re.MULTILINE))
    source = re.sub(r"^export ", "", RULES_JS.read_text(), flags=re.MULTILINE)
    context.eval(re.sub(r"^import .*\n", "", source, flags=re.MULTILINE))
    return context


@pytest.fixture(scope="module")
def fits():
    context = rules_context()

    def call(answer, editor):
        return json.loads(
            context.eval(
                f"JSON.stringify(answerFitsEditor({json.dumps(answer)}, {json.dumps(editor)}))"
            )
        )

    return call


@pytest.fixture(scope="module")
def insertion_error_key():
    context = rules_context()

    def call(code):
        return context.eval(f"insertErrorKey({json.dumps(code)})")

    return call


# Observed on lesson 1.2, question 8: sqrt(9y^2), answer 3y.
DYNAMIC_Y = {
    "ok": True,
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789y",
    "maxLength": 16,
    "templates": {"fraction": False, "radical": False, "exponent": True},
}

# Observed on question 7: sqrt(-324), an integer-or-decimal answer box.
TEXTBOX_NUMERIC = {
    "ok": True,
    "kind": "textbox",
    "enabled": True,
    "allowedCharacters": "[0-9.-]",
    "maxLength": 9,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}


def test_the_answer_to_the_observed_question_is_insertable(fits):
    assert fits("3y", DYNAMIC_Y) == {"insertable": True}


def test_a_variable_the_question_does_not_use_is_refused(fits):
    # The whole "11y" episode: y was legal for one question and silently
    # dropped by the next, because the set is per question.
    verdict = fits("11z", DYNAMIC_Y)

    assert verdict["insertable"] is False
    assert verdict["code"] == "answer-has-rejected-characters"
    assert verdict["detail"] == "z"


def test_structure_is_refused_with_the_template_named(fits):
    verdict = fits("9*sqrt(5)/(5*x)", DYNAMIC_Y)

    assert verdict["insertable"] is False
    assert verdict["code"] == "answer-needs-template"
    assert "fraction" in verdict["detail"]


def test_a_radical_sign_is_refused_even_when_the_question_allows_radicals(fits):
    # The template has to be pressed; its notation can never be typed.
    editor = {**DYNAMIC_Y, "templates": {**DYNAMIC_Y["templates"], "radical": True}}
    verdict = fits("√5", editor)

    assert verdict["insertable"] is False
    assert verdict["code"] == "answer-needs-template"
    assert verdict["detail"] == "radical"


def test_a_numeric_box_pattern_is_applied_as_a_character_class(fits):
    assert fits("-18", TEXTBOX_NUMERIC) == {"insertable": True}
    assert fits("2.75", TEXTBOX_NUMERIC) == {"insertable": True}

    verdict = fits("18y", TEXTBOX_NUMERIC)
    assert verdict["insertable"] is False
    assert verdict["detail"] == "y"


def test_an_answer_longer_than_the_box_is_refused(fits):
    verdict = fits("1234567890", TEXTBOX_NUMERIC)  # maxLength 9

    assert verdict["insertable"] is False
    assert verdict["code"] == "answer-too-long"


def test_a_disabled_or_unreadable_editor_refuses(fits):
    assert fits("3y", {**DYNAMIC_Y, "enabled": False})["code"] == "editor-disabled"
    assert fits("3y", {"ok": False, "code": "no-focused-control"})["code"] == (
        "no-focused-control"
    )
    assert fits("3y", {**DYNAMIC_Y, "allowedCharacters": ""})["code"] == (
        "editor-rules-unknown"
    )


def test_an_empty_answer_is_never_insertable(fits):
    assert fits("", DYNAMIC_Y)["code"] == "answer-empty"


def test_structured_insertion_preserves_an_existing_error_key(insertion_error_key):
    """M1: an injection timeout must not be relabelled as a missing bridge."""
    assert insertion_error_key("errorOperationTimeout") == "errorOperationTimeout"
    assert insertion_error_key("template-unavailable") == "errorEditorUnknown"


def test_the_readable_answer_is_shown_even_when_it_cannot_be_typed():
    """Regression: the panel showed `sqrt(30)*sqrt(y)*sqrt(z)/(5*z)`.

    The readable form `√(30yz)/(5z)` was available, but the panel picked what
    could be *inserted* and the readable form fails that pattern. Display and
    insertability are different questions.
    """
    background = (PROJECT_ROOT / "extension" / "background.js").read_text()
    view = (PROJECT_ROOT / "extension" / "common" / "panel-view.js").read_text()

    assert "function readableAnswer" in background
    assert "displayText," in background
    # The panel shows the readable form first, and only falls back. Which of
    # the two it picks is exercised directly in tests/test_hawkes_panel.py.
    assert "state.displayText || state.answer" in view


def test_a_compound_denominator_keeps_its_parentheses():
    background = (PROJECT_ROOT / "extension" / "background.js").read_text()

    # "1/12x^7y" reads as "(1/12)x^7y", which is a different value, so a
    # denominator is left bare only for a plain number or a single variable.
    assert "const group = (side)" in background
    assert "reads as" in background


def test_an_option_question_is_never_typed_into():
    """Regression: a radio-button question would not even solve.

    `inspectField` only looked for text fields, so the focused radio read as
    "no answer field" and the flow stopped before solving. An option question
    has an answer worth working out and showing; only the selecting is the
    user's. The planner must also refuse it, and refuse to type blind when the
    editor publishes no character set at all.
    """
    import json as _json
    import re as _re

    plan = (PROJECT_ROOT / "extension" / "common" / "editor-plan.js").read_text()
    plan = _re.sub(
        r"^import .*\n", "", _re.sub(r"^export ", "", plan, flags=_re.M), flags=_re.M
    )
    context = rules_context()
    context.eval(plan)

    option = {
        "ok": True,
        "kind": "option",
        "enabled": True,
        "allowedCharacters": "",
        "maxLength": None,
        "templates": {"fraction": False, "radical": False, "exponent": False},
    }
    verdict = _json.loads(
        context.eval(
            "JSON.stringify(planEntry(%s, %s))"
            % (_json.dumps("Not a Real Number"), _json.dumps(option))
        )
    )
    assert verdict["ok"] is False
    assert verdict["code"] == "editor-option-answer"

    # The editor itself finds the option, so the question still gets solved.
    editor = (PROJECT_ROOT / "extension" / "content" / "hawkes-editor.js").read_text()
    assert "function focusedOption" in editor
    assert '"option-answer"' in editor
    assert '"editor-option-answer"' in editor


def test_non_real_prose_in_a_numeric_editor_is_treated_as_a_choice(fits):
    """A numeric Hawkes box cannot take the letters in the named escape."""
    editor = {
        "ok": True,
        "kind": "textbox",
        "enabled": True,
        "allowedCharacters": "[0-9.-]",
        "maxLength": 9,
        "templates": {"fraction": False, "radical": False, "exponent": False},
    }
    verdict = fits("Not a Real Number", editor)
    assert verdict == {"insertable": False, "code": "editor-option-answer"}


def test_an_option_question_is_found_without_focusing_a_radio():
    """Requiring focus on an option question is circular.

    On a typed question the caret says where the answer goes. On an option
    question, clicking a radio *is* answering — so demanding focus first would
    mean choosing before being told what to choose. Observed live: the panel
    reported "no answer field" and never solved `sqrt(-121)`.
    """
    editor = (PROJECT_ROOT / "extension" / "content" / "hawkes-editor.js").read_text()

    # The option group itself is the signal, not the caret.
    assert 'input[type="radio"].opt' in editor
    question = (
        PROJECT_ROOT / "extension" / "content" / "hawkes-question.js"
    ).read_text()
    assert 'input[type="radio"].opt' in question
    assert "function optionGroup()" in editor
    assert "names.size === 1" in editor
    assert "focused !== document.body" not in editor
    assert '"option-answer"' in editor


# --- a table cell that holds a fraction -------------------------------------
#
# Live, on 2026-09-07, lesson 2.1's four-blank table was read correctly,
# crossed to Facet as a grid, and answered exactly -- and every value was
# refused:
#
#     answer-parts-unplaceable {"parts":4,"tableTargets":4,
#       "cellFit":["answer-needs-template","answer-needs-template",
#                  "answer-needs-template","answer-needs-template"],
#       "editorKind":"textbox","allowed":[]}
#     answer-not-insertable    {"editor":"answer-parts","plan":"answer-parts"}
#
# The writer had already learned that a Hawkes answer cell owns a numerator
# control and a denominator control, and that typing `/` opens the pair. The
# rule deciding whether to offer Insert had not: it judged `16/9` as one whole
# value against one box, saw a `/`, and named a keypad template the question
# does not publish and that entry never needed.


@pytest.fixture(scope="module")
def table_fits():
    context = rules_context()

    def call(parts, targets, editor):
        return json.loads(
            context.eval(
                "JSON.stringify(tableAnswerVerdicts("
                f"{json.dumps(parts)}, {json.dumps(targets)}, {json.dumps(editor)}))"
            )
        )

    return call


#: The editor the live page published for that question: digits and a minus
#: sign, four characters, and not one keypad template.
CELL_EDITOR = {
    "ok": True,
    "kind": "textbox",
    "code": "described",
    "enabled": True,
    "allowedCharacters": "[0-9-]",
    "maxLength": 4,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}


def cell_mapping(ids, max_length=None):
    """A mapping of the shape the reader states, over the given controls."""
    return [
        {
            "blank": index + 1,
            "id": one,
            "row": index + 1,
            "column": 1,
            "maxLength": max_length,
            "label": f"y #{index + 1}",
        }
        for index, one in enumerate(ids)
    ]


#: The four boxes that mapping named, in semantic blank order.
LIVE_CELLS = cell_mapping(
    [
        "MatrixTextBoxes2_num",
        "MatrixTextBoxes8_num",
        "MatrixTextBoxes9_num",
        "MatrixTextBoxes5_num",
    ]
)


def test_the_live_fractions_are_placeable_in_the_cells_that_hold_them(table_fits):
    """The exact refusal: four proved answers, four cells, four refusals."""
    verdicts = table_fits(["16/9", "-8/3", "1/3", "34/9"], LIVE_CELLS, CELL_EDITOR)

    assert verdicts == [{"insertable": True}] * 4


def test_a_whole_integer_table_is_judged_exactly_as_before(table_fits):
    """Plain numeric entry is what already worked live. It must not move."""
    assert (
        table_fits(["3", "-8", "12", "-4"], LIVE_CELLS, CELL_EDITOR)
        == [{"insertable": True}] * 4
    )


def test_each_half_is_bounded_by_its_own_box(table_fits):
    """`100/9` fits two four-character boxes and would never fit one."""
    verdicts = table_fits(["100/9", "1/2", "1/2", "1/2"], LIVE_CELLS, CELL_EDITOR)

    assert verdicts == [{"insertable": True}] * 4


def test_a_half_too_long_for_its_own_box_is_still_refused(table_fits):
    """The bound is per box, not abolished."""
    verdicts = table_fits(["16/99999", "1/2", "1/2", "1/2"], LIVE_CELLS, CELL_EDITOR)

    assert verdicts[0] == {"insertable": False, "code": "answer-too-long"}


def test_a_half_the_question_will_not_take_is_still_refused(table_fits):
    """The character set is the question's, and applies to both halves."""
    verdicts = table_fits(["1/x", "1/2", "1/2", "1/2"], LIVE_CELLS, CELL_EDITOR)

    assert verdicts[0] == {
        "insertable": False,
        "code": "answer-has-rejected-characters",
        "detail": "x",
    }


def test_a_fraction_in_a_cell_that_cannot_open_a_second_box_is_refused(table_fits):
    """A pair is how the value goes in. A cell with no pair cannot take it."""
    plain = cell_mapping(["txtAns1", "txtAns2", "txtAns3", "txtAns4"])
    verdicts = table_fits(["1/3", "2", "3", "4"], plain, CELL_EDITOR)

    assert verdicts[0] == {"insertable": False, "code": "table-cell-not-expandable"}
    assert verdicts[1:] == [{"insertable": True}] * 3


def test_the_cells_own_published_bound_still_wins_over_the_questions(table_fits):
    """Each box states its own length; the fraction path reads the same one."""
    narrow = cell_mapping(
        ["MatrixTextBoxes2_num", "MatrixTextBoxes8_num"], max_length=2
    )
    verdicts = table_fits(["100/9", "1/2"], narrow, CELL_EDITOR)

    assert verdicts[0] == {"insertable": False, "code": "answer-too-long"}
    assert verdicts[1] == {"insertable": True}


# --- the answer as mathematics, not as the spelling it travelled in ----------
#
# Live, on 2026-09-07, the distance between (7,0) and (-3,-1). Facet solved it
# exactly and the panel showed
#
#     sqrt101
#
# beside "This question's answer box does not accept: s" -- the `s` of `sqrt`,
# which in the panel's face reads as a 5. Both were the same defect: the host's
# machine spelling reached the card and the entry planner unconverted, and that
# question's editor publishes `0123456789-` with a Radical template, so every
# letter of `sqrt` is refused one at a time.


@pytest.fixture(scope="module")
def notation():
    context = rules_context()

    def call(text):
        return context.eval(f"mathNotation({json.dumps(text)})")

    return call


@pytest.fixture(scope="module")
def displayable():
    context = rules_context()

    def call(text):
        return context.eval(f"displayableAnswer({json.dumps(text)})")

    return call


#: The editor Hawkes published for that question, from the live log verbatim.
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


def test_a_bare_machine_radical_is_read_as_a_radical(notation) -> None:
    """`sqrt101` is one radical over one number, and is written as one."""
    assert notation("sqrt101") == "√101"
    assert notation("cbrt27") == "∛27"


def test_a_bracketed_radicand_keeps_what_the_bracket_was_holding(notation):
    """The conversion that was already made, still made, and only once.

    `sqrt(30)*y` cannot mean sqrt(30y). What keeps them apart is the explicit
    multiplication, which survives; the bracket around a single number does
    not need to, and a person does not write one.
    """
    assert notation("sqrt(101)") == "√101"
    assert notation("sqrt(30)*y") == "√30*y"
    assert notation("sqrt(30*y)") == "√(30*y)"


def test_ordinary_answers_pass_through_untouched(notation) -> None:
    assert notation("2/3") == "2/3"
    assert notation("-x^13 + 2x^12") == "-x^13 + 2x^12"
    assert notation("Not a Real Number") == "Not a Real Number"


def test_the_editor_builds_the_radical_it_publishes_a_template_for() -> None:
    """Not typed: pressed. The radicand is typed into the slot it opens."""
    context = rules_context()
    plan_js = PROJECT_ROOT / "extension" / "common" / "editor-plan.js"
    source = re.sub(r"^export ", "", plan_js.read_text(), flags=re.MULTILINE)
    context.eval(re.sub(r"^import .*\n", "", source, flags=re.MULTILINE))
    plan = json.loads(
        context.eval(
            "JSON.stringify(planEntry("
            f"{json.dumps('sqrt101')}, {json.dumps(RADICAL_EDITOR)}))"
        )
    )

    assert plan == {
        "ok": True,
        "steps": [
            {"op": "template", "name": "Radical"},
            {"op": "type", "text": "101"},
        ],
    }


def test_the_machine_spelling_is_still_refused_by_the_character_set(fits) -> None:
    """The rule did not get looser: `sqrt101` typed literally is still wrong.

    What changed is that nothing asks the box to take it any more.
    """
    assert fits("sqrt101", RADICAL_EDITOR) == {
        "insertable": False,
        "code": "answer-has-rejected-characters",
        "detail": "s q r t",
    }


def test_the_prompts_own_instruction_never_reaches_the_answer_card(displayable):
    """The host's model contract is built out of English sentences.

    A model that echoes its instruction back instead of answering hands one
    over as the answer. `validateAnswer` already refuses it, and the machine
    form is checked against that -- but the readable form was published
    unchecked, so the sentence reached the card while a good `keyboard_entry`
    sat behind it.
    """
    assert displayable("all answers as they would ordinarily be written") is False
    assert (
        displayable("Reply with exactly two labelled lines and nothing else") is False
    )


def test_the_answers_a_person_should_see_are_all_displayable(displayable) -> None:
    """The rule is about shape, and must not catch mathematics or an escape."""
    for answer in ("√101", "√(30yz)/(5z)", "2/3", "-x^13 + 2x^12", "|x|", "17/4"):
        assert displayable(answer) is True, answer
    # The named escapes Hawkes really does ask for are four words at most.
    assert displayable("Not a Real Number") is True
    assert displayable("Not Factorable") is True


def test_the_event_page_publishes_notation_and_never_unchecked_prose() -> None:
    """The wiring behind the two rules above, which run DOM-free above it.

    `readableAnswer` is what the card shows and was published unchecked; the
    machine form beside it was validated all along. Both now go through the
    same two gates.
    """
    background = (PROJECT_ROOT / "extension" / "background.js").read_text()

    # The readable form is notation, by the rule the entry planner shares.
    assert "return mathNotation(" in background
    # And it reaches the card only when it is an answer at all.
    assert (
        "displayText: displayableAnswer(displayText) ? displayText : answer,"
        in background
    )
    # A refusal is stamped with the answer it was raised for, and a changed
    # question drops it rather than carrying it onto the next one.
    assert "errorAnswer: state.entryText || state.answer" in background
    assert 'errorKey: sameQuestion ? state.errorKey : ""' in background
    assert "errorArgs: sameQuestion ? (state.errorArgs ?? []) : []" in background
    # And a fresh solve clears whatever the last answer was refused for.
    assert "errorArgs: []," in background

    # There is one conversion, not a copy of it in the planner.
    plan = (PROJECT_ROOT / "extension" / "common" / "editor-plan.js").read_text()
    assert "answer = mathNotation(answer);" in plan
    assert "sqrt\\(" not in plan


def test_a_solvers_bracketed_radicand_reads_without_the_bracket(notation) -> None:
    """The exact solvers return SymPy's `sqrt(101)`; a person reads `√101`.

    The bracket belongs to that notation, not to the mathematics, and only
    where the radicand is one plain number or one symbol. Anything compound
    keeps it -- `√(2x)` means something `√2x` does not.
    """
    assert notation("sqrt(101)") == "√101"
    assert notation("10*sqrt(2)") == "10*√2"
    assert notation("cbrt(27)") == "∛27"
    assert notation("sqrt(2*x)") == "√(2*x)"
    assert notation("sqrt(x+1)") == "√(x+1)"


def test_the_exact_distance_answer_is_planned_as_a_radical() -> None:
    """End to end for the live question: `sqrt(101)` in, Radical template out.

    Facet's exact stage now answers the distance between two points, and this
    is the form it returns. Nothing types the letters of `sqrt` anywhere.
    """
    context = rules_context()
    plan_js = PROJECT_ROOT / "extension" / "common" / "editor-plan.js"
    source = re.sub(r"^export ", "", plan_js.read_text(), flags=re.MULTILINE)
    context.eval(re.sub(r"^import .*\n", "", source, flags=re.MULTILINE))
    plan = json.loads(
        context.eval(
            "JSON.stringify(planEntry("
            f"{json.dumps('sqrt(101)')}, {json.dumps(RADICAL_EDITOR)}))"
        )
    )

    assert plan == {
        "ok": True,
        "steps": [
            {"op": "template", "name": "Radical"},
            {"op": "type", "text": "101"},
        ],
    }
