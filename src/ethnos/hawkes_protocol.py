"""Versioned messages between the Firefox add-on and the Ethnos native host.

The browser may ask only for named operations. It cannot pass a shell command,
a filesystem path, a model name, a URL, or a Python expression: every field
below is either an enumerated operation or opaque problem content, and the host
chooses its own models and paths from settings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .hawkes_graph import GraphPlan, GraphPoint

PROTOCOL_VERSION = 1

# Firefox caps a native message at 1 MB in each direction. A full-page PNG
# screenshot base64-encodes well under that, but the limit is enforced rather
# than assumed so an oversized payload fails loudly at the boundary.
MAX_MESSAGE_BYTES = 1024 * 1024


class GraphContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    family: Literal["parabola"]
    orientation: Literal["vertical"]
    bounds: list[float] = Field(min_length=4, max_length=4)
    snap: list[float] = Field(min_length=2, max_length=2)
    controls: Literal["vertex-and-symmetric-points"]

    @model_validator(mode="after")
    def valid_grid(self) -> GraphContext:
        if (
            self.bounds[0] >= self.bounds[1]
            or self.bounds[2] >= self.bounds[3]
            or min(self.snap) <= 0
        ):
            raise ValueError("graph requires ordered bounds and positive snap")
        return self


class AnswerShape(BaseModel):
    """How the page takes an answer, as the add-on observed it.

    Deliberately one enumerated word rather than a description of the page.
    The add-on already normalises every Hawkes answer control it supports into
    one of these four, and this is the only distinction that changes what an
    answer has to *be*: a single box takes one value, a multi-value question
    takes the reported number of values, and an option question is answered by
    choosing rather than by typing. A graph carries normalized geometry bounds
    and snap spacing. Everything else about the page -- which
    field, what characters it accepts, which templates it offers, where the
    caret goes -- stays on the browser side, because none of it changes the
    mathematics.

    What the shape *means* is decided by the host, not here. A single box is
    still a two-value answer when the question says to separate them with a
    comma, and reading that out of the instruction is Ethnos's job.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["field", "option", "multi", "graph"] = "field"
    count: int = Field(default=1, ge=1, le=4)
    graph: GraphContext | None = None

    @model_validator(mode="after")
    def count_matches_kind(self) -> AnswerShape:
        if (self.kind == "graph") != (self.graph is not None):
            raise ValueError("graph context must match answer kind")
        if self.kind == "multi" and self.count < 2:
            raise ValueError("a multi answer needs at least two parts")
        if self.kind != "multi" and self.count != 1:
            raise ValueError("only a multi answer may have more than one part")
        return self


class ProblemPayload(BaseModel):
    """What the add-on saw. Every field is optional except the screenshot."""

    model_config = ConfigDict(extra="forbid")

    prompt_text: str = Field(default="", max_length=4000)
    question_label: str = Field(default="", max_length=200)
    screenshot_png_base64: str = Field(default="", max_length=MAX_MESSAGE_BYTES)
    # Presentation MathML read from the page. When present the question needs
    # no transcription at all: it is exact, and costs nothing.
    mathml: list[str] = Field(default_factory=list, max_length=8)
    graph_points: list[GraphPoint] = Field(default_factory=list, max_length=32)
    #: How the page will take the answer. Absent when the add-on did not say,
    #: which is read as the single-box shape every earlier version implied.
    answer_shape: AnswerShape | None = None


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = PROTOCOL_VERSION
    operation: Literal["health", "solve_hawkes_problem"]
    request_id: str = Field(max_length=64)
    origin: str = Field(default="", max_length=200)
    solve_engine: Literal["ethnos", "facet"] = "ethnos"
    problem: ProblemPayload | None = None


class AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_plan: GraphPlan | None = None
    graph_coefficients: list[str] = Field(default_factory=list, max_length=3)
    display_text: str = ""
    keyboard_entry: str = ""
    # Distinct values for a multi-value answer. Keeping these structured avoids
    # recovering mathematical boundaries from display prose later.
    parts: list[str] = Field(default_factory=list, max_length=4)


class Certainty(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = ""
    transcription: str = ""
    insertable: bool = False
    issues: list[str] = Field(default_factory=list)
    #: Whether the page's own instruction reached the host. When it did not,
    #: no exact operation can match and the answer necessarily comes from a
    #: model reading the picture with no statement of what to do -- the least
    #: reliable configuration this add-on has. Reported so the panel can say
    #: so, because a solve made that way is otherwise indistinguishable from
    #: one made from a well-posed question.
    prompt_seen: bool = True
    #: Which engine's answer this is. `exact` is SymPy and the polynomial
    #: solver -- deterministic, checkable, and not a model. `facet` is the
    #: remote reasoner. `model` is the local vision-and-model fallback. Kept
    #: separate from `method` so a reader is never left inferring whether a
    #: named thing was a solver or a language model.
    answered_by: Literal["exact", "facet", "model"] | None = None
    #: What the deterministic stage did before anything else was asked. This
    #: is the router's own account: `solved` means nothing further ran at all.
    router: Literal["solved", "declined", "not-run"] | None = None
    #: Why the exact stage declined, in the words the host already uses.
    router_detail: str = ""
    #: How the question itself reached Ethnos: read from the page's markup, or
    #: transcribed from a picture of it.
    reading: Literal["mathml", "screenshot", "svg"] | None = None
    #: The named method behind the answer -- a solver's name when `answered_by`
    #: is `exact`, a model's name otherwise. Never a model name for a solver.
    method: str = ""
    #: Whether Facet was asked at all. False on an exact solve even when Facet
    #: was the selected engine, because it genuinely was not called.
    facet_invoked: bool = False
    #: What Ethnos required of Facet, and what Facet reported doing. Both are
    #: carried because a difference between them is the thing worth seeing.
    requested_backend: str | None = None
    actual_backend: str | None = None
    #: Facet's own fallback claim. None when Facet did not run.
    fallback: bool | None = None
    model: str | None = None
    runtime: str | None = None
    device: str | None = None
    elapsed_ms: float | None = None


class SolveProgress(BaseModel):
    """Sent while a solve runs, so the panel can say what is happening.

    A solve takes the better part of a minute, almost all of it in the two
    independent image readings. Reporting each stage is the difference between
    a progress line and a frozen one.
    """

    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = PROTOCOL_VERSION
    request_id: str = ""
    kind: Literal["progress"] = "progress"
    stage: Literal["reading", "checking", "solving", "done"]
    detail: str = ""


class SolveResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = PROTOCOL_VERSION
    request_id: str = ""
    status: Literal["ready", "ambiguous", "unsupported", "error", "ok"]
    message: str = ""
    problem_text: str = ""
    answer: AnswerPayload | None = None
    certainty: Certainty | None = None


def error_response(
    request_id: str,
    message: str,
    status: Literal["ambiguous", "unsupported", "error"] = "error",
) -> SolveResponse:
    """A refusal that carries no answer, so the add-on cannot insert from it."""
    return SolveResponse(request_id=request_id, status=status, message=message)
