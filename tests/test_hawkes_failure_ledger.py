"""The bounded ledger a failure leaves behind when nobody is watching.

The observatory could only ever answer "what is happening now", and answering
it needed the session to still be there -- so triaging a live refusal meant a
high-reasoning agent staying attached to the browser to catch one. The add-on
now keeps its own bounded record of runs that ended badly, and this asserts the
four properties that make that acceptable in something reading a student's
coursework: it holds none of the work, it holds enough to diagnose without
anyone having turned diagnostics up first, it is bounded and erasable, and
writing it cannot change what the browser does.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"
MODULE = EXTENSION / "common" / "failure-record.js"
BACKGROUND = EXTENSION / "background.js"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)

PRELUDE = """
var written = [];
var storageFails = false;
var stored = {};
var browser = {
  storage: {
    local: {
      get: function (key) {
        if (storageFails) { return Promise.reject(new Error("no storage")); }
        var out = {};
        if (Object.prototype.hasOwnProperty.call(stored, key)) { out[key] = stored[key]; }
        return Promise.resolve(out);
      },
      set: function (patch) {
        if (storageFails) { return Promise.reject(new Error("no storage")); }
        written.push(Object.keys(patch));
        Object.assign(stored, patch);
        return Promise.resolve();
      },
      remove: function (key) { delete stored[key]; return Promise.resolve(); },
    },
  },
};
"""


@pytest.fixture()
def js():
    context = quickjs.Context()
    context.eval(PRELUDE)
    context.eval(IMPORT_LINE.sub("", MODULE.read_text(encoding="utf-8")).replace("export ", ""))
    return context


def value(context, expression):
    return json.loads(context.eval(f"JSON.stringify({expression})"))


def settle(context, expression):
    """Run one promise to completion; QuickJS does not drain jobs by itself."""
    context.eval(f"var settled; ({expression}).then(function (v) {{ settled = v; }});")
    for _ in range(200):
        if not context.execute_pending_job():
            break
    return json.loads(context.eval("JSON.stringify(settled === undefined ? null : settled)"))


#: One ordinary insertion failure, as the event page would report it.
FAILURE = {
    "run": "r1",
    "generation": "g1",
    "at": 1_000_000,
    "outcome": "not-insertable",
    "errorKey": "",
    "phase": "solved",
    "stage": "done",
    "stages": ["reading", "solving", "done"],
    "windowId": 3,
    "tabId": 9,
    "frameId": 0,
    "fields": 1,
    "editor": {
        "ok": True,
        "kind": "dynamic",
        "code": "described",
        "name": "answerBox",
        "enabled": True,
        "maxLength": 40,
        "allowedCharacters": "0-9+-/()",
        "templates": {"fraction": True, "radical": False, "exponent": False},
        "slots": {"base": "0-9", "numerator": "0-9"},
    },
    "evidence": {"read": "markup", "expressions": 2, "promptChars": 88,
                 "signature": "fld|abcdef|120"},
    "certainty": {"source": "facet", "answered_by": "facet", "facet_invoked": True,
                  "router": "exact", "method": "solve"},
    "answerLength": 9,
    "answerParts": 0,
    "hostRequests": 1,
    "marker": "3d9a1f77aa21",
    "version": "0.46.0",
    "notInsertable": {"editor": "answer-needs-template",
                      "plan": "template-refused-by-question"},
    "events": ["answer-not-insertable"],
}


def build(context, **overrides):
    payload = {**FAILURE, **overrides}
    return value(context, f"buildFailureRecord({json.dumps(payload)})")


def merge(context, ledger, record, now=None):
    when = record["at"] if now is None else now
    return value(context, f"mergeFailure({json.dumps(ledger)}, {json.dumps(record)}, {when})")


# --- never the work --------------------------------------------------------


def test_no_amount_of_coursework_offered_to_a_record_reaches_one(js):
    """The rule that makes a persistent diagnostic acceptable at all.

    The ring redacts by key; this refuses by construction. Every field of a
    record is named by `buildFailureRecord` and filtered again through
    `SAFE_RECORD_KEYS`, so a call site that hands it the whole reply -- which
    is exactly how a redaction rule gets lost -- stores nothing extra.
    """
    poisoned = build(
        js,
        answer="x = 3/4",
        displayText="x = ¾",
        problemText="Find the vertex of the parabola",
        screenshot="data:image/png;base64,AAAA",
        password="hunter2",
        token="ghp_secret",
        cookie="session=abc",
        editor={**FAILURE["editor"], "text": "what the student typed"},
    )
    flat = json.dumps(poisoned)

    for leaked in ("3/4", "¾", "parabola", "AAAA", "hunter2", "ghp_secret",
                   "session=abc", "what the student typed"):
        assert leaked not in flat, leaked
    assert set(poisoned) <= set(value(js, "SAFE_RECORD_KEYS"))


def test_what_the_student_typed_into_the_box_is_not_part_of_describing_the_box(js):
    """`text` on a described editor is the answer so far, not the editor."""
    described = value(js, f"editorEvidence({json.dumps({**FAILURE['editor'], 'text': 'sqrt(2)'})})")

    assert "text" not in described
    assert described["allowed"] == "0-9+-/()"


def test_a_record_holds_the_answers_shape_and_never_its_text(js):
    record = build(js)

    assert record["answerShape"]["length"] == 9
    assert "answer" not in record


# --- enough to diagnose, without anyone having turned diagnostics up -------


def test_the_complete_editor_description_is_kept_by_default(js):
    """`answer-needs-template` names one of four templates against an unknown
    character set. Reading that back off the page cost a screenshot of the
    owner's coursework to reach a guess, and the description was `debug`-only.
    """
    editor = build(js)["editor"]

    assert editor["kind"] == "dynamic"
    assert editor["enabled"] is True
    assert editor["count"] == 1
    assert editor["maxLength"] == 40
    assert editor["allowed"] == "0-9+-/()"
    assert editor["templates"] == "fraction"
    assert editor["slots"] == {"base": "0-9", "numerator": "0-9"}


def test_every_control_of_a_multi_field_question_is_described(js):
    record = build(js, editor={
        "ok": True, "kind": "multi", "code": "described-multi",
        "editors": [
            {"ok": True, "kind": "dynamic", "enabled": True, "allowedCharacters": "0-9.-",
             "templates": {"fraction": False}, "name": "x", "maxLength": 12},
            {"ok": True, "kind": "option", "enabled": False, "allowedCharacters": "",
             "templates": {}, "name": "notReal", "maxLength": None},
        ],
    })

    assert record["editor"]["count"] == 2
    assert [one["kind"] for one in record["editor"]["controls"]] == ["dynamic", "option"]
    # A control nobody can type into is the thing that made a two-part answer
    # into a three-part one live; whether each is enabled has to be in here.
    assert [one["enabled"] for one in record["editor"]["controls"]] == [True, False]


def test_the_evidence_the_route_and_the_runtime_all_survive_into_one_record(js):
    record = build(js, certainty={
        "source": "facet", "answered_by": "facet", "facet_invoked": True,
        "router": "regression", "method": "fit", "runtime": "ollama",
        "model": "qwen", "actual_backend": "cuda", "device": "gpu",
    })

    assert record["evidence"]["read"] == "markup"
    assert record["route"]["router"] == "regression"
    assert record["runtime"] == {
        "runtime": "ollama", "model": "qwen", "requestedBackend": "",
        "backend": "cuda", "device": "gpu", "fallback": False,
    }


def test_a_run_names_the_host_requests_it_made(js):
    """`<run>.<n>` is the request id all the way through the companion and into
    Facet, so listing them is what joins a browser gesture to a Facet run."""
    record = build(js, hostRequests=3)

    assert record["host"]["ids"] == ["r1.1", "r1.2", "r1.3"]


def test_an_insertion_failure_still_names_the_solve_that_produced_the_answer(js):
    """Solving and inserting are two gestures and therefore two runs. By the
    time the insertion fails, the solve's own entries may be out of the ring."""
    record = build(
        js,
        run="r2",
        outcome="failed",
        errorKey="errorAnswerRejected",
        solve={"run": "r1", "answerLength": 9,
               "certainty": {"runtime": "ollama", "model": "qwen", "actual_backend": "cuda"}},
    )

    assert record["solve"]["run"] == "r1"
    assert record["solve"]["runtime"]["model"] == "qwen"


# --- one fault, one group --------------------------------------------------


def test_the_same_fault_on_different_questions_is_one_fingerprint(js):
    """Grouping is the whole point: a ledger of forty groups of one tells the
    next agent nothing about which root cause is worth their afternoon."""
    first = build(js, run="r1", at=1_000_000, generation="g1",
                  evidence={**FAILURE["evidence"], "signature": "a|111|10", "promptChars": 40},
                  answerLength=4, marker="aaaa11112222")
    second = build(js, run="r2", at=9_000_000, generation="g7",
                   evidence={**FAILURE["evidence"], "signature": "b|222|90", "promptChars": 300},
                   answerLength=31, marker="bbbb33334444")

    assert first["fingerprint"] == second["fingerprint"]
    assert first["fingerprint"].startswith("f1:")
    assert re.fullmatch(r"f1:[0-9a-f]{16}", first["fingerprint"])


@pytest.mark.parametrize(
    "change",
    [
        {"errorKey": "errorEthnosTimeout"},
        {"stages": ["reading", "solving"]},
        {"notInsertable": {"editor": "answer-has-rejected-characters", "plan": "no-plan"}},
        {"editor": {**FAILURE["editor"], "allowedCharacters": "0-9"}},
        {"editor": {**FAILURE["editor"], "enabled": False}},
        {"editor": {**FAILURE["editor"], "templates": {"fraction": True, "radical": True}}},
        {"certainty": {**FAILURE["certainty"], "router": "reasoning"}},
        {"outcome": "failed"},
    ],
)
def test_a_different_diagnostic_field_is_a_different_group(js, change):
    assert build(js)["fingerprint"] != build(js, **change)["fingerprint"]


def test_the_fingerprint_folds_no_field_derived_from_the_coursework(js):
    """A fingerprint that moved with the question would group nothing."""
    folded = value(js, f"fingerprintFields(buildFailureRecord({json.dumps(FAILURE)}))")
    names = {name for name, _ in folded}

    # Every one of these differs between two instances of one fault, and any
    # of them in here would produce a ledger of groups of one -- which is the
    # thing the ledger exists to stop.
    assert names.isdisjoint({
        "run", "generation", "at", "marker", "version", "elapsed",
        "evidenceSignature", "evidenceExpressions", "evidencePromptChars",
        "answerLength", "window", "tab", "frame",
    })
    # And these are what actually separates one fault from another.
    assert {"errorKey", "stages", "editorAllowed", "editorTemplates",
            "editorEnabled", "notInsertableEditor", "routeRouter"} <= names


def test_repeated_occurrences_become_one_group_with_a_count(js):
    ledger = value(js, "blankLedger()")
    for index in range(7):
        ledger = merge(js, ledger, build(js, run=f"r{index}", at=1_000_000 + index * 1000))

    assert len(ledger["groups"]) == 1
    group = ledger["groups"][0]
    assert group["count"] == 7
    assert group["firstRun"] == "r0"
    # Representative, and bounded: the most recent, which are the ones whose
    # records are most likely to still be retained.
    assert group["runs"] == ["r2", "r3", "r4", "r5", "r6"]


def test_a_group_records_every_build_it_has_happened_on(js):
    """"Still happening after the fix" is the question a ledger has to answer."""
    ledger = value(js, "blankLedger()")
    ledger = merge(js, ledger, build(js, run="r1", at=1_000_000, marker="beforethefix"))
    ledger = merge(js, ledger, build(js, run="r2", at=2_000_000, marker="afterthefix1"))

    assert ledger["groups"][0]["markers"] == ["beforethefix", "afterthefix1"]


# --- bounded, and honest about it ------------------------------------------


def test_records_are_capped_and_the_oldest_go_first(js):
    limit = value(js, "MAX_RECORDS")
    ledger = value(js, "blankLedger()")
    for index in range(limit + 12):
        ledger = merge(js, ledger, build(js, run=f"r{index}", at=1_000_000 + index * 1000,
                                         errorKey=f"errorSynthetic{index}"))

    assert len(ledger["records"]) == limit
    assert ledger["records"][0]["run"] == "r12"
    assert ledger["dropped"]["count"] == 12


def test_a_count_outlives_every_record_that_produced_it(js):
    """Records are for detail and are evicted first; groups are for counting."""
    limit = value(js, "MAX_RECORDS")
    ledger = value(js, "blankLedger()")
    for index in range(5):
        # One recurring fault, then a run of distinct ones that pushes its
        # records out of the ledger without pushing out its group.
        ledger = merge(js, ledger, build(js, run=f"old{index}", at=1_000_000 + index * 10))
    for index in range(limit):
        ledger = merge(js, ledger, build(js, run=f"new{index}", at=2_000_000 + index * 10,
                                         errorKey=f"errorDistinct{index}"))

    recurring = next(g for g in ledger["groups"] if g["count"] > 1)
    assert recurring["count"] == 5
    assert recurring["runs"] == ["old0", "old1", "old2", "old3", "old4"]
    # Groups are capped higher than records exactly so this can be true.
    assert value(js, "MAX_GROUPS") > limit
    assert not [r for r in ledger["records"] if r["fingerprint"] == recurring["fingerprint"]]


def test_groups_are_capped_too(js):
    limit = value(js, "MAX_GROUPS")
    ledger = value(js, "blankLedger()")
    for index in range(limit + 6):
        ledger = merge(js, ledger, build(js, run=f"r{index}", at=1_000_000 + index * 1000,
                                         errorKey=f"errorSynthetic{index}"))

    assert len(ledger["groups"]) == limit


def test_anything_older_than_the_retention_window_is_dropped(js):
    window = value(js, "MAX_AGE_MS")
    ledger = value(js, "blankLedger()")
    ledger = merge(js, ledger, build(js, run="ancient", at=1_000_000), now=1_000_000)
    ledger = merge(
        js, ledger,
        build(js, run="recent", at=1_000_000 + window + 5000, errorKey="errorOther"),
        now=1_000_000 + window + 5000,
    )

    assert [record["run"] for record in ledger["records"]] == ["recent"]
    assert len(ledger["groups"]) == 1
    assert ledger["dropped"]["age"] == 1


def test_the_ledger_stays_under_its_own_size_bound(js):
    """Count binds before size in ordinary use; size is the backstop for a
    record that is unusually large, and it drops the oldest until it fits."""
    cap = value(js, "MAX_BYTES")
    ledger = value(js, "blankLedger()")
    wide = {f"slot{index}": "0123456789" * 4 for index in range(24)}
    for index in range(value(js, "MAX_RECORDS")):
        ledger = merge(js, ledger, build(
            js, run=f"r{index}", at=1_000_000 + index * 1000,
            errorKey=f"errorSynthetic{index}",
            editor={**FAILURE["editor"], "slots": wide},
        ))

    # Measured the way the module measures it: `JSON.stringify` is compact,
    # and a bound checked against a differently-spaced serialization is not
    # the bound the browser is actually keeping.
    assert len(json.dumps(ledger, separators=(",", ":"))) <= cap
    assert ledger["dropped"]["bytes"] > 0


def test_a_ledger_written_by_another_version_is_started_over_not_misread(js):
    merged = merge(js, {"version": 99, "records": [{"run": "alien"}], "groups": [1]},
                   build(js, run="r1"))

    assert [record["run"] for record in merged["records"]] == ["r1"]
    assert merged["version"] == value(js, "LEDGER_VERSION")


def test_garbage_in_storage_cannot_stop_a_failure_being_recorded(js):
    for junk in ('"not a ledger"', "42", "null", '{"records": "nope", "groups": 7}'):
        merged = value(js, f"mergeFailure({junk}, buildFailureRecord({json.dumps(FAILURE)}), 1)")
        assert len(merged["records"]) == 1


# --- across the event page's own lifetimes --------------------------------


def test_a_later_event_page_adds_to_the_ledger_rather_than_replacing_it(js):
    """The page is non-persistent. A ledger that started fresh on every load
    would hold only whatever failed since the last time Firefox got bored."""
    first = merge(js, value(js, "blankLedger()"),
                  build(js, run="r1", at=1_000_000, generation="g1"))
    second = merge(js, first, build(js, run="r2", at=2_000_000, generation="g2"))

    assert [record["generation"] for record in second["records"]] == ["g1", "g2"]
    assert second["groups"][0]["count"] == 2
    assert second["groups"][0]["generations"] == ["g1", "g2"]


# --- writing one cannot change what the browser does ----------------------


def test_a_record_is_written_under_one_key_and_nothing_else(js):
    js.eval("stored = {}; written = [];")
    settle(js, f"recordFailure(buildFailureRecord({json.dumps(FAILURE)}))")

    assert value(js, "written") == [["failures"]]
    assert value(js, "Object.keys(stored)") == ["failures"]


def test_two_failures_a_moment_apart_do_not_lose_one_another(js):
    """Read-modify-write on a key nobody owns is a race; the writes chain."""
    js.eval("stored = {};")
    js.eval(
        "var one = buildFailureRecord(%s);" % json.dumps({**FAILURE, "run": "rA"})
        + "var two = buildFailureRecord(%s);" % json.dumps({**FAILURE, "run": "rB", "at": 1_000_100})
    )
    js.eval("recordFailure(one); recordFailure(two);")
    for _ in range(200):
        if not js.execute_pending_job():
            break

    assert [record["run"] for record in value(js, "stored.failures.records")] == ["rA", "rB"]


def test_storage_being_unavailable_costs_the_record_and_nothing_else(js):
    js.eval("storageFails = true;")
    settle(js, f"recordFailure(buildFailureRecord({json.dumps(FAILURE)}))")
    js.eval("storageFails = false;")

    assert value(js, "Object.keys(stored)") == []


def test_reading_the_ledger_does_not_rewrite_it(js):
    js.eval("stored = {}; ")
    settle(js, f"recordFailure(buildFailureRecord({json.dumps(FAILURE)}))")
    js.eval("written = [];")
    read = settle(js, "readFailures(1000000)")

    assert read["records"][0]["run"] == "r1"
    assert value(js, "written") == []


def test_clearing_diagnostics_clears_the_ledger_too(js):
    settle(js, f"recordFailure(buildFailureRecord({json.dumps(FAILURE)}))")
    settle(js, "clearFailures()")

    assert value(js, "Object.keys(stored)") == []


def test_the_recorder_starts_nothing_that_could_hold_an_event_page_open(js):
    """Four things wake or keep a suspended event page: a timer, an alarm, a
    port, and a message. A diagnostic that used any of them would change the
    timing of the session it was meant to observe."""
    source = MODULE.read_text(encoding="utf-8")

    for held in ("setTimeout", "setInterval", "requestIdleCallback", "alarms",
                 "connectNative", "runtime.connect", "sendMessage", "onMessage",
                 "addListener", "captureVisibleTab", "scripting", "tabs."):
        assert held not in source, held


def test_the_failure_path_never_waits_for_the_record(js):
    """The panel has already been told. A diagnostic must not sit in front of
    the user being told, and an operation must not fail because storage did."""
    background = BACKGROUND.read_text(encoding="utf-8")

    assert "await recordFailure" not in background
    assert "await retain(" not in background
    assert "return recordFailure" not in background
    # Every call goes through the one helper, and the helper is fire-and-forget.
    assert background.count("recordFailure(") == 1
    retainer = background[background.index("function retain(") :]
    assert "await" not in retainer[: retainer.index("\n}\n")]


# --- the whole path, through the event page itself -------------------------


@pytest.fixture()
def page():
    """The real event page, loaded the way the ownership harness loads it."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "ownership_harness", PROJECT_ROOT / "tests" / "test_hawkes_insertion_ownership.py"
    )
    harness = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(harness)
    return harness.make_page()


def stored_ledger(page):
    return page.json("__H.localStored.failures || null")


def test_a_real_failure_leaves_a_real_record(page):
    """End to end, through `fail` rather than around it.

    Every property above is asserted against the module in isolation, which
    proves the module. This proves the wiring: that the event page's own
    failure path reaches it, with the state the page was actually holding.
    """
    page.own_window_a()
    page.run('startRun(); runStages = ["reading", "solving"];')
    page.run('fail("errorAnswerRejected", { detail: "x = 3/4 was rejected" });')
    page.pump()

    ledger = stored_ledger(page)
    assert ledger is not None, page.json("__H.logged")
    assert len(ledger["records"]) == 1
    kept = ledger["records"][0]
    assert kept["errorKey"] == "errorAnswerRejected"
    assert kept["outcome"] == "failed"
    assert kept["stages"] == ["reading", "solving"]
    assert kept["phase"] == "solved"
    # The editor the page was holding, described in full, with no setting on.
    assert kept["editor"]["kind"] == "dynamic"
    assert kept["editor"]["allowed"] == "0123456789y"
    assert kept["editor"]["enabled"] is True
    assert kept["target"] == {"window": 1, "tab": 11, "frame": 0, "fields": 1}
    assert kept["run"] and kept["generation"]
    assert re.fullmatch(r"f1:[0-9a-f]{16}", kept["fingerprint"])
    assert ledger["groups"][0]["count"] == 1


def test_the_same_failure_twice_is_counted_once_by_the_running_page(page):
    for _ in range(3):
        # Each run starts from the state a reviewed answer leaves behind, which
        # is what `prepare` re-establishes between one gesture and the next.
        page.own_window_a()
        page.run('startRun(); runStages = ["reading", "solving"];')
        page.run('fail("errorAnswerRejected");')
        page.pump()

    ledger = stored_ledger(page)
    assert len(ledger["groups"]) == 1
    assert ledger["groups"][0]["count"] == 3
    assert len(set(ledger["groups"][0]["runs"])) == 3


def test_a_run_that_never_started_writes_nothing(page):
    """A record nothing can be correlated to is not worth a write."""
    page.own_window_a()
    page.run('setRun(""); fail("errorAnswerRejected");')
    page.pump()

    assert stored_ledger(page) is None


def test_the_page_writes_no_ledger_when_nothing_fails(page):
    page.own_window_a()
    page.run("startRun(); update({ phase: 'solved' });")
    page.pump()

    assert stored_ledger(page) is None


def test_only_a_terminal_diagnostic_state_is_retained(js):
    """A record per solve would be a log, not a ledger, and would fill the
    bound with successes on the way to pushing the failures out."""
    background = BACKGROUND.read_text(encoding="utf-8")
    calls = re.findall(r'retain\(\s*"([a-z-]+)"', background)

    assert sorted(set(calls)) == ["disputed", "failed", "not-insertable"]
    # `fail` is the one funnel every failure passes through.
    fail_body = background[background.index("function fail(") :][:900]
    assert 'retain("failed"' in fail_body
