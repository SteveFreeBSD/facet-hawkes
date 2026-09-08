"""A pair whose brackets the page draws rather than the student typing them.

Lesson 3.3 step 1 asks for the vertex of `k(x) = (x-1)^2 - 4` and renders
`( [box] )` around a single dynamic box. Facet answers `(1,-4)` correctly and
the add-on refused it every time:

    answer-not-insertable {"editor":"answer-needs-template",
      "plan":"template-refused-by-question","answerLength":6,
      "editorKind":"dynamic","editorMaxLength":16,
      "allowed":"1234567890-+,","templates":"fraction+radical+exponent",
      "editorNeeds":"parentheses","planNeeds":"parentheses"}

The box publishes a comma and no parentheses template, so `(1,-4)` cannot be
entered by any route while `1,-4` fits exactly. The discriminator is the
template and it is the page's own: a question that means its brackets offers
the template to build them -- which is how interval notation is asked -- and a
question that offers none drew them instead.
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


#: The live lesson 3.3 vertex control, exactly as the page published it.
VERTEX = {
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


def _typed(result):
    return "".join(step["text"] for step in result["steps"] if step["op"] == "type")


def test_the_vertex_goes_in_without_its_brackets(plan):
    result = plan("(1,-4)", VERTEX)

    assert result["ok"] is True
    assert _typed(result) == "1,-4"
    # Nothing is built: every step is typing, into the box the page bracketed.
    assert {step["op"] for step in result["steps"]} == {"type"}


def test_a_question_that_offers_the_template_still_builds_its_brackets(plan):
    """Interval notation is asked by offering `PBrace`. That path is unchanged,
    and it is what stops this from eating an answer that means its brackets."""
    editor = {**VERTEX, "templates": {**VERTEX["templates"], "parentheses": True}}

    result = plan("(1,-4)", editor)

    assert result["ok"] is True
    assert result["steps"][0] == {"op": "template", "name": "PBrace"}
    assert _typed(result) == "1,-4"


def test_a_box_that_takes_no_comma_is_still_refused(plan):
    """The comma in the character set is the page saying the box holds a pair.
    Without it there is no evidence of a drawn shell, so nothing is assumed."""
    editor = {**VERTEX, "allowedCharacters": "1234567890-+"}

    result = plan("(1,-4)", editor)

    assert result == {
        "ok": False,
        "code": "template-refused-by-question",
        "detail": "parentheses",
    }


def test_a_plain_textbox_is_left_alone(plan):
    """ "Parentheses can only come from a template" is the dynamic editor's
    rule. A plain box states its own pattern and may simply accept them."""
    editor = {
        "kind": "textbox",
        "allowedCharacters": "[0-9,.-]",
        "templates": {"parentheses": False},
    }

    result = plan("(1,-4)", editor)

    assert result["ok"] is False


def test_a_product_of_two_groups_is_not_a_bracketed_pair(plan):
    """`(a-5b)(x+5y)` is not enclosed by one pair, so nothing is stripped and
    the factoring answer keeps needing the template it really does need."""
    editor = {
        **VERTEX,
        "allowedCharacters": "1234567890abxy-+,",
    }

    result = plan("(a-5b)(x+5y)", editor)

    assert result == {
        "ok": False,
        "code": "template-refused-by-question",
        "detail": "parentheses",
    }


def test_a_single_bracketed_value_is_not_a_pair(plan):
    """One drawn bracket around one value is not evidence of a pair shell, and
    stripping it would change `(x+1)` into a different answer."""
    editor = {**VERTEX, "allowedCharacters": "1234567890xy-+,"}

    result = plan("(x+1)", editor)

    assert result["ok"] is False
    assert result["code"] == "template-refused-by-question"


def test_a_three_part_bracketed_group_is_not_a_pair(plan):
    result = plan("(1,-4,7)", VERTEX)

    assert result["ok"] is False


def test_a_pair_with_a_fraction_in_it_builds_that_fraction(plan):
    """The halves are planned separately, so a structural part still gets its
    template -- and the top-level slash is never mistaken for the whole
    answer's fraction, which is what splitting the interior as one run would
    have done."""
    result = plan("(1/2,-3)", VERTEX)

    assert result["ok"] is True
    assert result["steps"][0] == {"op": "template", "name": "Fraction"}
    assert {"op": "slot", "name": "denominator"} in result["steps"]
    # Back out to the base line before the comma, or it lands in the fraction.
    assert {"op": "base"} in result["steps"]
    assert _typed(result) == "12,-3"


def test_an_empty_half_is_refused(plan):
    assert plan("(1,)", VERTEX)["ok"] is False
    assert plan("(,-4)", VERTEX)["ok"] is False


# --- what the panel offers -------------------------------------------------


@pytest.fixture(scope="module")
def view():
    """`describeView(state, now)`, running as the panel runs it."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js", "panel-view.js"):
        source = (COMMON / name).read_text(encoding="utf-8")
        context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))

    def call(state):
        return json.loads(
            context.eval(f"JSON.stringify(describeView({json.dumps(state)}, 0, {{}}))")
        )

    return call


def test_the_panel_now_offers_the_vertex_for_insertion(view):
    """The user-visible outcome: Insert was disabled under an amber note on
    every attempt at this question, and the answer was correct throughout."""
    solved = view(
        {
            "phase": "solved",
            "answer": "(1,-4)",
            "displayText": "(1,-4)",
            "entryText": "(1,-4)",
            "editor": VERTEX,
            "promptSeen": True,
            "source": "Facet Exact",
            "signature": "QBase1_input|1d2an14|5664",
        }
    )

    assert solved["insert"]["enabled"] is True
    assert solved["status"]["kind"] == "ready"
    # Still reviewed as the ordered pair it is; only the typing drops the
    # brackets the page already draws.
    assert solved["answer"]["text"] == "(1,-4)"


def test_the_panel_still_refuses_when_the_box_takes_no_comma(view):
    refused = view(
        {
            "phase": "solved",
            "answer": "(1,-4)",
            "displayText": "(1,-4)",
            "entryText": "(1,-4)",
            "editor": {**VERTEX, "allowedCharacters": "1234567890-+"},
            "promptSeen": True,
            "source": "Facet Exact",
            "signature": "s",
        }
    )

    assert refused["insert"]["enabled"] is False
    assert refused["status"]["key"] == "errorTemplateRefused"
