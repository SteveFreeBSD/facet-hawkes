"""Ethnos client for the Facet remote protocol v2.

Ethnos owns the page: the browser work, the markup capture, which question is
being answered, what shape its answer takes, and what may be typed where. Facet
owns the answering: whether a question is settled by deterministic exact
mathematics or by a reasoning model, which runtime and which processor runs it,
the metrics, and the evidence that the work ran where Facet says it ran. This
module is the whole of the boundary between them, and nothing Hawkes-specific
belongs in it.

There are two ways to cross. `generate_text` runs a prompt Ethnos wrote, and is
what the graph and regression paths use: they need a model to produce a plan
that Ethnos then proves for itself. `solve_math` hands over a *question* --
an instruction, the exact expressions it is about, and how many separate values
its answer takes -- and lets Facet route it. The second is the one that moved:
the exact solvers used to run here and Facet saw only what they declined.

A caller states a *constraint* -- "this must not run on a CPU", "do not accept
a fallback" -- and receives a typed result carrying the provenance Facet
measured. It never names a host, a runtime, a model, or a device: which
accelerator satisfies a constraint is Facet's decision to make and Facet's to
report, so this client keeps working when Facet later routes differently.

A request that cannot be met raises. It never degrades into a local answer:
a silent substitution would leave a Facet-shaped provenance on work Facet never
did, which is worse than no answer at all.

The transport runs one fixed remote helper with the request on standard input.
Normally that helper is a local subprocess: the browser, this native host and
the Facet runtime all live on the same machine, so the arrangement this
replaced -- SSH from that machine back into itself -- bought no isolation and
cost a network hop, a login shell and a key. SSH remains, as an *explicit*
choice for the day Facet genuinely runs somewhere else. It is never reached for
on its own: a local transport that fails is reported as a failure, because
silently crossing a machine boundary nobody asked to cross would put a solve on
hardware the provenance does not describe.

Either way the argv is a constant and `facet-remote` is the process boundary.
No part of a prompt, a host, a path, a model, or a device is ever assembled from
caller input, so there is nothing in a request for a shell to interpret and no
way for one to ask for a different program.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

FACET_PROTOCOL_VERSION = 2

#: Operations this client knows how to ask for. Facet enforces its own closed
#: set; this one exists so a typo here fails locally rather than remotely.
FACET_OPERATIONS: tuple[str, ...] = ("generate_text", "solve_math")

#: The routes Facet may report having taken, and how literally a value it
#: returns must be read. Both are closed sets: a route or a mode this client
#: does not know is a result it cannot safely act on, not one to guess at.
FACET_ROUTES: frozenset[str] = frozenset({"exact", "reasoning"})
FACET_ENTRY_MODES: frozenset[str] = frozenset({"verbatim", "math", "auto"})

#: Which *family* an answer belongs to, beside how literally to read it.
#:
#: A scalar, an ordered pair, several separate values, one chosen alternative.
#: Facet decides what the answer is; Ethnos decides how it is entered, and this
#: is the fact Ethnos needs before it can say whether it has a way to enter it
#: at all. Until it existed the structure had to be recovered by parsing the
#: string, and every new exact family was found to be unenterable only after it
#: was already answering live questions -- see `docs/ANSWER_CAPABILITIES.md`.
#:
#: Additive, and absent on an older Facet. An answer that names no form is read
#: exactly as it always was, so this can never fail a solve on its own.
FACET_ANSWER_FORMS: frozenset[str] = frozenset(
    {"scalar", "ordered-pair", "parts", "choice"}
)

#: What Facet may be asked to produce. `value` is an answer to write down. The
#: other two are *plans*: a proposal Ethnos proves for itself before anything
#: is drawn, and which carry no writable value at all.
VALUE = "value"
PARABOLA_PLAN = "parabola_plan"
QUADRATIC_REGRESSION = "quadratic_regression"
POINT_PLOT_PLAN = "point_plot_plan"
FACET_RESULT_KINDS: frozenset[str] = frozenset(
    {VALUE, PARABOLA_PLAN, QUADRATIC_REGRESSION, POINT_PLOT_PLAN}
)
PLAN_KINDS: frozenset[str] = frozenset(
    {PARABOLA_PLAN, QUADRATIC_REGRESSION, POINT_PLOT_PLAN}
)

#: What the exact route may return. A value, obviously -- and a plotting plan,
#: because a question that states its own pairs has already written the plan
#: down: reading them engages no model and nothing is proposed. Every other
#: plan is a proposal about geometry nobody wrote out, which the exact solvers
#: cannot make, so claiming one was exact would be a false provenance.
EXACTLY_SOLVED_KINDS: frozenset[str] = frozenset({VALUE, POINT_PLOT_PLAN})

#: What the deterministic stage may report having done. `not-run` belongs only
#: to a plan: the exact solvers answer expressions, not geometry, so they were
#: never asked -- which is a different claim from having tried and declined.
FACET_ROUTER_STATES: frozenset[str] = frozenset({"solved", "declined", "not-run"})

#: How many separate values Facet may be asked for, and may return.
#:
#: Four was the shape this was written against -- `x = ___ or ___`, and a
#: quartic's four roots. A table-completion question publishes one control per
#: blank cell, and lesson 2.1's `x = y²` table has five. Must equal
#: `hawkes_protocol.MAX_ANSWER_PARTS`; the tests assert it.
MAX_ANSWER_PARTS = 5
MAX_REGRESSION_POINTS = 32

# Deployment configuration. Nothing in the protocol or in any caller depends
# on where Facet runs; the transport and, for SSH, its address are selected
# before this client starts and are fixed for the whole of its run.

#: The one program either transport executes. It is the runtime, process and
#: protocol boundary: it owns Facet's uv-tool environment, and Ethnos reaches
#: Facet by starting it and writing one request to its standard input --
#: never by importing `facet_runtime` into this process and calling it.
FACET_REMOTE_HELPER = "/home/steve/.local/bin/facet-remote"

#: How that helper is reached. `local` is the normal path and the default;
#: `ssh` is the explicit choice for a Facet that genuinely runs elsewhere.
#: There is no third state and no automatic promotion between these two.
FACET_TRANSPORT_LOCAL = "local"
FACET_TRANSPORT_SSH = "ssh"
FACET_TRANSPORTS: tuple[str, ...] = (FACET_TRANSPORT_LOCAL, FACET_TRANSPORT_SSH)

#: Read only on the SSH transport. The default is casbox's own LAN address, left
#: from the arrangement this replaced; on the default transport nothing reads
#: it. Set it deliberately if a Facet ever genuinely runs elsewhere.
FACET_SSH_TARGET = os.environ.get("FACET_SSH_TARGET", "steve@192.168.0.247")

#: A fixed argv, in full: the helper's absolute path and nothing else. It is a
#: process on this machine, so there is no login shell in the path at all.
FACET_LOCAL_COMMAND: tuple[str, ...] = (FACET_REMOTE_HELPER,)

#: A fixed argv, in full. `BatchMode` refuses to prompt for a credential,
#: `ClearAllForwardings` refuses agent, X11, port and socket forwarding, and
#: `-T` refuses a terminal: this is a pipe to one named program, not a session.
FACET_SSH_COMMAND: tuple[str, ...] = (
    "ssh",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=5",
    "-o",
    "ClearAllForwardings=yes",
    "-T",
    FACET_SSH_TARGET,
    FACET_REMOTE_HELPER,
)


#: Environment names the Facet runtime reads for itself -- which model each
#: backend uses, and where Ollama is. SSH never carried them: the far side got
#: a fresh login environment, so Facet ran on its own configured defaults. A
#: local subprocess inherits everything this process was started with, which
#: would silently hand Facet whatever `FACET_*` happened to be set in the
#: browser's environment and change an answer without changing a request. The
#: local transport therefore strips them, so both transports present Facet with
#: the same configuration surface.
FACET_ENVIRONMENT_PREFIX = "FACET_"

DEFAULT_TIMEOUT_SECONDS = 190.0
MAX_PROMPT_BYTES = 12 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024

REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,64}\Z")

# Text fields every Facet result must carry. `metrics` and `evidence` are
# objects rather than strings and are checked separately.
RESULT_TEXT_FIELDS = (
    "text",
    "requested_backend",
    "actual_backend",
    "runtime",
    "model",
    "device",
)


class FacetError(RuntimeError):
    """Facet did not return a usable result."""


class FacetTransportError(FacetError):
    """The remote helper could not be reached, or never answered."""


class FacetProtocolError(FacetError):
    """A message did not match the contract, in either direction."""


class FacetExecutionError(FacetError):
    """Facet refused the request, or ran and failed."""

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def _selected_transport() -> str:
    """Read the transport once, and refuse a name that is not one of the two.

    Defaulting an unrecognised name to `local` would turn a misspelled `ssh`
    into a silent local run, which is exactly the substitution this transport
    is not allowed to make. An unset variable is not a misspelling, so it takes
    the default; anything else fails before a request is ever built.
    """
    name = os.environ.get("FACET_TRANSPORT", "").strip().lower()
    if not name:
        return FACET_TRANSPORT_LOCAL
    if name not in FACET_TRANSPORTS:
        raise FacetTransportError(
            f"FACET_TRANSPORT={name!r} is not a Facet transport; "
            f"use one of {', '.join(FACET_TRANSPORTS)}"
        )
    return name


#: The transport and the argv this process will use, decided once, before any
#: request exists. A local transport that fails raises; it never becomes an SSH
#: attempt, and SSH never quietly becomes a local one.
FACET_TRANSPORT = _selected_transport()
FACET_COMMAND: tuple[str, ...] = (
    FACET_SSH_COMMAND if FACET_TRANSPORT == FACET_TRANSPORT_SSH else FACET_LOCAL_COMMAND
)


def transport_report() -> dict[str, Any]:
    """What this process would actually run, for a status or an observation.

    A reader of a status line needs the transport that was chosen, not the one
    the documentation assumed: the whole failure this replaced was a topology
    everyone had stopped checking.
    """
    return {
        "transport": FACET_TRANSPORT,
        "helper": FACET_REMOTE_HELPER,
        "command": list(FACET_COMMAND),
        "target": (
            FACET_SSH_TARGET
            if FACET_TRANSPORT == FACET_TRANSPORT_SSH
            else "this machine"
        ),
    }


def _child_environment() -> dict[str, str]:
    """The environment the helper is started with.

    Everything this process holds, less every `FACET_*` name -- see
    `FACET_ENVIRONMENT_PREFIX`. Applied to both transports so that the one
    difference between them stays *where* Facet runs.
    """
    return {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(FACET_ENVIRONMENT_PREFIX)
    }


@dataclass(frozen=True)
class FacetResult:
    """What Facet did, as Facet reported it.

    Everything after `text` is provenance. It is carried whole rather than
    summarised because the point of the boundary is that a consumer can say
    where an answer came from without having to take anyone's word for it.
    """

    text: str
    requested_backend: str
    actual_backend: str
    runtime: str
    model: str
    device: str
    elapsed_ms: float
    fallback: bool
    metrics: dict[str, Any]
    evidence: dict[str, Any]


def safe_request_id(candidate: str, *, prefix: str = "ethnos") -> str:
    """Reduce a caller's identifier to the bounded shape Facet accepts.

    A Hawkes request id reaches Ethnos from the browser, so it is untrusted
    text. Facet would refuse an unexpected one, which would turn a cosmetic
    difference into a failed solve; reducing it here keeps the correlation
    without letting the browser choose what crosses the boundary.
    """
    cleaned = re.sub(r"[^A-Za-z0-9._:-]", "-", candidate)[:48].strip("-.:")
    return f"{prefix}-{cleaned or uuid4().hex[:12]}"


def _request_payload(
    operation: str,
    request_id: str,
    body: dict[str, Any],
    *,
    accelerator_required: bool,
    allow_fallback: bool,
) -> str:
    """Serialise one request, refusing locally what Facet would refuse anyway.

    `body` carries the one field the named operation takes -- a prompt, or a
    problem -- and nothing else. There is no field here through which a caller
    could name a runtime, a model, a device, or a machine, because there is no
    such field in the protocol.
    """
    if operation not in FACET_OPERATIONS:
        raise FacetProtocolError(f"{operation} is not a Facet operation")
    if not REQUEST_ID_PATTERN.match(request_id):
        raise FacetProtocolError("request_id is not in the shape Facet accepts")
    payload = json.dumps(
        {
            "facet_protocol_version": FACET_PROTOCOL_VERSION,
            "operation": operation,
            "request_id": request_id,
            **body,
            "constraints": {
                "accelerator_required": accelerator_required,
                "allow_fallback": allow_fallback,
            },
        },
        separators=(",", ":"),
    )
    if len(payload.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise FacetProtocolError("request exceeds the Facet protocol size limit")
    return payload


def _unique_keys(pairs):
    """Refuse a repeated key anywhere in a response.

    `json.loads` keeps the last of a repeated key silently. A plan naming a
    vertex twice would be read as whichever came last, and nothing after this
    point could tell that a choice had been made on its behalf.
    """
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise FacetProtocolError(f"Facet named {key} more than once")
        seen[key] = value
    return seen


def _envelope(stdout: str) -> dict[str, Any]:
    if len(stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise FacetProtocolError("Facet response exceeded the size limit")
    try:
        envelope = json.loads(stdout, object_pairs_hook=_unique_keys)
    except json.JSONDecodeError as error:
        raise FacetProtocolError("Facet returned malformed JSON") from error
    if not isinstance(envelope, dict):
        raise FacetProtocolError("Facet response was not an object")
    version = envelope.get("facet_protocol_version")
    # `True == 1` in Python, so the type is checked before the value.
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != FACET_PROTOCOL_VERSION
    ):
        raise FacetProtocolError(
            f"Facet answered protocol {version!r}, not {FACET_PROTOCOL_VERSION}"
        )
    return envelope


def _result(payload: dict[str, Any]) -> FacetResult:
    """Read the fields this client requires, and tolerate any others.

    Facet may report more than Ethnos knows how to read; that is a compatible
    change and must not fail a solve. Missing or mistyped *required* fields are
    not compatible, because every one of them is a provenance claim.
    """
    text = {}
    for field in RESULT_TEXT_FIELDS:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise FacetProtocolError(f"Facet result omitted {field}")
        text[field] = value
    elapsed = payload.get("elapsed_ms")
    if (
        not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or elapsed < 0
    ):
        raise FacetProtocolError("Facet result omitted elapsed_ms")
    fallback = payload.get("fallback")
    if not isinstance(fallback, bool):
        raise FacetProtocolError("Facet result omitted fallback")
    metrics, evidence = payload.get("metrics"), payload.get("evidence")
    if not isinstance(metrics, dict):
        raise FacetProtocolError("Facet result omitted metrics")
    if not isinstance(evidence, dict):
        raise FacetProtocolError("Facet result omitted evidence")
    return FacetResult(
        elapsed_ms=float(elapsed),
        fallback=fallback,
        # Passed through whole, so a metric or a proof Ethnos has never heard
        # of still reaches whoever asked for the provenance.
        metrics=dict(metrics),
        evidence=dict(evidence),
        **text,
    )


def _result_object(
    completed: subprocess.CompletedProcess[str], *, operation: str, request_id: str
) -> dict[str, Any]:
    """Read one answered envelope, or raise the reason it is not one."""
    if not completed.stdout.strip():
        detail = completed.stderr.strip()[:400]
        raise FacetTransportError(
            f"Facet returned no response (status {completed.returncode})"
            f"{': ' + detail if detail else ''}"
        )
    envelope = _envelope(completed.stdout)
    status = envelope.get("status")
    # Status is read before the exit code, so a failure can never be mistaken
    # for an answer because a process exited zero.
    if status == "error":
        error = envelope.get("error")
        kind = error.get("kind") if isinstance(error, dict) else None
        detail = error.get("message") if isinstance(error, dict) else None
        if not isinstance(kind, str) or not isinstance(detail, str):
            raise FacetProtocolError("Facet failed without a structured reason")
        raise FacetExecutionError(kind, detail)
    if status != "ok":
        raise FacetProtocolError(f"Facet returned an unknown status {status!r}")
    if completed.returncode != 0:
        raise FacetProtocolError(
            f"Facet claimed success but exited with status {completed.returncode}"
        )
    if envelope.get("request_id") != request_id:
        raise FacetProtocolError("Facet answered a different request")
    if envelope.get("operation") != operation:
        raise FacetProtocolError("Facet answered a different operation")
    result = envelope.get("result")
    if not isinstance(result, dict):
        raise FacetProtocolError("Facet claimed success without a result")
    return result


def _exchange(
    operation: str,
    request_id: str,
    body: dict[str, Any],
    *,
    accelerator_required: bool,
    allow_fallback: bool,
    timeout: float,
) -> dict[str, Any]:
    """Send one request over the fixed transport and return its result object."""
    payload = _request_payload(
        operation,
        request_id,
        body,
        accelerator_required=accelerator_required,
        allow_fallback=allow_fallback,
    )
    try:
        completed = subprocess.run(
            FACET_COMMAND,
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=_child_environment(),
        )
    # A missing helper, an unreachable host and a helper that never answered
    # all arrive here, and all of them stop here. There is no second attempt
    # over the other transport: an answer that came from a machine the caller
    # did not choose would carry a provenance describing hardware the request
    # was never routed to.
    except (OSError, subprocess.SubprocessError) as error:
        raise FacetTransportError(
            f"Facet {FACET_TRANSPORT} transport failed: {error}"
        ) from error
    return _result_object(completed, operation=operation, request_id=request_id)


def generate_text(
    prompt: str,
    *,
    request_id: str,
    accelerator_required: bool = False,
    allow_fallback: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> FacetResult:
    """Execute one bounded intelligence request on Facet, or raise.

    `accelerator_required` is a need, not a device: it says the work must not
    land on a CPU, and leaves the choice of accelerator to Facet.
    """
    if not prompt.strip():
        raise FacetProtocolError("prompt must be a non-empty string")
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise FacetProtocolError("prompt exceeds the Facet protocol size limit")
    parsed = _result(
        _exchange(
            "generate_text",
            request_id,
            {"prompt": prompt},
            accelerator_required=accelerator_required,
            allow_fallback=allow_fallback,
            timeout=timeout,
        )
    )
    # Facet already refuses this. Ethnos asked for it, so Ethnos checks it too:
    # the one provenance claim a consumer can verify, it should verify.
    if parsed.fallback and not allow_fallback:
        raise FacetProtocolError("Facet reported a fallback this request forbade")
    return parsed


@dataclass(frozen=True)
class FacetAnswer:
    """One answer, in the shape the question asked for.

    `kind` says which shape that is, and the shapes do not overlap. A `value`
    answer carries `display`, and exactly one of `entry` or `parts`: there is
    no single string that could be typed into several boxes, and recovering the
    boundary between two answers by splitting display prose afterwards is
    guessing at mathematics after the fact.

    `entry_mode` says how literally to take a value: `verbatim` means it is
    already exactly what belongs in an answer, `math` means it is mathematics
    to be rendered in the consumer's own entry syntax, and `auto` means it is
    mathematics unless it is a plain phrase.

    A plan carries `plan` and nothing else -- no display, no entry, no parts.
    It is a *proposal* about geometry, not an answer, and Ethnos proves it
    against the page's own mathematics before any of it is actuated. Leaving
    room for a value on a plan would let a reasoned proposal arrive shaped
    like a settled answer.
    """

    kind: str
    display: str = ""
    entry: str = ""
    parts: tuple[str, ...] = ()
    entry_mode: str = ""
    #: The answer's family, when Facet named one. Empty from a Facet that
    #: predates the field, which is read as "unnamed" and never as a refusal.
    form: str = ""
    plan: dict[str, Any] | None = None


@dataclass(frozen=True)
class FacetSolution:
    """How Facet answered a question, and what it used to do it.

    `route` is the decision this whole boundary exists to move: `exact` means
    Facet computed the answer with its deterministic solvers and no model ran
    at all; `reasoning` means the deterministic stage declined -- `router_detail`
    says which gap -- and a model answered instead. Everything after `answer`
    is provenance, carried whole so a consumer can say where an answer came
    from without taking anyone's word for it.
    """

    route: str
    answer: FacetAnswer
    source: str
    method: str
    router: str
    router_detail: str
    runtime: str
    model: str | None
    device: str | None
    requested_backend: str | None
    actual_backend: str | None
    elapsed_ms: float
    fallback: bool
    metrics: dict[str, Any]
    evidence: dict[str, Any]


def _required_text(payload: dict[str, Any], field: str, where: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise FacetProtocolError(f"Facet {where} omitted {field}")
    return value


def _optional_text(payload: dict[str, Any], field: str, where: str) -> str | None:
    """A provenance field that is genuinely absent on one of the two routes.

    None is an answer here -- an exact solve used no model and no processor,
    and says so -- but a present-and-empty value is not: that is a claim that
    failed to be made rather than one that does not apply.
    """
    value = payload.get(field, None)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise FacetProtocolError(f"Facet {where} reported an empty {field}")
    return value


def _answer(payload: Any, expected_kind: str) -> FacetAnswer:
    """Read one answer of the kind that was asked for, or refuse it.

    A result of a different kind than the one requested is refused outright.
    Ethnos asked for geometry or for a value, and acting on the other would
    mean acting on an answer to a question nobody asked.
    """
    if not isinstance(payload, dict):
        raise FacetProtocolError("Facet result carried no answer object")
    kind = payload.get("kind")
    if kind not in FACET_RESULT_KINDS:
        raise FacetProtocolError(f"Facet returned an unknown answer kind {kind!r}")
    if kind != expected_kind:
        raise FacetProtocolError(
            f"Facet answered with {kind}, but {expected_kind} was asked for"
        )
    if kind in PLAN_KINDS:
        return _plan_answer(payload, kind)
    display = _required_text(payload, "display", "answer")
    entry = payload.get("entry", "")
    if not isinstance(entry, str):
        raise FacetProtocolError("Facet answer entry was not a string")
    parts = payload.get("parts", [])
    if not isinstance(parts, list) or len(parts) > MAX_ANSWER_PARTS:
        raise FacetProtocolError(
            f"Facet answer carried more than {MAX_ANSWER_PARTS} parts"
        )
    if any(not isinstance(part, str) or not part.strip() for part in parts):
        raise FacetProtocolError("Facet answer carried an empty part")
    mode = payload.get("entry_mode")
    if mode not in FACET_ENTRY_MODES:
        # An unknown mode is an instruction Ethnos cannot follow. Guessing at
        # it would decide, on no evidence, whether to rewrite a value that is
        # about to be typed into a real answer box.
        raise FacetProtocolError(f"Facet answer named an unknown entry_mode {mode!r}")
    if bool(entry.strip()) == bool(parts):
        # Both or neither: either two competing answers, or none at all.
        raise FacetProtocolError(
            "Facet answer must carry exactly one of a single entry or separate parts"
        )
    form = payload.get("form", "")
    # A family this client does not know is a family it has no entry path for,
    # and acting on it as though it were a scalar is how an answer of the wrong
    # shape reaches a real answer box. Absent is different from unknown: an
    # older Facet names no form at all, and that is the behaviour this replaced.
    if form != "" and form not in FACET_ANSWER_FORMS:
        raise FacetProtocolError(f"Facet answer named an unknown form {form!r}")
    return FacetAnswer(
        kind=kind,
        display=display,
        entry=entry,
        parts=tuple(parts),
        entry_mode=mode,
        form=form,
    )


def _plan_answer(payload: dict[str, Any], kind: str) -> FacetAnswer:
    """Read a proposed plan, and refuse one carrying a writable value.

    A plan is proved before it is actuated. A `display`, an `entry` or a
    `parts` list beside one would be a value that skipped that proof, so their
    presence is refused rather than ignored.
    """
    if set(payload) != {"kind", "plan"}:
        raise FacetProtocolError(f"a {kind} result carries only a plan")
    plan = payload["plan"]
    if not isinstance(plan, dict) or not plan:
        raise FacetProtocolError(f"Facet returned no plan for {kind}")
    return FacetAnswer(kind=kind, plan=plan)


def _solution(
    payload: dict[str, Any], *, allow_fallback: bool, expected_kind: str = VALUE
) -> FacetSolution:
    """Read a routed solve, and refuse one that contradicts itself.

    Facet states both which route it took and what that route used. Those two
    claims have to agree: an exact solve naming a model, or a reasoned answer
    naming no processor, is a result whose provenance is wrong, and provenance
    that is wrong about itself may not be trusted about anything else.
    """
    route = payload.get("route")
    if route not in FACET_ROUTES:
        raise FacetProtocolError(f"Facet reported an unknown route {route!r}")
    answer = _answer(payload.get("answer"), expected_kind)
    provenance = payload.get("provenance")
    if not isinstance(provenance, dict):
        raise FacetProtocolError("Facet result carried no provenance")
    router = provenance.get("router")
    if router not in FACET_ROUTER_STATES:
        raise FacetProtocolError(f"Facet reported an unknown router state {router!r}")
    detail = provenance.get("router_detail", "")
    if not isinstance(detail, str):
        raise FacetProtocolError("Facet reported a malformed router_detail")
    elapsed = provenance.get("elapsed_ms")
    if (
        not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or elapsed < 0
    ):
        raise FacetProtocolError("Facet result omitted elapsed_ms")
    fallback = provenance.get("fallback")
    if not isinstance(fallback, bool):
        raise FacetProtocolError("Facet result omitted fallback")
    metrics, evidence = provenance.get("metrics"), provenance.get("evidence")
    if not isinstance(metrics, dict) or not isinstance(evidence, dict):
        raise FacetProtocolError("Facet result omitted metrics or evidence")
    solution = FacetSolution(
        route=route,
        answer=answer,
        source=_required_text(provenance, "source", "provenance"),
        method=_required_text(provenance, "method", "provenance"),
        router=router,
        router_detail=detail,
        runtime=_required_text(provenance, "runtime", "provenance"),
        model=_optional_text(provenance, "model", "provenance"),
        device=_optional_text(provenance, "device", "provenance"),
        requested_backend=_optional_text(provenance, "requested_backend", "provenance"),
        actual_backend=_optional_text(provenance, "actual_backend", "provenance"),
        elapsed_ms=float(elapsed),
        fallback=fallback,
        # Passed through whole, so a metric or a proof Ethnos has never heard
        # of still reaches whoever asked for the provenance.
        metrics=dict(metrics),
        evidence=dict(evidence),
    )
    if route == "exact":
        if router != "solved":
            raise FacetProtocolError("Facet claimed an exact answer it did not solve")
        if solution.model or solution.actual_backend:
            raise FacetProtocolError(
                "Facet claimed an exact answer but named a model or a processor"
            )
        if answer.kind not in EXACTLY_SOLVED_KINDS:
            raise FacetProtocolError(
                f"a {answer.kind} is proposed, not solved, so it cannot be exact"
            )
    else:
        if not solution.model or not solution.actual_backend:
            raise FacetProtocolError(
                "Facet claimed a reasoned answer without naming what reasoned"
            )
        # A value was reasoned because the deterministic stage declined it. A
        # plan was reasoned because there was no deterministic stage to ask.
        # Either claim is fine; the wrong one for the kind is not.
        wanted = "declined" if answer.kind == VALUE else "not-run"
        if router != wanted:
            raise FacetProtocolError(
                f"a reasoned {answer.kind} cannot come from a router that says {router}"
            )
    if fallback and not allow_fallback:
        raise FacetProtocolError("Facet reported a fallback this request forbade")
    return solution


def solve_math(
    *,
    instruction: str,
    request_id: str,
    expressions: list[str] | None = None,
    answer_parts: int = 1,
    label: str = "",
    result_kind: str = VALUE,
    graph: dict[str, Any] | None = None,
    points: list[dict[str, str]] | None = None,
    answer_table: dict[str, Any] | None = None,
    answer_representation: dict[str, Any] | None = None,
    answer_choices: list[str] | None = None,
    accelerator_required: bool = True,
    allow_fallback: bool = False,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> FacetSolution:
    """Hand Facet a question and let Facet decide how it gets answered.

    What crosses is the question and nothing else: the instruction in words,
    the mathematics it is about, how many separate values its answer takes, and
    the question's own label. The mathematics is either exact expressions --
    something somebody wrote down -- or the normalised coordinates of
    measurements nobody wrote a function for; a value question carries exactly
    one of the two. A graph question adds normalised geometry instead: a
    family, an orientation, bounds and a snap grid. There is no field here for
    a document, a page, an element, a picture, or an action, so a caller that
    owns a browser cannot accidentally hand any of it over.

    `result_kind` says what to produce. `value` is an answer to write down; a
    plan is a *proposal*, and proving it stays entirely on this side.

    `answer_parts` is a requirement on the reply -- a property of the question,
    not of the page -- and `accelerator_required` is a need rather than a
    device. Which route answers, and on what, is Facet's to decide and Facet's
    to report.

    `answer_table` is a question that is a grid: the values it states and the
    blanks it asks for, in the columns it names. `answer_representation` is the
    form every separate answer must take. Both are requirements on the reply in
    the same sense `answer_parts` is, and both cross as structure so that the
    side which answers can compute from them and check against them. Neither
    describes a page: there is no field, no control and no character set here.

    `answer_choices` is the same kind of thing again, for a question answered
    by *choosing*: the alternatives the question publishes, in its own words.
    They are the whole contract for such an answer, because a choice is matched
    against them rather than typed -- an answer that is not one of them selects
    nothing. Like a table, they cross as structure: flattened into the
    instruction they could be read by a model and by nothing else, and could
    not be checked against at all.
    """
    if result_kind not in FACET_RESULT_KINDS:
        raise FacetProtocolError(f"{result_kind} is not a Facet result kind")
    if not instruction.strip():
        raise FacetProtocolError("instruction must be a non-empty string")
    problem: dict[str, Any] = {"instruction": instruction}
    if result_kind != VALUE:
        problem["result_kind"] = result_kind
    expressions = list(expressions or [])
    points = list(points or [])
    # A value question is about mathematics somebody wrote down, or about
    # measurements nobody wrote a function for. Both at once is two questions,
    # and neither is none. Facet enforces this too; it is checked here so a
    # caller's mistake fails locally rather than over a transport.
    if result_kind == VALUE and bool(expressions) == bool(points):
        raise FacetProtocolError(
            "a value question is about expressions or about points, not both "
            "and not neither"
        )
    if result_kind == POINT_PLOT_PLAN and expressions:
        problem["expressions"] = expressions
    if result_kind == PARABOLA_PLAN or (result_kind == VALUE and not points):
        if not expressions or any(not item.strip() for item in expressions):
            raise FacetProtocolError("every expression must be non-empty")
        problem["expressions"] = expressions
    if result_kind == VALUE:
        if not 1 <= answer_parts <= MAX_ANSWER_PARTS:
            raise FacetProtocolError(
                f"answer_parts must be 1 to {MAX_ANSWER_PARTS}, not {answer_parts}"
            )
        problem["answer_parts"] = answer_parts
    if result_kind == VALUE and answer_table is not None:
        if not isinstance(answer_table, dict) or set(answer_table) != {
            "columns",
            "rows",
        }:
            raise FacetProtocolError("an answer table is columns and rows")
        blanks = [
            cell.get("blank")
            for row in answer_table["rows"]
            for cell in row
            if isinstance(cell, dict) and "blank" in cell
        ]
        # The grid and the count are two statements of the same fact, and a
        # caller whose two statements disagree has read one of them wrongly.
        # Facet refuses this too; it is checked here so the mistake fails
        # locally rather than over a transport.
        if blanks != list(range(1, answer_parts + 1)):
            raise FacetProtocolError(
                "the table's blanks must be numbered from one, in order, and "
                "match answer_parts"
            )
        problem["answer_table"] = answer_table
    if result_kind == VALUE and answer_choices:
        if len(answer_choices) < 2 or any(
            not isinstance(choice, str) or not choice.strip()
            for choice in answer_choices
        ):
            raise FacetProtocolError(
                "a choice is made between at least two published alternatives"
            )
        # A question answered by choosing has one answer. Facet refuses the
        # pair too; checked here so a caller's mistake fails locally rather
        # than over a transport -- and this is the pair that produced the
        # defect: five alternatives read as five answers.
        if answer_parts != 1:
            raise FacetProtocolError(
                f"a question answered by choosing has one answer, not {answer_parts}"
            )
        problem["answer_choices"] = list(answer_choices)
    if result_kind != VALUE and answer_choices:
        raise FacetProtocolError("only a value question is answered by choosing")
    if result_kind == VALUE and answer_representation is not None:
        if not isinstance(answer_representation, dict) or set(
            answer_representation
        ) != {"kind", "max_length"}:
            raise FacetProtocolError("a representation is a kind and a max_length")
        problem["answer_representation"] = answer_representation
    if result_kind != VALUE and (answer_table or answer_representation):
        # A plan carries no value for anybody to write down, so a requirement
        # on the form of one is a question about something else.
        raise FacetProtocolError("only a value question takes an answer shape")
    if result_kind == PARABOLA_PLAN:
        if not isinstance(graph, dict) or not graph:
            raise FacetProtocolError("a parabola plan needs normalised geometry")
        problem["graph"] = graph
    if result_kind == PARABOLA_PLAN and points:
        # A parabola plan is drawn from a function on a grid. Points are a
        # different question's evidence, and passing them silently would have
        # sent a question Facet reads as being about something else.
        raise FacetProtocolError("a parabola plan is geometry, not measurements")
    if result_kind == QUADRATIC_REGRESSION or (result_kind == VALUE and points):
        if not points or len(points) > MAX_REGRESSION_POINTS:
            raise FacetProtocolError(
                f"a regression takes 1 to {MAX_REGRESSION_POINTS} points"
            )
        if any(set(point) != {"x", "y"} for point in points):
            raise FacetProtocolError("a point is one x and one y")
        problem["points"] = points
    if label.strip():
        problem["label"] = label
    return _solution(
        _exchange(
            "solve_math",
            request_id,
            {"problem": problem},
            accelerator_required=accelerator_required,
            allow_fallback=allow_fallback,
            timeout=timeout,
        ),
        allow_fallback=allow_fallback,
        expected_kind=result_kind,
    )
