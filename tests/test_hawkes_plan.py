"""Planning the keystrokes and template presses for an answer.

The Hawkes dynamic box cannot be handed a whole expression: structure is built
one template at a time, and a template only loads when the box it attaches to
already holds something. These plans were derived from live entry of two real
answers, and are run against the shipped module under QuickJS.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_JS = PROJECT_ROOT / "extension" / "common" / "editor-plan.js"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


RULES_JS = PROJECT_ROOT / "extension" / "common" / "editor-rules.js"


@pytest.fixture(scope="module")
def plan():
    # The planner shares the character rule with editor-rules; load both.
    rules = re.sub(r"^export ", "", RULES_JS.read_text(), flags=re.MULTILINE)
    source = re.sub(r"^export ", "", PLAN_JS.read_text(), flags=re.MULTILINE)
    source = re.sub(r"^import .*\n", "", source, flags=re.MULTILINE)
    context = quickjs.Context()
    context.eval(rules)
    context.eval(source)

    def call(answer, editor):
        return json.loads(context.eval(
            f"JSON.stringify(planEntry({json.dumps(answer)}, {json.dumps(editor)}))"
        ))

    return call


# Observed on lesson 1.2 question 9: fifth root of y^5 x^30 z^25.
EXPONENTS = {
    "allowedCharacters": "0123456789yx-z",
    "templates": {"fraction": False, "radical": True, "exponent": True},
}
# Observed on question 10: sqrt(y^3 / (144 x^14 y^5)).
FRACTIONS = {
    "allowedCharacters": "0123456789yxz-",
    "templates": {"fraction": True, "radical": True, "exponent": True},
}


def test_plain_answer_is_one_typing_step(plan):
    assert plan("3y", EXPONENTS) == {"ok": True, "steps": [{"op": "type", "text": "3y"}]}


def test_the_exponent_plan_matches_what_worked_live(plan):
    # x^6yz^5 was entered exactly this way and rendered correctly.
    assert plan("x^6yz^5", EXPONENTS) == {
        "ok": True,
        "steps": [
            {"op": "type", "text": "x"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "6"},
            {"op": "base"},
            {"op": "type", "text": "yz"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "5"},
        ],
    }


def test_the_fraction_plan_matches_what_worked_live(plan):
    # 1/(12x^7y): fraction, numerator, then the denominator with a nested
    # exponent. Loading a fraction focuses the numerator, which is why the
    # numerator comes first and the denominator needs an explicit slot move.
    assert plan("1/(12*x^7*y)", FRACTIONS) == {
        "ok": True,
        "steps": [
            {"op": "template", "name": "Fraction"},
            {"op": "type", "text": "1"},
            {"op": "slot", "name": "denominator"},
            {"op": "type", "text": "12x"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "7"},
            {"op": "base"},
            {"op": "type", "text": "y"},
        ],
    }


def test_explicit_multiplication_is_dropped(plan):
    # Ethnos writes 3*y; the editor wants juxtaposition and no question's
    # character set contains "*".
    assert plan("3*y", EXPONENTS)["steps"] == [{"op": "type", "text": "3y"}]


def test_display_spacing_is_dropped(plan):
    assert plan("x^2 + 16x + 64", {
        "allowedCharacters": "-0123456789+xy",
        "templates": {"fraction": False, "radical": False, "exponent": True},
    }) == {
        "ok": True,
        "steps": [
            {"op": "type", "text": "x"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "2"},
            {"op": "base"},
            {"op": "type", "text": "+16x+64"},
        ],
    }


def test_factored_product_uses_parenthesis_templates(plan):
    editor = {
        "allowedCharacters": "0123456789-+y",
        "templates": {
            "fraction": False, "radical": False, "exponent": True,
            "parentheses": True,
        },
    }
    assert plan("(y - 8)(y + 8)", editor) == {
        "ok": True,
        "steps": [
            {"op": "template", "name": "PBrace"},
            {"op": "type", "text": "y-8"},
            {"op": "base"},
            {"op": "template", "name": "PBrace"},
            {"op": "type", "text": "y+8"},
        ],
    }


def test_factor_variable_is_typed_before_parenthesis_template(plan):
    editor = {
        "allowedCharacters": "0123456789-+xy",
        "templates": {
            "fraction": False, "radical": False, "exponent": True,
            "parentheses": True,
        },
    }
    assert plan("4x^3y(xy^2+2x-4)", editor)["steps"][:5] == [
        {"op": "type", "text": "4x"},
        {"op": "template", "name": "Exponent"},
        {"op": "type", "text": "3"},
        {"op": "base"},
        {"op": "type", "text": "y"},
    ]


def test_an_exponent_needs_something_to_raise(plan):
    # Pressing Exponent on an empty box makes the editor raise a modal refusal,
    # which then holds focus. Refuse before touching the page.
    assert plan("^2", EXPONENTS)["code"] == "exponent-without-base"


def test_a_template_the_question_forbids_is_refused(plan):
    no_exponent = {**EXPONENTS, "templates": {**EXPONENTS["templates"], "exponent": False}}
    verdict = plan("x^2", no_exponent)
    assert verdict["code"] == "template-refused-by-question"
    assert verdict["detail"] == "exponent"

    verdict = plan("1/2", EXPONENTS)  # fraction is False here
    assert verdict["code"] == "template-refused-by-question"
    assert verdict["detail"] == "fraction"


def test_a_square_root_is_planned_rather_than_refused(plan):
    # Radicals used to be declined outright; the Radical template loads on an
    # empty box and focuses the radicand, exactly like Fraction.
    assert plan("√5", FRACTIONS)["steps"] == [
        {"op": "template", "name": "Radical"},
        {"op": "type", "text": "5"},
    ]


def test_a_factor_before_a_radical_stays_outside(plan):
    """The live y/sqrt(30) answer must build y outside the radical."""
    assert plan("y√30/30", FRACTIONS)["steps"] == [
        {"op": "template", "name": "Fraction"},
        {"op": "type", "text": "y"},
        {"op": "template", "name": "Radical"},
        {"op": "type", "text": "30"},
        {"op": "slot", "name": "denominator"},
        {"op": "type", "text": "30"},
    ]


def test_explicit_keyboard_radical_is_the_same_unambiguous_plan(plan):
    """The planner consumes the host's machine form, not compact display."""
    assert plan("y*sqrt(30)/30", FRACTIONS) == plan("y√30/30", FRACTIONS)


def test_a_character_the_question_rejects_is_refused(plan):
    verdict = plan("3w", EXPONENTS)
    assert verdict["code"] == "answer-has-rejected-characters"
    assert verdict["detail"] == "w"


def test_nested_fractions_are_declined_rather_than_mis_entered(plan):
    # Two top-level slashes need a traversal this planner does not do.
    assert plan("1/2/3", FRACTIONS)["ok"] is False


def test_a_negative_or_parenthesised_exponent_is_read(plan):
    assert plan("x^(-2)", EXPONENTS)["steps"] == [
        {"op": "type", "text": "x"},
        {"op": "template", "name": "Exponent"},
        {"op": "type", "text": "-2"},
    ]
    assert plan("x^y", EXPONENTS)["code"] == "exponent-not-understood"


def test_a_rational_exponent_nests_a_fraction_in_the_exponent(plan):
    # y^(3/2), from "convert the given radical expression to rational exponent
    # notation". Fraction loads on an empty box and focuses the numerator, so
    # nothing is typed into the exponent before the fraction is loaded.
    assert plan("y^(3/2)", FRACTIONS) == {
        "ok": True,
        "steps": [
            {"op": "type", "text": "y"},
            {"op": "template", "name": "Exponent"},
            {"op": "template", "name": "Fraction"},
            {"op": "type", "text": "3"},
            {"op": "slot", "name": "denominator"},
            {"op": "type", "text": "2"},
        ],
    }


def test_a_rational_exponent_needs_the_fraction_template_too(plan):
    no_fraction = {**FRACTIONS, "templates": {**FRACTIONS["templates"], "fraction": False}}
    verdict = plan("y^(3/2)", no_fraction)

    assert verdict["code"] == "template-refused-by-question"
    assert verdict["detail"] == "fraction"


def test_a_plain_integer_exponent_is_unaffected(plan):
    assert plan("x^6", EXPONENTS)["steps"] == [
        {"op": "type", "text": "x"},
        {"op": "template", "name": "Exponent"},
        {"op": "type", "text": "6"},
    ]


RADICALS = {
    "allowedCharacters": "0123456789yz-",
    "templates": {"fraction": True, "radical": True, "exponent": True},
}


def test_a_radical_over_a_fraction_is_planned(plan):
    # sqrt(6y/(5z)) rationalised is sqrt(30yz)/(5z): a fraction whose numerator
    # is a radical. The denominator move must return to the fraction, not to
    # the radical opened inside it.
    assert plan("√(30yz)/(5z)", RADICALS) == {
        "ok": True,
        "steps": [
            {"op": "template", "name": "Fraction"},
            {"op": "template", "name": "Radical"},
            {"op": "type", "text": "30yz"},
            {"op": "slot", "name": "denominator"},
            {"op": "type", "text": "5z"},
        ],
    }


def test_a_bare_radical_takes_the_token_after_it(plan):
    assert plan("√2/2", RADICALS)["steps"] == [
        {"op": "template", "name": "Fraction"},
        {"op": "template", "name": "Radical"},
        {"op": "type", "text": "2"},
        {"op": "slot", "name": "denominator"},
        {"op": "type", "text": "2"},
    ]


def test_a_radical_the_question_forbids_is_refused(plan):
    no_radical = {**RADICALS, "templates": {**RADICALS["templates"], "radical": False}}
    verdict = plan("√2", no_radical)

    assert verdict["code"] == "template-refused-by-question"
    assert verdict["detail"] == "radical"


def test_a_cube_root_is_now_built_rather_than_declined(plan):
    """This used to be declined by name: `IndexedRadical` has an index slot the
    planner did not fill. It fills it now, verified live on lesson 1.2 question
    9 -- the cube root of 320, entered as 4 times the cube root of 5.
    """
    verdict = plan("∛2", RADICALS)

    assert verdict["ok"] is True
    assert verdict["steps"][0] == {"op": "template", "name": "IndexedRadical"}
    assert verdict["steps"][1] == {"op": "type", "text": "3"}


TEXTBOX = {
    "kind": "textbox",
    "allowedCharacters": "[0-9-]",
    "maxLength": 11,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}


def test_a_textbox_rule_is_read_as_a_pattern_not_a_character_set(plan):
    """Regression found on question 1 of a fresh practice set.

    A plain answer box publishes its rule as `[0-9-]`. Read as a literal set
    that string contains `[`, `0`, `-`, `9`, `]` -- but not `6` -- so the
    planner rejected "64" for a box that plainly accepts it. It did not bite
    only because the typeable path answered first.
    """
    assert plan("64", TEXTBOX) == {"ok": True, "steps": [{"op": "type", "text": "64"}]}
    assert plan("-64", TEXTBOX)["ok"] is True

    verdict = plan("64a", TEXTBOX)
    assert verdict["code"] == "answer-has-rejected-characters"
    assert verdict["detail"] == "a"


# Lesson 1.2 question 7: the fourth root of y^20*z^16/81, whose own control
# lists `Mod` in `qdyBase_AllowedTemplates` -- the question saying its answer
# is built with absolute-value bars.
BARS = {
    "allowedCharacters": "0123456789yz-",
    "templates": {
        "fraction": True,
        "radical": True,
        "exponent": True,
        "absoluteValue": True,
    },
}


def test_absolute_value_becomes_the_editors_mod_template(plan):
    """`Mod` is the editor's own name for bars.

    `addElement` groups it with `PBrace` and `SBrace` and guards it with
    `qualifyLoadParenthesis`, so it loads like a parenthesis: on an empty box,
    focused inside.
    """
    assert plan("|y|", BARS) == {
        "ok": True,
        "steps": [{"op": "template", "name": "Mod"}, {"op": "type", "text": "y"}],
    }


def test_the_even_root_answer_is_buildable(plan):
    """The answer Hawkes wanted for question 7, as steps.

    The power sits inside the bars, which is why the solver prints `|y^5|`
    rather than `|y|^5`: the two are equal for every real y, but only one puts
    the exponent on a box the cursor can reach.
    """
    built = plan("z^4|y^5|/3", BARS)
    assert built["ok"] is True
    names = [step.get("name") or step["op"] for step in built["steps"]]
    assert names == [
        "Fraction", "type", "Exponent", "type", "base",
        "Mod", "type", "Exponent", "type", "denominator", "type",
    ]


def test_bars_are_refused_when_the_question_does_not_permit_them(plan):
    """A question that lists no `Mod` template will not take one."""
    refusal = plan("|y^5|z^4/3", FRACTIONS)
    assert refusal["ok"] is False
    assert refusal["code"] == "answer-needs-absolute-value"


def test_an_unclosed_bar_is_refused_rather_than_guessed(plan):
    refusal = plan("|y^5", BARS)
    assert refusal["ok"] is False
    assert refusal["code"] == "absolute-value-not-understood"


# Lesson 1.2 question 9: the cube root of 320, whose answer is 4 times the cube
# root of 5 -- a radical the simplification keeps rather than removes.
INDEXED = {
    "allowedCharacters": "0123456789x",
    "templates": {
        "fraction": True,
        "radical": True,
        "exponent": True,
        "absoluteValue": False,
    },
}


def test_a_cube_root_fills_the_index_then_the_radicand(plan):
    """`IndexedRadical` is `loadRadical(fromKeypad, IsIndexed)`.

    It focuses the index box and offers the radicand as its next slot, which is
    the order the executor walks slots in, so the index is typed first and one
    `base` step moves into the radicand.
    """
    assert plan("4∛5", INDEXED) == {
        "ok": True,
        "steps": [
            {"op": "type", "text": "4"},
            {"op": "template", "name": "IndexedRadical"},
            {"op": "type", "text": "3"},
            {"op": "base"},
            {"op": "type", "text": "5"},
        ],
    }


def test_a_square_root_stays_the_plain_radical(plan):
    """Index two needs no index box, so it is `Radical`, not `IndexedRadical`."""
    assert plan("√20", INDEXED) == {
        "ok": True,
        "steps": [{"op": "template", "name": "Radical"}, {"op": "type", "text": "20"}],
    }


def test_the_index_is_read_from_the_sign(plan):
    """The solver writes the index into the sign: `∜` is four, `⁵√` is five."""
    for answer, index in (("∜3", "4"), ("⁵√7", "5"), ("∛5", "3")):
        steps = plan(answer, INDEXED)["steps"]
        assert steps[0] == {"op": "template", "name": "IndexedRadical"}
        assert steps[1] == {"op": "type", "text": index}
