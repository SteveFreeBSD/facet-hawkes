"""An executable gate between what Facet emits and what this repository enters.

Facet owns what an answer is. Hawkes Assistant owns how it is entered. Every
recurring defect has been in neither half but in a *composition* neither half
named: `(1,-4)` was enterable and `17/2` was enterable and `(17/2,-1/2)` was
not, found live on coursework after Facet had answered it correctly for a day.

`docs/ANSWER_CAPABILITIES.md` made the map readable. It could not make it
binding, because it was prose about four coarse `form` values, and a new solver
does not usually add a form -- it adds a *notation* under one that already has a
row. `docs/answer-capabilities.json` is the authority instead, and these tests
run it: every declared composition is put through the real solvers, rendered by
the host's own rule, and handed to the real entry planner under QuickJS.

Building this found two defects in one afternoon. A two-value regression said
`form: "scalar"`; a fractional linear root crossed as `verbatim` LaTeX and the
keypad refused it on the backslash. Both are fixed in facet-runtime, and both
were invisible to every test on either side.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace

import pytest

from ethnos.answer_capabilities import (
    NOTATION_FEATURES,
    composition,
    compositions_of,
    load,
    notation_of,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON = PROJECT_ROOT / "extension" / "common"
IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)
CAPABILITIES_MD = PROJECT_ROOT / "docs" / "ANSWER_CAPABILITIES.md"
RUNTIME_ROOT = PROJECT_ROOT.parent / "facet-runtime"

#: Plan kinds are proposals rather than values: nothing is typed, so they have
#: no notation and no planner route to exercise.
PLAN_FORMS = ("parabola_plan", "point_plot_plan", "quadratic_regression")


@pytest.fixture(scope="module")
def authority():
    return load()


@pytest.fixture(scope="module")
def planner():
    """The shipped entry planner, in a real JS engine, with nothing stubbed."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    for name in ("config.js", "editor-rules.js", "editor-plan.js"):
        source = (COMMON / name).read_text(encoding="utf-8")
        context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))

    def call(name, *arguments):
        rendered = ", ".join(json.dumps(argument) for argument in arguments)
        return json.loads(context.eval(f"JSON.stringify({name}({rendered}))"))

    return call


def solve(probe):
    """Run one declared probe through the real exact router."""
    from facet_runtime.exact import solve_exact

    extras = {k: v for k, v in probe.items() if k not in ("instruction", "expressions")}
    return solve_exact(probe["instruction"], probe["expressions"], **extras)


def entered(solution):
    """What the host would hand the planner, and the family to read each under.

    Through `answer_payload`, which is the host's own single definition of it,
    rather than through `entry_for` alone. An equation is why: the host does
    not linearize `f(x)=-5x-3` as one expression -- that would insert implicit
    multiplication into a name -- it renders the value and composes the two.
    And the page decides which of the two is typed, so both are classified.
    """
    from ethnos.hawkes_host import answer_payload

    # A recorded emission arrives as plain data; a live solution arrives as the
    # runtime's own object. Both name the same two sides.
    relation = getattr(solution, "relation", None)
    payload = answer_payload(
        solution.display,
        solution.entry,
        solution.parts,
        solution.entry_mode,
        SimpleNamespace(**relation) if isinstance(relation, dict) else relation,
    )
    if payload.parts:
        return [(solution.form, value) for value in payload.parts]
    if payload.relation is not None:
        # Two strings, two families. The whole equation is the `relation` this
        # answer is; its right side alone, which is what a page printing
        # `f(x) =` takes, is entered exactly as a scalar of the same notation
        # is -- same planner route, same rows, and those rows already exist.
        return [
            (solution.form, payload.keyboard_entry),
            ("scalar", payload.relation.keyboard_entry),
        ]
    return [(solution.form, payload.keyboard_entry)]


@pytest.fixture(scope="module")
def runtime_emissions(tmp_path_factory):
    """Exact answers reached by facet-runtime's own solver test corpus.

    The runtime tests are the maintained probes for its emitters. Observing
    their real ``ExactSolution`` objects keeps this closure source independent
    of Hawkes lessons and avoids copying their mathematical cases here.
    """
    record = tmp_path_factory.mktemp("runtime-emissions") / "answers.json"
    environment = os.environ.copy()
    environment["FACET_EXACT_EMISSION_RECORD"] = str(record)
    plugin_path = str(PROJECT_ROOT / "tests")
    old_path = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = os.pathsep.join(
        part for part in (plugin_path, old_path) if part
    )
    finished = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(RUNTIME_ROOT / "tests"),
            "--rootdir",
            str(RUNTIME_ROOT),
            "-p",
            "runtime_emission_recorder",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert record.exists(), "facet-runtime's exact-emission recorder wrote no result"
    return json.loads(record.read_text(encoding="utf-8"))


# --- the authority is well formed ------------------------------------------


def test_the_form_set_matches_facets_closed_set(authority):
    """Growing `ANSWER_FORMS` is a protocol change, and this is where the
    consumer finds out about it."""
    from facet_runtime.exact import ANSWER_FORMS

    assert tuple(authority.forms) == ANSWER_FORMS


def test_every_entry_uses_a_declared_form_and_feature(authority):
    known = set(authority.forms) | set(authority.plan_kinds)
    for entry in authority.entries:
        assert entry.form in known, entry.id
        assert set(entry.notation) <= set(NOTATION_FEATURES), entry.id
        assert entry.editor in authority.editors, entry.id
        assert entry.status in ("supported", "unsupported"), entry.id


def test_every_entry_names_a_mechanism_that_exists(authority):
    """A row naming a function that was renamed away reads as coverage and is a
    dead pointer, which is worse than no row."""
    # The host is half of some mechanisms: a graph's plan is made there.
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            *(PROJECT_ROOT / "extension").rglob("*.js"),
            *(PROJECT_ROOT / "src" / "ethnos").glob("*.py"),
        ]
    )
    missing = [
        f"{entry.id}: {name}"
        for entry in authority.entries
        for name in entry.mechanism
        if not re.search(rf"\b{re.escape(name)}\b", sources)
    ]

    assert missing == []


# --- what Facet emits ------------------------------------------------------


def undeclared_compositions(authority, emissions, source_key):
    """Group undeclared emitted compositions by the probe that reached them."""
    undeclared = {}
    for emission in emissions:
        for key in {
            composition(form, notation_of(text))
            for form, text in entered(SimpleNamespace(**emission))
        }:
            if key not in authority.declared_compositions():
                undeclared.setdefault(key, []).append(emission[source_key])
    return undeclared


def test_every_probe_emits_the_composition_it_is_declared_under(authority):
    """The emitter half. A declared composition that no question produces is a
    claim about Facet that nothing checked."""
    wrong = []
    for entry in authority.entries:
        if entry.probe is None:
            continue
        solution, decline = solve(entry.probe)
        if solution is None:
            wrong.append(f"{entry.id}: declined -- {decline}")
            continue
        found = {
            composition(form, notation_of(text)) for form, text in entered(solution)
        }
        if entry.composition not in found:
            wrong.append(
                f"{entry.id}: declared {entry.composition}, emitted {sorted(found)}"
            )

    assert wrong == []


def test_every_composition_the_lesson_corpus_emits_is_declared(authority):
    """Keep the live-course closure beside the broader runtime closure.

    Thirty-seven real lesson questions, answered by the real router and
    classified on what the host would type. A composition arriving here that
    nothing has declared is exactly the state this whole page exists to end --
    an answer Facet is confident about that nothing has agreed to enter.
    """
    from facet_runtime.exact import solve_exact

    corpus = json.loads(
        (PROJECT_ROOT / "benchmarks" / "hawkes_lesson_coverage.json").read_text()
    )["cases"]
    undeclared = {}
    for case in corpus:
        solution, _ = solve_exact(case["prompt"], case["expressions"])
        if solution is None:
            continue
        for key in {
            composition(form, notation_of(text)) for form, text in entered(solution)
        }:
            if key not in authority.declared_compositions():
                undeclared.setdefault(key, []).append(case["id"])

    assert undeclared == {}, (
        f"undeclared compositions reached the consumer: {undeclared}. Add a row "
        "to docs/answer-capabilities.json saying how each is entered, or saying "
        "plainly that it is not."
    )


def test_every_composition_the_runtime_exact_tests_emit_is_declared(
    authority, runtime_emissions
):
    """Close over the runtime's emitter probes, not only Hawkes lessons.

    facet-runtime's own suite exercises exact branches and value variants that
    no current lesson-corpus question happens to reach. The recorder observes
    the real answer objects those tests construct; a new composition therefore
    has to be declared even when live-course coverage has not met it yet.
    """
    assert runtime_emissions, "facet-runtime's tests constructed no exact answers"
    undeclared = undeclared_compositions(authority, runtime_emissions, "test")

    assert undeclared == {}, (
        f"undeclared compositions reached the consumer: {undeclared}. Add a row "
        "to docs/answer-capabilities.json saying how each is entered, or saying "
        "plainly that it is not."
    )


def test_the_runtime_tests_reach_every_declared_interval_through_the_router(
    authority, runtime_emissions
):
    """The closure above sees only answers the router builds.

    The inequality family's tests held their rational and decimal ends at
    `solve_linear_inequality` -- one file said so, because a router answer with
    a rational end was a composition nothing here declared -- so none reached
    the recorder, the closure passed, and the router was meanwhile answering a
    live lesson 1.7 question `(-∞,-7/2)`. Every interval composition declared
    here has to be one those tests actually get from the router.
    """
    reached = {
        composition(form, notation_of(text))
        for emission in runtime_emissions
        for form, text in entered(SimpleNamespace(**emission))
    }
    declared = {
        entry.composition for entry in authority.entries if "interval" in entry.notation
    }

    assert sorted(declared - reached) == [], (
        "declared interval compositions no facet-runtime test reaches through "
        "solve_exact; a test holding an answer below the router is invisible here"
    )


def test_a_multi_value_answer_always_says_it_is_one(authority):
    """The invariant the regression defect broke: `parts` and `form` agree."""
    for entry in authority.entries:
        if entry.probe is None:
            continue
        solution, _ = solve(entry.probe)
        if solution is None or not solution.parts:
            continue
        assert solution.form == "parts", f"{entry.id} carries parts as {solution.form}"


# --- what Hawkes can enter -------------------------------------------------


@pytest.mark.parametrize(
    "entry_id", [e.id for e in load().supported() if e.form not in PLAN_FORMS]
)
def test_every_supported_composition_plans_against_its_own_editor(
    entry_id, authority, planner
):
    """The consumer half, and the claim that matters: "supported" means the
    shipped planner really produces steps for this value on this page."""
    entry = next(item for item in authority.entries if item.id == entry_id)
    editor = authority.editor_for(entry)

    if entry.form == "choice":
        verdict = planner("answerFitsEditor", entry.example, editor)
        assert verdict["code"] == "editor-option-answer"
        return
    # Nothing is typed into a graph. The value is turned into a plan against
    # the geometry the page's own graph reported, by the host's own rule.
    if editor["kind"] == "graph":
        from ethnos.hawkes_graph import number_line_plan
        from ethnos.hawkes_protocol import GraphContext

        context = GraphContext.model_validate(editor["context"])
        assert number_line_plan(entry.example, context).intervals, entry.id
        return
    # A multi-part answer is planned one part at a time, against the control
    # that part is typed into -- so that is how it is exercised here.
    result = planner("planEntry", entry.example, editor)

    assert result.get("ok") is True, (
        f"{entry.id} is declared supported but the planner refused "
        f"{entry.example!r}: {result.get('code')} {result.get('detail', '')!r}"
    )


@pytest.mark.parametrize("entry_id", [e.id for e in load().unsupported()])
def test_every_unsupported_composition_is_refused_by_the_code_it_declares(
    entry_id, authority, planner
):
    """ "Unsupported" is a finished state, and a finished state is testable.
    What is not finished is discovering it live."""
    entry = next(item for item in authority.entries if item.id == entry_id)
    editor = authority.editor_for(entry)

    if entry.refusal == "answer-invalid":
        result = planner("validateAnswer", entry.example)
        assert result.get("ok") is False
        assert result.get("code") == entry.refusal
        return
    result = planner("planEntry", entry.example, editor)

    assert result.get("ok") is False, f"{entry.id} is declared unsupported but planned"
    assert result.get("code") == entry.refusal


def test_a_probe_and_its_example_are_the_same_composition(authority):
    """The example is what the planner is driven with, so it has to be what the
    solver actually produces rather than a hand-written stand-in."""
    drifted = []
    for entry in authority.entries:
        if entry.probe is None or entry.form in PLAN_FORMS:
            continue
        solution, _ = solve(entry.probe)
        if solution is None:
            continue
        if composition(entry.form, notation_of(entry.example)) != entry.composition:
            drifted.append(f"{entry.id}: example is not its own composition")

    assert drifted == []


# --- the prose cannot drift from the authority -----------------------------


def test_the_markdown_names_every_declared_composition(authority):
    """`ANSWER_CAPABILITIES.md` stays the readable map, and a composition that
    is declared but unwritten is a map with a hole in it."""
    document = CAPABILITIES_MD.read_text(encoding="utf-8")

    missing = [entry.id for entry in authority.entries if entry.id not in document]
    assert missing == [], f"declared but absent from the readable map: {missing}"


def test_the_markdown_points_at_the_authority():
    document = CAPABILITIES_MD.read_text(encoding="utf-8")

    assert "answer-capabilities.json" in document
    assert "Facet owns what the answer is" in document


def test_compositions_of_reads_parts_one_at_a_time():
    """A multi-part answer is planned per part, so it presents one composition
    per part rather than an average of them."""
    assert compositions_of("parts", "", ["-3", "1/2"]) == {
        "parts/plain",
        "parts/fraction",
    }
    assert compositions_of("scalar", "sqrt(101)", []) == {"scalar/radical"}


# --- the two cases this page was written around ----------------------------


def test_the_ordered_pair_of_rationals_is_declared_supported(authority, planner):
    """The composition the live midpoint defect exposed, asserted by name.

    `(1,-4)` was enterable and `17/2` was enterable and `(17/2,-1/2)` was not,
    which is the whole argument for classifying compositions rather than forms.
    """
    entry = next(
        item
        for item in authority.entries
        if item.composition == "ordered-pair/fraction+group+comma"
    )

    assert entry.supported
    assert "planCommaList" in entry.mechanism
    assert entry.coverage["live"] == "yes"
    assert (
        planner("planEntry", entry.example, authority.editor_for(entry))["ok"] is True
    )


def test_a_decimal_is_entered_only_where_the_box_publishes_the_point(
    authority, planner
):
    """Making the exact form enterable must not read as making every decimal
    enterable -- and a box that publishes the point must not be declared as
    refusing one.

    Both were once one row, "decimal anything", unsupported because no observed
    box accepted a decimal point. The live plain boxes publish `[0-9.-]`, the
    planner types a decimal straight into one, and the exact discount family
    answers in cents. So the rows split on the one page fact that decides it,
    and each side is held to its own editor.
    """
    rows = [entry for entry in authority.entries if "decimal" in entry.notation]
    refused = next(entry for entry in rows if entry.id == "scalar-decimal")

    assert not refused.supported
    assert refused.refusal == "answer-has-rejected-characters"
    assert any(entry.supported for entry in rows)
    for entry in rows:
        editor = authority.editor_for(entry)
        publishes_point = planner(
            "accepts", editor["allowedCharacters"], ".", editor["kind"]
        )
        assert publishes_point is entry.supported, entry.id


@pytest.fixture(scope="module")
def routing():
    """The shipped transport policy, in a real JS engine, with nothing stubbed."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    source = (COMMON / "transport.js").read_text(encoding="utf-8")
    context.eval(IMPORT_LINE.sub("", source).replace("export ", ""))

    def call(expression):
        return json.loads(context.eval(f"JSON.stringify({expression})"))

    return call


def test_a_row_that_names_a_writer_names_the_one_its_page_is_routed_to(
    authority, routing
):
    """A writer the row's own page could never reach is a dead claim.

    `parts-plain` named `enterOwnedFields` against a dynamic integer box, and
    several dynamic boxes are routed to the keypad writer, `enterPlan`. The
    planner check above could not see that: planning is the same either way,
    and only the transport differs. So every supported row naming one of the
    transport table's writers is routed by `chooseTransport` as its page would
    be -- several of its editor for a multipart row, one otherwise -- and has
    to name the writer that comes back.
    """
    writers = set(routing("Object.values(TRANSPORTS).map((one) => one.writer)"))
    wrong = []
    for entry in authority.supported():
        named = writers & set(entry.mechanism)
        if not named:
            continue
        editor = {"ok": True, **authority.editor_for(entry)}
        page = (
            {"ok": True, "kind": "multi", "editors": [editor, editor]}
            if entry.form == "parts"
            else editor
        )
        routed = routing(f"chooseTransport({json.dumps(page)}, {{}})")
        if not routed.get("ok") or routed["writer"] not in named:
            wrong.append(f"{entry.id}: names {sorted(named)}, routed {routed}")

    assert wrong == []


def test_the_rendered_document_is_up_to_date():
    """The tables are data. Hand-maintained data beside a machine-readable copy
    of the same facts is the drift this gate exists to end, applied to itself."""
    import subprocess

    finished = subprocess.run(
        ["python3", str(PROJECT_ROOT / "scripts" / "render_answer_capabilities.py")],
        capture_output=True,
        text=True,
    )

    assert finished.returncode == 0, finished.stderr or finished.stdout
