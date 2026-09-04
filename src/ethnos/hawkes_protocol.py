"""Versioned messages between the Firefox add-on and the Ethnos native host.

The browser may ask only for named operations. It cannot pass a shell command,
a filesystem path, a model name, a URL, or a Python expression: every field
below is either an enumerated operation or opaque problem content, and the host
chooses its own models and paths from settings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1

# Firefox caps a native message at 1 MB in each direction. A full-page PNG
# screenshot base64-encodes well under that, but the limit is enforced rather
# than assumed so an oversized payload fails loudly at the boundary.
MAX_MESSAGE_BYTES = 1024 * 1024


class AnswerShape(BaseModel):
    """How the page takes an answer, as the add-on observed it.

    Deliberately one enumerated word rather than a description of the page.
    The add-on already normalises every Hawkes answer control it supports into
    one of these three, and this is the only distinction that changes what an
    answer has to *be*: a single box takes one value, a paired `y = [] or []`
    editor takes two, and an option question is answered by choosing rather
    than by typing. Everything else about the page -- which field, what
    characters it accepts, which templates it offers, where the caret goes --
    stays on the browser side, because none of it changes the mathematics.

    What the shape *means* is decided by the host, not here. A single box is
    still a two-value answer when the question says to separate them with a
    comma, and reading that out of the instruction is Ethnos's job.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["field", "option", "pair"] = "field"


class ProblemPayload(BaseModel):
    """What the add-on saw. Every field is optional except the screenshot."""

    model_config = ConfigDict(extra="forbid")

    prompt_text: str = Field(default="", max_length=4000)
    question_label: str = Field(default="", max_length=200)
    screenshot_png_base64: str = Field(default="", max_length=MAX_MESSAGE_BYTES)
    # Presentation MathML read from the page. When present the question needs
    # no transcription at all: it is exact, and costs nothing.
    mathml: list[str] = Field(default_factory=list, max_length=8)
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

    display_text: str = ""
    keyboard_entry: str = ""
    # Distinct values for the one currently supported multi-editor shape:
    # two roots separated by Hawkes' visible "or". Keeping these structured
    # avoids recovering mathematical boundaries from display prose later.
    parts: list[str] = Field(default_factory=list, max_length=2)


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
