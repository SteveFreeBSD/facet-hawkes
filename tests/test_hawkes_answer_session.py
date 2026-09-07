"""A finished answer survives an idle Firefox event-page unload safely.

The session value contains coursework, so its contract is intentionally much
narrower than ordinary panel state: one completed answer, held in memory-only
``storage.session`` and never trusted until ``prepare()`` has read the live
question again.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"
MODULE = EXTENSION / "common" / "answer-session.js"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
EXPORT = re.compile(r"\bexport\s+(?:const|function)\s+")


@pytest.fixture
def context():
    ctx = quickjs.Context()
    ctx.eval(
        EXPORT.sub(
            lambda match: match.group(0).replace("export ", ""), MODULE.read_text()
        )
    )
    return ctx


def evaluate(context, expression):
    return json.loads(context.eval(f"JSON.stringify({expression})"))


def solved_state(**changes):
    state = {
        "phase": "solved",
        "windowId": 7,
        "tabId": 11,
        "frameId": 0,
        "fieldId": "QBase1_input",
        "fieldIds": [],
        "answer": "x = 4",
        "displayText": "x = 4",
        "entryText": "4",
        "answerParts": [],
        "editor": {"kind": "dynamic", "ok": True},
        "placedText": "",
        "promptSeen": True,
        "problemText": "Solve the equation.",
        "signature": "QBase1_input|abc|42",
        "source": "Facet Exact",
        "detail": "Answered by: Facet Exact",
        "errorKey": "",
        "errorArgs": [],
        "graphPlan": None,
    }
    state.update(changes)
    return state


def test_only_a_completed_identified_answer_is_cacheable(context):
    good = solved_state(debugOnly="must not survive")
    snapshot = evaluate(context, f"snapshotSolvedAnswer({json.dumps(good)}, 1234)")

    assert snapshot["schema"] == 1
    assert snapshot["savedAt"] == 1234
    assert snapshot["state"]["answer"] == "x = 4"
    assert "debugOnly" not in snapshot["state"]
    assert snapshot["state"]["editor"] == {"kind": "dynamic", "ok": True}

    for changes in (
        {"phase": "solving"},
        {"signature": None},
        {"answer": "", "displayText": "", "answerParts": []},
    ):
        candidate = solved_state(**changes)
        assert (
            evaluate(context, f"snapshotSolvedAnswer({json.dumps(candidate)})") is None
        )


def test_restore_revalidates_the_schema_and_state_shape(context):
    snapshot = evaluate(
        context,
        f"snapshotSolvedAnswer({json.dumps(solved_state())}, 1234)",
    )
    restored = evaluate(context, f"restoreSolvedAnswer({json.dumps(snapshot)})")

    assert restored["phase"] == "solved"
    assert restored["signature"] == "QBase1_input|abc|42"
    assert restored["answer"] == "x = 4"
    assert evaluate(context, "restoreSolvedAnswer({schema: 99, state: {}})") is None
    assert (
        evaluate(context, "restoreSolvedAnswer({schema: 1, state: {phase: 'solved'}})")
        is None
    )


def test_a_graph_answer_keeps_the_live_snapshot_that_insertion_will_recheck(context):
    graph = solved_state(
        editor={"kind": "graph", "snapshot": {"question": "digest"}},
        graphPlan={"action": "plot-parabola"},
        graphCoefficients=[1, 0, -4],
    )
    restored = evaluate(
        context,
        f"restoreSolvedAnswer(snapshotSolvedAnswer({json.dumps(graph)}, 1234))",
    )

    assert restored["graphPlan"] == {"action": "plot-parabola"}
    assert restored["graphCoefficients"] == [1, 0, -4]
    assert restored["editor"]["snapshot"] == {"question": "digest"}


def test_session_storage_is_the_only_answer_cache_and_prepare_rechecks_it():
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    prepare = background.split("async function prepare", 1)[1].split(
        "\nfunction frameErrorKey", 1
    )[0]

    assert "browser.storage.session.get(ANSWER_SESSION_KEY)" in background
    assert (
        "browser.storage.session.set({ [ANSWER_SESSION_KEY]: snapshot })" in background
    )
    assert "browser.storage.local.set({ [ANSWER_SESSION_KEY]" not in background
    assert "await seedRememberedAnswer(windowId)" in prepare
    assert "sameQuestionSignature(signature, previous.signature)" in prepare
    assert "tab.id === previous.tabId" in prepare
    assert "choice.frameId === previous.frameId" in prepare
