"""A table-completion question with five blanks, which was answered as one box.

Lesson 2.1 completes a table of values for `x = y²`. The page draws five blank
cells in two row-headed DOM rows. Live, on 2026-09-07 (run
`rmtrgct2452e4`), the add-on reported:

    multiFieldEvidence  {"fields": 5, "fieldIds": [3, 6, 8, 10, 11]}
    editor-described    {"kind": "textbox", "editors": 0,
                         "collection": {"controls": 10, "usable": 10}}
    question-read       {"answerTable": "held-1-kept-0-header-1"}
    solved              {"answerLength": 1}

The model collection describes all ten value cells, not the five blanks, and
the old reader expected a header row above vertical records. These tests pin
the real row-headed shape and make the validated five blank positions, rather
than that ten-cell collection, define the request's cardinality.

These tests pin the shape the page actually publishes, from
`tests/fixtures/table-completion.html`, at every gate the count crosses: the
DOM sweep, the page's own editor model, the two readings being reconciled, the
shape sent to the host, and the wire the host answers on.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "table-completion.html"

#: The five blanks, in the order the page draws them: y for x=0, x for y=2√2,
#: y for x=64, y for x=25, and x for y=-√3. Taken from the fixture so the two
#: cannot drift.
FIELD_IDS = re.findall(r'<input[^>]*id="([^"]+)"', FIXTURE.read_text(encoding="utf-8"))

#: What the five blanks are, once `x = y²` is applied to the cell beside each.
#: The given cells carry exact radicals; every answer is a signed integer,
#: which is what the page's own `[0-9-]` and four-character limit publish.
EXPECTED_PARTS = ["0", "8", "8", "5", "3"]


def shared_constant(name: str) -> str:
    """One constant's value as `common/config.js` declares it."""
    found = re.search(rf"\b{name} = (.+);", (EXTENSION / "common" / "config.js").read_text())
    assert found is not None, f"{name} is not declared in common/config.js"
    return found.group(1)


def _lift(source: str, name: str) -> str:
    """Lift one brace-balanced function out of `background.js`."""
    start = source.index(f"function {name}(")
    depth = 0
    for cursor in range(source.index("{", start), len(source)):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return source[start : cursor + 1]
    raise AssertionError(f"{name} is not brace-balanced")


def _flatten(relative: str) -> str:
    """One `common/` module as plain script text.

    These three are DOM-free and import only each other, so dropping the module
    keywords is enough to run the add-on's real rules rather than a stand-in
    for them.
    """
    lines = (EXTENSION / relative).read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if not line.startswith("import ")]
    return "\n".join(
        line[len("export ") :] if line.startswith("export ") else line for line in kept
    )


def background(*names: str):
    """`background.js` functions, over the add-on's own answer rules."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    for module in ("common/config.js", "common/editor-rules.js", "common/editor-plan.js"):
        context.eval(_flatten(module))
    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    for name in names:
        context.eval(_lift(source, name))

    def call(*arguments):
        packed = ", ".join(json.dumps(argument) for argument in arguments)
        return json.loads(context.eval(f"JSON.stringify({names[-1]}({packed}))"))

    return call


def result(context, expression):
    return json.loads(context.eval(f"JSON.stringify({expression})"))


# --- what the page's own markup says ---------------------------------------


def test_the_fixture_is_the_live_shape() -> None:
    """The observed two-by-six grid, exact five ids, and two given radicals."""
    markup = FIXTURE.read_text(encoding="utf-8")

    assert len(FIELD_IDS) == 5
    assert FIELD_IDS == [
        "MatrixTextBoxes3_num",
        "MatrixTextBoxes6_num",
        "MatrixTextBoxes8_num",
        "MatrixTextBoxes10_num",
        "MatrixTextBoxes11_num",
    ]
    assert len(set(FIELD_IDS)) == 5
    assert "<thead>" not in markup
    assert markup.count("<tr>") == 2
    assert all(row.count("<td>") == 6 for row in re.findall(r"<tr>(.*?)</tr>", markup))
    # Given exactly, as the page wrote them; neither is an answer.
    assert "<msqrt><mn>2</mn></msqrt>" in markup
    assert "<msqrt><mn>3</mn></msqrt>" in markup


# --- the DOM sweep ----------------------------------------------------------


@pytest.fixture
def table_completion_page():
    """Five visible, editable boxes and no separator element anywhere.

    A table of values never says "or" between its cells, so the separator rule
    discards them as a *decision* -- exactly as it does for lesson 3.3's
    labelled pair. What matters is that they survive as candidates.
    """
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    source = (EXTENSION / "content" / "hawkes-editor.js").read_text()
    context = quickjs.Context()
    context.eval(
        r"""
        class Element {
          constructor({id = "", left = 0, top = 0, width = 20, height = 20} = {}) {
            this.id = id;
            this.left = left;
            this.top = top;
            this.width = width;
            this.height = height;
            this.disabled = false;
            this.readOnly = false;
            this.isConnected = true;
            this.value = "";
            this.selectionStart = 0;
            this.selectionEnd = 0;
            this.accept = true;
            this.textContent = "";
          }
          getBoundingClientRect() {
            return {
              left: this.left, right: this.left + this.width,
              top: this.top, bottom: this.top + this.height,
              width: this.width, height: this.height,
            };
          }
          dispatchEvent(event) {
            return event.type !== "beforeinput" || this.accept;
          }
          matches(selector) { return selector.includes("input"); }
          closest() { return null; }
          focus() { document.activeElement = this; }
          setSelectionRange(start, end) {
            this.selectionStart = start;
            this.selectionEnd = end;
          }
        }
        class HTMLInputElement extends Element {}
        class HTMLTextAreaElement extends Element {}
        class HTMLIFrameElement extends Element {}
        class HTMLFrameElement extends Element {}
        class InputEvent { constructor(type) { this.type = type; } }

        const body = new Element();
        const documentElement = new Element();
        globalThis.fields = [];
        globalThis.extras = [];
        // The sweep sorts by top and then left, which is the real DOM's
        // row-major order rather than the table's ordered-pair order.
        globalThis.addField = (id, row, column) => {
          fields.push(new HTMLInputElement({
            id: id, top: 100 + row * 40, left: 100 + column * 120, width: 80,
          }));
        };
        globalThis.window = {
          location: {origin: "https://learn.hawkeslearning.com"},
          getSelection() { return null; },
        };
        globalThis.document = {
          activeElement: null, body, documentElement,
          querySelectorAll(selector) {
            if (selector.includes('input[type="radio"].opt')) return [];
            if (selector.includes('customMessageBox')) return [];
            // Nothing on a table of values says "or".
            if (selector === "*") return [];
            if (selector.includes("input.qbaseCSS")) return [...fields, ...extras];
            return [];
          },
        };
        globalThis.ethnosCadence = {
          normalize(value) { return value; },
          planCharacters() { return {offsets: []}; },
          async playCharacters(characters, write) {
            for (const character of characters) {
              const failure = write(character);
              if (failure) return {failure};
            }
            return {failure: null};
          },
        };
        """
    )
    # Two x-row blanks, then three y-row blanks: the exact order and positions
    # reported by the real DOM sweep.
    for identifier, row, column in [
        (FIELD_IDS[0], 0, 1),
        (FIELD_IDS[1], 0, 4),
        (FIELD_IDS[2], 1, 0),
        (FIELD_IDS[3], 1, 2),
        (FIELD_IDS[4], 1, 3),
    ]:
        context.eval(f"addField({json.dumps(identifier)}, {row}, {column});")
    # The owner clicked one of them, which is how the live run was focused.
    context.eval("document.activeElement = fields[0];")
    context.eval(source)
    return context


def test_all_five_blanks_are_reported_as_candidates(table_completion_page):
    """The DOM side reproduces the exact five ids from the latest run."""
    reported = result(table_completion_page, "ethnosHawkes.inspectField()")

    assert reported["code"] == "focused-answer-field"
    assert reported["via"] == "focused-field"
    assert reported["fieldId"] == "MatrixTextBoxes3_num"
    assert reported["multiFieldEvidence"] == {
        "fields": 5,
        "separatorCandidates": 0,
        "separators": 0,
        "fieldIds": FIELD_IDS,
    }


def test_the_boxes_are_still_discarded_as_a_decision(table_completion_page):
    """The "or" rule is unchanged: with no separator these are not adopted here."""
    reported = result(table_completion_page, "ethnosHawkes.inspectField()")

    assert reported["code"] != "multi-answer-fields"
    assert "fieldIds" not in reported


def test_a_sixth_box_is_still_refused(table_completion_page):
    """This is a bound, not its removal.

    A question with more parts than the add-on can place is still refused
    whole, rather than half-answered -- which is the behaviour that made the
    five-blank case diagnosable in the first place.
    """
    table_completion_page.eval('addField("MatrixTextBoxes6_num", 5, 1);')
    evidence = result(table_completion_page, "ethnosHawkes.inspectField()")[
        "multiFieldEvidence"
    ]

    assert evidence["fields"] == 6
    assert evidence["fieldIds"] == []


def test_a_disabled_box_is_still_not_a_candidate(table_completion_page):
    """A control nobody can type into is not one of the question's answers."""
    table_completion_page.eval("fields[4].disabled = true;")
    evidence = result(table_completion_page, "ethnosHawkes.inspectField()")[
        "multiFieldEvidence"
    ]

    assert evidence["fields"] == 4
    assert evidence["fieldIds"] == FIELD_IDS[:4]


# --- the page's own editor model --------------------------------------------


def describe_editor(controls: int, enabled: int | None = None):
    """Run the MAIN-world probe against a page publishing `controls` boxes."""
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    context = quickjs.Context()
    context.eval(
        f"""
        const total = {controls};
        const live = {controls if enabled is None else enabled};
        globalThis.window = {{quant_wp_UI: {{
          focusedElementIndex: 0,
          controlsCollection: Array.from({{length: total}}, (unused, at) => ({{
            enabled: at < live,
          }})),
          controlsCollectionData: Array.from({{length: total}}, (unused, at) => ({{
            Name: "cell" + (at + 1),
            // A plain answer box: not dynamic, and not an option.
            isQDy: false,
            boxValue: "",
            enableState: at < live,
            // What each blank published live: digits and a leading minus, four
            // characters, no keypad templates at all.
            validString: "[0-9-]",
            maxLength: 4,
          }})),
        }}}};
        """
    )
    source = (EXTENSION / "content" / "hawkes-describe.js").read_text(encoding="utf-8")
    return json.loads(context.eval(source).json())


def test_five_published_controls_are_one_multi_answer() -> None:
    """A genuine five-control collection remains a five-part editor."""
    described = describe_editor(5)

    assert described["ok"] is True
    assert described["code"] == "described-multi"
    assert described["kind"] == "multi"
    assert [one["name"] for one in described["editors"]] == [
        "cell1", "cell2", "cell3", "cell4", "cell5",
    ]
    assert all(one["allowedCharacters"] == "[0-9-]" for one in described["editors"])
    assert all(one["maxLength"] == 4 for one in described["editors"])


def test_a_disabled_control_is_not_counted_among_the_five() -> None:
    """The rule that stopped lesson 3.3 asking for a third coordinate."""
    described = describe_editor(6, enabled=5)

    assert described["kind"] == "multi"
    assert len(described["editors"]) == 5


def test_six_published_controls_are_still_not_a_multi_answer() -> None:
    """Past the bound the model is not adopted, and one box is described."""
    described = describe_editor(6)

    assert described["kind"] == "textbox"


def test_the_real_ten_cell_collection_describes_only_the_focused_box() -> None:
    """Hawkes publishes every table cell; that count is not answer cardinality."""
    described = describe_editor(10)

    assert described["kind"] == "textbox"
    assert described["collection"] == {
        "controls": 10,
        "controlKeys": 10,
        "dataKeys": 10,
        "paired": 10,
        "described": 10,
        "usable": 10,
        "focused": 0,
        "branch": "focused",
    }


# --- reconciling the two readings -------------------------------------------


def test_five_agreeing_readings_place_the_answer() -> None:
    """Five boxes found, five enabled editors published: the ids are adopted."""
    adopt = background("answerFieldIds")

    assert adopt(
        {"fieldId": "MatrixTextBoxes3_num"},
        {"fields": 5, "separators": 0, "fieldIds": FIELD_IDS},
        {"kind": "multi", "editors": [{}, {}, {}, {}, {}]},
    ) == FIELD_IDS


def test_a_model_counting_differently_is_still_not_adopted() -> None:
    """Four published editors against five boxes is the disagreement itself."""
    adopt = background("answerFieldIds")

    assert (
        adopt(
            {"fieldId": "MatrixTextBoxes3_num"},
            {"fields": 5, "fieldIds": FIELD_IDS},
            {"kind": "multi", "editors": [{}, {}, {}, {}]},
        )
        == []
    )


# --- the shape sent to the host ---------------------------------------------


def test_the_real_table_overrides_the_ten_cell_collection_with_five_parts() -> None:
    """The validated blank positions turn the real focused editor into five parts."""
    from hawkes_dom import read_fixture

    shape = background("answerShapeOf")
    table = read_fixture("table-completion.html")["answerTable"]

    assert shape(
        describe_editor(10),
        table,
    ) == {
        "kind": "multi",
        "count": 5,
    }


@pytest.mark.parametrize(
    "blanks",
    [[1, 2, 4, 5, 6], [1, 2, 3, 4, 5, 6], [2, 3, 4, 5, 6]],
)
def test_an_ambiguous_table_never_overrides_the_editor(blanks) -> None:
    """Only two-to-five sequential blanks can alter answer cardinality."""
    table = {
        "columns": ["x", "y"],
        "rows": [[{"text": str(index)}, {"blank": blank}] for index, blank in enumerate(blanks)],
    }

    assert background("answerShapeOf")(describe_editor(10), table) == {
        "kind": "field",
        "representations": [{"kind": "signed-integer", "maxLength": 4}],
    }


def test_five_parts_are_planned_against_their_own_editors() -> None:
    """Each answer is preflighted against the box it is going into."""
    fits = background("multiEntryPlans", "multiAnswerFits")

    assert fits(
        EXPECTED_PARTS,
        {
            "kind": "multi",
            "editors": [
                {"kind": "textbox", "allowedCharacters": "[0-9-]", "maxLength": 4}
            ] * 5,
        },
    ) is True


# --- the wire the host answers on -------------------------------------------


def test_the_protocol_carries_five_parts() -> None:
    from ethnos.hawkes_protocol import AnswerPayload, AnswerShape

    shape = AnswerShape(
        kind="multi",
        count=5,
        representations=[{"kind": "signed-integer", "maxLength": 4}] * 5,
    )
    assert shape.count == 5
    assert AnswerPayload(parts=EXPECTED_PARTS).parts == EXPECTED_PARTS


def test_the_protocol_still_refuses_more_than_the_bound() -> None:
    import pydantic

    from ethnos.hawkes_protocol import MAX_ANSWER_PARTS, AnswerPayload, AnswerShape

    with pytest.raises(pydantic.ValidationError):
        AnswerShape(kind="multi", count=MAX_ANSWER_PARTS + 1)
    with pytest.raises(pydantic.ValidationError):
        AnswerPayload(parts=["1"] * (MAX_ANSWER_PARTS + 1))


def test_the_host_asks_facet_for_five() -> None:
    """`required_answer_parts` passes the page's count through untouched."""
    from ethnos.hawkes_host import required_answer_parts
    from ethnos.hawkes_protocol import AnswerShape

    shape = AnswerShape(kind="multi", count=5)
    assert required_answer_parts(shape, "Complete the table of values below.") == 5


def test_facet_accepts_a_five_part_requirement() -> None:
    """The next hop must not refuse a request the browser is allowed to make."""
    from ethnos.facet_client import MAX_ANSWER_PARTS, FacetProtocolError, solve_math

    assert MAX_ANSWER_PARTS >= 5
    with pytest.raises(FacetProtocolError, match="answer_parts must be 1 to"):
        solve_math(
            instruction="Complete the table of values below.",
            request_id="r-test",
            expressions=["x = y^2"],
            answer_parts=MAX_ANSWER_PARTS + 1,
        )


# --- one bound, in every copy of it -----------------------------------------


def test_every_copy_of_the_bound_agrees() -> None:
    """Thirteen places said "four"; a copy left behind is the bug returning.

    The browser's copies are compared by the build's own shared-constant check.
    These are the two the build cannot see: the wire the add-on talks to, and
    the wire the host talks to. A request the browser may make and the next hop
    refuses is a refusal with nobody's name on it.
    """
    from ethnos.facet_client import MAX_ANSWER_PARTS as FACET_BOUND
    from ethnos.hawkes_protocol import MAX_ANSWER_PARTS as WIRE_BOUND

    assert WIRE_BOUND == FACET_BOUND == int(shared_constant("MAX_ANSWER_PARTS"))
