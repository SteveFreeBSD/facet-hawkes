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

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


@pytest.fixture(scope="module")
def fits():
    source = re.sub(r"^export ", "", RULES_JS.read_text(), flags=re.MULTILINE)
    context = quickjs.Context()
    context.eval(source)

    def call(answer, editor):
        return json.loads(
            context.eval(
                f"JSON.stringify(answerFitsEditor({json.dumps(answer)}, {json.dumps(editor)}))"
            )
        )

    return call


@pytest.fixture(scope="module")
def insertion_error_key():
    source = re.sub(r"^export ", "", RULES_JS.read_text(), flags=re.MULTILINE)
    context = quickjs.Context()
    context.eval(source)

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

    import quickjs as _quickjs

    rules = _re.sub(
        r"^export ",
        "",
        (PROJECT_ROOT / "extension" / "common" / "editor-rules.js").read_text(),
        flags=_re.M,
    )
    plan = (PROJECT_ROOT / "extension" / "common" / "editor-plan.js").read_text()
    plan = _re.sub(
        r"^import .*\n", "", _re.sub(r"^export ", "", plan, flags=_re.M), flags=_re.M
    )
    context = _quickjs.Context()
    context.eval(rules)
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
