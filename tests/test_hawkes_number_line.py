"""A solution set drawn on Hawkes' number line.

Live, on 2026-09-12, lesson 1.7 step 2: "graph the solution set" of a compound
inequality. Hawkes draws its QNumberLine -- a `role="application"` container
holding `svg#svg_numberline`, tick labels, and one button per interval shape --
and no answer box. The add-on only ever looked for the Cartesian `#QGraph`, so
the question fell through to the field sweep and the panel said
`no-focused-answer-field`.

Facet already solves the set exactly. These hold the three things added around
it: recognising the surface, turning the set into a plan the line can show, and
writing that plan through QNumberLine's own `data` property with the page's own
reading of it as the proof.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ethnos.hawkes_graph import NumberLinePlan, number_line_plan
from ethnos.hawkes_host import handle
from ethnos.hawkes_protocol import GraphContext
from facet_loopback import facet, reasoning
from test_hawkes_answer_publication import QUESTION_A
from test_hawkes_insertion_ownership import page  # noqa: F401

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

ROOT = Path(__file__).resolve().parents[1]
EDITOR = ROOT / "extension" / "content" / "hawkes-editor.js"
GRAPH = ROOT / "extension" / "common" / "graph-actions.js"

ALL_SHAPES = ["open", "closed", "open-closed", "closed-open"]
CONTEXT = {
    "family": "numberline",
    "bounds": [-10.0, 10.0],
    "snap": [1.0],
    "controls": "interval-buttons",
    "intervals": ALL_SHAPES,
    # QNumberLine's own default, where a question states no `maxplots`.
    "count": 3,
}


def plan(left, left_closed, right, right_closed):
    return union((left, left_closed, right, right_closed))


def union(*intervals):
    """A plan of one or more intervals, each `(left, closed, right, closed)`."""
    return {
        "kind": "numberline",
        "intervals": [
            {
                "left": {"value": left, "closed": left_closed},
                "right": {"value": right, "closed": right_closed},
            }
            for left, left_closed, right, right_closed in intervals
        ],
    }


# --- recognising the surface -------------------------------------------------


def inspect(*, line: bool = True, width: int = 600, fields: str = "[]"):
    """A page drawing Hawkes' number line the way its template really nests it.

    `#NumberLineContainer` is the template's, and is `role="application"`; the
    engine builds `#divBaseContainer` inside it with the same role, and the SVG
    inside that. One line, two application containers.
    """
    context = quickjs.Context()
    context.eval(f"""
      globalThis.HTMLIFrameElement = class {{}};
      globalThis.HTMLFrameElement = class {{}};
      globalThis.window = {{location: {{origin: 'https://learn.hawkeslearning.com'}}}};
      const box = {{width: {width}, height: 210}};
      const outer = {{
        id: 'UIT1NumberLineContainer',
        getBoundingClientRect: () => box,
        querySelector: s => s === 'svg#svg_numberline' && {str(line).lower()} ? svg : null,
      }};
      const surface = {{
        id: 'divBaseContainer',
        getBoundingClientRect: () => box,
        querySelector: s => s === 'svg#svg_numberline' && {str(line).lower()} ? svg : null,
      }};
      const svg = {{ closest: s => s === '[role="application"]' ? surface : null }};
      globalThis.document = {{
        activeElement: null,
        querySelectorAll: s => s === '[role="application"]' ? [outer, surface]
          : s === 'svg#svg_numberline' ? ({str(line).lower()} ? [svg] : [])
          : s.startsWith('#QGraph') ? [] : {fields},
      }};
    """)
    context.eval(EDITOR.read_text(encoding="utf-8"))
    return json.loads(context.eval("JSON.stringify(ethnosHawkes.inspectField())"))


def test_a_number_line_with_no_answer_box_is_the_answer_surface():
    assert inspect() == {
        "ready": True,
        "code": "graph-answer",
        "via": "number-line-surface",
        "fieldId": "divBaseContainer",
    }


def test_an_application_surface_that_is_not_a_number_line_is_not_claimed():
    assert inspect(line=False).get("code") != "graph-answer"


def test_a_number_line_the_page_is_not_drawing_is_not_claimed():
    assert inspect(width=0).get("code") != "graph-answer"


def test_a_number_line_beside_an_answer_box_leaves_the_box_the_answer():
    result = inspect(
        fields="[{id:'txtAns1_num', getBoundingClientRect:()=>({width:60,height:20}),"
        " disabled:false, readOnly:false, type:'text', value:''}]"
    )

    assert result.get("via") != "number-line-surface"


# --- the page's own number line, modelled on QNumberLine ---------------------

#: `data` reads and plots the answer exactly as QInitNumberLine's accessor
#: does: the setter parses `<qmath><qXbrac>a,b</qXbrac></qmath>` and plots the
#: interval snapped to a tick; the getter reports what is plotted, numbers
#: written as Hawkes writes them.
PAGE = """
var now = 0, timers = [];
var setTimeout = (fn, ms) => { timers.push({fn, at: now + ms}); return timers.length; };
var XMLSerializer = class { serializeToString(node) { return node.id + ':' + node.text; } };
var TICKS = TICK_LABELS;
var plotted = ANSWER;
var writes = [];
function snap(value) {
  if (/syminfinite/i.test(value)) return value.trim();
  const n = Number(value);
  return String(TICKS.map(Number).reduce((a, b) => Math.abs(b - n) < Math.abs(a - n) ? b : a));
}
var line = {
  disableNL: DISABLED,
  loadNumberLine() {},
  clearNumberLine() {},
};
Object.defineProperty(line, 'data', {
  get() { return plotted; },
  set(text) {
    writes.push(text);
    // `plotUserAnswer`: split on the union, plot each interval snapped to a
    // tick, and stop silently at the engine's own maximum, as QNLGlobal does.
    const pieces = String(text).replace(/<\\/?qmath>/g, '').split('<qspchar>symUnion</qspchar>')
      .map(piece => piece.match(/^<(q\\w+brac)>(.*),(.*)<\\/\\1>$/)).filter(Boolean)
      .slice(0, ENGINE_MAX);
    if (!pieces.length) return;
    plotted = '<qmath>' + pieces.map(m => '<' + m[1] + '>' + snap(m[2]) + ',' + snap(m[3]) + '</' + m[1] + '>')
      .join('<qspchar>symUnion</qspchar>') + '</qmath>';
  },
});
var mode = {
  strUITemplateContainer: 'UIT1',
  objNumberLine: line,
  controlsJSON: MAXPLOTS === null ? {numline: {plotdata: {}}}
    : {numline: {plotdata: {maxplots: () => String(MAXPLOTS)}}},
  setActiveMode() { window.objActiveMode = this; },
  getUserAnswer() { this.setActiveMode(); return this.objNumberLine.data; },
  setUserAnswer(text) { this.setActiveMode(); this.objNumberLine.data = text; },
  isEmpty() { this.setActiveMode(); return this.objNumberLine.data === ''; },
};
var buttons = Object.fromEntries(BUTTONS.map(id => [id, {id}]));
var ticks = TICKS.map(label => ({getAttribute: n => n === 'label' ? label : null}));
var holder = { contains: node => Object.values(buttons).includes(node) };
var svg = { closest: s => s === '[role="application"]' ? surface : null };
var surface = {
  isConnected: true,
  parentElement: holder,
  contains: () => false,
  getBoundingClientRect: () => ({width: 600, height: 210}),
  querySelector: s => s === 'svg#svg_numberline' ? svg : (s === 'span.clsMath[label]' ? ticks[0] : null),
  querySelectorAll: s => s === 'span.clsMath[label]' ? ticks : [],
};
// The template's own container, which the engine's surface sits inside, and
// which is an application container too.
var container = {
  id: 'UIT1NumberLineContainer',
  isConnected: true,
  contains: node => node === surface,
  getBoundingClientRect: () => ({width: 600, height: 210}),
  querySelector: s => s === 'svg#svg_numberline' ? svg : null,
};
var questionNodes = Object.fromEntries(['questionDescription', 'questionString', 'partInformation']
  .map(id => [id, {id, text: 'q', isConnected: true}]));
var window = {
  location: {origin: 'https://learn.hawkeslearning.com'},
  // The line is not in the control collection; the template keeps it on the mode.
  quant_wp_UI: {controlsCollection: []},
  objActiveMode: mode,
};
var document = {
  getElementById: id => buttons[id] ?? questionNodes[id]
    ?? (id === container.id ? container : null),
  querySelectorAll: s => s === '[role="application"]' ? [container, surface]
    : s === 'svg#svg_numberline' ? [svg] : [],
};
"""


def number_line(
    *,
    buttons=("BOO", "BCC", "BOC", "BCO", "NLClear"),
    ticks=tuple(str(n) for n in range(-10, 11)),
    answer="",
    disabled="undefined",
    maxplots=None,
    engine_max=3,
):
    context = quickjs.Context()
    context.eval(
        PAGE.replace("TICK_LABELS", json.dumps(list(ticks)))
        .replace("ANSWER", json.dumps(answer))
        .replace("DISABLED", disabled)
        .replace("BUTTONS", json.dumps(list(buttons)))
        .replace("MAXPLOTS", json.dumps(maxplots))
        .replace("ENGINE_MAX", str(engine_max))
    )
    source = re.sub(r"^export ", "", GRAPH.read_text(encoding="utf-8"), flags=re.M)
    context.eval(source)
    return context


def run(context, offered=None):
    context.eval(
        "var done = null; Promise.resolve(graphOperation("
        + json.dumps(offered)
        + ")).then(r => { done = r; }, e => { done = {ok: false, code: String(e)}; });"
    )
    for _ in range(200):
        while context.execute_pending_job():
            pass
        if context.eval("done !== null"):
            break
        if not context.eval("timers.length"):
            break
        context.eval(
            "timers.sort((a,b) => a.at-b.at); var t = timers.shift();"
            " now = Math.max(now, t.at); t.fn();"
        )
    return json.loads(context.eval("JSON.stringify(done)"))


def test_the_probe_describes_the_line_from_the_page_itself():
    described = run(number_line())

    assert described["ok"] is True
    assert described["kind"] == "graph"
    assert described["context"] == CONTEXT
    assert described["snapshot"]["answer"] == ""
    # The context crosses to the host as it is, and the host accepts it.
    GraphContext.model_validate(described["context"])


def test_circled_buttons_publish_the_same_shapes_as_braces():
    described = run(number_line(buttons=("COO", "CCC")))

    assert described["context"]["intervals"] == ["open", "closed"]


def test_a_page_without_the_model_is_refused_with_what_it_does_hold():
    context = number_line()
    context.eval("mode.objNumberLine = undefined;")

    refused = run(context)

    assert refused["code"] == "graph-numberline-model-missing"
    assert refused["found"]["numberLine"] is False
    assert refused["found"]["activeMode"] == "object"


def test_a_line_owned_by_some_other_template_is_not_this_ones():
    context = number_line()
    context.eval("mode.strUITemplateContainer = 'UIT2';")

    assert run(context)["code"] == "graph-numberline-model-elsewhere"


def test_a_disabled_line_is_not_described_as_answerable():
    assert run(number_line(disabled="true"))["code"] == "graph-numberline-disabled"


@pytest.mark.parametrize(
    ("offered_plan", "written"),
    [
        (plan("-6", False, "7", True), "<qmath><qpsbrac>-6,7</qpsbrac></qmath>"),
        (plan("-6", True, "7", False), "<qmath><qspbrac>-6,7</qspbrac></qmath>"),
        (plan("-6", True, "7", True), "<qmath><qsbrac>-6,7</qsbrac></qmath>"),
        (plan("-6", False, "7", False), "<qmath><qpbrac>-6,7</qpbrac></qmath>"),
        (
            plan("-inf", False, "3", True),
            "<qmath><qpsbrac>-<qspchar>symInfinite</qspchar>,3</qpsbrac></qmath>",
        ),
        (
            plan("2", True, "inf", False),
            "<qmath><qspbrac>2,<qspchar>symInfinite</qspchar></qspbrac></qmath>",
        ),
    ],
)
def test_each_interval_is_written_through_the_pages_own_model(offered_plan, written):
    context = number_line()
    described = run(context)

    result = run(context, {"plan": offered_plan, "snapshot": described["snapshot"]})

    assert result["ok"] is True, result
    assert result["code"] == "numberline-verified"
    assert json.loads(context.eval("JSON.stringify(writes)")) == [written]
    # Still what the page reports, after it has had time to settle, and no
    # longer empty by the page's own check.
    assert context.eval("mode.getUserAnswer()") == written
    assert context.eval("mode.isEmpty()") is False


def test_a_shape_the_line_offers_no_button_for_is_not_written():
    context = number_line(buttons=("BOO", "BCC"))
    described = run(context)

    result = run(
        context,
        {"plan": plan("-6", False, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["code"] == "graph-numberline-shape-unoffered"
    assert context.eval("writes.length") == 0


def test_an_end_between_ticks_is_not_written():
    context = number_line()
    described = run(context)

    result = run(
        context,
        {"plan": plan("-6.5", False, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["code"] == "graph-plan-off-grid"
    assert context.eval("writes.length") == 0


def test_somebody_elses_interval_on_the_line_is_never_replaced():
    existing = "<qmath><qpbrac>1,2</qpbrac></qmath>"
    context = number_line(answer=existing)
    described = run(context)

    result = run(
        context,
        {"plan": plan("-6", False, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["code"] == "graph-numberline-not-empty"
    assert context.eval("mode.getUserAnswer()") == existing


def test_a_line_that_changed_since_it_was_described_is_not_written():
    context = number_line()
    described = run(context)
    context.eval("questionNodes.questionString.text = 'another question';")

    result = run(
        context,
        {"plan": plan("-6", False, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["code"] == "graph-target-stale"
    assert context.eval("writes.length") == 0


def test_a_closed_infinite_end_is_an_invalid_plan():
    context = number_line()
    described = run(context)

    result = run(
        context,
        {"plan": plan("-inf", True, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["code"] == "graph-plan-invalid"


def test_a_page_that_plots_something_else_is_caught_and_says_so():
    """The proof is the page's reading, not the assignment."""
    context = number_line()
    described = run(context)
    context.eval("TICKS = ['-10', '0', '10'];")

    result = run(
        context,
        {"plan": plan("-6", False, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["ok"] is False
    assert result["code"] == "graph-numberline-not-settled"
    assert result["leftBehind"] is True


def test_a_page_that_undoes_the_interval_while_settling_is_caught():
    context = number_line()
    described = run(context)
    context.eval(
        "var clearLater = () => setTimeout(() => { plotted = ''; }, 250); clearLater();"
    )

    result = run(
        context,
        {"plan": plan("-6", False, "7", True), "snapshot": described["snapshot"]},
    )

    assert result["code"] == "graph-numberline-not-settled"


def test_the_line_states_how_many_intervals_it_takes():
    assert run(number_line())["context"]["count"] == 3
    described = run(number_line(maxplots=2, engine_max=2))
    assert described["context"]["count"] == 2
    assert described["probe"]["maxIntervalsStated"] is True


@pytest.mark.parametrize(
    ("offered_plan", "written"),
    [
        (
            union(("-inf", False, "1", False), ("4", False, "inf", False)),
            "<qmath><qpbrac>-<qspchar>symInfinite</qspchar>,1</qpbrac>"
            "<qspchar>symUnion</qspchar>"
            "<qpbrac>4,<qspchar>symInfinite</qspchar></qpbrac></qmath>",
        ),
        (
            union(("-inf", False, "-4", True), ("-2", True, "inf", False)),
            "<qmath><qpsbrac>-<qspchar>symInfinite</qspchar>,-4</qpsbrac>"
            "<qspchar>symUnion</qspchar>"
            "<qspbrac>-2,<qspchar>symInfinite</qspchar></qspbrac></qmath>",
        ),
        (
            union(("-inf", False, "1", False), ("1", False, "inf", False)),
            "<qmath><qpbrac>-<qspchar>symInfinite</qspchar>,1</qpbrac>"
            "<qspchar>symUnion</qspchar>"
            "<qpbrac>1,<qspchar>symInfinite</qspchar></qpbrac></qmath>",
        ),
        (
            union(
                ("-5", False, "-2", False),
                ("2", False, "5", False),
                ("7", True, "9", True),
            ),
            "<qmath><qpbrac>-5,-2</qpbrac><qspchar>symUnion</qspchar><qpbrac>2,5</qpbrac>"
            "<qspchar>symUnion</qspchar><qsbrac>7,9</qsbrac></qmath>",
        ),
    ],
)
def test_a_union_is_written_as_hawkes_writes_one(offered_plan, written):
    context = number_line()
    described = run(context)

    result = run(context, {"plan": offered_plan, "snapshot": described["snapshot"]})

    assert result["ok"] is True, result
    assert result["intervals"] == len(offered_plan["intervals"])
    assert json.loads(context.eval("JSON.stringify(writes)")) == [written]
    assert context.eval("mode.getUserAnswer()") == written


def test_more_intervals_than_the_line_takes_are_never_written():
    context = number_line(maxplots=2, engine_max=2)
    described = run(context)
    three = union(
        ("-5", False, "-2", False), ("2", False, "5", False), ("7", True, "9", True)
    )

    result = run(context, {"plan": three, "snapshot": described["snapshot"]})

    assert result["code"] == "graph-numberline-too-many-intervals"
    assert context.eval("writes.length") == 0


def test_an_engine_that_plots_fewer_than_it_said_is_caught():
    """The page's own reading decides, even against its own stated maximum."""
    context = number_line(maxplots=3, engine_max=1)
    described = run(context)

    result = run(
        context,
        {
            "plan": union(("-inf", False, "1", False), ("4", False, "inf", False)),
            "snapshot": described["snapshot"],
        },
    )

    assert result["code"] == "graph-numberline-not-settled"
    assert result["leftBehind"] is True


@pytest.mark.parametrize(
    "offered_plan",
    [
        union(("4", False, "inf", False), ("-inf", False, "1", False)),
        union(("-inf", False, "1", True), ("1", True, "inf", False)),
        union(("-5", False, "2", False), ("1", False, "5", False)),
    ],
)
def test_intervals_out_of_order_or_overlapping_are_not_written(offered_plan):
    context = number_line()
    described = run(context)

    result = run(context, {"plan": offered_plan, "snapshot": described["snapshot"]})

    assert result["code"] == "graph-plan-invalid"
    assert context.eval("writes.length") == 0


# --- the host: the set becomes a plan the line can show ----------------------


def line_context(**changes):
    return GraphContext.model_validate({**CONTEXT, **changes})


@pytest.mark.parametrize(
    ("solution_set", "expected"),
    [
        ("(-6,7]", plan("-6", False, "7", True)),
        ("[-6,7)", plan("-6", True, "7", False)),
        ("[-6,7]", plan("-6", True, "7", True)),
        ("(-6,7)", plan("-6", False, "7", False)),
        ("(-∞,3]", plan("-inf", False, "3", True)),
        ("[2,∞)", plan("2", True, "inf", False)),
        ("(-∞,∞)", plan("-inf", False, "inf", False)),
    ],
)
def test_each_exact_interval_becomes_its_plan(solution_set, expected):
    assert number_line_plan(solution_set, line_context()).model_dump() == expected


@pytest.mark.parametrize(
    ("solution_set", "expected"),
    [
        (
            "(-∞,1)∪(4,∞)",
            union(("-inf", False, "1", False), ("4", False, "inf", False)),
        ),
        (
            "(-∞,-4]∪[-2,∞)",
            union(("-inf", False, "-4", True), ("-2", True, "inf", False)),
        ),
        (
            "(-∞,1)∪(1,∞)",
            union(("-inf", False, "1", False), ("1", False, "inf", False)),
        ),
        (
            "(-5,-2)∪(2,5)",
            union(("-5", False, "-2", False), ("2", False, "5", False)),
        ),
    ],
)
def test_a_union_becomes_one_interval_per_piece(solution_set, expected):
    assert number_line_plan(solution_set, line_context()).model_dump() == expected


def test_a_half_tick_end_is_placed_where_the_line_steps_by_halves():
    made = number_line_plan("(-2.5,1/2]", line_context(snap=[0.5]))

    assert made.intervals[0].left.value == "-2.5"
    assert made.intervals[0].right.value == "0.5"


@pytest.mark.parametrize(
    ("solution_set", "context", "reason"),
    [
        ("(-6,7/2]", {}, "not one of the number line's ticks"),
        ("(-6,1/3]", {"snap": [0.5]}, "not one of the number line's ticks"),
        ("(-12,7]", {}, "off the number line"),
        ("(-6,7]", {"intervals": ["open", "closed"]}, "publishes no open-closed"),
        ("∅", {}, "empty set"),
        ("(-∞,-3)∪(3,∞)", {"count": 1}, "at most 1 interval"),
        ("(-∞,1)∪(2,3)∪(4,5)∪(6,7)", {}, "at most 3 intervals"),
        ("(4,∞)∪(-∞,1)", {}, "not in order"),
        ("(-∞,1]∪[1,∞)", {}, "overlap"),
        ("(-∞,1)∪(4,∞]", {}, "never included"),
        ("[-∞,3)", {}, "never included"),
        ("(7,-6)", {}, "not in order"),
    ],
)
def test_what_the_line_cannot_show_exactly_is_refused(solution_set, context, reason):
    with pytest.raises(ValueError, match=reason):
        number_line_plan(solution_set, line_context(**context))


@pytest.mark.parametrize(
    "change",
    [
        {"bounds": [-10.0, 10.0, -10.0, 10.0]},
        {"snap": [1.0, 1.0]},
        {"intervals": []},
        {"intervals": ["open", "open"]},
        {"controls": "draggable-points"},
        {"bounds": [10.0, -10.0]},
        {"count": 0},
        {"count": 13},
    ],
)
def test_a_number_line_context_states_its_own_geometry(change):
    with pytest.raises(ValueError):
        line_context(**change)


def test_a_plane_cannot_borrow_a_number_lines_intervals():
    with pytest.raises(ValueError):
        GraphContext.model_validate(
            {
                "family": "points",
                "bounds": [-10.0, 10.0, -10.0, 10.0],
                "snap": [1.0, 1.0],
                "controls": "draggable-points",
                "count": 2,
                "intervals": ["open"],
            }
        )


NUMBER_LINE_MATH = (
    "<math><mo>−</mo><mn>24</mn><mo>&lt;</mo><mn>3</mn><mi>y</mi><mo>−</mo>"
    "<mn>6</mn><mo>≤</mo><mn>15</mn></math>"
)


def solve_on_line(monkeypatch, prompt, math=NUMBER_LINE_MATH, **adapters):
    loopback = facet(monkeypatch, **adapters)
    result = handle(
        {
            "operation": "solve_hawkes_problem",
            "request_id": "number-line",
            "origin": "https://learn.hawkeslearning.com",
            "problem": {
                "prompt_text": prompt,
                "mathml": [math],
                "answer_shape": {"kind": "graph", "graph": CONTEXT},
            },
        }
    )
    return result, loopback


def test_the_host_draws_facets_exact_solution_set(monkeypatch):
    result, loopback = solve_on_line(
        monkeypatch,
        "Consider the following compound inequality. Graph the solution set.",
    )

    assert result.status == "ready"
    assert loopback.prompts == []
    assert result.answer.graph_plan.model_dump() == plan("-6", False, "7", True)
    assert result.answer.display_text == "(-6,7]"
    assert result.certainty.answered_by == "exact"
    assert result.certainty.method == "SymPy exact linear inequality"
    # Facet was asked a question, never told there is a number line.
    assert "graph" not in loopback.problems[0]


def test_the_host_draws_an_exact_union(monkeypatch):
    result, loopback = solve_on_line(
        monkeypatch,
        "Graph the solution set of the absolute value inequality.",
        math="<math><mo>|</mo><mn>2</mn><mi>x</mi><mo>−</mo><mn>5</mn><mo>|</mo>"
        "<mo>&gt;</mo><mn>3</mn></math>",
    )

    assert result.status == "ready", result
    assert loopback.prompts == []
    assert result.answer.graph_plan.model_dump() == union(
        ("-inf", False, "1", False), ("4", False, "inf", False)
    )
    assert result.answer.display_text == "(-∞,1)∪(4,∞)"
    assert result.certainty.answered_by == "exact"


def test_a_reasoned_solution_set_is_never_drawn(monkeypatch):
    result, loopback = solve_on_line(
        monkeypatch,
        "Graph the solution set of the inequality.",
        math="<math><msup><mi>x</mi><mn>2</mn></msup><mo>&lt;</mo><mn>4</mn></math>",
        **reasoning("FINAL ANSWER: (-2,2)"),
    )

    assert loopback.prompts, "the exact stage should have declined a quadratic"
    assert result.status != "ready"
    assert "exactly solved" in result.message


def test_the_plan_crosses_the_wire_as_a_number_line_plan():
    NumberLinePlan.model_validate(plan("-6", False, "7", True))
    with pytest.raises(ValueError):
        NumberLinePlan.model_validate(
            {**plan("-6", False, "7", True), "click": "Submit"}
        )


# --- the event page takes the plan for this page's line, and no other ---------


def accept(page, family):  # noqa: F811
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "divBaseContainer",
          editor: {
            json.dumps(
                {
                    "ok": True,
                    "kind": "graph",
                    "context": {**CONTEXT, "family": family},
                    "snapshot": {"answer": ""},
                }
            )
        },
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        acceptReply({
            json.dumps(
                {
                    "status": "ready",
                    "problem_text": "Graph the solution set.",
                    "answer": {
                        "graph_plan": plan("-6", False, "7", True),
                        "display_text": "(-6,7]",
                    },
                    "certainty": {
                        "source": "Facet Exact",
                        "answered_by": "exact",
                        "facet_invoked": True,
                        "insertable": True,
                    },
                }
            )
        });
        """
    )
    page.pump()


def test_the_event_page_accepts_a_number_line_plan_for_its_number_line(page):  # noqa: F811
    accept(page, "numberline")

    assert page.json("state.phase") == "solved"
    assert page.json("state.graphPlan") == plan("-6", False, "7", True)
    assert page.json("state.displayText") == "(-6,7]"


def test_a_number_line_plan_for_some_other_graph_is_refused(page):  # noqa: F811
    accept(page, "points")

    assert page.json("state.phase") == "failed"
