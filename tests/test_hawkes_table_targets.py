"""One authoritative mapping from a table's blanks to the page's own boxes.

Live, on 2026-09-07, lesson 2.1's completion table was read correctly, crossed
to Facet as a grid, and answered exactly -- and then could not be inserted.
Ten runs ended the same way:

    editor-described  {"kind": "textbox", "editors": 0,
                       "collection": {"controls": 10, "usable": 10}}
    answer-shape      not-insertable · refused editor=answer-parts

Two readings were being asked to agree and could not. Hawkes' own control
collection holds one model per *value* cell -- ten of them for a five-blank
grid, given and blank alike -- so it can say neither how many answers there are
nor which control is which; and the isolated DOM sweep that finds "the answer's
fields" sorts boxes top-to-bottom, left-to-right and demands the word "or"
between them. The live grid's records run down its columns, so the sweep's
order and the mathematics' order name different cells for every blank:

    blank order   MatrixTextBoxes 8, 3, 10, 11, 6
    reading order MatrixTextBoxes 3, 6, 8, 10, 11

Placing five correct values in reading order puts all five in the wrong box.

So the reader that accepts the table now also states where its answers go, once,
and that mapping is what the panel offers, what the insertion is pinned to, and
what the write is aimed at. It is re-derived by the same reader immediately
before anything is written and compared cell by cell; a disagreement refuses.
The mapping never leaves the browser -- the host is told the grid and nothing
about boxes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hawkes_dom import read_fixture, read_question
from table_pages import column_headed_page, random_grid, row_headed_page

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


# --- what the reader states -------------------------------------------------


@pytest.fixture(scope="module")
def live():
    return read_fixture("table-completion.html")


def test_the_live_grid_maps_five_blanks_to_five_named_boxes(live) -> None:
    """The exact live case, in the order the mathematics numbers the cells."""
    mapping = live["answerTargets"]

    assert mapping["schema"] == 1
    assert mapping["branch"] == "row-headed"
    assert mapping["count"] == 5
    assert [blank["blank"] for blank in mapping["blanks"]] == [1, 2, 3, 4, 5]
    assert [blank["id"] for blank in mapping["blanks"]] == [
        "MatrixTextBoxes8_num",
        "MatrixTextBoxes3_num",
        "MatrixTextBoxes10_num",
        "MatrixTextBoxes11_num",
        "MatrixTextBoxes6_num",
    ]


def test_the_mapping_disagrees_with_reading_order_and_says_so(live) -> None:
    """The whole defect in one line: the two orders are not the same list."""
    mapping = live["answerTargets"]
    written = re.findall(
        r'<input class="qbaseCSS" id="([^"]+)"',
        (PROJECT_ROOT / "tests" / "fixtures" / "table-completion.html").read_text(),
    )

    assert [blank["id"] for blank in mapping["blanks"]] != written
    assert mapping["domOrderMatches"] is False
    assert live["evidence"]["answerTableDetail"]["table"]["domOrderMatches"] is False


def test_the_page_draws_twice_as_many_controls_as_it_has_answers(live) -> None:
    """The reading the editor collection cannot make.

    Ten controls, five of them hidden beside the visible boxes: this is why the
    page's own model reported one textbox for a page showing five, and why the
    mapping is taken from the table rather than from that collection.
    """
    detail = live["evidence"]["answerTableDetail"]["table"]

    assert detail["controls"] == 10
    assert detail["blanks"] == 5
    assert len(live["answerTargets"]["blanks"]) == 5


def test_each_blank_is_named_by_its_cell_and_never_by_its_box(live) -> None:
    """What the panel shows beside each part: the table's words, not an id."""
    labels = [blank["label"] for blank in live["answerTargets"]["blanks"]]

    assert labels == ["y #1", "x #2", "y #3", "y #4", "x #5"]
    assert not any("MatrixTextBoxes" in label for label in labels)


@pytest.mark.parametrize("seed", range(24))
def test_a_randomized_grid_maps_every_blank_to_the_box_in_that_cell(seed) -> None:
    """Hawkes changes the values, the blank count and where the blanks are.

    Nothing here is the fixture's arrangement: each seed places two to five
    blanks anywhere in a two-to-five pair grid, with ids Hawkes' own numbering
    never makes contiguous and which are shuffled besides, so no ordering can
    be recovered by sorting or by arithmetic.
    """
    markup, expected = random_grid(seed)

    read = read_question(markup)

    assert read["evidence"]["answerTable"] == ""
    assert [blank["id"] for blank in read["answerTargets"]["blanks"]] == expected
    assert [blank["blank"] for blank in read["answerTargets"]["blanks"]] == list(
        range(1, len(expected) + 1)
    )


def test_blanks_in_one_row_agree_with_reading_order_and_are_still_mapped() -> None:
    """The easy arrangement must not be a special case: same mapping, same rule."""
    markup = row_headed_page(
        [[1, 4, 9], [None, None, None]], ["boxA", "boxB", "boxC"]
    )

    read = read_question(markup)

    assert [blank["id"] for blank in read["answerTargets"]["blanks"]] == [
        "boxA", "boxB", "boxC"
    ]
    assert read["answerTargets"]["domOrderMatches"] is True


def test_a_column_headed_table_is_mapped_the_same_way() -> None:
    """The other shape Hawkes draws: records down the page, one blank each."""
    markup = column_headed_page(
        ["Price", "Sold", "Revenue"],
        [[4, 5, None], [6, 7, None]],
        ["revenueA", "revenueB"],
    )

    read = read_question(markup)

    assert read["answerTargets"]["branch"] == "column-headed"
    assert [
        (blank["id"], blank["row"], blank["column"], blank["label"])
        for blank in read["answerTargets"]["blanks"]
    ] == [("revenueA", 1, 3, "Revenue #1"), ("revenueB", 2, 3, "Revenue #2")]


def test_reading_order_is_recorded_and_no_longer_refuses_a_table() -> None:
    """It guarded a placement that geometry decided; nothing decides by geometry now."""
    source = (EXTENSION / "content" / "hawkes-question.js").read_text()

    assert "blank-order-disagrees" not in source
    assert "domOrderMatches" in source


def test_a_box_with_no_id_is_refused_rather_than_mapped_by_position() -> None:
    """A cell this browser cannot name again is a cell it must not write to."""
    markup = row_headed_page([[1, 4], [None, None]], ["kept", ""], bare=["kept", ""])

    read = read_question(markup)

    assert read["evidence"]["answerTable"] == "blank-without-an-id"
    assert "answerTargets" not in read


def test_two_cells_naming_one_control_are_refused() -> None:
    """Two blanks and one box is a page that cannot hold two answers."""
    markup = row_headed_page([[1, 4], [None, None]], ["same", "same"], bare=["same"])

    read = read_question(markup)

    assert read["evidence"]["answerTable"] == "blank-id-repeated"


def test_a_blank_nobody_can_type_into_is_refused() -> None:
    """`visible and editable` is the whole of what a target is."""
    for attribute in (" disabled", " readonly"):
        markup = row_headed_page(
            [[1, 4], [None, None]], ["boxA", "boxB"], {"boxB": attribute}
        )

        read = read_question(markup)

        assert read["evidence"]["answerTable"] == "blank-not-editable", attribute


def test_the_mapping_never_reaches_the_host(live) -> None:
    """The grid crosses; where its answers go does not."""
    from ethnos.hawkes_host import handle
    from facet_loopback import facet

    loop = facet(pytest.MonkeyPatch())
    handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "table-targets-1",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": live["promptText"],
                "mathml": live["expressions"],
                "answer_table": live["answerTable"],
                "answer_shape": {"kind": "multi", "count": 5},
            },
        }
    )

    crossed = json.dumps(loop.problems)
    for browser_only in ("MatrixTextBoxes", "answerTargets", "qbaseCSS", "maxLength"):
        assert browser_only not in crossed


# --- what the writer does with it -------------------------------------------
#
# The writer moved. A completion cell is a controlled editor -- the page owns a
# model per cell and routes `input` through the one it has selected -- so
# writing from an isolated world placed four parts in their cells and the fifth
# in someone else's, and reported five successful writes. That work, and the
# harness that reproduces the failure it was written against, now live in
# `tests/test_hawkes_table_writer.py`. What is checked here is that this
# mapping is what the write is aimed at.


def test_the_table_writer_is_no_longer_in_the_isolated_prelude() -> None:
    """It cannot be: an isolated script cannot see the page's own selection."""
    source = (EXTENSION / "content" / "hawkes-editor.js").read_text()

    assert "insertTableParts" not in source.replace(
        "`insertTableParts` used to live at this point in the file", ""
    )
    assert "quant_wp_UI" not in source
    assert "insertTableParts" not in (EXTENSION / "background.js").read_text()


def test_the_generic_multi_field_writer_is_untouched() -> None:
    """`insertAnswerParts` is the "or"-separated shape and keeps its own rules."""
    source = (EXTENSION / "content" / "hawkes-editor.js").read_text()

    assert "async function insertAnswerParts(parts, expectedFieldIds" in source
    assert 'code: "answer-fields-not-empty"' in source
    assert 'code: "native-input-fields"' in source
    # And the single-field writer still composes from the field it is editing.
    assert "function writeCharacter(target, character)" in source


# --- what the event page does with it ---------------------------------------

from test_hawkes_insertion_ownership import make_page  # noqa: E402

#: The live editor description: one plain box, digits and a minus, four long.
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

#: What the geometric sweep offers for the same page: the boxes in reading
#: order, which is not the order the answers are in.
SWEPT_IDS = [
    "MatrixTextBoxes3_num",
    "MatrixTextBoxes6_num",
    "MatrixTextBoxes8_num",
    "MatrixTextBoxes10_num",
    "MatrixTextBoxes11_num",
]

TABLE_INSPECT = {
    "ready": True,
    "code": "focused-answer-field",
    "via": "focused-field",
    "fieldId": SWEPT_IDS[0],
    "multiFieldEvidence": {
        "fields": 5,
        "separatorCandidates": 0,
        "separators": 0,
        "fieldIds": SWEPT_IDS,
    },
}

#: The five values Facet proves for this grid, in semantic blank order.
PARTS = ["0", "8", "8", "5", "3"]


def table_question():
    return read_fixture("table-completion.html")


def mapping_of(question):
    return question["answerTargets"]["blanks"]


def solved_table_state(page, question, targets=None, parts=None):
    """The state a solved completion table leaves behind."""
    page.run(
        f"""
        state = {{
          ...blankState(),
          phase: "solved",
          windowId: 1, tabId: 11, frameId: 0,
          fieldId: {json.dumps(SWEPT_IDS[0])},
          fieldIds: [],
          tableTargets: {json.dumps(targets if targets is not None else mapping_of(question))},
          editor: {json.dumps(TABLE_EDITOR)},
          answer: "0, 8, 8, 5, 3",
          displayText: "0, 8, 8, 5, 3",
          entryText: "",
          answerParts: {json.dumps(parts or PARTS)},
          signature: questionSignature(
            {json.dumps(SWEPT_IDS[0])}, {json.dumps(question)}
          ),
        }};
        """
    )


def entries(page, name):
    return [call for call in page.json("__H.calls") if call["func"] == name]


def test_prepare_reacquires_the_mapping_and_drops_the_sweep() -> None:
    """The controls are the page's; they are re-found on every prepare.

    A stale mapping is what an event page holds after a re-render that kept the
    grid and renumbered its boxes. It must be replaced by this read, not
    written into -- and the geometric sweep, which is offering five ids at the
    same moment, must not be adopted beside it.
    """
    page = make_page()
    question = table_question()
    stale = [{**blank, "id": f"stale{blank['blank']}"} for blank in mapping_of(question)]
    solved_table_state(page, question, targets=stale)

    page.run("prepare(1);")
    page.pump()
    page.answer(TABLE_INSPECT)
    page.answer(TABLE_EDITOR)
    page.answer(question)

    assert [one["id"] for one in page.json("state.tableTargets")] == [
        one["id"] for one in mapping_of(question)
    ]
    assert page.json("state.fieldIds") == []
    assert page.json("state.phase") == "solved"
    mapped = page.said("table-targets-mapped")
    assert mapped and mapped[-1]["data"]["blanks"] == 5
    assert mapped[-1]["data"]["domOrderMatches"] is False
    assert mapped[-1]["data"]["swept"] == SWEPT_IDS
    assert mapped[-1]["data"]["adopted"] == []


def test_a_multi_reading_of_the_same_page_never_takes_the_targets() -> None:
    """Even when the collection publishes exactly five, the table decides.

    Five published editors and five boxes is the one shape `answerFieldIds`
    adopts, and adopting it here would place the answers in reading order --
    which for this grid is five wrong cells.
    """
    page = make_page()
    question = table_question()
    solved_table_state(page, question)
    editor = {
        "ok": True,
        "code": "described-multi",
        "kind": "multi",
        "editors": [{**TABLE_EDITOR} for _ in range(5)],
    }

    page.run("prepare(1);")
    page.pump()
    page.answer(TABLE_INSPECT)
    page.answer(editor)
    page.answer(question)

    assert page.json("state.fieldIds") == []
    assert [one["id"] for one in page.json("state.tableTargets")] == [
        one["id"] for one in mapping_of(question)
    ]


def test_the_insertion_writes_to_the_cells_the_mapping_names() -> None:
    """The whole point: five values, five cells, and not one of them by position."""
    page = make_page()
    question = table_question()
    solved_table_state(page, question)

    page.run("insert();")
    page.pump()
    page.answer(TABLE_EDITOR)  # the editor, re-read
    page.answer(question)  # the signature and the mapping, from one read
    page.answer({"ok": True, "code": "entered-table-cells", "settled": 5, "models": 5,
                 "cells": [one["id"] for one in mapping_of(question)]})
    page.answer(question)  # finishInsertion's rebase read

    [write] = entries(page, "enterTableCells")
    assert write["args"][0] == PARTS
    assert write["args"][1] == [
        "MatrixTextBoxes8_num",
        "MatrixTextBoxes3_num",
        "MatrixTextBoxes10_num",
        "MatrixTextBoxes11_num",
        "MatrixTextBoxes6_num",
    ]
    assert write["args"][1] != SWEPT_IDS, "reading order would be five wrong cells"
    assert page.json("state.phase") == "inserted"
    assert entries(page, "enterPlainAnswerParts") == []


def test_a_renumbered_grid_refuses_rather_than_writing_by_position() -> None:
    """Same question, same values, new boxes: nothing may be written.

    This is the failure the second reading exists to catch. The signature still
    matches -- the grid has not changed -- so every other gate agrees, and only
    the mapping can tell that the page it was reviewed against is gone.
    """
    page = make_page()
    question = table_question()
    solved_table_state(page, question)
    renumbered = json.loads(json.dumps(question))
    for blank in renumbered["answerTargets"]["blanks"]:
        blank["id"] = f"{blank['id']}_v2"

    page.run("insert();")
    page.pump()
    page.answer(TABLE_EDITOR)
    page.answer(renumbered)

    assert entries(page, "enterTableCells") == []
    assert page.json("state.errorKey") == "errorQuestionChanged"
    changed = page.said("table-targets-changed-before-insert")
    assert changed and changed[-1]["data"]["blanks"] == 5


def test_a_grid_that_stopped_mapping_at_all_refuses() -> None:
    """A box the reader can no longer name is not a box to write into."""
    page = make_page()
    question = table_question()
    solved_table_state(page, question)
    unmapped = json.loads(json.dumps(question))
    unmapped["answerTargets"]["blanks"] = []

    page.run("insert();")
    page.pump()
    page.answer(TABLE_EDITOR)
    page.answer(unmapped)

    assert entries(page, "enterTableCells") == []
    assert page.json("state.errorKey") == "errorQuestionChanged"


def test_an_answer_the_boxes_will_not_take_is_refused_before_the_write() -> None:
    """The question's own character rule, re-read, against the approved answer."""
    page = make_page()
    question = table_question()
    solved_table_state(page, question, parts=["0", "8", "8", "5", "3.5"])

    page.run("insert();")
    page.pump()
    page.answer(TABLE_EDITOR)
    page.answer(question)

    assert entries(page, "enterTableCells") == []
    assert page.json("state.errorKey") == "errorEditorUnknown"


def test_the_mapping_is_an_ownership_component() -> None:
    """A pinned insertion is abandoned if the state's mapping moves under it."""
    page = make_page()
    question = table_question()
    solved_table_state(page, question)

    page.run("insert();")
    page.pump()
    page.run(
        "state = {...state, tableTargets: state.tableTargets.map("
        "(one, index) => ({...one, id: index === 0 ? 'moved' : one.id}))};"
    )
    page.answer(TABLE_EDITOR)
    page.pump()

    assert entries(page, "enterTableCells") == []
    assert page.said("insertion-target-changed")
    assert "tableTargets" in page.said("insertion-target-changed")[-1]["data"]["changed"]


def test_the_mapping_is_never_named_in_a_host_request() -> None:
    """Every host call this event page makes, checked as text."""
    source = (EXTENSION / "background.js").read_text()
    shaped = source[source.index("          problem: {") :]
    shaped = shaped[: shaped.index("answer_shape: shape,")]

    assert "answer_table: question.answerTable" in shaped
    assert "answerTargets" not in shaped
    assert "tableTargets" not in shaped

