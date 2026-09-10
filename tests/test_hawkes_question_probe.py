"""Focused DOM regressions for the read-only Hawkes question probe."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from hawkes_dom import read_question


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
