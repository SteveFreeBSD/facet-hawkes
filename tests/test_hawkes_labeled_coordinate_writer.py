"""Label-owned coordinate entry reuses the existing controlled-field writer."""

import json
from pathlib import Path

import pytest

from test_hawkes_table_writer import PAGE, WRITER, quickjs

ROWS = [
    {"label": "R", "x": "txtAns-p_num", "y": "txtAns-z_num"},
    {"label": "T", "x": "txtAns-b_num", "y": "txtAns-d_num"},
    {"label": "U", "x": "txtAns-a_num", "y": "txtAns-k_num"},
]
VALUES = ["-4", "2", "0", "-6", "8", "0"]


def page(knockout=False):
    context = quickjs.Context()
    context.eval(PAGE)
    context.eval(WRITER)
    ids = [row[axis] for row in ROWS for axis in ("x", "y")]
    context.eval(f"buildTable({json.dumps(list(reversed(ids)))});")
    context.eval(f"const coordinateRows = {json.dumps(ROWS)};")
    context.eval(r"""
      const labelNodes = {};
      const byId = document.getElementById;
      document.getElementById = id => labelNodes[id] ?? byId(id);
      const query = document.querySelectorAll;
      document.querySelectorAll = selector => selector.includes('input') && !selector.includes('customMessageBox')
        ? fields.filter(field => field.kind === 'box') : query(selector);
      for (const row of coordinateRows) for (const axis of ['x','y']) {
        const field = byId(row[axis]);
        const id = 'label-' + field.id;
        labelNodes[id] = {textContent:`point ${row.label} ${axis} coordinate`};
        field.getAttribute = name => name === 'aria-labelledby' ? id : null;
      }
      globalThis.Event = class {constructor(type) {this.type = type;}};
    """)
    if knockout:
        context.eval(r"""
          const ui = window.quant_wp_UI;
          for (const [index, control] of ui.controlsCollection.entries()) {
            if (control.field.kind !== 'box') continue;
            delete control.boxValue;
            const field = control.field;
            const attribute = field.getAttribute;
            field.getAttribute = name => name === 'data-bind'
              ? "value: boxValue, valueUpdate: 'afterkeydown'" : attribute(name);
            const dispatch = field.dispatchEvent.bind(field);
            field.dispatchEvent = event => {
              if (event.type === 'input') return true;
              if (event.type === 'change') {
                control.buffer = field.value;
                ui.controlsCollectionData[index].boxValue = field.value;
                return true;
              }
              return dispatch(event);
            };
          }
        """)
    return context


def write(context):
    ids = [row[axis] for row in ROWS for axis in ("x", "y")]
    cadence = {"score": {"offsets": [0] * len("".join(VALUES))}}
    context.eval(
        f"var outcome; enterOwnedFields({json.dumps(VALUES)}, {json.dumps(ids)}, {json.dumps(cadence)}, 'coordinates', coordinateRows).then(value => outcome = value);"
    )
    for _ in range(20000):
        if not context.execute_pending_job():
            break
    return json.loads(context.eval("JSON.stringify(outcome)"))


@pytest.mark.parametrize("knockout", [False, True])
def test_shuffled_owners_receive_and_retain_their_own_coordinates(knockout):
    context = page(knockout)
    result = write(context)
    assert result["ok"], result
    assert result["settled"] == 6
    assert result["models"] == 6
    assert (
        json.loads(
            context.eval(
                "JSON.stringify(coordinateRows.flatMap(row => [document.getElementById(row.x).value, document.getElementById(row.y).value]))"
            )
        )
        == VALUES
    )


@pytest.mark.parametrize(
    "fault", ["label", "axis", "duplicate", "changed-during-entry"]
)
def test_wrong_or_changing_identity_is_refused(fault):
    context = page()
    change = "labelNodes['label-txtAns-p_num'].textContent = 'point T x coordinate';"
    if fault == "axis":
        change = (
            "labelNodes['label-txtAns-p_num'].textContent = 'point R y coordinate';"
        )
    elif fault == "duplicate":
        change = "coordinateRows[1].label = 'R';"
    elif fault == "changed-during-entry":
        change = (
            "const oldInput = __hawkesInput; __hawkesInput = event => { oldInput(event); "
            + change
            + " };"
        )
    context.eval(change)
    result = write(context)
    assert result["ok"] is False
    assert "identity" in result["code"] or "mapping" in result["code"]


def test_typed_set_publication_requires_matching_labels():
    context = quickjs.Context()
    source = (
        Path(__file__).resolve().parents[1] / "extension/common/labeled-coordinates.js"
    ).read_text()
    context.eval(source.replace("export function", "function"))
    points = [
        {"label": row["label"], "x": VALUES[index * 2], "y": VALUES[index * 2 + 1]}
        for index, row in enumerate(ROWS)
    ]
    call = f"labeledCoordinateAnswer({json.dumps(points)}, {json.dumps(ROWS)})"
    assert context.eval(call) == "R: (-4,2); T: (0,-6); U: (8,0)"
    points[1]["label"] = "R"
    assert (
        context.eval(
            f"labeledCoordinateAnswer({json.dumps(points)}, {json.dumps(ROWS)})"
        )
        is None
    )


@pytest.mark.parametrize("changed", [False, True])
def test_full_reply_to_writer_routes_by_label_and_pins_owners(changed):
    from test_hawkes_insertion_ownership import PLAIN_FIELD_EDITOR, make_page

    page = make_page()
    points = [
        {
            "label": row["label"],
            "x": VALUES[index * 2],
            "y": VALUES[index * 2 + 1],
            "reading": "page-model",
        }
        for index, row in enumerate(ROWS)
    ][::-1]
    question = {
        "promptText": "Identify the coordinates of the labeled points on the graph.",
        "expressions": [],
        "labeledPoints": points,
    }
    editor = {
        "ok": True,
        "kind": "labeled-coordinates",
        "coordinateEditor": PLAIN_FIELD_EDITOR,
        "rows": ROWS,
    }
    reply = {
        "status": "ready",
        "problem_text": question["promptText"],
        "answer": {
            "form": "labeled-coordinates",
            "labeled_coordinates": points,
            "display_text": "; ".join(
                f"{point['label']}: ({point['x']},{point['y']})" for point in points
            ),
        },
        "certainty": {
            "source": "Facet Exact",
            "answered_by": "exact",
            "facet_invoked": True,
            "model_calls": 0,
            "insertable": True,
        },
    }
    page.run(
        f"state = {{...blankState(), phase:'solving', windowId:1, tabId:11, frameId:0, fieldId:'labeled-coordinates', editor:{json.dumps(editor)}, signature:questionSignature({json.dumps(question)})}}; acceptReply({json.dumps(reply)});"
    )
    page.pump()
    assert page.json("state.phase") == "solved"
    assert page.json("state.answerCoordinates") == points
    page.run("insert();")
    page.pump()
    page.answer(editor)
    live_rows = [dict(row) for row in ROWS]
    if changed:
        live_rows[0]["x"], live_rows[1]["x"] = live_rows[1]["x"], live_rows[0]["x"]
    page.answer({"ok": True, "rows": live_rows})
    page.answer(question)
    if changed:
        assert page.writes == []
        return
    ids = [row[axis] for row in ROWS for axis in ("x", "y")]
    page.answer(
        {
            "ok": True,
            "code": "entered-answer-fields",
            "fields": ids,
            "settled": 6,
            "models": 6,
        }
    )
    page.answer(question)
    assert len(page.writes) == 1
    assert page.writes[0]["args"][0] == VALUES
    assert page.writes[0]["args"][1] == ids
    assert page.writes[0]["args"][3:] == ["coordinates", ROWS]
    assert page.json("state.phase") == "inserted"
