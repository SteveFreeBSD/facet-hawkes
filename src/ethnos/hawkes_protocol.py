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


class ProblemPayload(BaseModel):
    """What the add-on saw. Every field is optional except the screenshot."""

    model_config = ConfigDict(extra="forbid")

    prompt_text: str = Field(default="", max_length=4000)
    question_label: str = Field(default="", max_length=200)
    screenshot_png_base64: str = Field(default="", max_length=MAX_MESSAGE_BYTES)
    # Presentation MathML read from the page. When present the question needs
    # no transcription at all: it is exact, and costs nothing.
    mathml: list[str] = Field(default_factory=list, max_length=8)


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = PROTOCOL_VERSION
    operation: Literal["health", "solve_hawkes_problem"]
    request_id: str = Field(max_length=64)
    origin: str = Field(default="", max_length=200)
    problem: ProblemPayload | None = None


class AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_text: str = ""
    keyboard_entry: str = ""


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
