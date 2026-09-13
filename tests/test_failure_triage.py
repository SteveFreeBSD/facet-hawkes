"""Reading back the failures nobody was watching.

`scripts/triage_hawkes_failures.py` is the half of this that runs later: the
owner used Hawkes normally, some runs ended badly, and an agent arrives
afterwards with no session to look at. So two things are asserted here.

That the report it prints is the one the evidence supports -- grouped by fault
rather than by question, classified by the observatory's own rules so a bundle
and an observation can never disagree, and honest about what it no longer has.

And that it is genuinely offline and genuinely safe: no command, no network, no
window manager, no screenshot, no connection to the add-on -- and no path by
which a student's coursework can reach a file meant to be handed to someone
else, even out of a profile somebody has edited by hand.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import stat
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts" / "triage_hawkes_failures.py"
EXTENSION = PROJECT_ROOT / "extension"

SPEC = importlib.util.spec_from_file_location("triage_hawkes_failures", SCRIPT)
assert SPEC and SPEC.loader
TRIAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TRIAGE)

SOURCE = SCRIPT.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


# --- fixtures: a ledger shaped exactly as the add-on writes one ------------


def record(**overrides):
    base = {
        "run": "r1",
        "generation": "g1",
        "at": 1_757_000_000_000,
        "outcome": "not-insertable",
        "errorKey": "",
        "refusal": "",
        "phase": "solved",
        "stage": "done",
        "stages": ["reading", "solving", "done"],
        "stoppedIn": "done",
        "fingerprint": "f1:aaaaaaaaaaaaaaaa",
        "target": {"window": 3, "tab": 9, "frame": 0, "fields": 1},
        "editor": {
            "kind": "dynamic",
            "ok": True,
            "code": "described",
            "name": "box",
            "enabled": True,
            "maxLength": 40,
            "allowed": "0-9+-/()",
            "templates": "fraction",
            "slots": {"base": "0-9"},
            "count": 1,
            "controls": [],
        },
        "evidence": {
            "read": "markup",
            "expressions": 2,
            "graph": "",
            "table": "",
            "promptChars": 88,
            "signature": "fld|abcdef|120",
        },
        "route": {
            "source": "facet",
            "answeredBy": "facet",
            "facetInvoked": True,
            "router": "exact",
            "method": "solve",
            "reading": "",
            "insertable": False,
        },
        "runtime": {
            "runtime": "",
            "model": "",
            "requestedBackend": "",
            "backend": "",
            "device": "",
            "fallback": False,
        },
        "answerShape": {"length": 9, "parts": 0, "directFit": [], "plannedFit": []},
        "host": {"requests": 1, "ids": ["r1.1"]},
        "solve": None,
        "build": {"marker": "3d9a1f77aa21", "version": "0.46.0"},
        "traits": {
            "outcome": "not-insertable",
            "errorKey": "",
            "events": ["answer-not-insertable"],
            "evidenceRefused": False,
            "notInsertable": {
                "editor": "answer-needs-template",
                "plan": "template-refused-by-question",
            },
        },
    }
    base.update(overrides)
    return base


def group(records, **overrides):
    first = records[0]
    base = {
        "fingerprint": first["fingerprint"],
        "count": len(records),
        "firstSeen": records[0]["at"],
        "lastSeen": records[-1]["at"],
        "firstRun": records[0]["run"],
        "runs": [item["run"] for item in records][-5:],
        "markers": sorted({item["build"]["marker"] for item in records}),
        "generations": sorted({item["generation"] for item in records}),
        "errorKey": first["errorKey"],
        "outcome": first["outcome"],
        "stoppedIn": first["stoppedIn"],
        "editorKind": (first["editor"] or {}).get("kind", "none"),
        "traits": first["traits"],
    }
    base.update(overrides)
    return base


RUNTIME_TRAITS = {
    "outcome": "failed",
    "errorKey": "errorEthnosUnreachable",
    "events": [],
    "evidenceRefused": False,
    "notInsertable": None,
}


@pytest.fixture()
def ledger_file(tmp_path):
    shape = [
        record(
            run=f"rA{i}",
            at=1_757_000_000_000 + i * 60_000,
            generation="g1" if i < 2 else "g4",
            build={
                "marker": "3d9a1f77aa21" if i < 2 else "9c11aa22bb33",
                "version": "0.46.0",
            },
        )
        for i in range(4)
    ]
    runtime = [
        record(
            run=f"rB{i}",
            at=1_757_000_500_000 + i * 60_000,
            generation="g2",
            outcome="failed",
            errorKey="errorEthnosUnreachable",
            fingerprint="f1:bbbbbbbbbbbbbbbb",
            stage="connect",
            stoppedIn="connect",
            stages=["reading", "solving"],
            editor=None,
            traits=RUNTIME_TRAITS,
        )
        for i in range(2)
    ]
    ledger = {
        "version": 1,
        "records": shape + runtime,
        "groups": [group(shape), group(runtime)],
        "dropped": {"age": 1, "count": 2, "bytes": 0},
    }
    ring = [
        {
            "t": 1_757_000_000_100,
            "seq": 2,
            "level": "warn",
            "scope": "background",
            "gen": "g1",
            "run": "rA3",
            "event": "answer-not-insertable",
            "data": {
                "editor": "answer-needs-template",
                "answer": "x = 3/4",
                "problemText": "Find the vertex",
            },
        },
        {
            "t": 1_757_000_000_200,
            "seq": 3,
            "level": "info",
            "scope": "background",
            "gen": "g9",
            "run": "rA3",
            "event": "editor-described",
            "data": {"kind": "dynamic"},
        },
    ]
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"ledger": ledger, "ring": ring}), encoding="utf-8")
    return path


@pytest.fixture()
def view(ledger_file):
    return TRIAGE.triage(TRIAGE.read_ledger(path=str(ledger_file)))


# --- the report ------------------------------------------------------------


def test_repeated_failures_are_one_group_with_a_count(view):
    """The workflow this exists for: an agent sees grouped real failures and
    picks the one worth their afternoon, rather than four questions."""
    assert [g["count"] for g in view["groups"]] == [4, 2]
    assert view["occurrences"] == 6
    assert view["records"] == 6


def test_the_worst_group_is_reported_first(view):
    assert view["groups"][0]["count"] >= view["groups"][-1]["count"]
    printed = TRIAGE.report(view)
    assert printed.index("ANSWER-SHAPE") < printed.index("RUNTIME")


def test_the_class_is_the_observatorys_own_verdict_not_a_second_opinion(view):
    """The eight failure classes are declared once. A bundle that named a
    different one from an observation of the same run would be worse than
    either on its own."""
    observatory = TRIAGE._load("observe_live_hawkes")
    classes = {g["fingerprint"]: g["classification"] for g in view["groups"]}

    assert classes["f1:aaaaaaaaaaaaaaaa"] == "answer-shape"
    assert classes["f1:bbbbbbbbbbbbbbbb"] == "runtime"
    assert {name for name, _, _ in observatory.FAILURE_RULES} >= set(classes.values())
    # And the adapter lives with the rules, not here. Asserted against the
    # parsed signature rather than the source text, so wrapping the line does
    # not read as the adapter having moved.
    assert "FAILURE_RULES" not in SOURCE
    signature = next(
        node
        for node in ast.parse(SOURCE).body
        if isinstance(node, ast.FunctionDef) and node.name == "classify"
    )
    assert signature.args.args[0].arg == "observatory"


def test_the_report_carries_the_editor_evidence_a_diagnosis_needs(view):
    printed = TRIAGE.report(view)

    assert "templates=fraction" in printed
    assert "'0-9+-/()'" in printed
    assert "enabled=True" in printed
    assert "answer-needs-template" in printed
    assert "reading > solving > done" in printed


def test_the_report_says_what_it_no_longer_has(view):
    printed = TRIAGE.report(view)

    assert "1 by age · 2 by count" in printed
    assert "40 records, 64 groups, 14.0 days, 96 KB" in printed


def test_an_empty_ledger_is_a_finding_not_an_error(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text(
        json.dumps({"version": 1, "records": [], "groups": []}), encoding="utf-8"
    )

    printed = TRIAGE.report(TRIAGE.triage(TRIAGE.read_ledger(path=str(path))))

    assert "empty" in printed
    assert "Nothing to triage" in printed


def test_a_ledger_written_by_another_build_says_so(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(
        json.dumps(
            {
                "version": 99,
                "records": [record()],
                "groups": [group([record()])],
                "dropped": {},
            }
        ),
        encoding="utf-8",
    )

    printed = TRIAGE.report(TRIAGE.triage(TRIAGE.read_ledger(path=str(path))))

    assert "another build wrote this ledger" in printed


def test_a_fingerprint_from_another_era_of_the_rules_is_flagged(tmp_path):
    """Change what a fingerprint folds and the same fault gets a new name. A
    ledger holding both would report one problem as two without saying so."""
    stale = record(fingerprint="f0:1234567812345678")
    path = tmp_path / "era.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "records": [stale],
                "groups": [group([stale])],
                "dropped": {},
            }
        ),
        encoding="utf-8",
    )

    printed = TRIAGE.report(TRIAGE.triage(TRIAGE.read_ledger(path=str(path))))

    assert "fingerprinted by rules other than f1" in printed


# --- correlation -----------------------------------------------------------


def test_a_group_names_every_build_and_lifetime_it_has_happened_in(view):
    shape = view["groups"][0]

    assert shape["markers"] == ["3d9a1f77aa21", "9c11aa22bb33"]
    assert shape["generations"][:2] == ["g1", "g4"]
    assert "2 event pages" in TRIAGE.report(view) or "3 event pages" in TRIAGE.report(
        view
    )


def test_a_run_that_outlived_its_event_page_is_named_from_the_ring(view):
    """A record is written by one lifetime, so it cannot know its run turned
    over -- the page that would have noticed is the one that went away. The
    ring can still say, for as long as it holds the entries."""
    shape = view["groups"][0]

    assert shape["runs_spanning_generations"] == ["rA3"]
    assert "outlived its own event page" in TRIAGE.report(view)


def test_one_runs_lifetimes_are_not_read_as_the_whole_groups(view):
    """Six occurrences recorded across two event pages is not one run that
    spanned two, and classifying it as `lifecycle` would send the next agent
    after a fault that is not there."""
    assert view["groups"][0]["classification"] == "answer-shape"


def test_the_ring_is_joined_back_to_the_group_by_run_id(view):
    assert view["groups"][0]["ring_entries"]["rA3"] == 2
    assert "ring: rA3=2" in TRIAGE.report(view)


def test_a_group_says_how_much_of_itself_is_still_retained(ledger_file):
    raw = json.loads(ledger_file.read_text())
    raw["ledger"]["groups"][0]["count"] = 30
    ledger_file.write_text(json.dumps(raw), encoding="utf-8")

    view = TRIAGE.triage(TRIAGE.read_ledger(path=str(ledger_file)))

    assert view["groups"][0]["records_retained"] == 4
    assert view["groups"][0]["records_evicted"] == 26
    assert "4 retained, 26 evicted" in TRIAGE.report(view)


def test_one_run_can_be_asked_about_by_name(view):
    printed = TRIAGE.report(view, detail="rB1")

    assert "RUNTIME" in printed
    assert "ANSWER-SHAPE" not in printed


# --- the export ------------------------------------------------------------


def test_a_bundle_carries_the_group_its_records_and_its_ring(
    view, ledger_file, tmp_path
):
    read = TRIAGE.read_ledger(path=str(ledger_file))
    written = TRIAGE.export(view, read, "f1:aaaaaaaaaaaaaaaa", tmp_path / "bundle")
    bundle = json.loads((written["path"] / "failure-bundle.json").read_text())

    assert bundle["group"]["count"] == 4
    assert len(bundle["records"]) == 4
    assert len(bundle["ring"]) == 2
    assert (written["path"] / "summary.txt").is_file()


def test_naming_a_run_exports_that_run_alone(view, ledger_file, tmp_path):
    read = TRIAGE.read_ledger(path=str(ledger_file))
    written = TRIAGE.export(view, read, "rA3", tmp_path / "one")
    bundle = json.loads((written["path"] / "failure-bundle.json").read_text())

    assert [item["run"] for item in bundle["records"]] == ["rA3"]
    assert {entry["run"] for entry in bundle["ring"]} == {"rA3"}


def test_no_coursework_reaches_a_bundle_even_out_of_an_edited_profile(
    view, ledger_file, tmp_path
):
    """`storage.local` is a file on the owner's disk. The browser builds records
    by name, so nothing should need filtering here -- and a bundle is the one
    artefact of this system meant to be handed to somebody else, so it is
    filtered anyway, through the add-on's own allowlist."""
    raw = json.loads(ledger_file.read_text())
    raw["ledger"]["records"][0]["answer"] = "x = 3/4"
    raw["ledger"]["records"][0]["problemText"] = "Find the vertex of the parabola"
    raw["ledger"]["records"][0]["screenshot"] = "data:image/png;base64,AAAA"
    raw["ledger"]["records"][0]["credential"] = "hunter2"
    ledger_file.write_text(json.dumps(raw), encoding="utf-8")

    read = TRIAGE.read_ledger(path=str(ledger_file))
    written = TRIAGE.export(
        TRIAGE.triage(read), read, "f1:aaaaaaaaaaaaaaaa", tmp_path / "bundle"
    )
    flat = (written["path"] / "failure-bundle.json").read_text()

    for leaked in ("3/4", "parabola", "AAAA", "hunter2", "Find the vertex"):
        assert leaked not in flat, leaked


def test_a_ring_entry_is_redacted_a_second_time_on_the_way_into_a_bundle(
    view, ledger_file, tmp_path
):
    """The ring is already redacted by `common/log.js`. This is the second
    lock, keyed off that same module's own list of what counts as coursework."""
    read = TRIAGE.read_ledger(path=str(ledger_file))
    written = TRIAGE.export(view, read, "f1:aaaaaaaaaaaaaaaa", tmp_path / "bundle")
    bundle = json.loads((written["path"] / "failure-bundle.json").read_text())
    poisoned = next(e for e in bundle["ring"] if e["event"] == "answer-not-insertable")

    assert poisoned["data"]["answer"] == {"length": 7}
    assert poisoned["data"]["problemText"] == {"length": 15}
    assert poisoned["data"]["editor"] == "answer-needs-template"


def test_a_graph_plan_stored_before_it_was_redacted_is_scrubbed_on_export():
    """A ring written by an earlier build still holds plans whole.

    `insertion-pinned` stored a graph's plan as it was, coordinates and all,
    until `graphPlan` was named coursework. Those entries stay in a profile
    until the ring evicts them, so the bundle's second lock has to know too.
    """
    entry = {
        "t": 1,
        "level": "info",
        "event": "insertion-pinned",
        "data": {"tabId": 11, "graphPlan": {"vertex": {"x": "37", "y": "-41"}}},
    }

    scrubbed = TRIAGE.sanitize_entry(entry, TRIAGE.contract())

    assert scrubbed["data"] == {"tabId": 11, "graphPlan": {"present": True}}


def test_the_allowlist_is_the_add_ons_own_and_is_never_guessed_at(
    monkeypatch, tmp_path
):
    """Two copies of an allowlist is one copy that can fall behind, and the
    failure it produces -- a field let through rather than dropped -- is the
    kind nobody notices until it matters."""
    terms = TRIAGE.contract()
    declared = re.search(
        r"SAFE_RECORD_KEYS = Object\.freeze\(\s*\[(.*?)\]",
        (EXTENSION / "common" / "failure-record.js").read_text(encoding="utf-8"),
        re.S,
    )

    assert terms["safe_record_keys"] == re.findall(r'"([^"]+)"', declared.group(1))
    assert "answer" not in terms["safe_record_keys"]
    assert {"answer", "problemText", "screenshot"} <= set(terms["sensitive_keys"])

    monkeypatch.setattr(TRIAGE, "RECORD_MODULE", tmp_path / "gone.js")
    with pytest.raises(TRIAGE.TriageError, match="refusing to sanitize by guesswork"):
        TRIAGE.contract()


def test_a_bundle_is_written_for_its_owner_only(view, ledger_file, tmp_path):
    read = TRIAGE.read_ledger(path=str(ledger_file))
    written = TRIAGE.export(view, read, "f1:aaaaaaaaaaaaaaaa", tmp_path / "bundle")

    assert stat.S_IMODE(written["path"].stat().st_mode) == 0o700
    for child in written["path"].iterdir():
        assert stat.S_IMODE(child.stat().st_mode) == 0o600


def test_exporting_something_that_is_not_there_is_refused_not_invented(
    view, ledger_file, tmp_path
):
    read = TRIAGE.read_ledger(path=str(ledger_file))

    with pytest.raises(TRIAGE.TriageError, match="no failure group or run matches"):
        TRIAGE.export(view, read, "f1:nothing", tmp_path / "bundle")


# --- offline, and read-only ------------------------------------------------


def _code_only(text: str) -> str:
    """The source with docstrings and comments removed, so prose is not evidence."""
    stripped = re.sub(r"^\s*#.*$", "", text, flags=re.MULTILINE)
    module = ast.parse(stripped)
    for node in ast.walk(module):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)
        ):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body[0].value.value = ""
    return ast.unparse(module)


def test_it_runs_no_command_at_all():
    """The observatory needs a window manager and a screenshot tool. This needs
    a file. Nothing it does can touch the desktop, so it is safe to run in the
    middle of the owner's question without thinking about it."""
    code = _code_only(SOURCE)

    for forbidden in ("subprocess", "os.system", "os.popen", "shutil.which", "pty."):
        assert forbidden not in code, forbidden
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(TREE)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else node.names)
    }
    assert "subprocess" not in imported


def test_it_reaches_no_network_and_no_browser():
    code = _code_only(SOURCE)

    for forbidden in (
        "urllib",
        "http",
        "socket",
        "requests",
        "marionette",
        "webdriver",
        "qdbus",
        "spectacle",
        "inspect_live_firefox",
    ):
        assert forbidden not in code, forbidden


def test_it_never_captures_the_screen():
    """A Hawkes page is coursework. This tool has no way to photograph one and
    is not the place to add one -- the observatory's `--screenshot` is, and it
    demands a bundle and prints the command that deletes it."""
    code = _code_only(SOURCE)

    for forbidden in (
        "captureVisibleTab",
        "Spectacle",
        "spectacle",
        "grim",
        "scrot",
        "pyautogui",
        "mss",
        "ImageGrab",
        "shot(",
    ):
        assert forbidden not in code, forbidden
    # And with no way to run a command, there is nothing left to capture with.
    assert "subprocess" not in code


def test_it_reads_the_profile_database_through_a_copy():
    """Firefox may be running and holding that file."""
    code = _code_only(SOURCE)
    reader = (PROJECT_ROOT / "scripts" / "read_extension_log.py").read_text(
        encoding="utf-8"
    )

    assert "shutil.copy(store, copy)" in reader
    assert "reader.read_storage(store)" in code
    assert "sqlite3" not in code


def test_it_writes_only_into_the_bundle_it_was_asked_for():
    roots = set()
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        called = ast.unparse(node.func)
        if called in {"os.chmod", "os.mkdir", "os.makedirs"}:
            roots.add(ast.unparse(node.args[0]).split(" ")[0])
        elif isinstance(node.func, ast.Attribute) and node.func.attr in {
            "write_text",
            "write_bytes",
            "mkdir",
            "touch",
            "chmod",
        }:
            roots.add(ast.unparse(node.func.value).split(" ")[0])

    # Every write is rooted at the directory the caller named for the bundle,
    # or at a file inside it. Nothing else is a write target.
    assert roots <= {"out_dir", "child", "(out_dir"}, roots
    for verb in ("unlink", "rmtree", "os.remove", "os.rename", "shutil.move"):
        assert verb not in _code_only(SOURCE), verb


def test_it_never_speaks_to_the_extension():
    """No port, no message, no native connection: the four things that wake a
    suspended event page are none of them available here."""
    code = _code_only(SOURCE)

    for forbidden in (
        "connectNative",
        "sendNativeMessage",
        "runtime.connect",
        "storage.local.set",
        "postMessage",
    ):
        assert forbidden not in code, forbidden
