"""An ordered pair whose components are rationals, entered as one answer.

The recurring shape of this project's defects: Facet gains an exact family, the
answer is right, and the add-on turns out to have no way to type it. It happened
to the vertex, to the distance, to the quadrant, and on 2026-09-08 to the
midpoint -- `f1:808590338caf54c8` in the retained ledger:

    editor   kind=dynamic maxLength=16 templates=fraction+parentheses
    allowed  '0123456789-,'
    slots    numerator=0123456789-  denominator=0123456789
    refused  editor=answer-needs-template plan=answer-has-rejected-characters
    route    Facet Exact · SymPy exact midpoint of two points

Every piece was published. The question offers a Fraction template *and* a
parentheses template, the numerator slot takes a minus sign, the denominator
takes digits. The plan still refused, on the `/` -- because a fraction was only
ever recognised at the top level of an answer, and inside a group the character
loop met the slash with no branch for it.

That is a *composition* failure rather than a missing primitive, which is why
neither half looked broken. `(1,-4)` worked and `17/2` worked; `(17/2,-1/2)` did
not. See `docs/ANSWER_CAPABILITIES.md`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON = PROJECT_ROOT / "extension" / "common"
IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)


@pytest.fixture(scope="module")
def plan():
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js"):
        source = (COMMON / name).read_text(encoding="utf-8")
        context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))

    def call(answer, editor):
        return json.loads(
            context.eval(
                f"JSON.stringify(planEntry({json.dumps(answer)}, {json.dumps(editor)}))"
            )
        )

    return call


#: The live midpoint control, exactly as the ledger recorded it. The question
#: draws no brackets of its own: it publishes the parentheses template, so the
#: pair is built inside a group the plan presses for.
LIVE_MIDPOINT = {
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789-,",
    "maxLength": 16,
    "templates": {
        "fraction": True,
        "radical": False,
        "exponent": False,
        "parentheses": True,
        "absoluteValue": False,
    },
    "slots": {
        "base": "0123456789-,",
        "numerator": "0123456789-",
        "denominator": "0123456789",
        "exponent": "0123456789",
        "exponentBase": "0123456789xy",
        "index": "23456789",
        "radicand": "0123456789",
    },
}

#: The other pair topology: the page draws `( [box] )` and the box takes the
#: interior. Lesson 3.3's vertex control, which `test_hawkes_bracketed_pair`
#: covers for integer components.
PAGE_BRACKETED = {
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "1234567890-+,",
    "maxLength": 16,
    "templates": {
        "fraction": True,
        "radical": True,
        "exponent": True,
        "parentheses": False,
        "absoluteValue": False,
    },
}


def rendered(result):
    return " ".join(
        step["text"] if step["op"] == "type" else f"<{step.get('name', step['op'])}>"
        for step in result["steps"]
    )


def typed(result):
    return "".join(step["text"] for step in result["steps"] if step["op"] == "type")


# --- the live defect -------------------------------------------------------


def test_a_pair_of_rationals_is_built_inside_the_questions_own_brackets(plan):
    """The exact plan the live question needed and did not get."""
    result = plan("(17/2,-1/2)", LIVE_MIDPOINT)

    assert result["ok"] is True
    assert rendered(result) == (
        "<PBrace> <Fraction> 17 <denominator> 2 <base> , <Fraction> -1 <denominator> 2"
    )


def test_each_half_of_each_component_goes_into_its_own_slot(plan):
    """The slots publish different character sets -- the numerator takes a minus
    sign and the denominator does not -- so each is planned against its own."""
    result = plan("(-1/2,-3/2)", LIVE_MIDPOINT)

    assert result["ok"] is True
    assert typed(result) == "-12,-32"
    assert [step for step in result["steps"] if step["op"] == "slot"] == [
        {"op": "slot", "name": "denominator"},
        {"op": "slot", "name": "denominator"},
    ]


def test_the_caret_is_walked_out_of_the_first_fraction_before_the_comma(plan):
    """Without this the comma and the second component are typed into the first
    component's denominator, which is a wrong answer that looks entered."""
    result = plan("(17/2,-1/2)", LIVE_MIDPOINT)
    operations = [step["op"] for step in result["steps"]]

    comma = next(
        index
        for index, step in enumerate(result["steps"])
        if step["op"] == "type" and step["text"] == ","
    )
    assert operations[comma - 1] == "base"


def test_a_mixed_pair_builds_only_the_component_that_needs_it(plan):
    result = plan("(3,-1/2)", LIVE_MIDPOINT)

    assert result["ok"] is True
    assert rendered(result) == "<PBrace> 3, <Fraction> -1 <denominator> 2"


# --- and nothing that already worked has changed shape ---------------------


def test_an_integer_pair_is_still_one_typing_run(plan):
    """`(2,3)` planned as one `type` step before this and plans as one now.
    Splitting a list that carries no structure would be a new plan shape for
    every coordinate answer that already worked."""
    result = plan("(2,3)", LIVE_MIDPOINT)

    assert result["steps"] == [
        {"op": "template", "name": "PBrace"},
        {"op": "type", "text": "2,3"},
    ]


def test_a_page_bracketed_pair_of_rationals_still_takes_the_other_path(plan):
    """Where the page draws the brackets the pair is split before any template
    is pressed. That path already handled rationals and is untouched."""
    result = plan("(17/2,-1/2)", PAGE_BRACKETED)

    assert result["ok"] is True
    assert rendered(result) == (
        "<Fraction> 17 <denominator> 2 <base> , <Fraction> -1 <denominator> 2"
    )
    assert result["steps"][0] != {"op": "template", "name": "PBrace"}


def test_a_page_bracketed_integer_pair_is_unchanged(plan):
    result = plan("(1,-4)", PAGE_BRACKETED)

    assert result["ok"] is True
    assert typed(result) == "1,-4"
    assert {step["op"] for step in result["steps"]} == {"type"}


def test_a_top_level_rational_is_unchanged(plan):
    result = plan("17/2", LIVE_MIDPOINT)

    assert rendered(result) == "<Fraction> 17 <denominator> 2"


# --- and the refusals that should still refuse -----------------------------


def test_the_decimal_a_model_produces_is_still_refused(plan):
    """`(8.5,-0.5)` is the same value in a notation this box has no key for.
    Making the exact form enterable must not make the decimal enterable."""
    result = plan("(8.5,-0.5)", LIVE_MIDPOINT)

    assert result == {
        "ok": False,
        "code": "answer-has-rejected-characters",
        "detail": ".",
    }


def test_a_question_offering_no_fraction_template_still_refuses(plan):
    """A box with nowhere to put a denominator cannot take one, and guessing
    that a `/` will open one is how a half-built answer is left behind."""
    editor = {
        **LIVE_MIDPOINT,
        "templates": {**LIVE_MIDPOINT["templates"], "fraction": False},
    }

    result = plan("(17/2,-1/2)", editor)

    assert result["ok"] is False
    assert result["code"] == "answer-has-rejected-characters"


def test_a_box_that_takes_no_comma_refuses_the_pair(plan):
    """The comma is typed like anything else and is held to the same published
    set -- the base slot's, where the question publishes one."""
    editor = {
        **LIVE_MIDPOINT,
        "allowedCharacters": "0123456789-",
        "slots": {**LIVE_MIDPOINT["slots"], "base": "0123456789-"},
    }

    result = plan("(17/2,-1/2)", editor)

    assert result["ok"] is False
    assert result["code"] == "answer-has-rejected-characters"
    assert result["detail"] == ","


def test_an_empty_component_is_refused(plan):
    result = plan("(17/2,)", LIVE_MIDPOINT)

    assert result["ok"] is False


def test_a_denominator_the_slot_will_not_take_is_refused(plan):
    """Each half is checked against the slot it is actually typed into, so a
    denominator the question does not accept is refused before a key moves
    rather than raising the editor's own blocking dialog."""
    editor = {
        **LIVE_MIDPOINT,
        "slots": {**LIVE_MIDPOINT["slots"], "denominator": "3456789"},
    }

    result = plan("(17/2,-1/2)", editor)

    assert result["ok"] is False
    assert result["code"] == "answer-has-rejected-characters"
    assert result["detail"] == "2"
