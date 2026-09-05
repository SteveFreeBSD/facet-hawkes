"""The Facet remote protocol as Ethnos speaks it: the whole of the boundary."""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from ethnos.facet_client import (
    FACET_PROTOCOL_VERSION,
    FACET_SSH_COMMAND,
    FacetExecutionError,
    FacetProtocolError,
    FacetTransportError,
    generate_text,
    safe_request_id,
)

METRICS = {
    "prompt_tokens": 91,
    "generated_tokens": 12,
    "prefill_tps": 504.0,
    "decode_tps": 21.2,
}
EVIDENCE = {
    "source": "ollama /api/ps",
    "loaded_bytes": 13780173824,
    "device_memory_bytes": 13780173824,
    "device_resident_fraction": 1.0,
    "context_length": 16384,
    "quantization": "MXFP4",
}


def facet_result(**changes) -> dict:
    result = {
        "text": "FINAL ANSWER: x^2",
        "requested_backend": "gpu",
        "actual_backend": "gpu",
        "runtime": "Ollama 0.33.2",
        "model": "gpt-oss:20b",
        "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
        "elapsed_ms": 812.5,
        "fallback": False,
        "metrics": dict(METRICS),
        "evidence": dict(EVIDENCE),
    }
    result.update(changes)
    return {name: value for name, value in result.items() if value is not None}


def ok_envelope(request_id: str = "ethnos-test", **changes) -> dict:
    envelope = {
        "facet_protocol_version": FACET_PROTOCOL_VERSION,
        "status": "ok",
        "request_id": request_id,
        "operation": "generate_text",
        "result": facet_result(),
    }
    envelope.update(changes)
    return envelope


def error_envelope(kind: str, message: str = "no", **changes) -> dict:
    envelope = {
        "facet_protocol_version": FACET_PROTOCOL_VERSION,
        "status": "error",
        "request_id": "ethnos-test",
        "error": {"kind": kind, "message": message},
    }
    envelope.update(changes)
    return envelope


def answering(monkeypatch, envelope, *, returncode: int = 0, stderr: str = ""):
    """Stand in for the SSH call, and record exactly how it was invoked."""
    seen: dict = {}
    stdout = envelope if isinstance(envelope, str) else json.dumps(envelope)

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(argv, returncode, stdout, stderr)

    monkeypatch.setattr("ethnos.facet_client.subprocess.run", fake_run)
    return seen


def ask(**changes):
    call = {"request_id": "ethnos-test", "accelerator_required": True}
    call.update(changes)
    prompt = call.pop("prompt", "Solve x^2.")
    return generate_text(prompt, **call)


def test_a_valid_exchange_returns_a_typed_result(monkeypatch) -> None:
    answering(monkeypatch, ok_envelope())

    result = ask()

    assert result.text == "FINAL ANSWER: x^2"
    assert result.actual_backend == "gpu"
    assert result.runtime == "Ollama 0.33.2"
    assert result.model == "gpt-oss:20b"
    assert "Radeon 890M" in result.device
    assert result.elapsed_ms == 812.5
    assert result.fallback is False


def test_metrics_and_evidence_survive_the_boundary(monkeypatch) -> None:
    answering(monkeypatch, ok_envelope())

    result = ask()

    assert result.metrics == METRICS
    assert result.evidence == EVIDENCE


def test_the_request_is_versioned_and_states_a_constraint(monkeypatch) -> None:
    seen = answering(monkeypatch, ok_envelope())

    ask()

    sent = json.loads(seen["kwargs"]["input"])
    assert sent["facet_protocol_version"] == FACET_PROTOCOL_VERSION
    assert sent["operation"] == "generate_text"
    assert sent["request_id"] == "ethnos-test"
    assert sent["constraints"] == {
        "accelerator_required": True,
        "allow_fallback": False,
    }
    # The constraint is a need. Nothing names a device, a model, or a machine.
    assert "gpu" not in json.dumps(sent).lower()
    assert set(sent) == {
        "facet_protocol_version",
        "operation",
        "request_id",
        "prompt",
        "constraints",
    }


def test_the_prompt_never_enters_argv_and_no_shell_is_used(monkeypatch) -> None:
    seen = answering(monkeypatch, ok_envelope())
    prompt = "Simplify $(touch /tmp/never) ; `id` && echo nope."

    ask(prompt=prompt)

    assert tuple(seen["argv"]) == FACET_SSH_COMMAND
    assert prompt not in " ".join(seen["argv"])
    assert json.loads(seen["kwargs"]["input"])["prompt"] == prompt
    assert seen["kwargs"]["shell"] is False


def test_the_ssh_argv_is_a_constant_that_forwards_nothing() -> None:
    argv = list(FACET_SSH_COMMAND)

    assert argv[0] == "ssh"
    assert "-o" in argv and "BatchMode=yes" in argv
    assert "ClearAllForwardings=yes" in argv
    assert "-T" in argv
    # One fixed remote program, named absolutely, with no shell metacharacters
    # and no arguments of its own for anything to smuggle a request into.
    helper = argv[-1]
    assert helper.startswith("/") and " " not in helper
    assert not any(character in helper for character in ";|&$`<>()")


def test_the_transport_target_may_be_overridden_by_the_environment() -> None:
    environment = os.environ.copy()
    environment["FACET_SSH_TARGET"] = "steve@100.105.86.101"

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from ethnos.facet_client import FACET_SSH_COMMAND; "
            "print(FACET_SSH_COMMAND[-2])",
        ],
        text=True,
        capture_output=True,
        check=True,
        env=environment,
    )

    assert completed.stdout.strip() == "steve@100.105.86.101"


@pytest.mark.parametrize(
    "candidate",
    ["req 1", "req;rm -rf /", "req\n2", "../../etc/passwd", "", "x" * 300, "réq"],
)
def test_a_browser_supplied_id_is_reduced_before_it_crosses(candidate: str) -> None:
    request_id = safe_request_id(candidate)

    assert 1 <= len(request_id) <= 64
    assert request_id.startswith("ethnos-")
    assert all(character.isalnum() or character in "._:-" for character in request_id)


@pytest.mark.parametrize(
    "kind",
    [
        "invalid_request",
        "unsupported_version",
        "unsupported_operation",
        "constraint_unsatisfied",
        "execution_failed",
        "internal_error",
    ],
)
def test_every_structured_failure_raises_rather_than_answering(
    monkeypatch, kind: str
) -> None:
    answering(monkeypatch, error_envelope(kind, "the reason"), returncode=1)

    with pytest.raises(FacetExecutionError) as raised:
        ask()

    assert raised.value.kind == kind
    assert raised.value.detail == "the reason"


def test_an_error_is_an_error_even_when_the_helper_exits_zero(monkeypatch) -> None:
    # Status is authoritative. A helper bug must not turn a refusal into an
    # answer, so the exit code is never the thing that decides.
    answering(monkeypatch, error_envelope("execution_failed"), returncode=0)

    with pytest.raises(FacetExecutionError):
        ask()


def test_success_claimed_alongside_a_failed_exit_is_not_believed(
    monkeypatch,
) -> None:
    answering(monkeypatch, ok_envelope(), returncode=1)

    with pytest.raises(FacetProtocolError, match="claimed success"):
        ask()


@pytest.mark.parametrize("version", [0, 1, 3, "2", 2.5, True, None])
def test_a_reply_in_another_protocol_version_is_refused(monkeypatch, version) -> None:
    answering(monkeypatch, ok_envelope(facet_protocol_version=version))

    with pytest.raises(FacetProtocolError, match="protocol"):
        ask()


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        ("not json", "malformed JSON"),
        ("[]", "not an object"),
        ('"text"', "not an object"),
    ],
)
def test_a_malformed_reply_fails_closed(monkeypatch, stdout, message) -> None:
    answering(monkeypatch, stdout)

    with pytest.raises(FacetProtocolError, match=message):
        ask()


@pytest.mark.parametrize(
    "field",
    [
        "text",
        "requested_backend",
        "actual_backend",
        "runtime",
        "model",
        "device",
        "elapsed_ms",
        "fallback",
        "metrics",
        "evidence",
    ],
)
def test_every_required_result_field_is_required(monkeypatch, field: str) -> None:
    answering(monkeypatch, ok_envelope(result=facet_result(**{field: None})))

    with pytest.raises(FacetProtocolError, match=f"omitted {field}"):
        ask()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("text", ""),
        ("text", 7),
        ("model", "   "),
        ("device", ["a"]),
        ("elapsed_ms", "812"),
        ("elapsed_ms", -1),
        ("elapsed_ms", True),
        ("fallback", "false"),
        ("fallback", 0),
        ("metrics", "none"),
        ("evidence", []),
    ],
)
def test_every_required_result_field_is_type_checked(
    monkeypatch, field: str, value
) -> None:
    answering(monkeypatch, ok_envelope(result=facet_result(**{field: value})))

    with pytest.raises(FacetProtocolError, match=f"omitted {field}"):
        ask()


def test_a_later_facet_may_report_more_than_this_client_reads(monkeypatch) -> None:
    """Additive response fields are a compatible change, not a failed solve."""
    answering(
        monkeypatch,
        ok_envelope(
            queued_ms=4,  # a new envelope field
            result=facet_result(
                energy_joules=18.2,  # a new result field
                metrics={**METRICS, "cache_hit_tokens": 64},
                evidence={**EVIDENCE, "npu_lock": "/dev/accel/accel0"},
            ),
        ),
    )

    result = ask()

    assert result.text == "FINAL ANSWER: x^2"
    assert result.metrics["cache_hit_tokens"] == 64
    assert result.evidence["npu_lock"] == "/dev/accel/accel0"


def test_a_reply_to_a_different_request_is_refused(monkeypatch) -> None:
    answering(monkeypatch, ok_envelope(request_id="somebody-else"))

    with pytest.raises(FacetProtocolError, match="different request"):
        ask()


def test_a_reply_about_a_different_operation_is_refused(monkeypatch) -> None:
    answering(monkeypatch, ok_envelope(operation="inspect_image"))

    with pytest.raises(FacetProtocolError, match="different operation"):
        ask()


@pytest.mark.parametrize("status", ["", "partial", "ok ", None, True])
def test_an_unknown_status_is_never_read_as_success(monkeypatch, status) -> None:
    answering(monkeypatch, ok_envelope(status=status))

    with pytest.raises(FacetProtocolError, match="unknown status"):
        ask()


def test_a_failure_without_a_structured_reason_is_still_a_failure(
    monkeypatch,
) -> None:
    answering(monkeypatch, error_envelope("execution_failed", error="just a string"))

    with pytest.raises(FacetProtocolError, match="structured reason"):
        ask()


def test_a_fallback_the_request_forbade_is_refused(monkeypatch) -> None:
    """Facet already refuses this; the consumer that asked checks it too."""
    answering(monkeypatch, ok_envelope(result=facet_result(fallback=True)))

    with pytest.raises(FacetProtocolError, match="fallback"):
        ask()

    answering(monkeypatch, ok_envelope(result=facet_result(fallback=True)))
    assert ask(allow_fallback=True).fallback is True


def test_an_unreachable_host_is_a_transport_failure(monkeypatch) -> None:
    answering(monkeypatch, "", returncode=255, stderr="ssh: connect: no route")

    with pytest.raises(FacetTransportError, match="no route"):
        ask()


def test_a_transport_that_never_started_is_a_transport_failure(monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise OSError("ssh is not installed")

    monkeypatch.setattr("ethnos.facet_client.subprocess.run", refuse)

    with pytest.raises(FacetTransportError, match="not installed"):
        ask()


def test_a_timeout_is_a_transport_failure(monkeypatch) -> None:
    def stall(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("ssh", 190.0)

    monkeypatch.setattr("ethnos.facet_client.subprocess.run", stall)

    with pytest.raises(FacetTransportError):
        ask()


@pytest.mark.parametrize(
    ("prompt", "message"),
    [("", "non-empty"), ("   ", "non-empty"), ("x" * 12_500, "size limit")],
)
def test_a_request_this_client_cannot_honour_never_reaches_the_wire(
    monkeypatch, prompt, message
) -> None:
    monkeypatch.setattr(
        "ethnos.facet_client.subprocess.run",
        lambda *_a, **_k: pytest.fail("a rejected request reached the transport"),
    )

    with pytest.raises(FacetProtocolError, match=message):
        ask(prompt=prompt)


def test_an_id_this_client_would_not_have_made_never_reaches_the_wire(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ethnos.facet_client.subprocess.run",
        lambda *_a, **_k: pytest.fail("a rejected request reached the transport"),
    )

    with pytest.raises(FacetProtocolError, match="request_id"):
        ask(request_id="not a valid id")


def test_an_oversized_reply_is_refused(monkeypatch) -> None:
    answering(monkeypatch, "x" * (1024 * 1024 + 1))

    with pytest.raises(FacetProtocolError, match="size limit"):
        ask()
