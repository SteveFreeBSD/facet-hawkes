"""Behavioural tests for the add-on's frame-selection logic.

`extension/common/frames.js` decides which frame an answer may be inserted
into, and getting it wrong means typing into the wrong document or refusing to
type at all. Firefox cannot be driven from this environment, so the real
shipped source is executed under QuickJS and fed the `InjectionResult` arrays
Firefox would hand it, covering the top-frame, same-origin, cross-origin,
ambiguous, and no-focus outcomes.

The module is loaded by stripping its `export` keywords, which is the only
transform applied; the logic under test is the file that ships.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRAMES_JS = PROJECT_ROOT / "extension" / "common" / "frames.js"

quickjs = pytest.importorskip(
    "quickjs", reason="pip install quickjs to exercise the extension's JS logic"
)


@pytest.fixture(scope="module")
def select_answer_frame():
    """Return a callable that runs the shipped selectAnswerFrame under QuickJS."""
    source = re.sub(r"^export ", "", FRAMES_JS.read_text(), flags=re.MULTILINE)
    context = quickjs.Context()
    context.eval(source)

    def call(results):
        payload = json.dumps(results)
        return json.loads(context.eval(f"JSON.stringify(selectAnswerFrame({payload}))"))

    return call


def report(
    frame_id, *, ready=False, code=None, origin=None, field_id="", field_ids=None
):
    """Build one InjectionResult entry as Firefox would return it."""
    result = {"ready": ready, "fieldId": field_id}
    if code is not None:
        result["code"] = code
    if origin is not None:
        result["frameOrigin"] = origin
    if field_ids is not None:
        result["fieldIds"] = field_ids
    return {"frameId": frame_id, "result": result}


def test_top_frame_editor_is_selected(select_answer_frame):
    results = [report(0, ready=True, code="focused-answer-field")]

    assert select_answer_frame(results) == {"frameId": 0, "fieldId": ""}


def test_same_origin_iframe_editor_is_selected(select_answer_frame):
    # The regression that motivated frame handling: the editor is in a child
    # frame, so the top frame must not answer for it.
    results = [
        report(0, code="focus-in-subframe"),
        report(101, ready=True, code="focused-answer-field"),
    ]

    assert select_answer_frame(results) == {"frameId": 101, "fieldId": ""}


def test_cross_origin_frame_reports_the_host_to_grant(select_answer_frame):
    # The child never reported, so it was never injected: activeTab does not
    # reach it. The origin names exactly which host a permission would cover.
    results = [
        report(0, code="focus-in-subframe", origin="https://editor.hawkeslearning.com")
    ]

    assert select_answer_frame(results) == {
        "code": "focus-in-subframe",
        "origin": "https://editor.hawkeslearning.com",
    }


def test_cross_origin_frame_without_a_readable_origin(select_answer_frame):
    # A sandboxed or srcdoc frame has no usable src; the case is still
    # distinguishable from nothing being focused.
    results = [report(0, code="focus-in-subframe")]

    assert select_answer_frame(results) == {"code": "focus-in-subframe"}


def test_nothing_focused_anywhere(select_answer_frame):
    results = [
        report(0, code="no-focused-answer-field"),
        report(101, code="no-focused-answer-field"),
    ]

    assert select_answer_frame(results) == {"code": "no-focused-answer-field"}


def test_two_claiming_frames_fail_closed(select_answer_frame):
    # A sibling frame can hold a stale activeElement. Inserting into a guessed
    # frame would type the answer into the wrong document, so refuse instead.
    results = [
        report(0, ready=True, code="focused-answer-field"),
        report(101, ready=True, code="focused-answer-field"),
    ]

    assert select_answer_frame(results) == {"code": "ambiguous-frame"}


def test_read_only_field_is_reported_over_a_missing_one(select_answer_frame):
    results = [
        report(0, code="no-focused-answer-field"),
        report(101, code="field-not-editable"),
    ]

    assert select_answer_frame(results) == {"code": "field-not-editable"}


def test_subframe_wrong_site_does_not_outrank_the_top_frame(select_answer_frame):
    results = [
        report(0, code="focus-in-subframe", origin="https://editor.example"),
        report(101, code="wrong-site"),
    ]

    assert select_answer_frame(results) == {
        "code": "focus-in-subframe",
        "origin": "https://editor.example",
    }


def test_an_open_hawkes_dialog_outranks_every_other_report(select_answer_frame):
    # A modal holds focus, so every other frame reporting "nothing focused" is
    # a consequence of it. Reporting the symptom sent us chasing ghosts for
    # hours on the live lesson.
    results = [
        report(0, code="editor-dialog-open"),
        report(101, code="no-focused-answer-field"),
    ]

    assert select_answer_frame(results) == {"code": "editor-dialog-open"}


def test_top_frame_wrong_site_is_still_decisive(select_answer_frame):
    results = [
        report(0, code="wrong-site"),
        report(101, code="no-focused-answer-field"),
    ]

    assert select_answer_frame(results) == {"code": "wrong-site"}


@pytest.mark.parametrize(
    "results",
    [
        pytest.param([], id="empty"),
        pytest.param([{"frameId": 0}], id="no-result-field"),
        pytest.param([{"frameId": 0, "result": None}], id="null-result"),
        pytest.param([{"frameId": 0, "error": "boom"}], id="frame-threw"),
    ],
)
def test_unusable_results_are_refused(select_answer_frame, results):
    assert select_answer_frame(results) == {"code": "no-results"}


def test_the_selection_names_the_field_it_found(select_answer_frame):
    # The id is how a question change is noticed: Hawkes swaps the controls in
    # place, so nothing navigates.
    results = [report(0, ready=True, code="focused-answer-field", field_id="Tb1_num")]

    assert select_answer_frame(results) == {"frameId": 0, "fieldId": "Tb1_num"}


def test_the_selection_preserves_both_pinned_field_ids(select_answer_frame):
    results = [
        report(
            0,
            ready=True,
            code="paired-answer-fields",
            field_id="QBase1_input\u001fQBase2_input",
            field_ids=["QBase1_input", "QBase2_input"],
        )
    ]

    assert select_answer_frame(results) == {
        "frameId": 0,
        "fieldId": "QBase1_input\u001fQBase2_input",
        "fieldIds": ["QBase1_input", "QBase2_input"],
    }


def test_a_claim_without_a_frame_id_is_not_trusted(select_answer_frame):
    # frameId is what the insertion targets; a claim that cannot be targeted
    # must not be treated as success.
    results = [{"result": {"ready": True, "code": "focused-answer-field"}}]

    assert select_answer_frame(results) == {"code": "no-focused-answer-field"}
