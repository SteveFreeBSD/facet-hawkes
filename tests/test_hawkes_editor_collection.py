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


def describe(model: str) -> dict:
    """Run the MAIN-world probe against a page publishing this `quant_wp_UI`."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(f"globalThis.window = {{quant_wp_UI: {model}}};")
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
    }
    assert "SECRET" not in json.dumps(kept)


def test_a_probe_that_read_no_collection_still_reports_one() -> None:
    """An editor model that never loaded is a different fault again."""
    assert describe("undefined")["code"] == "editor-model-missing"
    assert describe("{controlsCollection: []}")["collection"]["branch"] == "none"
