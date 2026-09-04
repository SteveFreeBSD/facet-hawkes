"""Ethnos client for the Facet remote protocol v1.

Ethnos owns the question: the browser work, the exact solvers, retrieval, the
prompt, and what to do with an answer. Facet owns the execution: which runtime,
which processor, the metrics, and the evidence that the work ran where Facet
says it ran. This module is the whole of the boundary between them, and nothing
Hawkes-specific belongs in it.

A caller states a *constraint* -- "this must not run on a CPU", "do not accept
a fallback" -- and receives a typed result carrying the provenance Facet
measured. It never names a host, a runtime, a model, or a device: which
accelerator satisfies a constraint is Facet's decision to make and Facet's to
report, so this client keeps working when Facet later routes differently.

A request that cannot be met raises. It never degrades into a local answer:
a silent substitution would leave a Facet-shaped provenance on work Facet never
did, which is worse than no answer at all.

The transport is one SSH invocation of a fixed remote helper with the request
on standard input. The argv is a constant. No part of a prompt, a host, a path,
a model, or a device is ever assembled from caller input, so there is nothing
in a request for a shell to interpret and no way for one to ask for a different
program.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

FACET_PROTOCOL_VERSION = 1

#: Operations this client knows how to ask for. Facet enforces its own closed
#: set; this one exists so a typo here fails locally rather than remotely.
FACET_OPERATIONS: tuple[str, ...] = ("generate_text",)

# Deployment configuration: the only two lines in Ethnos that know where Facet
# runs today. Nothing in the protocol or in any caller depends on them, so
# moving Facet to another machine is an edit here and nothing else.
FACET_SSH_TARGET = "steve@192.168.0.247"
FACET_REMOTE_HELPER = "/home/steve/.local/bin/facet-remote"

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
    prompt: str,
    *,
    accelerator_required: bool,
    allow_fallback: bool,
) -> str:
    if operation not in FACET_OPERATIONS:
        raise FacetProtocolError(f"{operation} is not a Facet operation")
    if not REQUEST_ID_PATTERN.match(request_id):
        raise FacetProtocolError("request_id is not in the shape Facet accepts")
    if not prompt.strip():
        raise FacetProtocolError("prompt must be a non-empty string")
    if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
        raise FacetProtocolError("prompt exceeds the Facet protocol size limit")
    return json.dumps(
        {
            "facet_protocol_version": FACET_PROTOCOL_VERSION,
            "operation": operation,
            "request_id": request_id,
            "prompt": prompt,
            "constraints": {
                "accelerator_required": accelerator_required,
                "allow_fallback": allow_fallback,
            },
        },
        separators=(",", ":"),
    )


def _envelope(stdout: str) -> dict[str, Any]:
    if len(stdout.encode("utf-8")) > MAX_RESPONSE_BYTES:
        raise FacetProtocolError("Facet response exceeded the size limit")
    try:
        envelope = json.loads(stdout)
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


def _interpret(
    completed: subprocess.CompletedProcess[str],
    *,
    operation: str,
    request_id: str,
    allow_fallback: bool,
) -> FacetResult:
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
    parsed = _result(result)
    # Facet already refuses this. Ethnos asked for it, so Ethnos checks it too:
    # the one provenance claim a consumer can verify, it should verify.
    if parsed.fallback and not allow_fallback:
        raise FacetProtocolError("Facet reported a fallback this request forbade")
    return parsed


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
    operation = "generate_text"
    payload = _request_payload(
        operation,
        request_id,
        prompt,
        accelerator_required=accelerator_required,
        allow_fallback=allow_fallback,
    )
    try:
        completed = subprocess.run(
            FACET_SSH_COMMAND,
            input=payload,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise FacetTransportError(f"Facet SSH transport failed: {error}") from error
    return _interpret(
        completed,
        operation=operation,
        request_id=request_id,
        allow_fallback=allow_fallback,
    )
