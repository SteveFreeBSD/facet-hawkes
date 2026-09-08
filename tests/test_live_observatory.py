"""The observer, and the boundary that makes it safe to point at a live session.

`scripts/observe_live_hawkes.py` exists because correlating a live failure by
hand kept producing wrong answers: a screenshot, a diagnostic ring, two working
trees and three clocks, joined by eye. Two of those wrong answers were the same
mistake -- a temporary add-on running code the tree no longer held.

So two things are asserted here. That the correlation it draws is the one the
evidence supports, including when the evidence is thin and it has to say so.
And that pointing it at the owner's browser cannot change what that browser
does: no launch, no navigation, no input, and nothing that would wake or hold
open an event page Firefox had unloaded.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "observe_live_hawkes.py"
EXTENSION = PROJECT_ROOT / "extension"

SPEC = importlib.util.spec_from_file_location("observe_live_hawkes", SCRIPT)
assert SPEC and SPEC.loader
OBS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBS)


def entry(event, *, t=1000, run=None, gen="g1", level="info", **data):
    record = {"t": t, "seq": t, "level": level, "scope": "background", "event": event}
    if gen:
        record["gen"] = gen
    if run:
        record["run"] = run
    if data:
        record["data"] = data
    return record


def run_of(entries):
    groups = OBS.group_runs(entries)
    assert len(groups) == 1, [group["run"] for group in groups]
    return OBS.summarize_run(groups[0], OBS.clock(1_700_000_000.0))


# --- correlation -----------------------------------------------------------


def test_a_run_id_groups_an_operation_that_timestamps_would_interleave():
    """Two windows solving at once is the case adjacency has always got wrong."""
    entries = [
        entry("solve-started", t=1000, run="rA"),
        entry("solve-started", t=1010, run="rB"),
        entry("solved", t=2000, run="rB", answerLength=3),
        entry("failed", t=2100, run="rA", errorKey="errorSolveRefused"),
    ]

    groups = {group["run"]: group for group in OBS.group_runs(entries)}

    assert set(groups) == {"rA", "rB"}
    assert [e["event"] for e in groups["rA"]["entries"]] == ["solve-started", "failed"]
    assert [e["event"] for e in groups["rB"]["entries"]] == ["solve-started", "solved"]


def test_a_log_without_run_ids_is_grouped_by_adjacency_and_says_so():
    """An older build still has to be readable, but not to look authoritative."""
    entries = [
        entry("answer-target-inspected", gen=None, code="focused-answer-field"),
        entry("solve-started", t=1100, gen=None),
        entry("solved", t=1200, gen=None, answerLength=4),
        entry("answer-target-inspected", t=2000, gen=None, code="option-answer"),
        entry("solve-started", t=2100, gen=None),
    ]

    groups = OBS.group_runs(entries)

    assert [group["correlated"] for group in groups] == [False, False]
    # The prepare belongs with the solve it precedes; splitting them reported
    # every solve as a run with no question and no editor.
    assert len(groups[0]["entries"]) == 3
    assert groups[0]["run"].startswith("~adjacent")


def test_silence_ends_an_uncorrelated_run():
    """Nothing the add-on does takes five minutes.

    Without this, one adjacency group spanned six hours of the owner being
    elsewhere and reported itself as a single operation lasting `+21989128ms`.
    """
    entries = [
        entry("answer-target-inspected", t=1000, gen=None, code="option-answer"),
        entry("solve-started", t=1100, gen=None),
        entry("solve-started", t=1100 + OBS.RUN_GAP_MS + 1, gen=None),
    ]

    groups = OBS.group_runs(entries)

    assert len(groups) == 2
    assert len(groups[0]["entries"]) == 2


def test_a_run_that_outlives_its_event_page_is_visible_as_one_run():
    """The event page is non-persistent, so a solve can outlive the context
    that started it. Before generations were stamped, the survivor's entries
    and the newcomer's were one undifferentiated stream."""
    entries = [
        entry("solve-started", t=1000, run="rA", gen="g1"),
        entry("event-page-loaded", t=1500, run=None, gen="g2"),
        entry(
            "failed", t=2000, run="rA", gen="g2", level="warn", errorKey="errorNoBridge"
        ),
    ]
    reference = OBS.clock(1_700_000_000.0)

    groups = {group["run"]: group for group in OBS.group_runs(entries)}
    summary = OBS.summarize_run(groups["rA"], reference)

    # The run kept its identity across the turnover, and the turnover is what
    # the verdict names -- not the `errorNoBridge` it surfaced as.
    assert summary["generations"] == ["g1", "g2"]
    assert summary["failure"]["class"] == "lifecycle"


# --- what the extension thought -------------------------------------------


def test_the_first_failing_stage_comes_from_the_trail_not_from_a_guess():
    """`failed at solving` is true of a capture that never ran and of a model
    that answered nothing. The trail is what separates them."""
    summary = run_of(
        [
            entry("solve-started", t=1000, run="rA"),
            entry(
                "failed",
                t=9000,
                run="rA",
                level="warn",
                errorKey="errorEthnosTimeout",
                stage="solving",
                stages="capturing>reading>solving",
            ),
        ]
    )

    assert summary["stages"] == ["capturing", "reading", "solving"]
    assert summary["first_failing_stage"] == "solving"


def test_the_window_tab_and_frame_the_run_is_about_are_reported():
    """Everything downstream is scoped by the three of them: a solve reads that
    frame, an insertion writes to it, and a panel in another window is shown a
    blank. The only entry that used to name them was raised after an insertion
    had already gone wrong."""
    summary = run_of(
        [
            entry(
                "answer-target-inspected",
                t=1000,
                run="rA",
                code="focused-answer-field",
                windowId=337,
                tabId=91,
                frameId=4,
                frames=7,
            ),
            entry("solved", t=2000, run="rA", answerLength=5),
        ]
    )

    assert summary["target"] == {
        "window": 337,
        "tab": 91,
        "frame": 4,
        "frames_probed": 7,
    }


def test_the_question_and_editor_the_add_on_saw_are_both_reported():
    summary = run_of(
        [
            entry(
                "answer-target-inspected",
                t=1000,
                run="rA",
                code="focused-answer-field",
                via="focused-field",
                fields=0,
            ),
            entry(
                "evidence-refused",
                t=1100,
                run="rA",
                expressions=0,
                graph="none",
                table="none",
                promptChars=140,
            ),
            entry(
                "answer-parts-unplaceable",
                t=1200,
                run="rA",
                editorKind="multi",
                editorCount=2,
                editorEnabled=[True, True],
                allowed=["0123456789-", ""],
                templates=["fraction", ""],
            ),
            entry("solved", t=1300, run="rA", answerLength=9, insertable=True),
        ]
    )

    assert summary["question"]["read"] == "refused"
    assert summary["question"]["prompt_chars"] == 140
    assert summary["editor"]["code"] == "focused-answer-field"
    assert summary["editor"]["count"] == 2
    assert summary["editor"]["enabled"] == [True, True]


def test_structural_reader_evidence_survives_the_run_and_prints(monkeypatch):
    detail = {
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
            "controls": 1,
            "textOwners": [
                {
                    "tag": "label",
                    "classes": ["sr-only"],
                    "path": ["label.sr-only", "span.QFractionBox"],
                    "textNodes": 1,
                    "textChars": 14,
                    "ignored": False,
                    "containsControl": True,
                }
            ],
        },
    }
    monkeypatch.setattr(
        OBS,
        "working_tree_reader_marker",
        lambda: {"computed": True, "marker": "abcdef123456", "valid": True},
    )
    summary = run_of(
        [
            entry(
                "question-read",
                run="rA",
                expressions=1,
                answerTable="blank-not-empty",
                answerTableDetail=detail,
            ),
            entry("failed", t=1100, run="rA", errorKey="errorQuestionRegion"),
        ]
    )

    kept = summary["question"]["answer_table_detail"]
    assert kept["build_matches_tree"] is True
    assert kept["cell"]["textOwners"][0]["textChars"] == 14
    rendered = "\n".join(OBS._run_lines(summary))
    assert "blank-not-empty" in rendered
    assert "label.sr-only" in rendered
    assert "textChars=14" in rendered


def test_one_run_reports_each_five_part_boundary():
    summary = run_of(
        [
            entry(
                "host-request-shaped",
                run="rA",
                answerTable=True,
                tableRows=5,
                tableColumns=2,
                tableBlanks=5,
                answerShape="multi",
                answerParts=5,
            ),
            entry(
                "solved",
                t=1100,
                run="rA",
                answerLength=13,
                answerParts=5,
                hostAnswerParts=5,
            ),
            entry("answer-retained", t=1101, run="rA", answerParts=5, panels=1),
            entry(
                "panel-rendered",
                t=1102,
                run="rA",
                answerParts=5,
                answerLength=13,
                answerEmpty=False,
            ),
        ]
    )

    assert summary["host_request"]["answer_parts"] == 5
    assert summary["answer_parts"] == 5
    assert summary["host_answer_parts"] == 5
    assert summary["answer_retained"] == {"answer_parts": 5, "panels": 1}
    assert summary["panel_rendered"]["answer_parts"] == 5


def test_the_runtime_that_answered_is_carried_out_of_the_solve_entry():
    summary = run_of(
        [
            entry("solve-started", t=1000, run="rA"),
            entry(
                "solved",
                t=2000,
                run="rA",
                answerLength=6,
                source="Facet Reasoning · GPU",
                answeredBy="facet",
                facetInvoked=True,
                facetRuntime="ollama",
                facetModel="gpt-oss:20b",
                facetRequestedBackend="auto",
                facetBackend="gpu",
                facetDevice="AMD Radeon 890M Graphics (RADV STRIX1)",
            ),
        ]
    )

    assert summary["runtime"]["model"] == "gpt-oss:20b"
    assert summary["runtime"]["backend"] == "gpu"
    assert summary["runtime"]["device"].startswith("AMD Radeon 890M")
    assert summary["route"]["answered_by"] == "facet"


def test_a_graph_plan_from_an_older_build_still_reports_its_backend():
    """`graph-plan-validated` predates the prefixed names and must keep reading."""
    summary = run_of(
        [
            entry("solve-started", t=1000, run="rA"),
            entry(
                "graph-plan-validated",
                t=2000,
                run="rA",
                facetInvoked=True,
                facetModel="gpt-oss:20b",
                backend="gpu",
                device="AMD Radeon 890M Graphics (RADV STRIX1)",
            ),
        ]
    )

    assert summary["runtime"]["backend"] == "gpu"
    assert summary["runtime"]["model"] == "gpt-oss:20b"


# --- what changed between solve and insertion -----------------------------


def test_the_component_that_lost_the_insertion_is_named():
    summary = run_of(
        [
            entry("solved", t=1000, run="rA", answerLength=4),
            entry("insertion-pinned", t=1100, run="rA", tabId=7, signature="abcd1234"),
            entry(
                "insertion-target-changed",
                t=1200,
                run="rA",
                level="warn",
                why="question-read",
                changed="signature,answer",
                pinned={"tabId": 7, "signature": "abcd1234"},
            ),
        ]
    )

    assert summary["outcome"] == "abandoned"
    assert summary["ownership"]["changed"] == ["signature", "answer"]
    assert summary["ownership"]["pinned"]["tabId"] == 7
    assert summary["failure"]["class"] == "lifecycle"


def test_the_insertion_names_the_run_that_produced_the_answer():
    """Solving and inserting are two gestures and therefore two runs. "What
    changed between the solve and the insertion" needs them joined."""
    entries = [
        entry("solved", t=1000, run="rSolve", answerLength=4),
        entry("insertion-pinned", t=2000, run="rInsert", tabId=7, solvedIn="rSolve"),
        entry("inserted", t=2200, run="rInsert", via="typed"),
    ]
    reference = OBS.clock(1_700_000_000.0)
    groups = {group["run"]: group for group in OBS.group_runs(entries)}

    insertion = OBS.summarize_run(groups["rInsert"], reference)

    assert insertion["solved_in"] == "rSolve"
    assert insertion["outcome"] == "inserted"


def test_an_undisturbed_insertion_records_its_snapshot_and_no_change():
    summary = run_of(
        [
            entry("solved", t=1000, run="rA", answerLength=4),
            entry("insertion-pinned", t=1100, run="rA", tabId=7, fieldIds=2),
            entry("inserted", t=1300, run="rA", via="structured", elapsedMs=200),
        ]
    )

    assert summary["outcome"] == "inserted"
    assert summary["ownership"]["changed"] == []
    assert summary["failure"] is None


# --- which of the seven kinds of failure ----------------------------------


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([entry("failed", errorKey="errorWrongSite", level="warn")], "browser"),
        ([entry("failed", errorKey="errorNoFocusedField", level="warn")], "browser"),
        ([entry("failed", errorKey="errorQuestionRegion", level="warn")], "evidence"),
        (
            [entry("failed", errorKey="errorTranscriptionDisputed", level="warn")],
            "evidence",
        ),
        ([entry("failed", errorKey="errorSolveRefused", level="warn")], "capability"),
        (
            [entry("failed", errorKey="errorAnswerNeedsTemplate", level="warn")],
            "answer-shape",
        ),
        ([entry("failed", errorKey="errorEthnosUnreachable", level="warn")], "runtime"),
        ([entry("failed", errorKey="errorEthnosTimeout", level="warn")], "timing"),
        ([entry("failed", errorKey="errorQuestionChanged", level="warn")], "safety"),
        (
            [entry("failed", errorKey="errorInsertionAbandoned", level="warn")],
            "lifecycle",
        ),
    ],
)
def test_every_failure_lands_in_exactly_one_named_class(events, expected):
    assert run_of(events)["failure"]["class"] == expected


def test_a_solve_the_editor_will_not_take_is_a_shape_failure_not_a_success():
    """The panel showed an answer and Insert stayed disabled. Nothing pressed
    anything, nothing failed, and the ring recorded a clean solve and silence."""
    summary = run_of(
        [
            entry("solve-started", t=1000, run="rA"),
            entry("solved", t=2000, run="rA", answerLength=12, insertable=True),
            entry(
                "answer-not-insertable",
                t=2001,
                run="rA",
                level="warn",
                editor="editor-option-answer",
                plan="editor-option-answer",
            ),
        ]
    )

    assert summary["outcome"] == "solved"
    assert summary["failure"]["class"] == "answer-shape"
    assert summary["not_insertable"]["editor"] == "editor-option-answer"


def test_a_refused_reading_that_then_fails_is_evidence_not_capability():
    """The distinction that decides whether to look at the page or the solver."""
    summary = run_of(
        [
            entry("solve-started", t=1000, run="rA"),
            entry("evidence-refused", t=1100, run="rA", expressions=0, promptChars=0),
            entry(
                "failed", t=2000, run="rA", level="warn", errorKey="errorSolveRefused"
            ),
        ]
    )

    assert summary["failure"]["class"] == "evidence"


def test_a_clean_run_is_not_given_a_failure_class():
    assert (
        run_of([entry("solved", answerLength=4), entry("inserted", t=1100)])["failure"]
        is None
    )


# --- one clock -------------------------------------------------------------


def test_local_and_utc_come_from_one_reading():
    reference = OBS.clock(1_700_000_000.0)

    assert reference["epoch_ms"] == 1_700_000_000_000
    assert reference["utc"].startswith("2023-11-14T22:13:20")
    # Whatever the zone, the two describe the same instant.
    assert OBS._stamp(1_700_000_000_000, reference)["ago_seconds"] == 0.0
    assert OBS._stamp(1_699_999_990_000, reference)["ago_seconds"] == 10.0


# --- the boundary ----------------------------------------------------------

SOURCE = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _code_only(text: str) -> str:
    """The module with its comments and string literals removed.

    A capability check that reads prose finds every capability the prose
    explains it does not have. `scripts/build_extension.py` has the same trap
    in `FORBIDDEN_TOKENS` and answers it by wording around the tokens; a test
    can do better and look only at what runs.
    """
    import io
    import tokenize

    kept = []
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type in {tokenize.COMMENT, tokenize.STRING}:
            continue
        kept.append(token.string)
    return " ".join(kept)


CODE = _code_only(SOURCE)


def _subprocess_programs(tree: ast.AST) -> set[str]:
    """Every literal program name this module can hand to the operating system."""
    programs: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = (
            target.attr
            if isinstance(target, ast.Attribute)
            else getattr(target, "id", "")
        )
        if name not in {"run", "Popen", "check_output", "call", "check_call"}:
            continue
        for argument in node.args:
            if isinstance(argument, ast.List) and argument.elts:
                first = argument.elts[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    programs.add(first.value)
                else:
                    programs.add(f"<computed {ast.dump(first)[:40]}>")
    return programs


def test_the_observer_can_only_run_commands_that_read():
    """The whole value of this tool is in the "read-only" part.

    A subcommand able to press something would have to be reasoned about before
    every use, on a live coursework session, which is exactly the cost this was
    written to remove.
    """
    assert _subprocess_programs(TREE) <= OBS.ALLOWED_COMMANDS
    assert "firefox" not in OBS.ALLOWED_COMMANDS


def test_it_never_launches_or_drives_the_browser():
    """`inspect_live_firefox` may focus a window and give focus back. Nothing
    here may open one, navigate one, or send it input.

    Asserted as the exact surface used rather than as absent words: this module
    reaches Firefox only through the inspector, and only through the members
    below -- every one of which reads, except `shot`, which borrows focus for a
    capture and returns it.
    """
    for forbidden in (
        "geckodriver",
        "marionette",
        "WebDriver",
        "webdriver",
        "xdotool",
        "ydotool",
        "wtype",
        "new_tab",
        "new_window",
    ):
        assert forbidden not in CODE, forbidden

    used = {
        node.attr
        for node in ast.walk(TREE)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "inspector"
    }

    assert used == {
        "_kwin_windows",
        "_one_firefox_window",
        "_extension_status",
        "_matching_processes",
        "InspectionError",
        "FIREFOX_CLASS",
        "shot",
    }, used
    # `shot` is reached from one place only, and that place refuses unless
    # there is a bundle directory to put the capture in.
    assert SOURCE.count("inspector.shot") == 1
    assert "inspector.shot(bundle /" in SOURCE


def test_it_presses_nothing_on_the_page():
    """Submit, Check, Next, Skip and Try Similar each spend a graded attempt."""
    for forbidden in (
        "Submit",
        "Skip",
        "click",
        "keypress",
        "sendKeys",
        "dispatchEvent",
    ):
        assert forbidden not in CODE, forbidden


def test_it_reaches_no_network_except_the_local_runner():
    """A local Ollama probe is the one socket, and it is a loopback address."""
    urls = re.findall(r"https?://[^\s\"']+", SOURCE)
    reachable = {
        url for url in urls if "://" in url and not url.startswith("http://127.0.0.1")
    }

    # Only the loopback runner. Anything else in the file is prose.
    assert {url for url in reachable if url in CODE} == set()
    assert OBS.OLLAMA_ROOT.startswith("http://127.0.0.1")
    # And it is asked only when a run actually named a runtime.
    assert OBS.ollama_state(False)["asked"] is False


def test_it_reads_the_profile_database_through_a_copy():
    """Firefox is running and holding that file; a reader that opened it in
    place would be taking a lock on the session under observation."""
    reader = SCRIPT.parent / "read_extension_log.py"
    assert "shutil.copy(store, copy)" in reader.read_text(encoding="utf-8")
    # And the observer has no second way in. It reads the ring and the retained
    # failure ledger through that one reader, so there is exactly one place
    # where the rule "copy it first" has to hold.
    assert "reader.read_storage(store_path)" in SOURCE
    assert "sqlite3" not in _code_only(SOURCE)


def test_it_writes_nothing_into_the_profile_or_the_extension():
    """Read-only means the observation leaves the thing observed unchanged.

    The only files it creates are the bundle it made itself, and the only
    directory it names is that bundle. It deletes nothing at all -- a Hawkes
    screenshot is the owner's to remove, on the command this prints.
    """
    writes = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"write_text", "write_bytes", "mkdir", "chmod", "touch"}
    ]
    roots = {ast.unparse(node.func.value).split(" ")[0] for node in writes}

    # Every write is rooted at the bundle directory this run created, or at the
    # path the caller named for it. Nothing else is a write target.
    assert roots <= {"bundle", "path", "child"}, roots
    for verb in ("unlink", "rmtree", "os.remove", "os.rename", "shutil.move"):
        assert verb not in CODE, verb


def test_a_coursework_screenshot_is_never_left_loose():
    """It goes into a bundle whose deletion command is printed, or not at all."""

    class _Inspector:
        def shot(self, *_args):  # pragma: no cover - must not be reached
            raise AssertionError("a screenshot was taken without a bundle")

    refused = OBS._screenshot(_Inspector(), True, None, None, [])

    assert refused["taken"] is False
    assert "--bundle" in refused["why"]
    assert "delete   rm -rf" in SOURCE


def test_the_bundle_says_the_screenshot_is_coursework():
    assert "COURSEWORK" in SOURCE
    assert "0o700" in SOURCE and "0o600" in SOURCE


# --- observation does not change extension lifecycle ----------------------


def test_the_observer_never_speaks_to_the_extension():  # noqa: D401
    """The proof that observation cannot wake or hold open an event page.

    An event page Firefox has unloaded is woken by a message: a port, a
    `runtime.sendMessage`, a native-messaging connection, an alarm. This module
    sends none, so what it sees is what the session was doing anyway. It reads
    the ring off disk instead, which is why the ring is worth having.
    """
    for waking in (
        "connectNative",
        "sendMessage",
        "runtime.connect",
        "browser.runtime",
        "chrome.runtime",
        "nativeMessaging",
    ):
        assert waking not in CODE, waking
    # The native host is named once, as a process to look for in /proc. That
    # lookup reads `cmdline`; it starts nothing and connects to nothing.
    assert SOURCE.count("ethnos.hawkes_host") == 1
    assert "_matching_processes" in SOURCE


def test_the_observer_polls_nothing():
    """One pass, no waiting, no repeat.

    Repeated sampling is how a diagnostic starts holding open the context it is
    describing. Every probe here is called once per observation; the tool is
    run again when a newer picture is wanted, which is a decision the agent
    makes rather than a loop this file runs.
    """
    assert "sleep" not in CODE
    assert "--watch" not in SOURCE
    assert "--follow" not in SOURCE
    probes = (
        "_kwin_windows",
        "_extension_status",
        "read_entries",
        "_matching_processes",
    )
    for probe in probes:
        assert CODE.count(probe) == 1, probe


def test_the_documented_command_reexecs_through_the_project_runtime(monkeypatch):
    calls = []
    monkeypatch.setattr(OBS.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(OBS.sys, "executable", "/usr/bin/python3")
    monkeypatch.setattr(OBS.sys, "argv", [str(SCRIPT), "--run", "rA"])
    monkeypatch.setattr(
        OBS.os, "execv", lambda program, argv: calls.append((program, argv))
    )

    OBS.ensure_marker_runtime()

    project_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    assert calls == [
        (
            project_python,
            [project_python, str(SCRIPT), "--run", "rA"],
        )
    ]


def test_the_marker_touches_no_browser_api_that_could_hold_a_context_open():
    """The one thing added to the running add-on, exercised for real.

    `common/build-marker.js` reads the add-on's own source text and folds it. If
    it reached for storage, a port or a message it would be capable of
    extending the life of the event page it is describing, and a diagnostic
    that changes the lifecycle it reports is worse than none.
    """
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.add_callable(
        "__sha256",
        lambda text: json.dumps(list(hashlib.sha256(text.encode()).digest())),
    )
    context.eval(
        """
        globalThis.touched = [];
        const watcher = (name) => new Proxy(function () {}, {
          get: (_t, key) => { touched.push(`${name}.${String(key)}`); return watcher(name); },
          apply: () => { touched.push(`${name}()`); return watcher(name); },
        });
        globalThis.browser = watcher("browser");
        globalThis.TextEncoder = function () { this.encode = (text) => text; };
        globalThis.crypto = { subtle: { digest: (_alg, text) =>
          Promise.resolve(new Uint8Array(JSON.parse(__sha256(text)))) } };
        """
    )
    source = (EXTENSION / "common" / "build-marker.js").read_text(encoding="utf-8")
    context.eval(
        re.sub(r"^import\s[\s\S]*?;\s*$", "", source, flags=re.M).replace("export ", "")
    )
    context.eval(
        """
        var folded;
        foldSources(collectSources({ demo: function demo() { return 1; } }))
          .then((value) => { folded = value; });
        """
    )
    for _ in range(200):
        if not context.execute_pending_job():
            break

    assert json.loads(context.eval("JSON.stringify(touched)")) == []
    assert context.eval("folded.symbols") == 1


def test_the_marker_is_computed_off_the_operation_path():
    """Deferred, never awaited, and scheduled once.

    A solve must not wait on a diagnostic, and an event page must not be held
    open by one. It is a single bounded pass behind a zero-delay timer, after
    settings have settled.
    """
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")

    assert "await foldSources" not in background
    assert "await collectSources" not in background
    assert background.count("foldSources(") == 1
    deferred = background[background.rindex("settingsReady.then") :]
    assert "setTimeout(" in deferred[:120]
    assert "foldSources(collectSources(markedCode()))" in deferred[:400]
    # Failure of the diagnostic is a logged line, never a failed operation.
    assert "build-marker-unavailable" in background


def test_a_run_id_costs_the_ring_nothing_it_did_not_already_spend():
    """Correlation is two short strings per entry, not another storage write."""
    log = (EXTENSION / "common" / "log.js").read_text(encoding="utf-8")

    assert "export function setRun" in log
    # `setRun` and `newRunId` are assignments and arithmetic; neither may reach
    # storage, because a run id is minted on every panel gesture.
    body = log[log.index("export function setRun") : log.index("/** Queue one entry")]
    assert "storage" not in body and "await" not in body
    assert "RING_LIMIT = 200" in log
