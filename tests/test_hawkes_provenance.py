"""Telling the truth about which engine answered, and what it was.

The panel used to say one word -- "markup", "symbolic", "Facet · GPU" -- for a
pipeline with several distinguishable layers in it. A router decides what runs,
exact solvers answer what they can, a reasoner answers the rest, a vision model
sometimes reads the question, and an accelerator may or may not be the one that
was asked for. Collapsing those makes an answer look better sourced than it is,
and the most misleading case is the quiet one: choosing the Facet engine and
being shown "Facet" for a question Facet never saw.

What is checked here is that every one of those layers is named separately, and
that nothing claims a source it did not have.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ethnos.facet_client import FacetResult, FacetTransportError
from ethnos.hawkes_host import handle

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

#: Real live-lesson markup the exact solvers answer: y^(3/4) * y^(3/5).
EXACTLY_SOLVED = (
    "<math><mstyle>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>4</mn></mfrac></msup>"
    "<mo>⋅</mo>"
    "<msup><mi>y</mi><mfrac><mn>3</mn><mn>5</mn></mfrac></msup>"
    "</mstyle></math>"
)
EXACT_INSTRUCTION = "Simplify. Express your answer using rational exponents."

#: (x + 1) / (x^2 - 9). "Find the domain" matches no exact operation.
DECLINED = (
    "<math><mrow><mfrac>"
    "<mrow><mi>x</mi><mo>+</mo><mn>1</mn></mrow>"
    "<mrow><msup><mi>x</mi><mn>2</mn></msup><mo>−</mo><mn>9</mn></mrow>"
    "</mfrac></mrow></math>"
)
DECLINED_INSTRUCTION = (
    "Find the domain of the following function. Write your answer in interval notation."
)


def ask(markup, instruction, *, engine="facet"):
    return handle(
        {
            "protocol_version": 1,
            "operation": "solve_hawkes_problem",
            "request_id": "provenance-1",
            "origin": "https://learn.hawkeslearning.com",
            "solve_engine": engine,
            "problem": {"prompt_text": instruction, "mathml": [markup]},
        }
    )


def facet_answering(monkeypatch, result):
    def fake(_prompt, **_kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("ethnos.facet_client.generate_text", fake)


FACET_RUN = FacetResult(
    text="FINAL ANSWER: (-∞,-3)∪(-3,3)∪(3,∞)",
    requested_backend="gpu",
    actual_backend="gpu",
    runtime="Ollama 0.33.2",
    model="gpt-oss:20b",
    device="AMD Radeon 890M Graphics (RADV STRIX1)",
    elapsed_ms=10386.5,
    fallback=False,
    metrics={},
    evidence={},
)


def test_facet_selected_and_exactly_solved_says_so_and_says_facet_did_not_run(
    monkeypatch,
) -> None:
    """The quiet misleading case: Facet chosen, Facet never called."""
    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("Facet ran for an exactly solved question"),
    )

    certainty = ask(EXACTLY_SOLVED, EXACT_INSTRUCTION).certainty

    assert certainty.answered_by == "exact"
    assert certainty.facet_invoked is False
    assert certainty.router == "solved"
    assert certainty.reading == "mathml"
    # A solver, named as a solver. Never a model name, and never "model".
    assert certainty.method == "SymPy exact symbolic"
    # Nothing Facet-shaped may appear on an answer Facet did not produce.
    assert certainty.model is None
    assert certainty.runtime is None
    assert certainty.device is None
    assert certainty.actual_backend is None
    assert certainty.fallback is None
    # Timed, because "instant" is a claim worth being able to check.
    assert certainty.elapsed_ms is not None and certainty.elapsed_ms >= 0


def test_a_facet_answer_names_the_router_the_reasoner_and_the_processor(
    monkeypatch,
) -> None:
    facet_answering(monkeypatch, FACET_RUN)

    certainty = ask(DECLINED, DECLINED_INSTRUCTION).certainty

    assert certainty.answered_by == "facet"
    assert certainty.facet_invoked is True
    # Why Facet was reached at all, in the router's own words.
    assert certainty.router == "declined"
    assert certainty.router_detail == "no exact operation matched the instruction"
    assert certainty.method == "gpt-oss:20b"
    assert certainty.runtime == "Ollama 0.33.2"
    assert certainty.requested_backend == "gpu"
    assert certainty.actual_backend == "gpu"
    assert certainty.device == "AMD Radeon 890M Graphics (RADV STRIX1)"
    assert certainty.fallback is False
    # The expression still came off the page, not out of a picture.
    assert certainty.reading == "mathml"
    assert certainty.elapsed_ms == 10386.5


def test_a_requested_backend_is_reported_beside_the_one_that_ran(
    monkeypatch,
) -> None:
    """What Ethnos asked for and what happened are separate claims."""
    facet_answering(
        monkeypatch,
        FacetResult(
            **{
                **FACET_RUN.__dict__,
                "requested_backend": "gpu",
                "actual_backend": "npu",
            }
        ),
    )

    certainty = ask(DECLINED, DECLINED_INSTRUCTION).certainty

    assert (certainty.requested_backend, certainty.actual_backend) == ("gpu", "npu")


def test_a_facet_failure_claims_no_answer_source_at_all(monkeypatch) -> None:
    facet_answering(monkeypatch, FacetTransportError("no route to host"))

    response = ask(DECLINED, DECLINED_INSTRUCTION)

    assert response.status == "error"
    assert response.answer is None
    # No certainty means no provenance: there is no answer to have a source.
    assert response.certainty is None


def test_no_provenance_survives_into_the_next_question(monkeypatch) -> None:
    """A Facet run must leave nothing behind on the answer that follows it."""
    facet_answering(monkeypatch, FACET_RUN)
    first = ask(DECLINED, DECLINED_INSTRUCTION).certainty
    assert first.model == "gpt-oss:20b"

    monkeypatch.setattr(
        "ethnos.facet_client.generate_text",
        lambda *_a, **_k: pytest.fail("Facet ran for an exactly solved question"),
    )
    second = ask(EXACTLY_SOLVED, EXACT_INSTRUCTION).certainty

    assert second.answered_by == "exact"
    assert second.facet_invoked is False
    for stale in ("model", "runtime", "device", "actual_backend", "fallback"):
        assert getattr(second, stale) is None, f"{stale} survived the last question"


def test_the_local_model_fallback_is_not_called_an_exact_solver() -> None:
    """`answered_by` separates the solver from the model that reads a picture."""
    from ethnos.hawkes_protocol import Certainty

    assert set(
        Certainty.model_fields["answered_by"].annotation.__args__[0].__args__
    ) == {
        "exact",
        "facet",
        "model",
    }


# --- what the panel and the settings page actually say ---------------------


def _lift(source: str, name: str) -> str:
    start = source.index(f"function {name}(")
    depth, index = 0, source.index("{", start)
    for cursor in range(index, len(source)):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return source[start : cursor + 1]
    raise AssertionError(f"{name} is not brace-balanced")


@pytest.fixture
def notes():
    quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")
    source = (EXTENSION / "background.js").read_text(encoding="utf-8")
    context = quickjs.Context()
    context.eval(_lift(source, "answeredByBadge"))
    context.eval(_lift(source, "provenanceNotes"))

    def run(certainty):
        return json.loads(
            context.eval(f"JSON.stringify(provenanceNotes({json.dumps(certainty)}))")
        )

    return run


def test_the_panel_says_facet_was_not_invoked_on_an_exact_solve(notes) -> None:
    lines = notes(
        {
            "source": "markup",
            "answered_by": "exact",
            "router": "solved",
            "reading": "mathml",
            "method": "SymPy exact symbolic",
            "facet_invoked": False,
            "elapsed_ms": 3.4,
        }
    )

    assert "Answered by: Ethnos Exact" in lines
    assert "Method: SymPy exact symbolic" in lines
    assert "Router: Ethnos Exact answered" in lines
    assert "Facet: not invoked" in lines
    assert "Question read: page MathML" in lines
    assert "Elapsed: 3 ms" in lines
    # Nothing about a processor, because nothing ran on one.
    assert not [line for line in lines if line.startswith(("Device:", "Backend:"))]


def test_the_panel_names_every_layer_of_a_facet_solve(notes) -> None:
    lines = notes(
        {
            "source": "Facet · GPU",
            "answered_by": "facet",
            "router": "declined",
            "router_detail": "no exact operation matched the instruction",
            "reading": "mathml",
            "method": "gpt-oss:20b",
            "facet_invoked": True,
            "requested_backend": "gpu",
            "actual_backend": "gpu",
            "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
            "runtime": "Ollama 0.33.2",
            "fallback": False,
            "elapsed_ms": 10386.5,
        }
    )

    assert "Answered by: Facet · GPU" in lines
    # The reasoner is labelled as one. A solver would have said "Method".
    assert "Reasoner: gpt-oss:20b" in lines
    assert (
        "Router: Ethnos Exact declined (no exact operation matched the instruction)"
        in lines
    )
    assert "Runtime: Ollama 0.33.2" in lines
    assert "Backend: gpu" in lines
    assert "Device: AMD Radeon 890M Graphics (RADV STRIX1)" in lines
    assert "Fallback: none" in lines
    assert "Elapsed: 10.4 s" in lines


def test_a_diverted_backend_is_shown_as_a_difference(notes) -> None:
    lines = notes(
        {"answered_by": "facet", "requested_backend": "gpu", "actual_backend": "cpu"}
    )

    assert "Backend: gpu requested, cpu actual" in lines


def test_an_older_host_reporting_no_engine_is_not_relabelled(notes) -> None:
    """Absent provenance is left as it was, never guessed into a claim."""
    lines = notes({"source": "symbolic"})

    assert lines == ["Source: symbolic", "Facet: not invoked"]


def test_the_settings_wording_matches_what_the_engine_setting_does() -> None:
    messages = json.loads(
        (EXTENSION / "_locales" / "en" / "messages.json").read_text(encoding="utf-8")
    )
    help_text = messages["optionsSolveEngineHelp"]["message"]

    # The old wording said Facet was a separate MathML-only path. It has not
    # been one since the exact solvers started running first.
    assert "MathML-only path" not in help_text
    assert "Exact math runs locally first" in help_text
    assert "decline" in help_text
    # The choice is named for what it selects: what happens after the exact
    # stage, not who answers everything.
    assert messages["optionsSolveEngineEthnos"]["message"] == "Ethnos only"
    assert messages["optionsSolveEngineFacet"]["message"] == "Ethnos, then Facet"
    # SymPy is named as a solver, and nowhere called a model.
    assert messages["optionsPipelineExactValue"]["message"] == "SymPy, on this machine"
    assert "model" not in messages["optionsPipelineExactLabel"]["message"].lower()


def test_the_settings_page_shows_the_pipeline_without_asking_the_network() -> None:
    options_js = (EXTENSION / "options" / "options.js").read_text(encoding="utf-8")
    options_html = (EXTENSION / "options" / "options.html").read_text(encoding="utf-8")
    pipeline = _lift(options_js, "showPipeline")

    for stage in ("pipeline-exact", "pipeline-reasoner", "pipeline-observed"):
        assert f'id="{stage}"' in options_html

    # Rendering a preferences screen must not wake an SSH connection and a
    # model host. Everything shown comes from storage and the stored setting.
    assert "browser.storage.local.get" in pipeline
    for reaching_out in ("askEthnos", "sendNativeMessage", "connectNative", "fetch("):
        assert reaching_out not in pipeline
    # An unobserved reasoner is said to be unobserved rather than assumed.
    assert "optionsPipelineObservedNone" in pipeline
