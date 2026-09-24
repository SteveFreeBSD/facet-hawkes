"""Focused DOM regressions for the read-only Hawkes question probe."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hawkes_dom import read_question
from hawkes_dom import read_fixture


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_a_labeled_cartesian_point_is_read_from_page_owned_svg_geometry():
    result = read_fixture("labeled-point.html")

    assert result["labeledPoint"] == {
        "label": "Q",
        "x": "-4",
        "y": "2",
        "reading": "svg",
    }
    assert "graphPoints" not in result
    assert result["evidence"]["graph"] == "labeled-point-exact"
    assert result["evidence"]["graphQuestion"] == "labeled-point"
    assert result["evidence"]["graphDecision"] == "accepted"


@pytest.mark.parametrize(
    ("description", "center", "label", "expected"),
    [
        (
            "A dot drawn 3 units below the origin.",
            (200, 252.5),
            (190, 230),
            ("0", "-3"),
        ),
        (
            "A dot drawn 6 units right of the origin.",
            (305, 200),
            (295, 178),
            ("6", "0"),
        ),
        ("A dot drawn at the origin.", (200, 200), (190, 178), ("0", "0")),
    ],
)
def test_axis_points_and_the_origin_are_derived_without_special_coordinates(
    description, center, label, expected
):
    markup = (PROJECT_ROOT / "tests/fixtures/labeled-point.html").read_text()
    markup = (
        markup.replace(
            "A dot drawn 4 units left of and 2 units above the origin.", description
        )
        .replace(
            'cx="130" cy="165" r="5" data-left="125" data-top="160"',
            f'cx="{center[0]}" cy="{center[1]}" r="5" '
            f'data-left="{center[0] - 5}" data-top="{center[1] - 5}"',
        )
        .replace(
            'x="123" y="146" data-left="120" data-top="134"',
            f'x="{label[0]}" y="{label[1]}" data-left="{label[0]}" data-top="{label[1]}"',
        )
    )

    result = read_question(markup)

    assert (result["labeledPoint"]["x"], result["labeledPoint"]["y"]) == expected


def test_duplicate_target_labels_fail_closed_as_ambiguous():
    markup = (PROJECT_ROOT / "tests/fixtures/labeled-point.html").read_text()
    markup = markup.replace(
        "</svg>",
        '<text x="200" y="200" data-left="195" data-top="188" '
        'data-width="10" data-height="14">Q</text></svg>',
    )

    result = read_question(markup)

    assert "labeledPoint" not in result
    assert result["evidence"]["graphDecision"] == "ambiguous"
    assert result["evidence"]["graph"] == "point-label-count-2"


def test_a_point_between_grid_lines_fails_closed_instead_of_rounding():
    markup = (
        (PROJECT_ROOT / "tests/fixtures/labeled-point.html")
        .read_text()
        .replace(
            'cx="130" cy="165" r="5" data-left="125" data-top="160"',
            'cx="138" cy="165" r="5" data-left="133" data-top="160"',
        )
    )

    result = read_question(markup)

    assert "labeledPoint" not in result
    assert result["evidence"]["graphDecision"] == "ambiguous"
    assert result["evidence"]["graph"] == "point-not-on-grid"


def test_a_missing_svg_label_is_structurally_unavailable_not_guessed():
    markup = (
        (PROJECT_ROOT / "tests/fixtures/labeled-point.html")
        .read_text()
        .replace(">Q</text>", ">S</text>")
    )

    result = read_question(markup)

    assert "labeledPoint" not in result
    assert result["evidence"]["graphDecision"] == "unavailable"
    assert result["evidence"]["graph"] == "point-label-missing"


def test_mixed_mathjax_word_problem_keeps_all_surrounding_prose_once():
    result = read_question(
        r"""
        <div>Step 1 of 1</div>
        <div class="question">
          <span>Kathy buys a hardcover novel for </span>
          <div class="inline-math">
            <mjx-container class="MathJax">
              <mjx-math aria-hidden="true">$24.80</mjx-math>
              <mjx-assistive-mml>
                <math id="MathJax-Element-1"><mtext>$</mtext><mn>24.80</mn></math>
              </mjx-assistive-mml>
            </mjx-container>
          </div>
          <span>. This is with a </span>
          <div class="inline-math">
            <mjx-container class="MathJax">
              <mjx-math aria-hidden="true">20%</mjx-math>
              <mjx-assistive-mml>
                <math id="MathJax-Element-2"><mn>20</mn><mo>%</mo></math>
              </mjx-assistive-mml>
            </mjx-container>
          </div>
          <span> discount from the original price. What was the original price?</span>
        </div>
        <input class="qbaseCSS" id="txtAns1">
        """
    )

    assert result["promptText"] == (
        "Step 1 of 1 Kathy buys a hardcover novel for . This is with a discount "
        "from the original price. What was the original price?"
    )
    assert len(result["expressions"]) == 2
    assert "<mn>24.80</mn>" in result["expressions"][0]
    assert "<mn>20</mn><mo>%</mo>" in result["expressions"][1]
    assert "$24.80" not in result["promptText"]
    assert "20%" not in result["promptText"]


def test_equation_only_math_stays_only_in_expressions():
    result = read_question(
        r"""
        <div>Step 1 of 1</div>
        <div class="question">
          <span>Solve the following equation.</span>
          <div class="display-math">
            <mjx-container class="MathJax">
              <mjx-math aria-hidden="true">x=4</mjx-math>
              <mjx-assistive-mml>
                <math><mi>x</mi><mo>=</mo><mn>4</mn></math>
              </mjx-assistive-mml>
            </mjx-container>
          </div>
        </div>
        <input class="qbaseCSS" id="txtAns1">
        """
    )

    assert result["promptText"] == "Step 1 of 1 Solve the following equation."
    assert result["expressions"] == ["<math><mi>x</mi><mo>=</mo><mn>4</mn></math>"]


def test_parallel_line_keeps_inline_point_beside_separate_source_equation():
    """Live Lesson 2.5 shape: both canonical owners contribute question data."""
    result = read_question(
        r"""
        <div id="partDescription">
          <p>Find the equation of the line which passes through the point
            <mjx-container><mjx-assistive-mml>
              <math><mo>(</mo><mrow><mrow><mo>−</mo><mn>8</mn></mrow>
                <mo>,</mo><mn>11</mn></mrow><mo>)</mo></math>
            </mjx-assistive-mml></mjx-container>
            and is <strong>parallel</strong> to the given line. Express your
            answer in slope-intercept form. Simplify your answer.</p>
        </div>
        <div id="questionString"><p>
          <mjx-container><mjx-assistive-mml>
            <math><mrow><mrow><mn>4</mn><mi>x</mi></mrow><mo>+</mo>
              <mrow><mn>8</mn><mi>y</mi></mrow></mrow><mo>=</mo>
              <mn>19</mn></math>
          </mjx-assistive-mml></mjx-container>
        </p></div>
        <div id="partInformation">Step 1 of 2</div>
        <input class="qbaseCSS" id="txtAns1">
        """
    )

    assert "parallel to the given line" in result["promptText"]
    assert len(result["expressions"]) == 2
    assert "<mn>4</mn><mi>x</mi>" in result["expressions"][0]
    assert "<mo>−</mo><mn>8</mn>" in result["expressions"][1]
    assert result["evidence"]["mathRelations"] == ["=", ""]


def test_instructional_form_math_is_not_a_second_stated_equation():
    result = read_question(
        r"""
        <div>Step 1 of 1</div>
        <div class="instruction">
          Determine if the following equation is linear. If the equation is
          linear, convert it to standard form:
          <mjx-container><mjx-assistive-mml>
            <math><mi>a</mi><mi>x</mi><mo>+</mo><mi>b</mi><mi>y</mi>
              <mo>=</mo><mi>c</mi></math>
          </mjx-assistive-mml></mjx-container>
        </div>
        <div class="equation"><mjx-container><mjx-assistive-mml>
          <math><msup><mrow><mo>(</mo><mo>-</mo><mn>2</mn><mo>+</mo><mi>y</mi>
            <mo>)</mo></mrow><mn>2</mn></msup><mo>-</mo>
            <msup><mi>y</mi><mn>2</mn></msup><mo>=</mo><mo>-</mo><mn>9</mn>
            <mi>x</mi><mo>+</mo><mn>4</mn></math>
        </mjx-assistive-mml></mjx-container></div>
        <input type="radio" class="opt" name="answer" aria-label="Linear">
        <input type="radio" class="opt" name="answer" aria-label="Not Linear">
        """
    )

    assert "standard form" in result["promptText"]
    assert len(result["expressions"]) == 1
    assert "<mn>9</mn>" in result["expressions"][0]
    assert "<mi>a</mi><mi>x</mi>" not in result["expressions"][0]
    assert result["evidence"]["instructionalMath"] == 1


def test_inline_instructional_form_before_sentence_period_is_not_an_equation():
    """The live owner keeps its period after the inline MathJax container."""
    result = read_question(
        r"""
        <div id="wrap-question">
          <div class="row">
            <div class="col-md-12 question_description_span12">
              <div class="pull-left question_description_pull_left">
                <div id="questionDescription"
                     class="pull-left push-up10 question_description_pushup10">
                  <p>Determine if the following equation is linear. If the equation
                    is linear, convert it to standard form:
                    <mjx-container><mjx-assistive-mml>
                      <math><mi>a</mi><mi>x</mi><mo>+</mo><mi>b</mi><mi>y</mi>
                        <mo>=</mo><mi>c</mi></math>
                    </mjx-assistive-mml></mjx-container>.</p>
                </div>
              </div>
            </div>
          </div>
          <div class="row">
            <div class="col-md-12"><div class="question-area">
              <div id="questionString" class="questionString_class"><p>
                <mjx-container><mjx-assistive-mml>
                  <math><msup><mrow><mo>(</mo><mn>8</mn><mo>+</mo><mi>y</mi>
                    <mo>)</mo></mrow><mn>2</mn></msup><mo>-</mo>
                    <msup><mi>y</mi><mn>2</mn></msup><mo>=</mo><mo>-</mo>
                    <mn>3</mn><mi>x</mi><mo>+</mo><mn>4</mn></math>
                </mjx-assistive-mml></mjx-container>
              </p></div>
              <div id="partInformation">Step 1 of 1 :</div>
            </div></div>
          </div>
        </div>
        <input type="radio" class="opt" name="answer" aria-label="Linear">
        <input type="radio" class="opt" name="answer" aria-label="Not Linear">
        """
    )

    assert len(result["expressions"]) == 1
    assert "<mn>8</mn>" in result["expressions"][0]
    assert "<mi>a</mi><mi>x</mi>" not in result["expressions"][0]
    # Canonical ownership excludes description math before the generic
    # instructional-template filter has to classify it.
    assert result["evidence"]["instructionalMath"] == 0


def test_two_stated_equations_are_not_mistaken_for_an_output_template():
    result = read_question(
        r"""
        <div>Solve the following equations.</div>
        <div><mjx-container><mjx-assistive-mml>
          <math><mi>x</mi><mo>+</mo><mi>y</mi><mo>=</mo><mn>4</mn></math>
        </mjx-assistive-mml></mjx-container></div>
        <div><mjx-container><mjx-assistive-mml>
          <math><mi>x</mi><mo>-</mo><mi>y</mi><mo>=</mo><mn>2</mn></math>
        </mjx-assistive-mml></mjx-container></div>
        <input class="qbaseCSS" id="txtAns1">
        """
    )

    assert len(result["expressions"]) == 2
    assert result["evidence"]["instructionalMath"] == 0


def test_math_generated_by_a_partial_graph_answer_is_not_question_math():
    result = read_question(
        r"""
        <div id="questionDescription">Graph the solution set.</div>
        <div id="questionString"><math><mi>x</mi><mo>+</mo><mi>y</mi>
          <mo>&lt;</mo><mn>4</mn></math></div>
        <div id="partInformation">Step 1 of 1
          <div id="answerTemplateContainer"><math><mi>y</mi><mo>=</mo>
            <mo>-</mo><mi>x</mi><mo>+</mo><mn>4</mn></math></div>
        </div>
        <input class="qbaseCSS" id="txtUserAnswer11_num">
        """
    )

    assert len(result["expressions"]) == 1
    assert "<mo><</mo>" in result["expressions"][0]


def test_question_string_owns_the_expression_over_description_math():
    result = read_question(
        r"""
        <div id="questionDescription">Graph the linear inequality
          <math><mi>A</mi><mi>x</mi><mo>+</mo><mi>B</mi><mi>y</mi>
            <mo>&lt;</mo><mi>C</mi></math></div>
        <div id="questionString"><math><mn>2</mn><mi>x</mi><mo>+</mo>
          <mn>6</mn><mi>y</mi><mo>&lt;</mo><mn>6</mn></math></div>
        <div id="partInformation">Step 1 of 1</div>
        """
    )

    assert len(result["expressions"]) == 1
    assert "<mn>2</mn>" in result["expressions"][0]
    assert "<mi>A</mi>" not in result["expressions"][0]


def test_answer_controls_inside_part_information_bound_partial_graph_math():
    result = read_question(
        r"""
        <div id="questionDescription">Graph the linear inequality.</div>
        <div id="questionString">
          <math><mn>2</mn><mi>x</mi><mo>+</mo><mn>6</mn><mi>y</mi>
            <mo>&lt;</mo><mn>6</mn></math>
          <div id="partInformation">
            <input type="radio" class="opt" name="boundary" aria-label="Dashed">
            <input class="qbaseCSS" id="txtUserAnswer11_num">
            <div class="boundary-equation"><math><mi>y</mi><mo>=</mo>
              <mo>-</mo><mfrac><mi>x</mi><mn>3</mn></mfrac>
              <mo>+</mo><mn>1</mn></math></div>
          </div>
        </div>
        """
    )

    assert len(result["expressions"]) == 1
    assert "<mo><</mo>" in result["expressions"][0]
    assert "<mfrac>" not in result["expressions"][0]
    assert result["evidence"]["mathRelations"] == ["<"]


@pytest.mark.parametrize(
    ("ordinal", "kept", "relation"),
    [("first", "<mn>2</mn>", ">"), ("second", "<mn>4</mn>", "≥")],
)
def test_system_graph_step_owns_the_named_inequality(ordinal, kept, relation):
    result = read_question(
        f"""
        <div id="questionDescription">Solve the system of two linear inequalities graphically.</div>
        <div id="questionString">
          <math><mi>x</mi><mo>&gt;</mo><mn>2</mn></math>
          <span>or</span>
          <math><mi>y</mi><mo>≥</mo><mn>4</mn></math>
        </div>
        <div id="partInformation">Step 1 of 3: Graph the solution set of the
          {ordinal} linear inequality.</div>
        <input class="qbaseCSS" id="txtUserAnswer11_num">
        """
    )

    assert len(result["expressions"]) == 1
    assert kept in result["expressions"][0]
    assert result["evidence"]["mathRelations"] == [relation]
    assert result["evidence"]["stepMathScope"] == ordinal


@pytest.mark.parametrize(("connector", "expected"), [("or", "or"), ("and", "and")])
def test_system_final_step_preserves_both_inequalities_and_the_connector(
    connector, expected
):
    result = read_question(
        f"""
        <div id="questionDescription">Solve the system of two linear inequalities graphically.</div>
        <div id="questionString">
          <math><mi>x</mi><mo>&gt;</mo><mn>6</mn></math>
          <span>{connector}</span>
          <math><mi>y</mi><mo>≥</mo><mn>5</mn></math>
        </div>
        <div id="partInformation">Step 3 of 3: Select and graph the option that
          describes the overall solution set.</div>
        <div id="QGraph"></div>
        """
    )

    assert len(result["expressions"]) == 2
    assert result["systemConnector"] == expected
    assert result["evidence"]["systemConnector"] == expected
    assert result["evidence"]["mathRelations"] == [">", "≥"]
    assert result["evidence"]["stepMathScope"] == ""


def test_partial_graph_math_is_excluded_without_canonical_question_ids():
    result = read_question(
        r"""
        <div>Graph the solution set.</div>
        <div class="equation"><math><mi>x</mi><mo>+</mo><mi>y</mi>
          <mo>&lt;</mo><mn>4</mn></math></div>
        <div id="answerTemplateContainer">
          <math><mi>y</mi><mo>=</mo><mo>-</mo><mi>x</mi><mo>+</mo><mn>4</mn></math>
          <input class="qbaseCSS" id="txtUserAnswer11_num">
        </div>
        """
    )

    assert len(result["expressions"]) == 1
    assert "<mo><</mo>" in result["expressions"][0]


def test_option_radios_bound_the_question_before_their_caption_mathml():
    """The answer choices' ∅ and ℝ are not expressions to solve."""
    quickjs = pytest.importorskip("quickjs")
    source = (PROJECT_ROOT / "extension" / "content" / "hawkes-question.js").read_text(
        encoding="utf-8"
    )
    context = quickjs.Context()
    context.eval(
        r"""
        function node(top, text, xml) {
          return {
            textContent: text,
            xml: xml,
            getBoundingClientRect() {
              return {top: top, width: 100, height: 20};
            },
            querySelector() { return null; },
          };
        }
        const prompt = node(40, "Solve the following linear equation.", "");
        const equation = node(80, "", "<math><mi>x</mi><mo>=</mo><mn>1</mn></math>");
        const option = node(160, "Infinite Solutions (R)", "");
        const optionMath = node(165, "", "<math><mi>R</mi></math>");
        globalThis.document = {
          querySelectorAll(selector) {
            if (selector === "math") return [equation, optionMath];
            if (selector === "p, div, span, td") return [prompt];
            if (selector.includes('input[type="radio"].opt')) return [option];
            return [];
          },
        };
        globalThis.XMLSerializer = function XMLSerializer() {
          this.serializeToString = element => element.xml;
        };
        """
    )

    result = json.loads(context.eval(source).json())

    assert result["promptText"] == "Solve the following linear equation."
    assert result["expressions"] == ["<math><mi>x</mi><mo>=</mo><mn>1</mn></math>"]


def test_formula_target_is_preserved_when_the_instruction_only_says_indicated():
    """The variable named beside live Q3 reaches the exact solver."""
    quickjs = pytest.importorskip("quickjs")
    source = (PROJECT_ROOT / "extension" / "content" / "hawkes-question.js").read_text(
        encoding="utf-8"
    )
    context = quickjs.Context()
    context.eval(
        r"""
        function node(top, text, xml = "") {
          return {
            textContent: text,
            xml,
            getBoundingClientRect() { return {top, width: 100, height: 20}; },
            querySelector() { return null; },
          };
        }
        const instruction = node(40, "Solve the following formula for the indicated variable.");
        const target = node(90, "C = 2πr; solve for r.");
        const equation = node(80, "", "<math><mi>C</mi><mo>=</mo><mn>2</mn><mi>π</mi><mi>r</mi></math>");
        const answer = node(160, "", "");
        globalThis.document = {
          querySelectorAll(selector) {
            if (selector === "math") return [equation];
            if (selector === "p, div, span, td") return [instruction, target];
            if (selector.includes("input.qbaseCSS")) return [answer];
            return [];
          },
        };
        globalThis.XMLSerializer = function XMLSerializer() {
          this.serializeToString = element => element.xml;
        };
        """
    )

    result = json.loads(context.eval(source).json())

    assert result["promptText"] == (
        "Solve the following formula for the indicated variable. Solve for r."
    )
    assert len(result["expressions"]) == 1


def test_a_plotting_instruction_is_read_rather_than_left_as_the_step_marker():
    """Live lesson 2.1 question 1: "Plot the following points in the Cartesian
    plane." matched no instruction verb, so the prompt fell back to the
    eleven-character "Step 1 of 1" -- and the companion, sent that, refused to
    write down a plan for a question it could not tell was a plotting one.
    """
    quickjs = pytest.importorskip("quickjs")
    source = (PROJECT_ROOT / "extension" / "content" / "hawkes-question.js").read_text(
        encoding="utf-8"
    )
    context = quickjs.Context()
    context.eval(
        r"""
        function node(top, text, xml = "") {
          return {
            textContent: text,
            xml,
            getBoundingClientRect() { return {top, width: 100, height: 20}; },
            querySelector() { return null; },
          };
        }
        const header = node(20, "Question 1 of 8, Step 1 of 1");
        const instruction = node(60, "Plot the following points in the Cartesian plane.");
        const pairs = node(100, "",
          "<math><mo>{</mo><mo>(</mo><mn>7</mn><mo>,</mo><mn>4</mn><mo>)</mo>"
          + "<mo>,</mo><mo>(</mo><mo>-</mo><mn>8</mn><mo>,</mo><mn>4</mn><mo>)</mo>"
          + "<mo>}</mo></math>");
        globalThis.document = {
          querySelectorAll(selector) {
            if (selector === "math") return [pairs];
            if (selector === "p, div, span, td") return [header, instruction];
            return [];
          },
        };
        globalThis.XMLSerializer = function XMLSerializer() {
          this.serializeToString = element => element.xml;
        };
        """
    )

    result = json.loads(context.eval(source).json())

    prompt = result["promptText"]
    assert "Plot the following points in the Cartesian plane." in prompt
    assert prompt != "Step 1 of 1"
    # The one property the companion's plotting specialist actually reads.
    assert re.search(r"\b(?:plot|graph|place|draw)\b[^.?!]*?\bpoints?\b", prompt, re.I)
    assert len(result["expressions"]) == 1


def test_a_named_positive_assumption_on_its_own_line_reaches_facet():
    """Live lesson 1.5: MathJax exposes both its drawn and assistive condition
    as ``Assume 𝑥>0x>0.``. Facet could not read that as a named assumption, so
    √(-108x^5) became the uninsertable ``6sqrt(3(-x^5))`` instead of
    ``6ix^2√(3x)``.
    """
    quickjs = pytest.importorskip("quickjs")
    source = (PROJECT_ROOT / "extension" / "content" / "hawkes-question.js").read_text(
        encoding="utf-8"
    )
    context = quickjs.Context()
    context.eval(
        r"""
        function node(top, text, xml = "") {
          return {
            textContent: text,
            xml,
            getBoundingClientRect() { return {top, width: 100, height: 20}; },
            querySelector() { return null; },
          };
        }
        // This is the exact instruction string captured at the Facet subprocess
        // boundary, apart from the live radicand changing between variants.
        const instruction = node(40,
          "Step\u00a01\u00a0of\u00a01 Evaluate the following square root expression.  "
          + "Assume 𝑥>0x>0.");
        const positive = node(65, "", "<math><mi>x</mi><mo>&gt;</mo><mn>0</mn></math>");
        const radical = node(90, "",
          "<math><msqrt><mrow><mo>-</mo><mn>108</mn>"
          + "<msup><mi>x</mi><mn>5</mn></msup></mrow></msqrt></math>");
        const answer = node(160, "", "");
        globalThis.document = {
          querySelectorAll(selector) {
            if (selector === "math") return [positive, radical];
            if (selector === "p, div, span, td") {
              return [instruction];
            }
            if (selector.includes("input.qbaseCSS")) return [answer];
            return [];
          },
        };
        globalThis.XMLSerializer = function XMLSerializer() {
          this.serializeToString = element => element.xml;
        };
        """
    )

    result = json.loads(context.eval(source).json())

    assert result["promptText"] == (
        "Step\u00a01\u00a0of\u00a01 Evaluate the following square root expression. "
        "Assume x > 0."
    )
    assert result["evidence"]["promptChars"] == 72
    assert len(result["expressions"]) == 2
