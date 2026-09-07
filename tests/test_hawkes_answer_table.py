"""The table a completion question is answered in, read as a table.

Lesson 2.1 completes a table of values for `x = y²`. The page draws two rows
headed `x` and `y`; each of the five following columns is an ordered pair with
one stated value and one answer box. Live,
on 2026-09-07, what crossed to Facet was the equation and a sentence:

    question-read  expressions=1 table=no-data-table promptChars=123

`x = y²` and "complete the table" is not a question anybody can answer -- the
givens *are* the question, and none of them crossed. `dataTable` could not have
carried them: it reads the table a question states its numbers in, and refuses
any table holding an answer control, which is exactly what this one is.

These tests read `tests/fixtures/table-completion.html` through the probe
itself and pin what now crosses: the grid, with each cell either a value the
page states or a numbered blank, and the radicals still exact.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pydantic
import pytest
from facet_loopback import facet, reasoning
from hawkes_dom import read_fixture, read_question

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "table-completion.html"

#: What the page states, in the order it draws the cells. The blanks are y for
#: x=0, x for y=2√2, y for x=64, y for x=25, and x for y=-√3.
EXPECTED_ROWS = [
    [{"mathml": "<math><mn>0</mn></math>"}, {"blank": 1}],
    [{"blank": 2}, {"mathml": "<math><mn>2</mn><msqrt><mn>2</mn></msqrt></math>"}],
    [{"mathml": "<math><mn>64</mn></math>"}, {"blank": 3}],
    [{"mathml": "<math><mn>25</mn></math>"}, {"blank": 4}],
    [{"blank": 5}, {"mathml": "<math><mo>-</mo><msqrt><mn>3</mn></msqrt></math>"}],
]


@pytest.fixture(scope="module")
def completion():
    return read_fixture("table-completion.html")


def variant(**replacements: str) -> dict:
    """The real fixture with one thing changed, read through the probe."""
    markup = FIXTURE.read_text(encoding="utf-8")
    for old, new in replacements.items():
        original = old.replace("__", " ")
        assert original in markup, original
        markup = markup.replace(original, new)
    return read_question(markup)


# --- the grid ---------------------------------------------------------------


def test_the_whole_grid_crosses(completion) -> None:
    """Two live DOM rows become five ordered pairs, with every cell accounted for."""
    assert completion["evidence"]["answerTable"] == ""
    assert completion["answerTable"] == {"columns": ["x", "y"], "rows": EXPECTED_ROWS}
    assert completion["evidence"]["answerTableDetail"] == {
        "reader": "answer-table",
        "schema": 1,
        "build": completion["evidence"]["answerTableDetail"]["build"],
        "decision": "accepted",
        "branch": "row-headed",
        "reason": "",
        "candidates": {
            "controls": 5,
            "holding": 1,
            "kept": 1,
            "droppedHidden": 0,
            "droppedNested": 0,
            "droppedRows": 0,
            "droppedHeader": 0,
        },
        "table": {
            "domRows": 2,
            "domColumns": 6,
            "logicalRows": 5,
            "logicalColumns": 2,
            "controls": 10,
            "math": 5,
            "mathJax": 10,
            "blanks": 5,
        },
        "cell": None,
    }


def test_five_blanks_are_numbered_in_reading_order(completion) -> None:
    """A reply's part N and the page's Nth box must mean the same cell."""
    blanks = [
        cell["blank"]
        for row in completion["answerTable"]["rows"]
        for cell in row
        if "blank" in cell
    ]

    assert blanks == [1, 2, 3, 4, 5]


def test_each_blank_keeps_the_value_beside_it(completion) -> None:
    """The relationship, not two lists: which given each blank is paired with."""
    paired = []
    for row in completion["answerTable"]["rows"]:
        [blank] = [cell["blank"] for cell in row if "blank" in cell]
        [given] = [cell for cell in row if "blank" not in cell]
        column = "y" if row.index(next(c for c in row if "blank" in c)) == 1 else "x"
        paired.append((blank, column, given.get("text") or given["mathml"]))

    assert paired == [
        (1, "y", "<math><mn>0</mn></math>"),
        (2, "x", "<math><mn>2</mn><msqrt><mn>2</mn></msqrt></math>"),
        (3, "y", "<math><mn>64</mn></math>"),
        (4, "y", "<math><mn>25</mn></math>"),
        (5, "x", "<math><mo>-</mo><msqrt><mn>3</mn></msqrt></math>"),
    ]


def test_radicals_cross_as_mathml_not_as_their_glyphs(completion) -> None:
    """MathJax draws a radical sign; it does not write one.

    The visible text of `2√2` is the two digits and nothing between them, so a
    cell read as text would state the number 22. Both radical cells carry the
    MathML the page left beside the glyphs, and neither carries any text.
    """
    radicals = [
        cell
        for row in completion["answerTable"]["rows"]
        for cell in row
        if "msqrt" in cell.get("mathml", "")
    ]

    assert len(radicals) == 2
    assert all("text" not in cell for cell in radicals)
    assert "<msqrt><mn>2</mn></msqrt>" in radicals[0]["mathml"]
    assert "<msqrt><mn>3</mn></msqrt>" in radicals[1]["mathml"]


def test_the_equation_is_still_the_only_expression(completion) -> None:
    """The table's own MathML sits below the answer line and is not an
    expression to solve; it is carried as the table instead."""
    assert completion["expressions"] == [
        "<math><mi>x</mi><mo>=</mo><msup><mi>y</mi><mn>2</mn></msup></math>"
    ]


def test_the_givens_do_not_leak_into_the_prompt(completion) -> None:
    """A table flattened into a sentence is a run of bare numbers."""
    for stated in ("64", "25", "2√2"):
        assert stated not in completion["promptText"]


# --- an answer box is a position, never a value -----------------------------


def test_what_is_typed_in_a_box_is_never_read() -> None:
    """The one thing that must never cross: the student's own answer.

    A control's contents are not a text node, so the cell reader cannot see
    them; this proves it against a page where every box is already filled in.
    """
    read = variant(**{'class="qbaseCSS"': 'class="qbaseCSS" value="999"'})

    assert read["evidence"]["answerTable"] == ""
    assert read["answerTable"]["rows"] == EXPECTED_ROWS
    assert "999" not in json.dumps(read)


def test_the_observed_hawkes_accessibility_labels_are_not_table_values(
    completion,
) -> None:
    """The two live text owners label both controls in the exact wrapper."""
    markup = FIXTURE.read_text(encoding="utf-8")

    assert markup.count('label class="sr-only"') == 10
    assert markup.count('input type="radio" class="opt"') == 5
    assert markup.count('span class="QFractionBox"') == 5
    assert completion["evidence"]["answerTable"] == ""


def test_a_student_text_mirror_is_not_ignored_or_transmitted() -> None:
    """Only accessibility labels are decoration, not arbitrary hidden mirrors."""
    read = variant(**{
        '<input__class="qbaseCSS"__id="MatrixTextBoxes3_num"__maxlength="4">':
        '<span name="NotAnObject" style="visibility:hidden">SECRET</span>'
        '<input class="qbaseCSS" id="MatrixTextBoxes3_num" maxlength="4">'
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    assert "answerTable" not in read
    assert "SECRET" not in json.dumps(read)
    culprit = read["evidence"]["answerTableDetail"]["cell"]["textOwners"][-1]
    assert culprit["tag"] == "span"
    assert culprit["hidden"] is True
    assert culprit["ignored"] is False
    assert culprit["textChars"] == 6


def test_an_accessibility_label_targeting_another_control_is_refused() -> None:
    """A nearby screen-reader label is not automatically part of this editor."""
    read = variant(**{
        'for="MatrixTextBoxes3_num"': 'for="AnotherControl"'
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    assert "answerTable" not in read
    culprit = read["evidence"]["answerTableDetail"]["cell"]["textOwners"][0]
    assert culprit["classes"] == ["sr-only"]
    assert culprit["forOther"] is True
    assert culprit["forCellControl"] is False
    assert culprit["target"] == "none"
    assert culprit["ignored"] is False


def test_an_unassociated_sr_only_label_is_still_refused() -> None:
    """`sr-only` alone is not enough to erase page text from a blank."""
    read = variant(**{
        'for="MatrixTextBoxes3_opt"': ''
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    culprit = read["evidence"]["answerTableDetail"]["cell"]["textOwners"][1]
    assert culprit["srOnly"] is True
    assert culprit["forCellControl"] is False
    assert culprit["ignored"] is False


def test_a_label_targeting_a_control_in_another_cell_is_refused() -> None:
    """Association is local to this mathematical blank, never table-wide."""
    read = variant(**{
        'for="MatrixTextBoxes3_opt"': 'for="MatrixTextBoxes6_opt"'
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    culprit = read["evidence"]["answerTableDetail"]["cell"]["textOwners"][1]
    assert culprit["forOther"] is True
    assert culprit["forCellControl"] is False
    assert culprit["ignored"] is False


def test_the_accessibility_label_wrapper_must_match_exactly() -> None:
    """A similarly named label outside the observed chain remains cell text."""
    read = variant(**{
        '<span__class="FractionBoxStyle">': '<span class="OtherBoxStyle">'
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    assert "answerTable" not in read


def test_math_beside_the_control_is_still_refused() -> None:
    """A Hawkes label does not license an actual mathematical value beside it."""
    read = variant(**{
        '<input__class="qbaseCSS"__id="MatrixTextBoxes3_num"__maxlength="4">':
        '<input class="qbaseCSS" id="MatrixTextBoxes3_num" maxlength="4">'
        '<math><mn>7</mn></math>'
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    assert "answerTable" not in read
    detail = read["evidence"]["answerTableDetail"]["cell"]
    assert detail["math"] == 1
    assert any(not owner["ignored"] for owner in detail["textOwners"])


def test_a_box_with_words_beside_it_is_refused() -> None:
    """A cell is a blank or a value. One that is both is not read as either."""
    read = variant(**{
        '<input class="qbaseCSS" id="MatrixTextBoxes3_num" maxlength="4">':
        '<input class="qbaseCSS" id="MatrixTextBoxes3_num" maxlength="4">or 0'
    })

    assert read["evidence"]["answerTable"] == "blank-not-empty"
    assert "answerTable" not in read


# --- failing closed ---------------------------------------------------------


def test_a_drawn_cell_with_no_mathml_is_refused() -> None:
    """MathJax without its assistive copy cannot be read, and is not guessed.

    Reading those glyphs as text is how `2√2` becomes `22`, which is a
    different number stated confidently. The table is refused whole.
    """
    read = read_question(
        re.sub(
            r"<mjx-assistive-mml.*?</mjx-assistive-mml>",
            "",
            FIXTURE.read_text(encoding="utf-8"),
            flags=re.DOTALL,
        )
    )

    assert read["evidence"]["answerTable"] == "drawn-without-mathml"
    assert "answerTable" not in read


def test_a_second_candidate_table_is_refused() -> None:
    """Two tables holding answer controls is a page nobody can read for sure."""
    markup = FIXTURE.read_text(encoding="utf-8")
    read = read_question(
        markup
        + '<table><thead><tr><th>u</th><th>v</th></tr></thead><tbody>'
        + '<tr><td>1</td><td><input class="qbaseCSS" id="Other1_num"></td></tr>'
        + '<tr><td>2</td><td><input class="qbaseCSS" id="Other2_num"></td></tr>'
        + "</tbody></table>"
    )

    # Two tables held a control and both survived every rule; picking between
    # them is what this reader will not do.
    assert read["evidence"]["answerTable"] == "held-2-kept-2"
    assert "answerTable" not in read


def test_a_box_outside_the_table_is_refused() -> None:
    """Parts are placed by a sweep that sorts every box on the page.

    A sixth box outside the table would shift every part by one, so a table
    that does not hold all of them cannot be trusted to number its own blanks.
    """
    markup = FIXTURE.read_text(encoding="utf-8")
    read = read_question(markup + '<input class="qbaseCSS" id="Loose_num">')

    assert read["evidence"]["answerTable"] == "controls-outside-table"
    assert "answerTable" not in read


def test_a_table_without_a_heading_row_is_refused() -> None:
    """Without the real x/y row labels, this could only be a layout table."""
    markup = FIXTURE.read_text(encoding="utf-8").replace(
        "<tr><td>x</td>", "<tr><td>not-x</td>"
    )
    read = read_question(markup)

    assert read["evidence"]["answerTable"] == "held-1-kept-0-header-1"
    assert "answerTable" not in read


def test_more_blanks_than_the_answer_bound_are_refused() -> None:
    """Six blanks is more parts than the add-on can place, so none are read."""
    markup = FIXTURE.read_text(encoding="utf-8")
    markup = markup.replace(
        '<input type="radio" class="opt" id="MatrixTextBoxes6_opt" hidden>'
        '</span></span></span></span></td></tr>',
        '<input type="radio" class="opt" id="MatrixTextBoxes6_opt" hidden>'
        '</span></span></span></span></td>'
        '<td>9</td></tr>',
    ).replace(
        '</mjx-assistive-mml></mjx-container></td></tr>\n</tbody></table>',
        '</mjx-assistive-mml></mjx-container></td>'
        '<td><input class="qbaseCSS" id="MatrixTextBoxes12_num"></td></tr>\n'
        '</tbody></table>',
    )
    read = read_question(markup)

    assert read["evidence"]["answerTable"] == "blanks-6"
    assert "answerTable" not in read


def test_a_ragged_row_headed_table_is_refused() -> None:
    """Unequal x/y rows are not recognized as the live answer-table shape."""
    read = variant(**{
        '<input__type="radio"__class="opt"__id="MatrixTextBoxes6_opt"__hidden>'
        '</span></span></span></span></td></tr>':
        '<input type="radio" class="opt" id="MatrixTextBoxes6_opt" hidden>'
        '</span></span></span></span></td>'
        '<td>spare</td></tr>'
    })

    assert read["evidence"]["answerTable"] == "held-1-kept-0-header-1"
    assert "answerTable" not in read


# --- the ordinary data table is untouched -----------------------------------


@pytest.mark.parametrize(
    "page", ["table.html", "table-thead.html", "table-mathjax.html"]
)
def test_ordinary_data_tables_read_exactly_as_before(page) -> None:
    """The two readers are disjoint by construction.

    One reads the table that holds no answer control; the other reads the table
    that does. `judge_one_table` in the browser harness asserts the same three
    pages against a real DOM.
    """
    read = read_fixture(page)

    assert read["evidence"]["table"] == ""
    assert read["dataTable"] == {
        "columns": ["Price per Photo", "Number of Photos Sold", "Revenue"],
        "rows": [["$56", "4", "$224"], ["$52", "5", "$260"], ["$24", "12", "$288"]],
    }
    # A word problem's table holds no answer control, so there is nothing here
    # for the completion reader to find, and it says exactly that.
    assert read["evidence"]["answerTable"] == "no-table-holds-a-control"
    assert "answerTable" not in read


def test_a_completion_table_is_not_read_as_a_data_table(completion) -> None:
    """And the reverse: the answer surface is not the question's data."""
    assert completion["evidence"]["table"] == "no-data-table"
    assert "dataTable" not in completion


# --- the wire ---------------------------------------------------------------


def test_the_protocol_carries_the_grid() -> None:
    from ethnos.hawkes_protocol import AnswerTable

    table = AnswerTable(columns=["x", "y"], rows=EXPECTED_ROWS)

    assert [cell.blank for row in table.rows for cell in row if cell.blank] == [
        1, 2, 3, 4, 5
    ]
    assert table.rows[1][1].mathml.endswith("</math>")


@pytest.mark.parametrize(
    "rows,why",
    [
        ([[{"text": "0"}, {"text": "1"}], [{"text": "2"}, {"text": "3"}]], "no blank"),
        ([[{"text": "0"}, {"blank": 2}], [{"text": "1"}, {"blank": 3}]], "not from one"),
        ([[{"text": "0"}, {"blank": 1}], [{"text": "1"}, {"blank": 3}]], "a gap"),
        ([[{"text": "0"}, {"blank": 1, "text": "8"}], [{"text": "1"}, {"blank": 2}]],
         "both at once"),
        ([[{}, {"blank": 1}], [{"text": "1"}, {"blank": 2}]], "neither"),
    ],
    ids=["no-blank", "not-from-one", "gap", "both", "neither"],
)
def test_the_protocol_refuses_a_grid_it_cannot_place(rows, why) -> None:
    from ethnos.hawkes_protocol import AnswerTable

    with pytest.raises(pydantic.ValidationError):
        AnswerTable(columns=["x", "y"], rows=rows)


def test_the_host_states_the_table_in_the_question() -> None:
    """What Facet is asked, once the givens exist to ask about."""
    from ethnos.hawkes_host import instruction_with_answer_table
    from ethnos.hawkes_protocol import AnswerTable

    stated = instruction_with_answer_table(
        "Complete the table of values below for the given equation.",
        AnswerTable(columns=["x", "y"], rows=EXPECTED_ROWS),
    )

    assert stated.splitlines()[-6:] == [
        "x | y",
        "0 | (part 1)",
        r"(part 2) | 2\sqrt{2}",
        "64 | (part 3)",
        "25 | (part 4)",
        r"(part 5) | -\sqrt{3}",
    ]


def test_the_host_leaves_the_question_alone_when_there_is_no_table() -> None:
    from ethnos.hawkes_host import instruction_with_answer_table

    assert instruction_with_answer_table("Simplify.", None) == "Simplify."


def test_a_cell_the_converter_cannot_translate_states_no_table_at_all() -> None:
    """A partial table would be a different question, so it is all or nothing."""
    from ethnos.hawkes_host import instruction_with_answer_table
    from ethnos.hawkes_protocol import AnswerTable

    table = AnswerTable(
        columns=["x", "y"],
        rows=[
            [{"text": "0"}, {"blank": 1}],
            [{"blank": 2}, {"mathml": "<math><munder><mi>x</mi></munder></math>"}],
        ],
    )

    assert instruction_with_answer_table("Complete it.", table) == "Complete it."


# --- what the diagnostics keep ----------------------------------------------


def test_only_the_refusal_code_reaches_the_retained_ledger() -> None:
    """A record survives the browser session; a cell of coursework must not.

    `questionEvidence` builds by name, so the table's contents have no field to
    arrive under -- this proves it against evidence carrying every one of them.
    """
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(
        (EXTENSION / "common" / "failure-record.js")
        .read_text(encoding="utf-8")
        .replace("export ", "")
    )
    evidence = {
        "read": "markup",
        "expressions": 1,
        "graph": "no-regression-instruction",
        "table": "no-data-table",
        "answerTable": "drawn-without-mathml",
        "promptChars": 104,
        "signature": "MatrixTextBoxes3_num|11fmr2s|1769",
        "answerTableDetail": {
            "reader": "answer-table",
            "schema": 1,
            "build": "abcdef123456",
            "decision": "refused",
            "branch": "row-headed",
            "reason": "blank-not-empty",
            "candidates": {"controls": 5, "holding": 1, "kept": 1},
            "table": {"logicalRows": 5, "logicalColumns": 2, "blanks": 1},
            "cell": {
                "logicalRow": 2,
                "logicalColumn": 1,
                "textOwners": [{
                    "tag": "label",
                    "classes": ["sr-only", "SECRET-CLASS"],
                    "path": ["label.sr-only", "span.QFractionBox"],
                    "textNodes": 1,
                    "textChars": 999,
                    "ignored": False,
                    "forCellControl": True,
                    "target": "input.qbaseCSS",
                    "rawText": "SECRET",
                    "value": "999",
                }],
                "rawDom": "<label>SECRET</label>",
            },
            "rawQuestion": "SECRET",
        },
        # None of these are fields; every one must be dropped.
        "answerTableRows": EXPECTED_ROWS,
        "columns": ["x", "y"],
        "cells": ["0", "64", "25"],
    }

    kept = json.loads(
        context.eval(f"JSON.stringify(questionEvidence({json.dumps(evidence)}))")
    )

    assert kept == {
        "read": "markup",
        "expressions": 1,
        # Bounded to sixteen characters, as every code in this record is.
        "graph": "no-regression-in",
        "table": "no-data-table",
        "answerTable": "drawn-without-mathml",
        "answerTableDetail": kept["answerTableDetail"],
        "promptChars": 104,
        "signature": "MatrixTextBoxes3_num|11fmr2s|1769",
    }
    detail = kept["answerTableDetail"]
    assert detail["branch"] == "row-headed"
    assert detail["cell"]["textOwners"][0]["classes"] == ["sr-only"]
    assert detail["cell"]["textOwners"][0]["forCellControl"] is True
    assert detail["cell"]["textOwners"][0]["target"] == "input.qbaseCSS"
    assert "rawText" not in detail["cell"]["textOwners"][0]
    assert "64" not in json.dumps(kept)
    assert "SECRET" not in json.dumps(kept)


def test_every_refusal_code_is_a_shape_and_never_a_cell() -> None:
    """The codes are read back by a human and stored; they name conditions."""
    source = (EXTENSION / "content" / "hawkes-question.js").read_text(encoding="utf-8")
    reader = source[source.index("const answerTable = (() => {") :]
    reader = reader[: reader.index("\n  const expressions")]
    codes = re.findall(r"""refuse\((["`])(.*?)\1\)""", reader)
    codes = [code for _, code in codes]

    assert len(codes) >= 10, "the reader names each of its refusals"
    for code in codes:
        # A placeholder in a code is a count of nodes or a tally of refusals,
        # never a cell: `${blanks.length}` and `${why}` and nothing else.
        assert re.fullmatch(
            r"[a-z-]+(-?\$\{[a-z]+(\.length)?\}|[a-z0-9-]+)*", code
        ), code
    # And `why` itself is built only from the tally's own names and counts.
    assert '.map(([name, count]) => `-${name}-${count}`)' in reader


# --- through the real Facet router ------------------------------------------


def solve_request(read: dict, parts: int) -> dict:
    """The request the add-on builds, from what the probe actually read."""
    table = read["answerTable"]
    return {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "answer-table-1",
        "origin": "https://learn.hawkeslearning.com",
        "solve_engine": "facet",
        "problem": {
            "prompt_text": read["promptText"],
            "mathml": read["expressions"],
            "answer_table": {"columns": table["columns"], "rows": table["rows"][:parts]},
            "answer_shape": {
                "kind": "multi",
                "count": parts,
            },
        },
    }


def test_the_table_reaches_the_question_facet_is_asked(monkeypatch, completion) -> None:
    """End to end: the real grid makes Facet ask for all five ordered parts."""
    from ethnos.hawkes_host import handle

    loop = facet(
        monkeypatch,
        **reasoning(
            "FINAL ANSWER: 0 8 8 5 3\nPART 1: 0\nPART 2: 8\nPART 3: 8\n"
            "PART 4: 5\nPART 5: 3"
        ),
    )

    response = handle(solve_request(completion, 5))

    [asked] = loop.prompts
    assert "0 | (part 1)" in asked
    assert r"(part 2) | 2\sqrt{2}" in asked
    assert "This question takes 5 separate answers." in asked
    assert response.status == "ready"
    assert response.answer.parts == ["0", "8", "8", "5", "3"]


def test_the_answer_boxes_themselves_never_cross(monkeypatch, completion) -> None:
    """Which cell a part belongs to crosses; which box it is typed into does not."""
    from ethnos.hawkes_host import handle

    loop = facet(
        monkeypatch,
        **reasoning(
            "FINAL ANSWER: 0 8 8 5 3\nPART 1: 0\nPART 2: 8\nPART 3: 8\n"
            "PART 4: 5\nPART 5: 3"
        ),
    )

    handle(solve_request(completion, 5))

    crossed = json.dumps(loop.problems)
    for browser_only in ("MatrixTextBoxes", "qbaseCSS", "fieldId", "maxlength"):
        assert browser_only not in crossed
