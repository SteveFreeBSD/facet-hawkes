"""The ownership boundary itself: who decides how a Hawkes question is answered.

The old shape was Ethnos → exact solvers → Facet only for what they declined.
Ethnos therefore made the routing decision, which is the most consequential
thing about a solve, from the side that owns a browser. The new shape is
Ethnos → one solve request → Facet decides exact mathematics or reasoning →
structured result → Ethnos validates it and actuates.

Two properties have to hold together for that move to be worth anything. The
deterministic behaviour must be *the same behaviour* -- same solver, same
answers, same declines -- and the browser's responsibilities must not have
followed it across. Everything here checks one or the other.

The real Facet runs in-process (`facet_loopback`), so the route is genuinely
decided on the far side and a model that is never asked anything is proof that
exact mathematics answered.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from facet_loopback import FakeAdapter, facet, reasoning

from ethnos.facet_client import FacetProtocolError, _solution
from ethnos.hawkes_host import handle

PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: Live-lesson markup, one per exact route the deterministic stage owns.
RATIONAL_EXPONENTS = (
    "<math><mstyle>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>4</mn></mfrac></msup>"
    "<mo>⋅</mo>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>5</mn></mfrac></msup>"
    "</mstyle></math>"
)
RATIONAL_EQUATION = (
    "<math><mrow>"
    "<mfrac><mn>1</mn><mi>x</mi></mfrac><mo>+</mo>"
    "<mfrac><mn>1</mn><mrow><mi>x</mi><mo>+</mo><mn>2</mn></mrow></mfrac>"
    "<mo>=</mo><mfrac><mn>3</mn><mn>4</mn></mfrac>"
    "</mrow></math>"
)
NEGATIVE_ROOT = "<math><msqrt><mrow><mo>−</mo><mn>36</mn></mrow></msqrt></math>"
VERTEX = (
    "<math><mi>p</mi><mo>(</mo><mi>x</mi><mo>)</mo><mo>=</mo>"
    "<mrow><mo>(</mo><mi>x</mi><mo>-</mo><mn>6</mn><mo>)</mo></mrow>"
    "<mrow><mo>(</mo><mi>x</mi><mo>+</mo><mn>2</mn><mo>)</mo></mrow>"
    "<mo>+</mo><mn>16</mn></math>"
)

RATIONAL_EXPONENT_INSTRUCTION = (
    "Simplify. Express your answer using rational exponents."
)

EXACT_QUESTIONS = [
    pytest.param(
        RATIONAL_EXPONENTS, RATIONAL_EXPONENT_INSTRUCTION, id="rational-exponents"
    ),
    pytest.param(
        RATIONAL_EQUATION,
        "Solve the following rational equation. Separate multiple answers with a comma.",
        id="rational-equation",
    ),
    pytest.param(
        NEGATIVE_ROOT,
        "Determine whether the following is a real number.",
        id="not-a-real-number",
    ),
    pytest.param(VERTEX, "Find the vertex.", id="vertex"),
]


def ask(monkeypatch, markup, instruction, *, engine, **overrides):
    """Answer one question through the real host, against a real Facet."""
    loopback = facet(monkeypatch, **overrides)
    response = handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "routing-1",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": engine,
            "problem": {"prompt_text": instruction, "mathml": [markup]},
        }
    )
    return response, loopback


# --- the deterministic behaviour is the same behaviour ----------------------


@pytest.mark.parametrize(("markup", "instruction"), EXACT_QUESTIONS)
def test_the_same_question_answers_identically_on_both_engines(
    monkeypatch, markup, instruction
) -> None:
    """One solver, two callers. The answer cannot depend on which one ran it.

    This is the reason the exact solvers were moved rather than copied. A
    second copy would agree on the day it was made and disagree later, and the
    disagreement would appear as one engine answering a question the other
    declines -- on the owner's real coursework.
    """
    local, _ = ask(monkeypatch, markup, instruction, engine="ethnos")
    routed, loopback = ask(monkeypatch, markup, instruction, engine="facet")

    assert loopback.prompts == [], "an exactly solvable question reached a model"
    assert local.status == routed.status == "ready"
    assert routed.answer == local.answer
    # Same reading, same solver, same verdict -- and both insertable.
    assert routed.certainty.answered_by == local.certainty.answered_by == "exact"
    assert routed.certainty.method == local.certainty.method
    assert routed.certainty.router == local.certainty.router == "solved"
    assert routed.certainty.insertable is local.certainty.insertable is True


def test_the_two_engines_are_distinguishable_by_provenance_alone(
    monkeypatch,
) -> None:
    """Identical answers, and never an identical account of where they came from."""
    where = dict(markup=RATIONAL_EXPONENTS, instruction=RATIONAL_EXPONENT_INSTRUCTION)
    local, _ = ask(monkeypatch, engine="ethnos", **where)
    routed, _ = ask(monkeypatch, engine="facet", **where)

    assert local.certainty.source == "markup"
    assert local.certainty.facet_invoked is False
    assert local.certainty.runtime is None
    # Facet answered this one, deterministically, and names both facts.
    assert routed.certainty.source == "Facet Exact"
    assert routed.certainty.facet_invoked is True
    assert routed.certainty.runtime.startswith("SymPy ")


def test_an_exact_answer_survives_an_accelerator_being_unavailable(
    monkeypatch,
) -> None:
    """Ethnos requires an accelerator of a *model*. Exact mathematics needs none.

    Refusing an exactly solvable question because a GPU was busy would refuse
    the best answers Facet has, for the least defensible reason.
    """
    nowhere = {
        name: FakeAdapter(name, available=False) for name in ("cpu", "gpu", "npu")
    }

    response, loopback = ask(
        monkeypatch,
        RATIONAL_EXPONENTS,
        RATIONAL_EXPONENT_INSTRUCTION,
        engine="facet",
        **nowhere,
    )

    assert loopback.prompts == []
    assert response.status == "ready"
    assert response.answer.display_text == "y^(27/20)"
    # And it claims no processor, rather than one it did not use.
    assert response.certainty.actual_backend is None


def test_a_decline_names_which_gap_it_fell_through(monkeypatch) -> None:
    """The reason is the whole value of a decline; without it a fallback is mute."""
    response, loopback = ask(
        monkeypatch,
        "<math><mrow><mfrac><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow>"
        "<mrow><msup><mi>x</mi><mn>2</mn></msup><mo>−</mo><mn>9</mn></mrow>"
        "</mfrac></mrow></math>",
        "Find the domain of the following function.",
        engine="facet",
        **reasoning("FINAL ANSWER: (-∞,-3)∪(-3,3)∪(3,∞)"),
    )

    assert len(loopback.prompts) == 1
    assert response.certainty.router == "declined"
    assert response.certainty.router_detail == (
        "no exact operation matched the instruction"
    )
    assert response.certainty.answered_by == "facet"


# --- a result that cannot be trusted is not acted on ------------------------


def provenance(**changes) -> dict:
    made = {
        "source": "Facet Exact",
        "method": "SymPy exact symbolic",
        "router": "solved",
        "router_detail": "",
        "runtime": "SymPy 1.14.0",
        "model": None,
        "device": None,
        "requested_backend": None,
        "actual_backend": None,
        "elapsed_ms": 1.5,
        "fallback": False,
        "metrics": {},
        "evidence": {"model_calls": 0},
    }
    made.update(changes)
    return made


def result(**changes) -> dict:
    made = {
        "route": "exact",
        "answer": {
            "kind": "value",
            "display": "y^(27/20)",
            "entry": "y^(27/20)",
            "parts": [],
            "entry_mode": "auto",
        },
        "provenance": provenance(),
    }
    made.update(changes)
    return made


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        (result(route="guess"), "a route Ethnos does not know"),
        (result(route=None), "no route at all"),
        (
            result(provenance=provenance(model="gpt-oss:20b")),
            "an exact answer that names a model",
        ),
        (
            result(provenance=provenance(actual_backend="gpu")),
            "an exact answer that names a processor",
        ),
        (
            result(route="reasoning", provenance=provenance(router="declined")),
            "a reasoned answer that names nothing that reasoned",
        ),
        (
            result(provenance=provenance(router="declined")),
            "an exact answer from a router that says it declined",
        ),
        (result(provenance=provenance(source="")), "provenance with no source"),
        (result(provenance=provenance(elapsed_ms=-1)), "a negative elapsed time"),
        (result(provenance=provenance(fallback="no")), "a fallback that is not a bool"),
        (
            result(provenance=provenance(fallback=True)),
            "a fallback this request forbade",
        ),
        (
            result(answer={"kind": "value", "display": "x", "entry_mode": "auto"}),
            "no value at all",
        ),
        (
            result(
                answer={
                    "kind": "value",
                    "display": "x",
                    "entry": "1",
                    "parts": ["1", "2"],
                    "entry_mode": "auto",
                }
            ),
            "a single entry and separate parts at once",
        ),
        (
            result(
                answer={
                    "kind": "value",
                    "display": "x",
                    "entry": "",
                    "parts": ["1", " "],
                    "entry_mode": "math",
                }
            ),
            "an empty part",
        ),
        (
            result(
                answer={
                    "kind": "value",
                    "display": "x",
                    "entry": "1",
                    "parts": [],
                    "entry_mode": "?",
                }
            ),
            "an entry mode Ethnos cannot follow",
        ),
        (
            result(
                answer={
                    "kind": "value",
                    "display": "",
                    "entry": "1",
                    "entry_mode": "auto",
                }
            ),
            "an answer with nothing to display",
        ),
        (result(answer="y^(27/20)"), "an answer that is not structured at all"),
        (result(provenance="Facet Exact"), "provenance that is not structured at all"),
    ],
)
def test_a_result_that_contradicts_itself_is_refused(payload, why) -> None:
    with pytest.raises(FacetProtocolError):
        _solution(payload, allow_fallback=False)
    assert why  # named for the failure message, not for the assertion


def test_a_well_formed_result_is_accepted(monkeypatch) -> None:
    """The refusals above must be refusing something, not everything."""
    solution = _solution(result(), allow_fallback=False)

    assert solution.route == "exact"
    assert solution.answer.parts == ()
    assert solution.answer.entry == "y^(27/20)"


# --- the browser's responsibilities did not follow the solver across --------

#: Everything a Hawkes page is made of. None of it is Facet's to know, and
#: `answer_shape` is deliberately not in the request either: what crosses is a
#: count of values, which is a property of the question.
PAGE_DETAIL = (
    "screenshot",
    "png",
    "base64",
    "mathml",
    "<math",
    "origin",
    "hawkeslearning",
    "tab",
    "frame",
    "window",
    "field",
    "editor",
    "selector",
    "keyboard",
    "answer_shape",
    "graph_points",
    "solve_engine",
)


def test_no_part_of_the_page_crosses_to_facet(monkeypatch) -> None:
    """Everything the add-on saw is offered. Only the question is passed on."""
    loopback = facet(monkeypatch, **reasoning("FINAL ANSWER: 4"))

    handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "hawkes-window-3-frame-1",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": "facet",
            "problem": {
                "prompt_text": "Find the domain of the following function.",
                "question_label": "Question 4 of 12",
                "mathml": [
                    "<math><mrow><mfrac><mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow>"
                    "<mrow><msup><mi>x</mi><mn>2</mn></msup><mo>−</mo><mn>9</mn>"
                    "</mrow></mfrac></mrow></math>"
                ],
                "answer_shape": {"kind": "multi", "count": 2},
            },
        }
    )

    crossed = json.dumps(
        [
            {key: value for key, value in request.items() if key != "request_id"}
            for request in loopback.requests
        ]
    ).lower()
    for detail in PAGE_DETAIL:
        assert detail not in crossed, f"{detail} crossed to Facet"
    # The one field the browser does influence is the id used to correlate a
    # reply, and it crosses only after being reduced to a bounded shape.
    assert re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", loopback.requests[0]["request_id"])
    # What did cross: the question, its label, and how many values it takes.
    problem = loopback.problems[0]
    assert problem["instruction"] == "Find the domain of the following function."
    assert problem["expressions"] == [r"\frac{x+1}{x^2-9}"]
    assert problem["answer_parts"] == 2
    assert problem["label"] == "Question 4 of 12"


#: Pressing any Hawkes control spends a graded attempt on the owner's
#: coursework. The add-on's own scripts are gated in `test_hawkes_extension`;
#: what is checked here is that the code the new routing added has no way to
#: act on a page at all -- no browser API, and on the Facet side no way to
#: start a process either.
BROWSER_CAPABILITY = (
    ".click(",
    "dispatchevent",
    "keyboardevent",
    "document.",
    "window.",
    "tabs.",
    "webdriver",
    "selenium",
    "playwright",
)

FACET_SIDE = (
    PROJECT_ROOT.parent / "facet-runtime" / "src" / "facet_runtime" / "solve.py",
    PROJECT_ROOT.parent / "facet-runtime" / "src" / "facet_runtime" / "remote.py",
    PROJECT_ROOT.parent / "facet-runtime" / "src" / "facet_runtime" / "exact",
)


def _sources(path: Path) -> list[Path]:
    return sorted(path.rglob("*.py")) if path.is_dir() else [path]


@pytest.mark.parametrize("path", FACET_SIDE, ids=lambda p: p.name)
def test_the_facet_side_can_neither_reach_a_page_nor_start_a_process(path) -> None:
    """Facet gained a routing decision. It gained no way to press anything."""
    if not path.exists():  # a checkout without the sibling repository
        pytest.skip(f"{path} is not present in this checkout")
    for source_file in _sources(path):
        source = source_file.read_text().lower()
        found = [token for token in BROWSER_CAPABILITY if token in source]
        assert found == [], f"{source_file.name} contains {found}"
        for runner in ("import subprocess", "os.system", "os.popen", "os.exec"):
            assert runner not in source, f"{source_file.name} can start a process"


def test_the_client_reaches_facet_and_nothing_else() -> None:
    """One fixed argv to one named helper, and no browser API anywhere in it."""
    source = (PROJECT_ROOT / "src" / "ethnos" / "facet_client.py").read_text()

    assert [token for token in BROWSER_CAPABILITY if token in source.lower()] == []
    assert source.count("subprocess.run(") == 1
    assert "shell=False" in source


def test_the_reasoning_prompt_never_offers_an_action() -> None:
    """A model on the reasoning route is asked for a value, not for a step."""
    from facet_runtime.solve import MathProblem, reasoning_prompt

    prompt = reasoning_prompt(
        MathProblem("Find the domain.", (r"\frac{x+1}{x^2-9}",), 2, "Question 4")
    ).lower()

    for control in ("submit", "check", "next", "skip", "click", "press", "button"):
        assert re.search(rf"\b{control}\b", prompt) is None


def test_the_suite_cannot_reach_the_real_facet_host() -> None:
    """The guard that would have caught the stale seam, kept honest itself.

    A test that patches a seam the code no longer calls goes out over SSH to
    the real machine, and one of these passed for exactly that reason: the call
    failed, and a failed call was what it asserted.
    """
    from ethnos import facet_client

    with pytest.raises(AssertionError, match="real Facet host"):
        facet_client.generate_text("Reply with one word.", request_id="guard-1")
