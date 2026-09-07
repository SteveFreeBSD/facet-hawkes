"""A retry never presents an earlier result as current."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"
IMPORT_LINE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE | re.DOTALL)


def test_running_view_suppresses_every_previous_answer_form():
    quickjs = pytest.importorskip("quickjs")
    source = "\n".join(
        IMPORT_LINE.sub("", (EXTENSION / "common" / name).read_text()).replace(
            "export ", ""
        )
        for name in ("config.js", "editor-rules.js", "editor-plan.js", "panel-view.js")
    )
    context = quickjs.Context()
    context.eval(source)
    stale = {
        "phase": "solving",
        "answer": "14",
        "displayText": "14",
        # The answer a previous insertion left on the card is one more form a
        # retry must not keep showing.
        "placedText": "14",
        "problemText": "an earlier question",
        "stage": "reading",
        "startedAt": 1,
    }

    view = json.loads(
        context.eval(f"JSON.stringify(describeView({json.dumps(stale)}, 2))")
    )

    assert view["answer"] == {"text": "", "empty": True, "placed": False}
    assert view["copy"]["enabled"] is False
    assert view["insert"]["enabled"] is False


def test_background_and_optimistic_panel_clear_retry_state():
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    popup = (EXTENSION / "popup" / "popup.js").read_text(encoding="utf-8")
    cleared = (
        'answer: ""',
        'displayText: ""',
        'entryText: ""',
        'problemText: ""',
        'source: ""',
    )

    solve_update = background[background.index('phase: "solving"') :]
    optimistic = popup[popup.index('render({ ...current, phase: "solving"') :]
    for field in cleared:
        assert field in solve_update[:700]
        assert field in optimistic[:500]
