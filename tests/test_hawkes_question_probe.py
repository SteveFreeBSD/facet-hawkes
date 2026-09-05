"""Focused DOM regressions for the read-only Hawkes question probe."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
