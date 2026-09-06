"""Which code is Firefox running?

Twice in one week a fix was diagnosed as not working when it had simply never
been loaded: `about:debugging` reports nothing about a temporary add-on's
contents, its manifest version does not move between edits, and Reload re-reads
whichever directory was first selected rather than the one being edited.

The marker answers it from inside. `common/build-marker.js` folds the source
text of what Firefox parsed; `scripts/observe_live_hawkes.py` folds the same
symbols off disk. The two must agree exactly or the comparison is worthless, so
they are run against each other here.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"
MARKER_JS = EXTENSION / "common" / "build-marker.js"
BACKGROUND = EXTENSION / "background.js"

SPEC = importlib.util.spec_from_file_location(
    "observe_live_hawkes", PROJECT_ROOT / "scripts" / "observe_live_hawkes.py"
)
assert SPEC and SPEC.loader
OBS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(OBS)

IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)


@pytest.fixture
def marker_context():
    """The real module, with a real SHA-256 behind `crypto.subtle`."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.add_callable(
        "__sha256", lambda text: json.dumps(list(hashlib.sha256(text.encode()).digest()))
    )
    context.eval(
        """
        globalThis.TextEncoder = function () { this.encode = (text) => text; };
        globalThis.crypto = { subtle: { digest: (_alg, text) =>
          Promise.resolve(new Uint8Array(JSON.parse(__sha256(text)))) } };
        """
    )
    source = MARKER_JS.read_text(encoding="utf-8")
    context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))
    return context


def fold_in_js(context, literal: str) -> dict:
    context.eval(
        f"var folded; foldSources(collectSources({{{literal}}})).then(v => {{ folded = v; }});"
    )
    for _ in range(500):
        if not context.execute_pending_job():
            break
    return json.loads(context.eval("JSON.stringify(folded)"))


# --- the two implementations agree ----------------------------------------


def test_the_browser_and_the_observer_fold_to_the_same_marker(marker_context):
    """The one property the whole comparison rests on."""
    literal = (
        'alpha: function alpha(a) { return a + 1; }, '
        'beta: { one: 1, two: "x" }'
    )
    in_browser = fold_in_js(marker_context, literal)

    entries = json.loads(
        marker_context.eval(f"JSON.stringify(collectSources({{{literal}}}))")
    )
    in_python = OBS.fold([(name, text) for name, text in entries])

    assert in_browser["marker"] == in_python["marker"]
    assert in_browser["symbols"] == in_python["symbols"] == 3
    assert in_browser["chars"] == in_python["chars"]


def test_changing_one_character_of_one_function_changes_the_marker(marker_context):
    """Otherwise it would not answer the question it exists for."""
    before = fold_in_js(marker_context, "solve: function solve() { return 1; }")
    after = fold_in_js(marker_context, "solve: function solve() { return 2; }")

    assert before["marker"] != after["marker"]
    assert len(before["marker"]) == 12


def test_the_order_things_are_listed_in_does_not_change_the_marker(marker_context):
    one = fold_in_js(marker_context, "a: function a() {}, b: function b() {}")
    other = fold_in_js(marker_context, "b: function b() {}, a: function a() {}")

    assert one["marker"] == other["marker"]


def test_a_data_export_counts_as_code(marker_context):
    """A frozen settings schema stringifies to `[object Object]`; serializing it
    instead is what makes a changed character set change the marker."""
    before = fold_in_js(marker_context, 'SETTINGS: { allowed: "0123456789" }')
    after = fold_in_js(marker_context, 'SETTINGS: { allowed: "0123456789-" }')

    assert before["marker"] != after["marker"]


def test_a_module_namespace_is_expanded_one_entry_per_export(marker_context):
    entries = json.loads(
        marker_context.eval(
            'JSON.stringify(collectSources({"common/log.js": '
            "{ warn: function warn() {}, RING: 200 }}))"
        )
    )

    assert [name for name, _ in entries] == ["common/log.js#RING", "common/log.js#warn"]


# --- the observer reads the running definition, not a copy of it ----------


def test_the_observer_takes_the_marked_list_out_of_background_js():
    """A second copy of that list here would be one more thing to keep in step,
    and its failure -- a marker that never matches -- looks exactly like the
    stale build it exists to detect."""
    parts = dict(OBS._marked_parts(BACKGROUND.read_text(encoding="utf-8")))

    assert "common/log.js#log" in parts
    assert "background.js#solve" in parts
    assert parts["background.js#solve"] == "solve"


def test_every_name_the_event_page_imports_is_covered_by_the_marker():
    """The list cannot fall behind the imports it mirrors."""
    background = BACKGROUND.read_text(encoding="utf-8")
    covered = {name for name, _ in OBS._marked_parts(background)}
    imported: set[str] = set()
    for statement in re.findall(r'import\s*\{([^}]*)\}\s*from\s*"([^"]+)"', background):
        names, module = statement
        for name in names.split(","):
            name = name.strip().split(" as ")[-1].strip()
            if name:
                imported.add(f"{module.lstrip('/')}#{name}")

    assert imported - covered == set(), sorted(imported - covered)


def test_the_named_background_functions_all_still_exist():
    """A renamed function would otherwise silently drop out of the marker."""
    background = BACKGROUND.read_text(encoding="utf-8")
    missing = [
        expression
        for name, expression in OBS._marked_parts(background)
        if name.startswith("background.js")
        and OBS._function_source(background, expression.strip()) is None
    ]

    assert missing == []


def test_a_default_value_in_the_parameter_list_does_not_end_the_function():
    """`askEthnos(operation, extra = {}, ...)` opens and closes a brace before
    its body starts. Matching from the first brace found returned forty-six
    characters of a two-thousand-character function -- silently, as a marker
    that simply never matched the browser's."""
    sample = (
        "async function target(operation, extra = {}, signal) {\n"
        "  return { operation, extra, signal };\n"
        "}\n"
    )
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(sample)

    assert OBS._function_source(sample, "target") == context.eval("String(target)")


def test_the_extracted_source_is_exactly_what_the_browser_would_stringify():
    """`_function_source` stands in for `Function.prototype.toString()`, so it
    has to reproduce it character for character -- braces inside strings and
    comments included."""
    sample = (
        'const before = 1;\n'
        'async function target(a = "}") {\n'
        '  // a } in a comment\n'
        '  /* and a } in a block */\n'
        '  return `${a}}`;\n'
        '}\n'
        'const after = 2;\n'
    )
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(sample)

    assert OBS._function_source(sample, "target") == context.eval("String(target)")


def test_the_working_tree_marker_is_computable_from_this_checkout():
    """If this cannot be computed, the observer can never say more than
    "unknown", and the tool loses the finding it was written for."""
    computed = OBS.working_tree_marker()

    assert computed["computed"] is True, computed.get("why")
    assert computed["unresolved"] == []
    assert len(computed["marker"]) == 12
    assert computed["symbols"] > 40


def test_a_marker_that_does_not_match_the_tree_is_reported_as_stale_code():
    verdict = OBS.code_verdict(
        {"marker": "0123456789ab", "symbols": 55},
        {"computed": True, "marker": "ffffffffffff", "symbols": 55},
        {"t": 10**13},
        {"temporary": True, "version": "0.46.0"},
    )

    assert verdict["verdict"] == "running-other-code"
    assert "Reload" in verdict["why"]


def test_a_build_from_before_this_tooling_says_so_rather_than_guessing():
    verdict = OBS.code_verdict(
        {}, {"computed": True, "marker": "ffffffffffff"}, {"t": 10**13}, {"temporary": True}
    )

    assert verdict["verdict"] == "unmarked-build"


def test_a_matching_marker_is_still_qualified_when_the_tree_moved_on(tmp_path, monkeypatch):
    """The case the marker alone cannot catch: files edited after the add-on
    was loaded are files whose current content Firefox has not read."""
    tree = tmp_path / "extension"
    (tree / "common").mkdir(parents=True)
    (tree / "background.js").write_text("// edited after the load\n")
    monkeypatch.setattr(OBS, "EXTENSION_DIR", tree)
    monkeypatch.setattr(OBS, "PROJECT_ROOT", tmp_path)

    verdict = OBS.code_verdict(
        {"marker": "abcabcabcabc"},
        {"computed": True, "marker": "abcabcabcabc"},
        {"t": 1000},  # the event page loaded long before the file was written
        {"temporary": True},
    )

    assert verdict["verdict"] == "running-this-tree-but-edited-since"
    assert verdict["changed_since_event_page_loaded"] == ["extension/background.js"]


def test_the_marker_says_what_it_does_not_cover():
    """The panel, the settings page and the content scripts load elsewhere. A
    marker implying more than it proves would be worse than none."""
    verdict = OBS.code_verdict({}, {"computed": False}, None, {})

    assert "content scripts" in verdict["covers"]
    assert "settings page" in verdict["covers"]


# --- the two ends of the comparison, on the real add-on -------------------


def test_the_event_page_and_the_observer_mark_this_tree_identically():
    """The end-to-end proof, on the actual add-on rather than on a sample.

    The event page folds `markedCode()` from the code it loaded; the observer
    folds the same symbols off disk. If these ever disagree, every live
    observation reports `running-other-code` against a browser that is running
    exactly this tree -- the false alarm that would send the next agent hunting
    a stale build that is not there.
    """
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    harness = importlib.util.spec_from_file_location(
        "ownership_harness", PROJECT_ROOT / "tests" / "test_hawkes_insertion_ownership.py"
    )
    module = importlib.util.module_from_spec(harness)
    harness.loader.exec_module(module)

    context = quickjs.Context()
    context.add_callable(
        "__sha256", lambda text: json.dumps(list(hashlib.sha256(text.encode()).digest()))
    )
    context.eval(module.HARNESS)
    context.eval("__H.sessionStored = {};")
    context.eval(
        """
        globalThis.TextEncoder = function () { this.encode = (text) => text; };
        globalThis.crypto = Object.assign(globalThis.crypto || {}, { subtle: {
          digest: (_alg, text) => Promise.resolve(new Uint8Array(JSON.parse(__sha256(text)))) } });
        """
    )
    context.eval(
        "\n".join(
            IMPORT_LINE.sub("", (EXTENSION / name).read_text(encoding="utf-8")).replace(
                "export ", ""
            )
            for name in module.MODULES
        )
    )
    context.eval("var out; foldSources(collectSources(markedCode())).then(v => { out = v; });")
    for _ in range(5000):
        if not context.execute_pending_job():
            break
    in_browser = json.loads(context.eval("JSON.stringify(out)"))
    on_disk = OBS.working_tree_marker()

    assert in_browser["symbols"] == on_disk["symbols"]
    assert in_browser["chars"] == on_disk["chars"]
    assert in_browser["marker"] == on_disk["marker"]
