"""Laying the answer out as mathematics, executed.

The answer travels between the host, the event page and the panel as one line
of text. Shown to a person, `\\frac{z^4|y^5|}{3}` is neither what Hawkes
renders nor what they must type -- reported by this add-on's owner as
"useless", and "confusing on what the answer really needs to be".

`common/answer-math.js` decides the layout and has no DOM, so it runs here
against the forms the solver actually produces.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

COMMON = Path(__file__).resolve().parents[1] / "extension" / "common"
IMPORT_LINE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE | re.DOTALL)

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


@pytest.fixture(scope="module")
def layout():
    source = IMPORT_LINE.sub(
        "", (COMMON / "answer-math.js").read_text()
    ).replace("export ", "")
    context = quickjs.Context()
    context.eval(source)

    def call(text):
        return json.loads(
            context.eval(f"JSON.stringify(layoutAnswer({json.dumps(text)}))")
        )

    return call


def kinds(row):
    return [item["kind"] for item in row["items"]]


def test_a_plain_answer_stays_one_piece_of_text(layout):
    """`13` gains nothing from being built out of elements."""
    assert layout("13") == {"kind": "row", "items": [{"kind": "text", "text": "13"}]}
    assert kinds(layout("Not a Real Number")) == ["text"]
    assert kinds(layout("(a - 5b)(x + 5y)")) == ["text"]


def test_an_empty_answer_lays_out_to_nothing(layout):
    assert layout("") == {"kind": "row", "items": []}


def test_powers_become_exponents(layout):
    row = layout("-x^13 + 2x^12 - 3x^11 + 5")

    assert kinds(row) == ["text", "sup", "text", "sup", "text", "sup", "text"]
    assert row["items"][1]["exponent"]["items"][0]["text"] == "13"


def test_a_parenthesised_exponent_is_taken_whole(layout):
    """`y^(3/2)` raises the fraction, not the 3."""
    row = layout("y^(3/2)")

    assert kinds(row) == ["text", "sup"]
    assert row["items"][1]["exponent"]["items"][0]["text"] == "3/2"


def test_a_bare_exponent_stops_at_its_own_run(layout):
    """`2x^2 + 3y` raises the 2, and stops. Taking the rest of the line would
    put the whole polynomial in the exponent."""
    row = layout("2x^2 + 3y")

    assert row["items"][1]["exponent"]["items"][0]["text"] == "2"
    assert row["items"][2]["text"] == " + 3y"


def test_a_fraction_becomes_a_numerator_over_a_denominator(layout):
    row = layout("\\frac{√5}{5}")

    assert kinds(row) == ["frac"]
    frac = row["items"][0]
    assert kinds(frac["numerator"]) == ["radical"]
    assert frac["denominator"]["items"][0]["text"] == "5"


def test_structure_survives_being_nested(layout):
    """The live shape from a fourth-root simplification: a fraction holding a
    power and an absolute value."""
    row = layout("\\frac{z^4|y^5|}{3}")

    numerator = row["items"][0]["numerator"]
    assert kinds(numerator) == ["text", "sup", "abs"]
    assert kinds(numerator["items"][2]["body"]) == ["text", "sup"]


def test_a_radical_covers_exactly_what_it_was_given(layout):
    """`√30y` is the root of thirty-y; `√(30)y` would not be. A rule drawn over
    the wrong span is a different answer, so the span is decided here."""
    bare = layout("√30y")
    grouped = layout("√(30y) + 1")

    assert bare["items"][0]["radicand"]["items"][0]["text"] == "30y"
    assert grouped["items"][0]["radicand"]["items"][0]["text"] == "30y"
    assert grouped["items"][1]["text"] == " + 1"


def test_an_indexed_root_keeps_its_index(layout):
    row = layout("∛8")

    assert row["items"][0]["index"] == "3"
    assert layout("√9")["items"][0]["index"] == ""


def test_unbalanced_input_still_lays_out(layout):
    """A malformed answer must still appear. Raising here would leave the panel
    with a fault banner instead of the answer it was handed."""
    for broken in ("\\frac{1}", "|y", "√(", "x^", "}{"):
        assert layout(broken)["kind"] == "row"


def test_every_form_the_solver_produces_is_handled(layout):
    """Taken from running the real solver, not invented."""
    for answer in (
        "-x^13 + 2x^12 - 3x^11 + 5",
        "(a - 5b)(x + 5y)",
        "\\frac{√5}{5}",
        "y^(3/2)",
        "\\frac{z^4|y^5|}{3}",
        "\\frac{√(30y)}{5√z}",
        "-5x(2y^2 + 3y - 5)",
        "13",
        "-1",
    ):
        row = layout(answer)
        assert row["items"], answer
        # Nothing is silently dropped: every character is still accounted for.
        def text_of(node):
            out = ""
            for item in node["items"]:
                if item["kind"] == "text":
                    out += item["text"]
                for field in ("exponent", "numerator", "denominator", "radicand", "body"):
                    if field in item:
                        out += text_of(item[field])
            return out
        stripped = re.sub(r"[\\^{}|()]|frac|√|∛|∜", "", answer)
        assert re.sub(r"[\s]", "", text_of(row)).replace("(", "").replace(")", "") != ""
