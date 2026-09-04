"""End-to-end correctness gates for the Hawkes answer pipeline.

These tests stop at the page-writer boundary. They do not open Firefox or
submit an answer; the live proof in docs/HAWKES_E2E_PROOF.md covers that final
browser step.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from ethnos.answer_image import extract_final_math
from ethnos.symbolic_solver import answer_symbolic_math

PROJECT_ROOT = Path(__file__).resolve().parents[1]
COMMON = PROJECT_ROOT / "extension" / "common"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")


@pytest.fixture(scope="module")
def plan_entry():
    rules = re.sub(
        r"^export ", "", (COMMON / "editor-rules.js").read_text(), flags=re.M
    )
    planner = re.sub(
        r"^export ", "", (COMMON / "editor-plan.js").read_text(), flags=re.M
    )
    planner = re.sub(r"^import .*\n", "", planner, flags=re.M)
    context = quickjs.Context()
    context.eval(rules)
    context.eval(planner)

    def call(answer: str, editor: dict) -> dict:
        return json.loads(
            context.eval(
                f"JSON.stringify(planEntry({json.dumps(answer)}, {json.dumps(editor)}))"
            )
        )

    return call


DYNAMIC_POLYNOMIAL = {
    "ok": True,
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789-+y",
    "maxLength": 16,
    "slots": {
        "base": "0123456789-+y",
        "exponent": "0123456789",
    },
    "templates": {
        "fraction": False,
        "radical": False,
        "exponent": True,
        "parentheses": False,
    },
}


def test_live_polynomial_question_survives_solver_to_keypad_plan(plan_entry):
    result = answer_symbolic_math(
        problem_text="Add or subtract the following polynomials, as indicated.",
        expressions=["(4*y^3+11-4*y)-(9-6*y+9*y^3)"],
    )

    assert result is not None
    answer = extract_final_math(result.raw_response)
    assert answer == "-5y^3 + 2y + 2"

    plan = plan_entry(answer, DYNAMIC_POLYNOMIAL)

    assert plan == {
        "ok": True,
        "steps": [
            {"op": "type", "text": "-5y"},
            {"op": "template", "name": "Exponent"},
            {"op": "type", "text": "3"},
            {"op": "base"},
            {"op": "type", "text": "+2y+2"},
        ],
    }


def test_unverified_model_answers_do_not_enter_this_gate():
    # A model result is not enough for this correctness gate. Exact markup or
    # an independently verified transcription must supply the solver input.
    assert (
        answer_symbolic_math(
            problem_text="Add or subtract the following polynomials, as indicated.",
            expressions=[],
        )
        is None
    )
