"""The panel, executed.

Every other extension test reads the add-on's JavaScript as text. That is
enough for the invariants -- which permissions, which tokens, which paths --
and it is not enough for behaviour: 0.22.0 shipped a panel whose `render()`
read a `const` declared thirty-eight lines below it, so every render threw
`ReferenceError`, the panel froze at "Checking…", and 428 passing tests said
nothing at all.

`common/panel-view.js` exists so that cannot happen again. It decides
everything the panel shows and returns it as plain data, with no DOM and no
`browser`, so it runs here under QuickJS against every phase the event page can
report.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON = PROJECT_ROOT / "extension" / "common"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

# Dependency order; the modules are concatenated because QuickJS here has no
# module loader and these three are deliberately import-free apart from each
# other.
MODULES = ("editor-rules.js", "editor-plan.js", "panel-view.js")

IMPORT_LINE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE | re.DOTALL)


@pytest.fixture(scope="module")
def view():
    """`describeView(state, now)`, running as the panel runs it."""
    source = "\n".join(
        IMPORT_LINE.sub("", (COMMON / name).read_text()).replace("export ", "")
        for name in MODULES
    )
    context = quickjs.Context()
    context.eval(source)

    def call(state, now=0, docked=False):
        argument = "null" if state is None else json.dumps(state)
        surface = json.dumps({"docked": docked})
        return json.loads(
            context.eval(f"JSON.stringify(describeView({argument}, {now}, {surface}))")
        )

    return call


# The editor description Hawkes publishes for a question answered by typing.
DYNAMIC_Y = {
    "ok": True,
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789y",
    "maxLength": 16,
    "templates": {"fraction": False, "radical": False, "exponent": True},
}

# One answered by choosing an option, which the add-on never does for you.
OPTION = {
    "ok": True,
    "kind": "option",
    "enabled": True,
    "allowedCharacters": "",
    "maxLength": None,
    "templates": {"fraction": False, "radical": False, "exponent": False},
}


def state(**overrides):
    """A state shaped exactly as `background.js` builds it."""
    base = {
        "phase": "idle",
        "tabId": None,
        "frameId": None,
        "editor": None,
        "problemText": "",
        "answer": "",
        "displayText": "",
        "entryText": "",
        "placedText": "",
        "promptSeen": True,
        "stage": "",
        "stageDetail": "",
        "signature": "",
        "source": "",
        "detail": "",
        "errorKey": "",
        "errorArgs": [],
        "startedAt": 0,
    }
    base.update(overrides)
    return base


PHASES = [
    "idle",
    "checking",
    "ready",
    "solving",
    "solved",
    "inserting",
    "inserted",
    "failed",
]


@pytest.mark.parametrize("phase", PHASES)
def test_every_phase_renders_without_throwing(view, phase):
    """The regression that started this file.

    A phase the panel cannot describe is a frozen panel, so each one is asked
    for directly rather than inferred from the source.
    """
    described = view(state(phase=phase, tabId=7, frameId=0, editor=DYNAMIC_Y))

    assert described["status"]["key"].startswith(("status", "error"))
    assert 0 <= described["progress"]["fraction"] <= 1
    assert isinstance(described["solve"]["disabled"], bool)


def test_a_state_that_never_arrived_says_so_rather_than_rendering_blank(view):
    described = view(None)

    assert described["status"] == {"key": "errorNoBridge", "args": [], "kind": "error"}
    assert described["solve"]["disabled"] is True
    assert described["insert"]["enabled"] is False


def test_insert_becomes_the_primary_action_once_there_is_an_answer(view):
    described = view(
        state(phase="solved", answer="3y", displayText="3y", editor=DYNAMIC_Y)
    )

    assert described["insert"] == {"enabled": True, "primary": True}
    # Solve stays available -- a doubted answer is re-solved from here -- but
    # stops carrying the emphasis.
    assert described["solve"]["primary"] is False
    assert described["status"]["kind"] == "ready"


def test_an_option_question_reads_as_your_turn_rather_than_a_failure(view):
    described = view(
        state(phase="solved", answer="3y", displayText="3y", editor=OPTION)
    )

    assert described["insert"]["enabled"] is False
    assert described["status"]["key"] == "errorOptionAnswer"
    # A note, not an error: the answer is right and only the selecting is yours.
    assert described["status"]["kind"] == "note"
    # And it can still be copied, which is the whole point of showing it.
    assert described["copy"] == {"enabled": True, "text": "3y"}


def test_non_real_answer_in_numeric_box_reads_as_manual_choice(view):
    numeric = {
        "ok": True,
        "kind": "textbox",
        "enabled": True,
        "allowedCharacters": "[0-9.-]",
        "maxLength": 9,
        "templates": {"fraction": False, "radical": False, "exponent": False},
    }
    described = view(
        state(
            phase="solved",
            answer="Not a Real Number",
            displayText="Not a Real Number",
            editor=numeric,
        )
    )

    assert described["insert"]["enabled"] is False
    assert described["status"] == {
        "key": "errorOptionAnswer",
        "args": [],
        "kind": "note",
    }


def test_a_reported_error_wins_over_the_phase(view):
    described = view(
        state(
            phase="solved",
            answer="3y",
            editor=DYNAMIC_Y,
            errorKey="errorTranscriptionDisputed",
        )
    )

    assert described["status"]["key"] == "errorTranscriptionDisputed"
    assert described["status"]["kind"] == "error"
    assert described["insert"]["enabled"] is False
    assert described["progress"] == {"fraction": 1, "state": "error"}
    # The primary button offers the retry rather than repeating "Solve".
    assert described["solve"]["key"] == "popupRetryButton"


def test_a_withheld_site_permission_offers_the_scoped_grant(view):
    described = view(state(phase="failed", errorKey="errorTabAccessLost"))

    assert described["solve"]["key"] == "popupGrantAccessButton"
    assert described["insert"]["enabled"] is False


def test_a_running_solve_reports_its_stage_and_how_long_it_has_taken(view):
    described = view(
        state(phase="solving", stage="reading", startedAt=1_000_000, editor=DYNAMIC_Y),
        now=1_000_000 + 23_400,
    )

    assert described["solve"]["key"] == "popupCancelButton"
    assert described["status"]["key"] == "stageReading"
    assert described["status"]["elapsed"] == 23
    assert described["running"] is True
    assert described["resetDisabled"] is True
    assert 0 < described["progress"]["fraction"] < 1


def test_the_bar_advances_monotonically_through_the_stages(view):
    fractions = [
        view(state(phase="solving", stage=stage, startedAt=1, editor=DYNAMIC_Y))[
            "progress"
        ]["fraction"]
        for stage in ("checking-host", "capturing", "reading", "checking", "solving")
    ]

    assert fractions == sorted(fractions)
    assert fractions[0] > 0  # pressing Solve does something visible at once
    assert fractions[-1] < 1  # and the bar is never full while work remains


def test_a_finished_insertion_shows_what_it_placed_rather_than_an_em_dash(view):
    """0.38 emptied the card at the moment the add-on had succeeded.

    The reviewed answer is still gone from state -- `answer`, `displayText` and
    `entryText` are all cleared by `finishInsertion` -- so nothing here can be
    inserted a second time. `placedText` is a display-only copy, and this card
    is the largest thing in the panel: blanking it read as the answer having
    been lost rather than as the answer having been delivered.
    """
    described = view(state(phase="inserted", placedText="3y", source="symbolic"))

    assert described["answer"] == {"text": "3y", "empty": False, "placed": True}
    # Worth keeping copyable: this is the value to check against the screen.
    assert described["copy"] == {"enabled": True, "text": "3y"}
    assert described["insert"]["enabled"] is False
    assert described["progress"] == {"fraction": 1, "state": "done"}
    assert described["status"]["kind"] == "ready"
    # And it still says which stage produced it.
    assert described["badge"] == {"key": "popupSourceBadge", "args": ["symbolic"]}


def test_a_placed_answer_is_never_shown_outside_the_inserted_phase(view):
    """The phase gates the display copy as well as the event page clearing it.

    Belt and braces: no ordering of state updates may put a placed answer
    beside live work, in the way a stale answer once sat beside a running
    retry.
    """
    for phase in ("ready", "solving", "solved", "checking", "failed"):
        described = view(state(phase=phase, placedText="3y", editor=DYNAMIC_Y))

        assert described["answer"]["text"] == ""
        assert described["answer"]["placed"] is False


def test_nothing_is_bound_to_enter_once_the_answer_is_in_the_field(view):
    """The retry this release was opened to fix.

    Enter used to take its action from whichever button was not disabled, and
    Solve stays enabled after an insertion so a doubted answer can be
    re-solved. So the key -- and the footer hint naming it -- offered to solve
    the question that had just been answered.
    """
    described = view(state(phase="inserted", placedText="3y"))

    assert described["primary"] == "none"
    assert described["hint"] is None
    # Available, but no longer presenting itself as the next step.
    assert described["solve"]["disabled"] is False
    assert described["solve"]["primary"] is False
    assert described["solve"]["key"] == "popupSolveAgainButton"


def test_the_footer_hint_never_names_an_action_the_panel_would_refuse(view):
    """One rule: the hint is whatever Enter is actually bound to."""
    cases = [
        (state(phase="ready", editor=DYNAMIC_Y), "solve", "popupHintSolve"),
        (
            state(phase="solving", stage="reading", startedAt=1),
            "cancel",
            "popupHintCancel",
        ),
        (
            state(phase="solved", answer="3y", displayText="3y", editor=DYNAMIC_Y),
            "insert",
            "popupHintInsert",
        ),
        (state(phase="inserting"), "none", None),
        (state(phase="inserted", placedText="3y"), "none", None),
    ]
    for reported, primary, hint in cases:
        described = view(reported)

        assert described["primary"] == primary
        assert described["hint"] == hint

    assert view(None)["primary"] == "none"
    assert view(None)["hint"] is None


def test_only_the_docked_sidebar_claims_to_be_watching_for_the_next_question(view):
    """Same state, two surfaces, two different truths about what happens next.

    The event page's watcher runs only while a panel port is connected. The
    sidebar keeps one open; the toolbar popup is torn down the moment focus
    moves, which is exactly when the user goes to press Submit.
    """
    reported = state(phase="inserted", placedText="3y")

    assert view(reported, docked=True)["status"]["key"] == "statusInsertedWatching"
    assert view(reported)["status"]["key"] == "statusInserted"


def test_the_shown_answer_is_the_readable_form_not_the_typeable_one(view):
    """Regression from 0.19: the panel showed the keyboard form.

    `√(30yz)/(5z)` is what the answer is; `sqrt(30)*sqrt(y)...` is only how it
    would have to be typed. Gating the display on typeability showed the wrong
    one of the two.
    """
    described = view(
        state(
            phase="solved",
            answer="sqrt(30yz)/(5z)",
            displayText="√(30yz)/(5z)",
            editor=DYNAMIC_Y,
        )
    )

    assert described["answer"]["text"] == "√(30yz)/(5z)"
    assert described["copy"]["text"] == "√(30yz)/(5z)"


def test_the_recognized_problem_is_dimmed_rather_than_removed_when_absent(view):
    """The panel keeps one shape, so nothing may appear or vanish."""
    empty = view(state(phase="ready"))
    filled = view(
        state(phase="solved", problemText="Simplify √(9y²)", editor=DYNAMIC_Y)
    )

    assert empty["problem"] == {"text": "", "idle": True}
    assert filled["problem"]["idle"] is False


def test_the_source_badge_is_absent_rather_than_empty_until_something_answered(view):
    assert view(state(phase="ready"))["badge"] is None
    assert view(state(phase="solved", source="symbolic", editor=DYNAMIC_Y))[
        "badge"
    ] == {
        "key": "popupSourceBadge",
        "args": ["symbolic"],
    }


def test_an_answer_reached_without_the_question_says_so(view):
    """An empty prompt forces the least reliable path this add-on has.

    No exact operation can be selected without a verb, so the question reaches
    a model as a picture with nothing stating what to do about it. That answer
    is still offered -- it is often right, and nothing is inserted unreviewed
    -- but it must not read identically to one derived exactly.
    """
    unread = view(
        state(
            phase="solved",
            answer="13",
            displayText="13",
            editor=DYNAMIC_Y,
            promptSeen=False,
        )
    )
    read = view(state(phase="solved", answer="13", displayText="13", editor=DYNAMIC_Y))

    assert unread["status"] == {"key": "statusSolvedUnread", "args": [], "kind": "note"}
    assert read["status"]["key"] == "statusSolved"
    assert read["status"]["kind"] == "ready"
    # Cautioned, not withheld: the answer is still offered for review.
    assert unread["insert"] == {"enabled": True, "primary": True}
    assert unread["primary"] == "insert"


def test_the_caution_needs_an_explicit_denial_not_a_missing_field(view):
    """A host too old to report it must not make every answer look doubtful."""
    described = view(
        state(
            phase="solved",
            answer="13",
            displayText="13",
            editor=DYNAMIC_Y,
            promptSeen=None,
        )
    )

    assert described["status"]["key"] == "statusSolved"
