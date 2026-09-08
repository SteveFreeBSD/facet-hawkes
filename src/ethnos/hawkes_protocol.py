"""Versioned messages between the Firefox add-on and the Ethnos native host.

The browser may ask only for named operations. It cannot pass a shell command,
a filesystem path, a model name, a URL, or a Python expression: every field
below is either an enumerated operation or opaque problem content, and the host
chooses its own models and paths from settings.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .hawkes_graph import GraphPlan, PointPlotPlan, GraphPoint

PROTOCOL_VERSION = 1

# Firefox caps a native message at 1 MB in each direction. A full-page PNG
# screenshot base64-encodes well under that, but the limit is enforced rather
# than assumed so an oversized payload fails loudly at the boundary.
MAX_MESSAGE_BYTES = 1024 * 1024


class GraphContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    family: Literal["parabola", "points"]
    #: A parabola states which way it opens. A set of points has no orientation.
    orientation: Literal["vertical"] | None = None
    bounds: list[float] = Field(min_length=4, max_length=4)
    snap: list[float] = Field(min_length=2, max_length=2)
    controls: Literal["vertex-and-symmetric-points", "draggable-points"]
    #: How many draggable controls a plotting graph offers, one per point.
    count: int | None = None

    @model_validator(mode="after")
    def valid_grid(self) -> GraphContext:
        if (
            self.bounds[0] >= self.bounds[1]
            or self.bounds[2] >= self.bounds[3]
            or min(self.snap) <= 0
        ):
            raise ValueError("graph requires ordered bounds and positive snap")
        # Each family states its own controls, and neither may borrow the
        # other's: a plan is proved against the geometry named here.
        if self.family == "parabola" and (
            self.orientation is None or self.controls != "vertex-and-symmetric-points"
        ):
            raise ValueError("a parabola states an orientation and its own controls")
        if self.family == "points" and (
            self.controls != "draggable-points"
            or self.count is None
            or not 1 <= self.count <= 12
        ):
            raise ValueError("a plotting graph states one control per stated point")
        return self


class AnswerRepresentation(BaseModel):
    """One mathematical representation the answer surface requires.

    This is deliberately not an editor description.  A signed integer and its
    maximum written length can change which equivalent form answers a question;
    selectors, templates, slots, and allowed-character patterns cannot cross.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["signed-integer"]
    maxLength: int = Field(ge=1, le=40)


#: How many separate values one question may ask for, on this wire.
#:
#: Named here as well as in `facet_client`, and asserted equal by the tests:
#: the two are different boundaries -- browser to host, host to Facet -- and a
#: request the browser is allowed to make that the next hop refuses is a
#: refusal with nobody's name on it.
MAX_ANSWER_PARTS = 5

#: How many alternatives one choice question may publish, and how long each
#: may be. Bounded here because the page decides both and this is the boundary.
MAX_ANSWER_CHOICES = 12
MAX_CHOICE_CHARS = 120


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
    caret goes -- stays on the browser side. A normalized representation may
    cross because it does change the form Facet must return: a question whose
    answer surface accepts only a signed integer must not receive a fraction.

    What the shape *means* is decided by the host, not here. A single box is
    still a two-value answer when the question says to separate them with a
    comma, and reading that out of the instruction is Ethnos's job.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["field", "option", "multi", "graph"] = "field"
    count: int = Field(default=1, ge=1, le=MAX_ANSWER_PARTS)
    graph: GraphContext | None = None
    representations: list[AnswerRepresentation] = Field(
        default_factory=list, max_length=MAX_ANSWER_PARTS
    )
    #: What an option question may be answered with, in the page's own words.
    #:
    #: The question's own alternatives, which is a property of the question in
    #: the same way its expressions are -- not a description of the page. A
    #: choice answer is *matched* against these rather than typed, so they are
    #: the whole contract: an answer that is not one of them selects nothing.
    #: Absent unless the add-on could read the whole group; a partial list
    #: would let a solver answer with one of four choices on a page showing
    #: five.
    choices: list[str] = Field(default_factory=list, max_length=MAX_ANSWER_CHOICES)

    @model_validator(mode="after")
    def count_matches_kind(self) -> AnswerShape:
        if (self.kind == "graph") != (self.graph is not None):
            raise ValueError("graph context must match answer kind")
        if self.kind == "multi" and self.count < 2:
            raise ValueError("a multi answer needs at least two parts")
        if self.kind != "multi" and self.count != 1:
            raise ValueError("only a multi answer may have more than one part")
        if self.representations and len(self.representations) != self.count:
            raise ValueError("answer representations must match the answer count")
        if self.kind in {"option", "graph"} and self.representations:
            raise ValueError("only written answers may name representations")
        if self.choices and self.kind != "option":
            raise ValueError("only an option answer is chosen from alternatives")
        if self.choices:
            if len(self.choices) < 2:
                raise ValueError("a choice is made between at least two alternatives")
            if any(not choice.strip() for choice in self.choices):
                raise ValueError("every alternative must carry words")
            if any(len(choice) > MAX_CHOICE_CHARS for choice in self.choices):
                raise ValueError("an alternative exceeds the size limit")
            if len(set(self.choices)) != len(self.choices):
                raise ValueError("the alternatives must be distinct")
        return self


class DataTable(BaseModel):
    """A table of quantities the question states, as the page wrote it.

    Headings and cells, verbatim. Not a picture of a table, not a flattened
    sentence, and not a description of the page: there is no element here, no
    selector, and no geometry, so what crosses is only what a reader of the
    printed question would have.

    Cells stay strings on purpose. "$56" is a price written in dollars, and
    deciding that it is the number 56 is a reading -- one the host makes, once,
    where it can be checked, rather than one the browser makes silently while
    scraping.
    """

    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=2, max_length=8)
    rows: list[list[str]] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def rectangular(self) -> DataTable:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every row must have one cell per column")
        if any(not name.strip() for name in self.columns):
            raise ValueError("every column must be named")
        if any(len(name) > 80 for name in self.columns):
            raise ValueError("a column name exceeds the size limit")
        if any(not cell.strip() or len(cell) > 40 for row in self.rows for cell in row):
            raise ValueError("every cell must be a short non-empty value")
        return self


class AnswerTableCell(BaseModel):
    """One cell of a table the question is answered in.

    Either a value the page states or a blank the answer goes in, never both
    and never neither. A blank carries its position and nothing else: what is
    currently typed into an answer box is not part of the question, has no
    field on this wire, and is never read.

    A stated value arrives as the page wrote it -- `mathml` when MathJax
    rendered the cell, `text` when it did not. Both are kept rather than
    flattened to one, because a radical sign is drawn and not written: the
    visible glyphs of `2√2` are two digits with nothing between them, and
    reading that cell as text would state a different number confidently.
    """

    model_config = ConfigDict(extra="forbid")

    #: 1-based position among the table's blanks, in the order the page draws
    #: them, so a reply's part N and the page's Nth box mean the same cell.
    blank: int | None = Field(default=None, ge=1, le=MAX_ANSWER_PARTS)
    mathml: str = Field(default="", max_length=4000)
    text: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def one_kind_of_cell(self) -> AnswerTableCell:
        stated = bool(self.mathml.strip()) or bool(self.text.strip())
        if (self.blank is None) == (not stated):
            raise ValueError("a cell is a stated value or a blank, never both")
        if self.mathml.strip() and self.text.strip():
            raise ValueError("a stated value is written one way, not two")
        return self


class AnswerTable(BaseModel):
    """The table a completion question is answered in.

    The same reading as `DataTable`, of the table on the other side of the
    answer line: a completion question draws its grid, states a value in some
    cells and leaves an answer box in the rest. Both halves are the question --
    without the givens there is nothing to complete -- and the relationship
    between them is the grid, so it is carried as one rather than as a list of
    numbers and a count of boxes.

    No element, no selector, no geometry, and no field ids. Which box a part is
    typed into stays in the browser; what crosses is which *cell* it is.
    """

    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(min_length=2, max_length=8)
    rows: list[list[AnswerTableCell]] = Field(min_length=2, max_length=32)

    @model_validator(mode="after")
    def rectangular_and_numbered(self) -> AnswerTable:
        if any(len(row) != len(self.columns) for row in self.rows):
            raise ValueError("every row must have one cell per column")
        if any(not name.strip() for name in self.columns):
            raise ValueError("every column must be named")
        if any(len(name) > 80 for name in self.columns):
            raise ValueError("a column name exceeds the size limit")
        blanks = [cell.blank for row in self.rows for cell in row if cell.blank]
        if not blanks:
            raise ValueError("a table answered by completing it has a blank in it")
        # Numbered from one, in order, with none missing and none repeated. A
        # gap here would mean a part with no cell to belong to.
        if blanks != list(range(1, len(blanks) + 1)):
            raise ValueError("blanks must be numbered from one, in reading order")
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
    #: The question's own data table, when it stated its numbers in one. Like
    #: `mathml`, this is the page saying what the question is rather than the
    #: host reading it back off a picture.
    data_table: DataTable | None = None
    #: The table the question is answered *in*, when it is answered by
    #: completing one. Disjoint from `data_table` by construction: one is the
    #: table that holds no answer control and the other is the table that does.
    answer_table: AnswerTable | None = None
    #: How the page will take the answer. Absent when the add-on did not say,
    #: which is read as the single-box shape every earlier version implied.
    answer_shape: AnswerShape | None = None


class SolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol_version: Literal[1] = PROTOCOL_VERSION
    operation: Literal["health", "solve_hawkes_problem"]
    request_id: str = Field(max_length=64)
    origin: str = Field(default="", max_length=200)
    #: Which pipeline answers this question. `facet` is the routed solver --
    #: exact mathematics, reasoning, and the graph specialists, all decided by
    #: Facet -- and is the default because it is the architecture: a caller that
    #: says nothing should get how questions are answered now, not how they were
    #: answered before the routing moved. `ethnos` remains the wire name for the
    #: companion's own reader, which answers a question stated as a picture
    #: rather than as mathematics. It is a capability, not a product choice, and
    #: the browser no longer offers it as one.
    solve_engine: Literal["ethnos", "facet"] = "facet"
    problem: ProblemPayload | None = None


class AnswerPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    graph_plan: GraphPlan | PointPlotPlan | None = None
    graph_coefficients: list[str] = Field(default_factory=list, max_length=3)
    display_text: str = ""
    keyboard_entry: str = ""
    # Distinct values for a multi-value answer. Keeping these structured avoids
    # recovering mathematical boundaries from display prose later.
    parts: list[str] = Field(default_factory=list, max_length=MAX_ANSWER_PARTS)


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
    #: The reply cardinality Ethnos required when it called Facet. This is a
    #: structural boundary fact, not an answer: it proves that a five-control
    #: page reached Facet as five requested parts rather than collapsing on
    #: either side of the native-host boundary.
    answer_parts: int | None = Field(default=None, ge=1, le=MAX_ANSWER_PARTS)
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
    #: transcribed from a picture of it. `table` is the page's own data table,
    #: read as a table -- exact in the same way `mathml` is, and for the same
    #: reason: the page wrote it down and nothing had to look at pixels.
    reading: Literal["mathml", "screenshot", "svg", "table"] | None = None
    #: The named method behind the answer -- a solver's name when `answered_by`
    #: is `exact`, a model's name otherwise. Never a model name for a solver.
    method: str = ""
    #: Whether Facet was asked at all. False on the companion's own image
    #: path, which is the only route that does not reach Facet.
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
