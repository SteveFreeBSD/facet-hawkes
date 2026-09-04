"""The diagnostic log, the settings schema, and the checks that gate them.

The add-on writes a log because every failure path in it used to be a bare
`catch {}`; it writes a *redacted* one because it reads a student's coursework,
and a diagnostic file the user is invited to paste into a bug report must not
carry their answers. Both halves are asserted here, the second by running the
redaction itself.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
COMMON = EXTENSION_DIR / "common"
BUILD_SCRIPT = PROJECT_ROOT / "scripts" / "build_extension.py"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

IMPORT_LINE = re.compile(r"^import\s.*?;\s*$", re.MULTILINE | re.DOTALL)


def _load_build_module():
    spec = importlib.util.spec_from_file_location("build_extension_diag", BUILD_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_extension = _load_build_module()


# The host objects the modules reach for. Enough to run them, and no more: a
# real storage area is not needed to assert what never reaches one.
PRELUDE = """
var recorded = [];
var console = {
  log: function (line, data) { recorded.push(["log", line, data]); },
  warn: function (line, data) { recorded.push(["warn", line, data]); },
  error: function (line, data) { recorded.push(["error", line, data]); },
};
var stored = {};
var browser = {
  storage: {
    local: {
      get: function () { return Promise.resolve(stored); },
      set: function (patch) { Object.assign(stored, patch); return Promise.resolve(); },
      remove: function () { return Promise.resolve(); },
    },
    onChanged: { addListener: function () {} },
  },
};
var listeners = {};
var self = { addEventListener: function (name, fn) { listeners[name] = fn; } };
function setTimeout() { return 1; }
function clearTimeout() {}
"""


def _modules(*names):
    return "\n".join(
        IMPORT_LINE.sub("", (COMMON / name).read_text()).replace("export ", "")
        for name in names
    )


@pytest.fixture(scope="module")
def context():
    ctx = quickjs.Context()
    ctx.eval(PRELUDE + _modules("log.js", "settings.js"))
    return ctx


def evaluate(context, expression):
    return json.loads(context.eval(f"JSON.stringify({expression})"))


# --- redaction -------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["answer", "displayText", "problemText", "screenshot", "detail", "value"],
)
def test_the_coursework_is_never_written_only_its_shape(context, key):
    """The rule that makes a log acceptable in something that reads answers."""
    redacted = evaluate(context, f'redact({{{key}: "3y + 11"}})')

    assert redacted == {key: {"length": 7}}
    assert "3y" not in json.dumps(redacted)


def test_a_screenshot_is_reduced_to_the_fact_that_there_was_one(context):
    redacted = evaluate(context, 'redact({screenshot_png_base64: "iVBORw0KGgo"})')

    assert redacted == {"screenshot_png_base64": {"length": 11}}


def test_redaction_reaches_into_nested_payloads(context):
    redacted = evaluate(context, 'redact({reply: {answer: "3y", status: "ready"}})')

    assert redacted == {"reply": {"answer": {"length": 2}, "status": "ready"}}


def test_an_ordinary_string_is_kept_but_bounded(context):
    long = evaluate(context, 'redact({note: "x".repeat(400)})')

    assert long["note"].endswith("…")
    assert len(long["note"]) == 161  # MAX_STRING plus the ellipsis


def test_the_profile_uuid_is_stripped_from_a_stack(context):
    described = evaluate(
        context,
        'describeError(Object.assign(new Error("boom"), {stack: '
        '"render@moz-extension://3f2b1c4d-0000-4000-8000-abcdefabcdef/popup/popup.js:12:3"}))',
    )

    assert described["message"] == "boom"
    # The UUID is unique per profile and this file is meant to be pasteable.
    assert "moz-extension" not in json.dumps(described)
    assert described["stack"] == ["render@/popup/popup.js:12:3"]


def test_a_stack_is_kept_short_enough_to_read(context):
    frames = "\\n".join(f"frame{index}@/a.js:1:1" for index in range(40))
    described = evaluate(
        context,
        f'describeError(Object.assign(new Error("deep"), {{stack: "{frames}"}}))',
    )

    assert len(described["stack"]) == 6


# --- levels ----------------------------------------------------------------


def test_nothing_below_the_chosen_level_is_recorded(context):
    context.eval('recorded = []; initLog("test", { level: "warn" });')
    context.eval(
        'log.info("ignored"); log.debug("ignored"); log.warn("kept"); log.error("kept");'
    )

    recorded = evaluate(context, "recorded.map((entry) => entry[1])")
    assert recorded == ["[ethnos:test] kept", "[ethnos:test] kept"]


def test_off_records_nothing_at_all(context):
    context.eval('recorded = []; setLogLevel("off");')
    context.eval(
        'log.error("suppressed"); log.warn("suppressed"); log.info("suppressed");'
    )

    assert evaluate(context, "recorded.length") == 0
    context.eval('setLogLevel("info");')


def test_an_uncaught_error_reaches_the_log_and_the_panel(context):
    """The failure mode this whole module exists for.

    A panel that throws mid-render stops updating and says nothing. Now it
    records the throw and calls back so the panel can show that it happened.
    """
    context.eval("""
        recorded = [];
        var fatal = null;
        initLog("panel", { level: "info", onFatal: function (info) { fatal = info; } });
        listeners.error({ message: "x is not initialized", filename:
          "moz-extension://3f2b1c4d-0000-4000-8000-abcdefabcdef/popup/popup.js",
          lineno: 170, colno: 41 });
    """)

    assert evaluate(context, "fatal.line") == 170
    assert evaluate(context, "fatal.source") == "/popup/popup.js"
    assert evaluate(context, "recorded[0][0]") == "error"


def test_a_rejected_promise_nobody_awaited_is_recorded_too(context):
    context.eval("""
        recorded = [];
        listeners.unhandledrejection({ reason: new Error("nobody caught this") });
    """)

    assert evaluate(context, "recorded[0][1]") == "[ethnos:panel] unhandled-rejection"


def test_the_ring_is_bounded_and_erasable():
    source = (COMMON / "log.js").read_text()

    assert "RING_LIMIT = 200" in source
    assert ".slice(-RING_LIMIT)" in source
    assert "browser.storage.local.remove(LOG_STORAGE_KEY)" in source


def test_the_log_never_leaves_the_machine():
    source = (COMMON / "log.js").read_text()

    # There is no transport anywhere in this add-on, and the log does not add
    # the first one. `storage.local` is not sync storage, either.
    for transport in (
        "fetch(",
        "XMLHttpRequest",
        "sendBeacon",
        "storage.sync",
        "WebSocket",
    ):
        assert transport not in source


# --- settings --------------------------------------------------------------


def test_every_default_survives_a_round_trip(context):
    defaults = evaluate(context, "defaultSettings()")

    assert defaults["solveEngine"] == "ethnos"
    assert set(defaults) == set(evaluate(context, "SETTING_KEYS"))
    for key, value in defaults.items():
        assert evaluate(context, f"coerce({json.dumps(key)}, {json.dumps(value)})") == {
            "ok": True,
            "value": value,
        }


@pytest.mark.parametrize(
    ("key", "offered", "expected"),
    [
        ("solveTimeoutSeconds", 5, 240),  # below the floor
        ("solveTimeoutSeconds", 100000, 240),  # above the ceiling
        ("solveTimeoutSeconds", "240", 240),  # a string from an input element
        ("panelWidth", 9000, 360),
        ("autoSolve", "yes", True),
        ("logLevel", "chatty", "info"),
        ("solveEngine", "garbage", "ethnos"),
    ],
)
def test_a_value_the_schema_rejects_falls_back_to_the_default(
    context, key, offered, expected
):
    """A corrupt preference should cost you the preference, not the add-on."""
    verdict = evaluate(context, f"coerce({json.dumps(key)}, {json.dumps(offered)})")

    assert verdict == {"ok": False, "value": expected}


def test_a_setting_the_schema_does_not_know_is_refused(context):
    assert evaluate(context, 'coerce("somethingElse", true)')["ok"] is False


@pytest.mark.parametrize("engine", ["ethnos", "facet"])
def test_solve_engine_accepts_only_the_closed_enum(context, engine):
    assert evaluate(context, f'coerce("solveEngine", "{engine}")') == {
        "ok": True,
        "value": engine,
    }


def test_the_timeout_the_solver_uses_is_the_one_that_was_set():
    background = (EXTENSION_DIR / "background.js").read_text()

    # It was a constant four minutes with no way to change it.
    assert "settings.solveTimeoutSeconds * 1000" in background
    assert "SOLVE_TIMEOUT_MS" not in background
    # And a change made while the event page is loaded takes effect.
    assert "onSettingsChanged" in background


def test_cadence_presets_resolve_to_distinct_serializable_arrangements(context):
    defaults = evaluate(context, "defaultSettings()")
    resolved = {}
    for genre in ("classical", "jazz", "lofi", "electronic"):
        offered = {**defaults, "entryGenre": genre}
        resolved[genre] = evaluate(
            context, f"resolveEntryCadence({json.dumps(offered)})"
        )

    assert resolved["classical"]["rhythmWeights"] != resolved["jazz"]["rhythmWeights"]
    assert resolved["lofi"]["swingRatio"] == 0.12
    assert resolved["electronic"]["variationRatio"] == 0.06
    for cadence in resolved.values():
        assert cadence["durationMinMs"] == 5000
        assert cadence["durationMaxMs"] == 10000


def test_custom_cadence_uses_advanced_controls_and_orders_its_window(context):
    defaults = evaluate(context, "defaultSettings()")
    offered = {
        **defaults,
        "entryGenre": "custom",
        "entryPattern": "syncopated",
        "entryTempoBpm": 144,
        "entryDurationMinSeconds": 11,
        "entryDurationMaxSeconds": 4,
        "entrySwingPercent": 37,
        "entryVariationPercent": 25,
        "entrySymbolRestPercent": 66,
    }

    cadence = evaluate(context, f"resolveEntryCadence({json.dumps(offered)})")

    assert cadence == {
        "tempoBpm": 144,
        "durationMinMs": 4000,
        "durationMaxMs": 11000,
        "rhythmWeights": [1, 0.56, 0.9, 1.24],
        "swingRatio": 0.37,
        "variationRatio": 0.25,
        "symbolRestRatio": 0.66,
    }


def test_editor_cadence_offsets_stay_bounded_and_respond_to_tempo():
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text()
    public_return = "    originAllowed,\n  };"
    test_return = (
        "    originAllowed,\n"
        "    __normalizeCadence: normalizedCadence,\n"
        "    __entryBeatOffsets: entryBeatOffsets,\n"
        "  };"
    )
    assert public_return in editor

    cadence_context = quickjs.Context()
    cadence_context.eval(
        PRELUDE
        + """
        var __cadenceSeed = 2463534242;
        var crypto = { getRandomValues: function (sample) {
          __cadenceSeed ^= __cadenceSeed << 13;
          __cadenceSeed ^= __cadenceSeed >>> 17;
          __cadenceSeed ^= __cadenceSeed << 5;
          sample[0] = __cadenceSeed >>> 0;
          return sample;
        } };
    """
        + _modules("log.js", "settings.js", "cadence.js")
    )
    cadence_context.eval(editor.replace(public_return, test_return))

    formula = json.dumps("x^2 + 18x + 81")
    defaults = evaluate(cadence_context, "defaultSettings()")
    for genre in ("classical", "jazz", "lofi", "electronic"):
        offered = json.dumps({**defaults, "entryGenre": genre})
        offsets = evaluate(
            cadence_context,
            "(function () {"
            f"const cadence = ethnosHawkes.__normalizeCadence(resolveEntryCadence({offered}));"
            f"return ethnosHawkes.__entryBeatOffsets([...{formula}], cadence);"
            "})()",
        )
        assert len(offsets) == len("x^2 + 18x + 81")
        assert offsets == sorted(offsets)
        assert 5000 <= offsets[-1] <= 10000

    def duration_at(tempo):
        offered = json.dumps(
            {
                **defaults,
                "entryGenre": "custom",
                "entryTempoBpm": tempo,
                "entryDurationMinSeconds": 2,
                "entryDurationMaxSeconds": 12,
            }
        )
        cadence_context.eval("__cadenceSeed = 2463534242")
        return evaluate(
            cadence_context,
            "(function () {"
            f"const cadence = ethnosHawkes.__normalizeCadence(resolveEntryCadence({offered}));"
            f"const offsets = ethnosHawkes.__entryBeatOffsets([...{formula}], cadence);"
            "return offsets[offsets.length - 1];"
            "})()",
        )

    assert duration_at(300) < duration_at(30)


def test_cadence_tempo_has_an_expressive_but_bounded_range(context):
    assert evaluate(context, 'coerce("entryTempoBpm", 30)') == {
        "ok": True,
        "value": 30,
    }
    assert evaluate(context, 'coerce("entryTempoBpm", 300)') == {
        "ok": True,
        "value": 300,
    }
    assert evaluate(context, 'coerce("entryTempoBpm", 301)') == {
        "ok": False,
        "value": 82,
    }


def test_semantic_preview_uses_the_real_bounded_note_score_without_mutating_plan():
    cadence_context = quickjs.Context()
    cadence_context.eval(
        PRELUDE
        + """
        var crypto = { getRandomValues: function (sample) {
          sample[0] = 2147483648;
          return sample;
        } };
        """
        + _modules("cadence.js")
    )
    steps = [
        {"op": "template", "name": "Fraction"},
        {"op": "type", "text": "2x+3"},
        {"op": "slot", "name": "denominator"},
        {"op": "type", "text": "5y"},
        {"op": "template", "name": "Exponent"},
        {"op": "type", "text": "2"},
    ]
    offered = {
        "tempoBpm": 300,
        "durationMinMs": 2000,
        "durationMaxMs": 4000,
        "rhythmWeights": [1, 0.68, 1.18, 0.78],
        "swingRatio": 0.12,
        "variationRatio": 0.18,
        "symbolRestRatio": 0.42,
    }
    result = evaluate(
        cadence_context,
        "(function () {"
        f"const steps = {json.dumps(steps)};"
        "const before = JSON.stringify(steps);"
        f"const phrase = ethnosCadence.planSemanticPhrase(steps, {json.dumps(offered)});"
        "return { phrase, unchanged: before === JSON.stringify(steps) };"
        "})()",
    )

    phrase = result["phrase"]
    assert result["unchanged"] is True
    assert [(note["character"], note["planIndex"]) for note in phrase["notes"]] == [
        ("2", 1),
        ("x", 1),
        ("+", 1),
        ("3", 1),
        ("5", 3),
        ("y", 3),
        ("2", 5),
    ]
    # Every note also carries what a rhythm display needs: when it lands, and
    # whether it is accented or followed by a structural rest. Deriving those
    # anywhere else is how a display and its schedule start disagreeing.
    assert [note["offsetMs"] for note in phrase["notes"]] == phrase["offsets"]
    # `+` is the only operator, and it is not the final note, so it is the only
    # note that earns a structural rest.
    assert [note["rest"] for note in phrase["notes"]] == [
        False,
        False,
        True,
        False,
        False,
        False,
        False,
    ]
    assert phrase["offsets"] == sorted(phrase["offsets"])
    assert 2000 <= phrase["durationMs"] <= 4000
    assert phrase["withinWindow"] is True
    kinds = {step["kind"] for step in phrase["timeline"]}
    assert {
        "character",
        "operator",
        "structure-enter",
        "rest",
        "resolution",
    } <= kinds
    # The timeline and the notes must agree about which positions are accented;
    # they are two views of one arrangement, not two opinions about it.
    assert {
        step["noteIndex"]: step["accent"]
        for step in phrase["timeline"]
        if step["kind"] in {"character", "operator"}
    } == {index: note["accent"] for index, note in enumerate(phrase["notes"])}


def test_the_hard_window_reports_which_end_overrode_the_tempo():
    """ "Within window" before a phrase plays is true by construction.

    Every planned phrase is clamped into the window, so a plan-time compliance
    readout can only ever say yes -- which hid the one fact worth reporting:
    at 300 BPM the phrase came out five seconds long because the window's floor
    decided, not the tempo. The measured verdict after a performance is a
    different claim and stays a genuine pass or fail.
    """
    cadence_context = quickjs.Context()
    cadence_context.eval(
        PRELUDE
        + """
        var crypto = { getRandomValues: function (sample) {
          sample[0] = 2147483648;
          return sample;
        } };
        """
        + _modules("cadence.js")
    )

    def plan(tempo):
        return evaluate(
            cadence_context,
            "ethnosCadence.planCharacters("
            '[..."2x+3y-7z"], '
            f"{{tempoBpm: {tempo}, durationMinMs: 5000, durationMaxMs: 10000}}"
            ")",
        )

    fast, natural, slow = plan(300), plan(82), plan(30)

    assert fast["clampedBy"] == "minimum"
    assert fast["blendedDurationMs"] < 5000
    assert fast["durationMs"] == 5000
    assert natural["clampedBy"] == "none"
    assert natural["durationMs"] == natural["blendedDurationMs"]
    assert slow["clampedBy"] == "maximum"
    assert slow["blendedDurationMs"] > 10000
    assert slow["durationMs"] == 10000
    # Clamped or not, the hard window is still honoured -- that is the point.
    for phrase in (fast, natural, slow):
        assert phrase["withinWindow"] is True
        assert 5000 <= phrase["durationMs"] <= 10000


def test_cadence_settings_can_be_persisted_as_one_atomic_patch():
    cadence_context = quickjs.Context()
    cadence_context.eval(PRELUDE + _modules("log.js", "settings.js"))
    cadence_context.eval(
        "var writeFinished = false;"
        "writeSettings({entryGenre: 'jazz', entryTempoBpm: 140})"
        ".then(function (ok) { writeFinished = ok; });"
    )
    for _ in range(20):
        if not cadence_context.execute_pending_job():
            break

    assert evaluate(cadence_context, "writeFinished") is True
    assert evaluate(cadence_context, "stored") == {
        "entryGenre": "jazz",
        "entryTempoBpm": 140,
    }

    cadence_context.eval(
        "writeSettings({entryGenre: 'classical', entryTempoBpm: 999})"
        ".then(function (ok) { writeFinished = ok; });"
    )
    for _ in range(20):
        if not cadence_context.execute_pending_job():
            break
    assert evaluate(cadence_context, "writeFinished") is False
    assert evaluate(cadence_context, "stored") == {
        "entryGenre": "jazz",
        "entryTempoBpm": 140,
    }


def test_semantic_preview_transport_cancels_a_pending_phrase_cleanly():
    cadence_context = quickjs.Context()
    cadence_context.eval(
        """
        var now = 0;
        var timers = [];
        var performance = { now: function () { return now; } };
        function setTimeout(fn, ms) {
          timers.push({ fn: fn, ms: ms });
          return timers.length;
        }
        function clearTimeout(id) { timers[id - 1] = null; }
        var crypto = { getRandomValues: function (sample) {
          sample[0] = 2147483648;
          return sample;
        } };
        var signal = {
          aborted: false,
          listener: null,
          addEventListener: function (_, listener) { this.listener = listener; },
          removeEventListener: function (_, listener) {
            if (this.listener === listener) { this.listener = null; }
          },
        };
        function abortPreview() {
          signal.aborted = true;
          if (signal.listener) { signal.listener(); }
        }
        """
        + _modules("cadence.js")
    )
    cadence_context.eval(
        """
        var visited = [];
        var transportResult = "pending";
        var phrase = ethnosCadence.planSemanticPhrase(
          [{ op: "type", text: "x+2" }],
          { durationMinMs: 2000, durationMaxMs: 2000 },
          function () { return 0.5; }
        );
        ethnosCadence.playSemanticPhrase(
          phrase,
          function (step) { visited.push(step.kind); },
          { signal: signal }
        ).then(
          function () { transportResult = "complete"; },
          function (error) { transportResult = error.name; }
        );
        """
    )
    for _ in range(20):
        cadence_context.execute_pending_job()
        if evaluate(cadence_context, "timers.filter(Boolean).length") > 0:
            break

    assert evaluate(cadence_context, "visited.length") > 0
    cadence_context.eval("abortPreview()")
    for _ in range(20):
        if not cadence_context.execute_pending_job():
            break

    assert evaluate(cadence_context, "transportResult") == "AbortError"
    assert evaluate(cadence_context, "timers.filter(Boolean).length") == 0


def test_every_declared_setting_has_a_control_and_every_control_a_setting(context):
    markup = (EXTENSION_DIR / "options" / "options.html").read_text()

    declared = set(evaluate(context, "SETTING_KEYS"))
    bound = set(re.findall(r'data-setting="([^"]+)"', markup))

    assert bound == declared


# --- the checks that gate all of this --------------------------------------


def test_the_build_rejects_a_read_above_its_own_declaration(tmp_path, monkeypatch):
    """The exact shape of the bug that shipped in 0.22.0."""
    tree = tmp_path / "extension"
    tree.mkdir()
    (tree / "broken.js").write_text(
        "function render(state) {\n"
        "  label(running ? 'cancel' : 'solve');\n"
        "  const running = state.phase === 'solving';\n"
        "  return running;\n"
        "}\n"
    )
    monkeypatch.setattr(build_extension, "EXTENSION_DIR", tree)

    problems: list[str] = []
    build_extension._check_declaration_order(problems)

    assert len(problems) == 1
    assert "'running' is read before its declaration" in problems[0]
    assert "broken.js:2" in problems[0]


def test_the_build_allows_a_reference_from_a_function_called_later(
    tmp_path, monkeypatch
):
    """Hoisting makes this legal, and a check that cried wolf would be turned off."""
    tree = tmp_path / "extension"
    tree.mkdir()
    (tree / "fine.js").write_text(
        "function outer() {\n"
        "  function later() { return limit; }\n"
        "  const limit = 3;\n"
        "  return later() + limit;\n"
        "}\n"
        "const settings = { limit: 1 };\n"
        "for (const limit of [1, 2]) { void limit; }\n"
    )
    monkeypatch.setattr(build_extension, "EXTENSION_DIR", tree)

    problems: list[str] = []
    build_extension._check_declaration_order(problems)

    assert problems == []


def test_a_name_inside_a_comment_or_a_string_is_not_a_read(tmp_path, monkeypatch):
    tree = tmp_path / "extension"
    tree.mkdir()
    (tree / "prose.js").write_text(
        "function f() {\n"
        "  // running is described here before it exists\n"
        '  const note = "running";\n'
        "  const running = 1;\n"
        "  return running + note.length;\n"
        "}\n"
    )
    monkeypatch.setattr(build_extension, "EXTENSION_DIR", tree)

    problems: list[str] = []
    build_extension._check_declaration_order(problems)

    assert problems == []


def test_the_build_rejects_a_selector_for_an_element_that_is_not_there(
    tmp_path, monkeypatch
):
    """The same total failure, reached by renaming an element instead."""
    tree = tmp_path / "extension"
    (tree / "page").mkdir(parents=True)
    (tree / "page" / "page.html").write_text(
        '<!doctype html><html><body><button id="solve"></button>'
        '<script type="module" src="page.js"></script></body></html>'
    )
    (tree / "page" / "page.js").write_text(
        'const solve = document.querySelector("#solve");\n'
        'const gone = document.querySelector("#renamed");\n'
    )
    monkeypatch.setattr(build_extension, "EXTENSION_DIR", tree)

    problems: list[str] = []
    build_extension._check_element_ids(problems)

    assert len(problems) == 1
    assert "'renamed'" in problems[0]


def test_the_shipped_tree_passes_both_checks():
    problems: list[str] = []
    build_extension._check_declaration_order(problems)
    build_extension._check_element_ids(problems)

    assert problems == []


# --- writing the ring ------------------------------------------------------

WRITER_STUB = """
var console = { log: function () {}, warn: function () {}, error: function () {} };
var store = {};
var timers = [];
function setTimeout(fn) { timers.push(fn); return timers.length; }
function clearTimeout() {}
var browser = { storage: { local: {
  get: function () { return Promise.resolve(store); },
  set: function (patch) { Object.assign(store, patch); return Promise.resolve(); },
  remove: function () { delete store.diagnostics; return Promise.resolve(); },
}}};
var self = { addEventListener: function () {} };
function runTimers() { var due = timers; timers = []; due.forEach(function (fn) { fn(); }); }
"""


class Writer:
    """A QuickJS context plus the job pump its promises need to settle."""

    def __init__(self, context):
        self.context = context

    def eval(self, script):
        return self.context.eval(script)

    def pump(self, limit=2000):
        for _ in range(limit):
            if not self.context.execute_pending_job():
                return


@pytest.fixture
def writer():
    """A fresh log with a storage area behind it, and a way to run its jobs."""
    context = quickjs.Context()
    context.eval(WRITER_STUB + _modules("log.js"))
    context.eval('initLog("test", { level: "info" });')
    return Writer(context)


def _events(context):
    return [entry["event"] for entry in evaluate(context, "store.diagnostics || []")]


def test_a_flush_settles_only_once_the_entries_are_written(writer):
    writer.eval('log.info("a"); log.info("b");')
    assert _events(writer) == []  # queued, not yet written

    writer.eval("var done = false; flushLog().then(function () { done = true; });")
    writer.pump()

    assert evaluate(writer, "done") is True
    assert _events(writer) == ["a", "b"]


def test_the_log_can_be_read_back_immediately_after_flushing(writer):
    """What "Copy diagnostics" does, and it must not miss the last entry."""
    writer.eval('log.info("a"); log.error("the failure you are reporting");')
    writer.eval(
        "var seen = null;"
        "flushLog().then(readLog).then(function (r) { seen = r.map(function (e) { return e.event; }); });"
    )
    writer.pump()

    assert evaluate(writer, "seen") == ["a", "the failure you are reporting"]


def test_an_entry_logged_during_a_write_is_not_left_behind(writer):
    """Regression: a second flush resolved at once and skipped the write.

    `flushLog()` returned immediately whenever a write was already running, so
    anything logged in between was still only queued when the caller read the
    log back -- and a copied diagnostic was missing its most recent lines.
    """
    writer.eval('log.info("first"); var one = flushLog();')
    writer.eval('log.info("during"); var two = flushLog();')
    writer.eval(
        "var seen = null;"
        "Promise.all([one, two]).then(readLog).then(function (r) {"
        "  seen = r.map(function (e) { return e.event; }); });"
    )
    writer.pump()

    assert evaluate(writer, "seen") == ["first", "during"]


def test_the_ring_drops_the_oldest_rather_than_growing(writer):
    writer.eval(
        "for (let index = 0; index < 260; index += 1) { log.info('e' + index); }"
    )
    writer.eval("var done = false; flushLog().then(function () { done = true; });")
    writer.pump()

    events = _events(writer)
    assert len(events) == 200
    assert events[0] == "e60"  # the oldest 60 were dropped
    assert events[-1] == "e259"


def test_clearing_leaves_nothing_queued_either(writer):
    writer.eval('log.info("a"); var done = false;')
    writer.eval("clearLog().then(flushLog).then(function () { done = true; });")
    writer.pump()

    assert evaluate(writer, "done") is True
    assert _events(writer) == []


@pytest.mark.parametrize(
    ("key", "typed", "expected"),
    [
        ("solveTimeoutSeconds", 9999, 900),  # pulled to the ceiling, not reset
        ("solveTimeoutSeconds", 1, 30),  # and to the floor
        ("panelWidth", 10000, 560),
        ("solveTimeoutSeconds", "nonsense", 240),  # not a number: fall back
    ],
)
def test_a_number_typed_out_of_range_is_pulled_into_it(context, key, typed, expected):
    """Someone typing 9999 into "30 to 900" means the maximum, not the default."""
    verdict = evaluate(context, f"clamp({json.dumps(key)}, {json.dumps(typed)})")

    assert verdict == {"ok": False, "value": expected}


def test_clamping_leaves_a_value_already_in_range_alone(context):
    assert evaluate(context, 'clamp("solveTimeoutSeconds", 120)') == {
        "ok": True,
        "value": 120,
    }
    # Only integers are clamped; everything else defers to the schema check.
    assert evaluate(context, 'clamp("logLevel", "chatty")') == {
        "ok": False,
        "value": "info",
    }
