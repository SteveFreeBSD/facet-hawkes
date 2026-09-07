"""Why the page's editor model said one box while the page showed five.

Steve removed the temporary add-on, loaded it fresh, pressed Solve once, and
the panel showed a single `0`. The build was current -- the running marker
`ac75732f0a93` folded from the working tree at `e48cec2`, 82 symbols, exactly
-- and the isolated DOM sweep had done its job:

    answer-target-inspected  multiFieldEvidence={"fields": 5, "fieldIds":
        ["MatrixTextBoxes3_num", "MatrixTextBoxes6_num", "MatrixTextBoxes8_num",
         "MatrixTextBoxes10_num", "MatrixTextBoxes11_num"]}
    editor-described         {"kind": "textbox", "code": "described",
                              "editors": 0, "maxLength": 4}

Five boxes found by name, and the page's own control collection described one
textbox. `answerShapeOf` reads that description and nothing else, so Facet was
asked for one value, returned one value correctly, and the panel rendered it.
The five parts became one *before* the question left the browser.

Which fault that was, this run could not say. A single described textbox is
what comes back when the collection holds one usable control, when four of five
are disabled, when `controlsCollectionData` covers only one index, and when the
collection is not array-like at all and the candidate loop never runs. Four
faults, one description, and no evidence between them.

These tests pin all four apart. Every existing test of this probe built the
collection the way it was imagined -- a dense array, data for every index,
everything enabled -- which is the one shape that was never in question.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE = PROJECT_ROOT / "extension" / "content" / "hawkes-describe.js"


def describe(model: str, drawn: int | None = None) -> dict:
    """Run the MAIN-world probe against a page publishing this `quant_wp_UI`.

    `drawn` is how many answer boxes the page is showing. Left out, there is no
    document at all and the probe reports `-1` -- unknown, and never grounds to
    overrule the page's own model.
    """
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(f"globalThis.window = {{quant_wp_UI: {model}}};")
    if drawn is not None:
        box = "{getBoundingClientRect: () => ({width: 60, height: 20})}"
        context.eval(
            "globalThis.document = {querySelectorAll: () => Array.from("
            f"{{length: {drawn}}}, () => ({box}))}};"
        )
    return json.loads(context.eval(PROBE.read_text(encoding="utf-8")).json())


def control(enabled: bool = True) -> str:
    return f"{{enabled: {'true' if enabled else 'false'}}}"


def data(enabled: bool = True) -> str:
    return (
        '{Name: "cell", isQDy: false, boxValue: "", validString: "[0-9-]",'
        f" maxLength: 4, enableState: {'true' if enabled else 'false'}}}"
    )


def dense(count: int, enabled: int | None = None) -> str:
    """A plain array of controls, each with its data. The imagined shape."""
    live = count if enabled is None else enabled
    controls = ", ".join(control(index < live) for index in range(count))
    rows = ", ".join(data(index < live) for index in range(count))
    return (
        f"{{focusedElementIndex: 0, controlsCollection: [{controls}],"
        f" controlsCollectionData: [{rows}]}}"
    )


# --- the four shapes that all describe one textbox --------------------------


def test_five_usable_controls_are_one_multi_answer() -> None:
    """The shape every earlier test used, and the one that was never at fault."""
    described = describe(dense(5))

    assert described["kind"] == "multi"
    assert described["collection"] == {
        "branch": "multi",
        "controls": 5,
        "controlKeys": 5,
        "dataKeys": 5,
        "paired": 5,
        "described": 5,
        "usable": 5,
        "focused": 0,
        "drawn": -1,
    }


def test_five_controls_with_four_disabled_say_so() -> None:
    """One usable control out of five. Before this, indistinguishable."""
    described = describe(dense(5, enabled=1))

    assert described["kind"] == "textbox"
    assert described["collection"]["branch"] == "one-usable"
    assert described["collection"]["controls"] == 5
    assert described["collection"]["described"] == 5
    assert described["collection"]["usable"] == 1


def test_data_covering_one_index_says_so() -> None:
    """Five controls, one of them with its data. Also one textbox, also named."""
    controls = ", ".join(control() for _ in range(5))
    described = describe(
        f"{{focusedElementIndex: 0, controlsCollection: [{controls}],"
        f" controlsCollectionData: [{data()}]}}"
    )

    assert described["kind"] == "textbox"
    assert described["collection"]["branch"] == "one-usable"
    assert described["collection"]["controls"] == 5
    assert described["collection"]["dataKeys"] == 1
    assert described["collection"]["paired"] == 1


def test_a_collection_that_is_not_array_like_says_so() -> None:
    """No `length`, so the candidate loop never runs and nothing is paired.

    The probe still describes the focused control and still returns one
    textbox. What separates this from the three above is that `controls` is -1
    while `controlKeys` counts five: the collection was there and the loop
    could not walk it.
    """
    controls = ", ".join(f'"{index}": {control()}' for index in range(5))
    rows = ", ".join(f'"{index}": {data()}' for index in range(5))
    described = describe(
        f"{{focusedElementIndex: 0, controlsCollection: {{{controls}}},"
        f" controlsCollectionData: {{{rows}}}}}"
    )

    assert described["kind"] == "textbox"
    assert described["collection"] == {
        "branch": "focused",
        "drawn": -1,
        "controls": -1,
        "controlKeys": 5,
        "dataKeys": 5,
        "paired": 0,
        "described": 0,
        "usable": 0,
        "focused": 0,
    }


def test_the_four_shapes_are_told_apart() -> None:
    """The whole point: one description, four collections, four readings."""
    controls = ", ".join(control() for _ in range(5))
    sparse = (
        f"{{focusedElementIndex: 0, controlsCollection: [{controls}],"
        f" controlsCollectionData: [{data()}]}}"
    )
    keyed_controls = ", ".join(f'"{index}": {control()}' for index in range(5))
    keyed_data = ", ".join(f'"{index}": {data()}' for index in range(5))
    keyed = (
        f"{{focusedElementIndex: 0, controlsCollection: {{{keyed_controls}}},"
        f" controlsCollectionData: {{{keyed_data}}}}}"
    )
    seen = [
        describe(model)
        for model in (dense(5), dense(5, enabled=1), sparse, keyed)
    ]

    # Three of the four describe a single textbox, which is what the live run
    # reported and could not explain.
    assert [one["kind"] for one in seen] == ["multi", "textbox", "textbox", "textbox"]
    assert len({json.dumps(one["collection"], sort_keys=True) for one in seen}) == 4


# --- the collection is counts, and only counts ------------------------------


def test_no_control_content_reaches_the_collection_report() -> None:
    """It is read back off a live page and stored in a bounded ledger."""
    described = describe(
        '{focusedElementIndex: 0,'
        ' controlsCollection: [{enabled: true, boxValue: "SECRET"}],'
        ' controlsCollectionData: [{Name: "SECRET", isQDy: false,'
        ' boxValue: "SECRET", validString: "[0-9-]", maxLength: 4,'
        " enableState: true}]}"
    )

    assert "SECRET" not in json.dumps(described["collection"])
    assert all(
        isinstance(value, (int, str)) for value in described["collection"].values()
    )


def test_the_retained_ledger_keeps_the_counts_and_nothing_else() -> None:
    from json import dumps

    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(
        (PROJECT_ROOT / "extension" / "common" / "failure-record.js")
        .read_text(encoding="utf-8")
        .replace("export ", "")
    )
    editor = {
        "ok": True,
        "kind": "textbox",
        "code": "described",
        "enabled": True,
        "maxLength": 4,
        "allowedCharacters": "[0-9-]",
        "collection": {
            "branch": "one-usable",
            "controls": 5,
            "controlKeys": 5,
            "dataKeys": 5,
            "paired": 5,
            "described": 5,
            "usable": 1,
            "focused": 0,
            "drawn": 1,
            # Not a field; it must be dropped.
            "boxValue": "SECRET",
        },
    }

    kept = json.loads(context.eval(f"JSON.stringify(editorEvidence({dumps(editor)}))"))

    assert kept["collection"] == {
        "branch": "one-usable",
        "controls": 5,
        "controlKeys": 5,
        "dataKeys": 5,
        "paired": 5,
        "described": 5,
        "usable": 1,
        "focused": 0,
        "drawn": 1,
    }
    assert "SECRET" not in json.dumps(kept)


def test_a_probe_that_read_no_collection_still_reports_one() -> None:
    """An editor model that never loaded is a different fault again."""
    assert describe("undefined")["code"] == "editor-model-missing"
    assert describe("{controlsCollection: []}")["collection"]["branch"] == "none"


# --- one drawn box is one answer -------------------------------------------
#
# Live, on 2026-09-07: `2x + y = 2`, "determine the missing coordinate in
# (4, ?) so that it satisfies the equation". One box on screen, one answer, and
# the answer is -6. The page's control collection published two usable controls
# for that one box -- a Hawkes answer box owns a numerator control and a
# denominator control, which is how typing `/` turns it into a fraction -- so
# this probe called it a two-part question:
#
#     editor-described {"kind":"multi","editors":2,"enabled":false,
#                       "collection":{"controls":2,"usable":2,"branch":"multi"}}
#     host-request-shaped {"answerShape":"multi","answerParts":2}
#     solved {"answerParts":2,"facetRouter":"declined","facetMethod":"gpt-oss:20b"}
#
# The host was asked for two answers and a reasoning model produced two -- `10`
# and `10` -- for a question with one. The panel offered them as #1 and #2, and
# insertion had nowhere to put either.
#
# The control collection was never a count of the question's blanks. The table
# reader established that for a cell; this is the same fact asked of the whole
# question, and the page's own drawn boxes are what settle it.


def pair_model(focused: int = 0) -> str:
    """One blank's two controls: the box, and the half a `/` would open."""
    controls = ", ".join(control() for _ in range(2))
    rows = ", ".join(data() for _ in range(2))
    return (
        f"{{focusedElementIndex: {focused}, controlsCollection: [{controls}],"
        f" controlsCollectionData: [{rows}]}}"
    )


def test_two_controls_behind_one_drawn_box_are_one_answer() -> None:
    """The live regression: one box, one answer, described as one."""
    described = describe(pair_model(), drawn=1)

    assert described["kind"] == "textbox"
    assert described["collection"]["branch"] == "one-drawn-box"
    assert described["collection"]["usable"] == 2
    assert described["collection"]["drawn"] == 1
    # And it is a usable description, not the disabled husk the multi branch
    # returned -- which is what "the answer editor could not be read" was.
    assert described["enabled"] is True
    assert described["allowedCharacters"] == "[0-9-]"
    assert described["maxLength"] == 4


def test_two_controls_behind_two_drawn_boxes_are_still_two_answers() -> None:
    """The genuine multi-field question is untouched."""
    described = describe(pair_model(), drawn=2)

    assert described["kind"] == "multi"
    assert len(described["editors"]) == 2
    assert described["collection"]["branch"] == "multi"


def test_a_completion_grid_is_not_collapsed_by_this() -> None:
    """Five blanks drawn as five boxes stay five, whatever the model holds."""
    described = describe(dense(5), drawn=5)

    assert described["kind"] == "multi"
    assert described["collection"]["branch"] == "multi"


def test_the_live_ten_control_grid_is_untouched() -> None:
    """The table path: ten controls, five drawn boxes, past the bound anyway."""
    described = describe(dense(10), drawn=5)

    assert described["kind"] == "textbox"
    assert described["collection"]["branch"] == "focused"
    assert described["collection"]["drawn"] == 5


def test_an_unknown_drawn_count_never_overrules_the_model() -> None:
    """No document to read: the page said nothing, so nothing is inferred."""
    described = describe(pair_model())

    assert described["collection"]["drawn"] == -1
    assert described["kind"] == "multi"


def test_the_described_box_is_the_one_the_page_has_selected() -> None:
    """Two controls, one box: the page's own mirror says which is being edited."""
    described = describe(pair_model(focused=1), drawn=1)

    assert described["kind"] == "textbox"
    assert described["collection"]["branch"] == "one-drawn-box"
