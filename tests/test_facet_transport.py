"""Which machine answers a solve, and how that is chosen.

The normal topology is one machine. The browser, the add-on, the native host
and the Facet runtime all run on `casbox`, and until this was written the
request still went `ssh steve@192.168.0.247 facet-remote` -- from casbox, into
casbox. It worked, so nobody looked; it cost a network round trip, a login
shell and a key on every question, and it read as evidence of a second machine
that does not exist.

The local subprocess is the normal path now. SSH is kept, because Facet running
elsewhere is a real deployment and the protocol has always been indifferent to
where it runs -- but it is reached only by name. These tests hold the three
properties that make that safe: local is the default, the two never substitute
for each other, and the local child is handed the same Facet configuration
surface the far side of an SSH connection used to get.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

from ethnos.facet_client import (
    FACET_COMMAND,
    FACET_ENVIRONMENT_PREFIX,
    FACET_LOCAL_COMMAND,
    FACET_REMOTE_HELPER,
    FACET_SSH_COMMAND,
    FACET_TRANSPORT,
    FACET_TRANSPORT_LOCAL,
    FACET_TRANSPORT_SSH,
    FACET_TRANSPORTS,
    FacetTransportError,
    generate_text,
    transport_report,
)
from test_facet_client import answering, ask, ok_envelope

#: Read the module's own idea of its transport out of a fresh interpreter, so
#: the environment is read where it is actually read: once, at import.
PROBE = (
    "from ethnos import facet_client as f; print(f.FACET_TRANSPORT, *f.FACET_COMMAND)"
)


def in_environment(**names: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.pop("FACET_TRANSPORT", None)
    environment.update(names)
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        text=True,
        capture_output=True,
        check=False,
        env=environment,
    )


# --- which transport, and how it is chosen ---------------------------------


def test_the_default_transport_is_a_local_subprocess() -> None:
    started = in_environment()

    assert started.returncode == 0, started.stderr
    assert started.stdout.split() == [FACET_TRANSPORT_LOCAL, FACET_REMOTE_HELPER]


def test_the_local_argv_is_the_helper_and_nothing_else() -> None:
    argv = list(FACET_LOCAL_COMMAND)

    assert argv == [FACET_REMOTE_HELPER]
    # Named absolutely, with no shell metacharacters and no arguments of its
    # own: `shell=False` on an argv there is nothing in to interpret anyway.
    assert argv[0].startswith("/") and " " not in argv[0]
    assert not any(character in argv[0] for character in ";|&$`<>()")
    assert "ssh" not in argv[0].split("/")


def test_the_ssh_argv_is_a_constant_that_forwards_nothing() -> None:
    argv = list(FACET_SSH_COMMAND)

    assert argv[0] == "ssh"
    assert "-o" in argv and "BatchMode=yes" in argv
    assert "ClearAllForwardings=yes" in argv
    assert "-T" in argv
    # One fixed remote program, named absolutely, with no shell metacharacters
    # and no arguments of its own for anything to smuggle a request into.
    helper = argv[-1]
    assert helper == FACET_REMOTE_HELPER
    assert helper.startswith("/") and " " not in helper
    assert not any(character in helper for character in ";|&$`<>()")


def test_ssh_is_selected_only_by_asking_for_it_by_name() -> None:
    started = in_environment(FACET_TRANSPORT="ssh")

    assert started.returncode == 0, started.stderr
    assert started.stdout.split() == [FACET_TRANSPORT_SSH, *FACET_SSH_COMMAND]


def test_local_may_also_be_named_explicitly() -> None:
    started = in_environment(FACET_TRANSPORT="LOCAL")

    assert started.returncode == 0, started.stderr
    assert started.stdout.split() == [FACET_TRANSPORT_LOCAL, FACET_REMOTE_HELPER]


@pytest.mark.parametrize("name", ["shh", "SSH2", "remote", "tailscale", "none", "0"])
def test_a_transport_that_is_not_one_of_the_two_fails_closed(name: str) -> None:
    """A misspelled `ssh` must not quietly become a local run, or the reverse."""
    started = in_environment(FACET_TRANSPORT=name)

    assert started.returncode != 0
    assert "is not a Facet transport" in started.stderr


def test_the_ssh_target_may_still_be_overridden_by_the_environment() -> None:
    started = in_environment(
        FACET_TRANSPORT="ssh", FACET_SSH_TARGET="steve@100.105.86.101"
    )

    assert started.returncode == 0, started.stderr
    assert "steve@100.105.86.101" in started.stdout.split()


def test_the_two_transports_are_the_whole_closed_set() -> None:
    assert FACET_TRANSPORTS == (FACET_TRANSPORT_LOCAL, FACET_TRANSPORT_SSH)
    assert FACET_COMMAND in (FACET_LOCAL_COMMAND, FACET_SSH_COMMAND)


# --- the transport never substitutes for the other one ---------------------


def test_a_request_uses_the_chosen_transport_and_only_that_one(monkeypatch) -> None:
    seen = answering(monkeypatch, ok_envelope())

    ask()

    assert tuple(seen["argv"]) == FACET_COMMAND
    assert seen["kwargs"]["shell"] is False


def test_a_missing_local_helper_raises_rather_than_reaching_for_ssh(
    monkeypatch,
) -> None:
    """The failure this forbids is the quiet one: a solve that silently crossed
    a machine boundary would report provenance for hardware it never ran on."""
    attempts: list[tuple[str, ...]] = []

    def refuse(argv, **kwargs):
        attempts.append(tuple(argv))
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr("ethnos.facet_client.FACET_TRANSPORT", FACET_TRANSPORT_LOCAL)
    monkeypatch.setattr("ethnos.facet_client.FACET_COMMAND", FACET_LOCAL_COMMAND)
    monkeypatch.setattr("ethnos.facet_client.subprocess.run", refuse)

    with pytest.raises(FacetTransportError, match="local transport failed"):
        generate_text("Solve x^2.", request_id="ethnos-test")

    assert attempts == [FACET_LOCAL_COMMAND]


def test_a_failed_ssh_transport_does_not_retry_locally(monkeypatch) -> None:
    attempts: list[tuple[str, ...]] = []

    def refuse(argv, **kwargs):
        attempts.append(tuple(argv))
        raise OSError("host is down")

    monkeypatch.setattr("ethnos.facet_client.FACET_TRANSPORT", FACET_TRANSPORT_SSH)
    monkeypatch.setattr("ethnos.facet_client.FACET_COMMAND", FACET_SSH_COMMAND)
    monkeypatch.setattr("ethnos.facet_client.subprocess.run", refuse)

    with pytest.raises(FacetTransportError, match="ssh transport failed"):
        generate_text("Solve x^2.", request_id="ethnos-test")

    assert attempts == [FACET_SSH_COMMAND]


def test_a_transport_failure_names_the_transport_that_failed(monkeypatch) -> None:
    def refuse(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 190.0)

    monkeypatch.setattr("ethnos.facet_client.subprocess.run", refuse)

    with pytest.raises(FacetTransportError, match=f"{FACET_TRANSPORT} transport"):
        generate_text("Solve x^2.", request_id="ethnos-test")


# --- what the helper is started with ---------------------------------------


def test_facet_configuration_in_this_environment_does_not_cross(monkeypatch) -> None:
    """SSH handed the far side a fresh login environment, so Facet always ran
    on its own configured models. A local child inherits this process's, and
    Firefox's environment is not a place to configure a solver from."""
    seen = answering(monkeypatch, ok_envelope())
    monkeypatch.setenv("FACET_GPU_TEXT_MODEL", "something-else:70b")
    monkeypatch.setenv("FACET_OLLAMA_URL", "http://10.0.0.9:11434")
    monkeypatch.setenv("FACET_TRANSPORT", "ssh")
    monkeypatch.setenv("PATH", os.environ["PATH"])

    ask()

    passed = seen["kwargs"]["env"]
    assert [name for name in passed if name.startswith(FACET_ENVIRONMENT_PREFIX)] == []
    assert passed["PATH"] == os.environ["PATH"]


def test_everything_that_is_not_facet_configuration_is_kept(monkeypatch) -> None:
    """A stripped `PATH` or `HOME` would break the helper for no gain: the
    inherited environment is narrowed to the names Facet reads, not emptied."""
    seen = answering(monkeypatch, ok_envelope())
    monkeypatch.setenv("HOME", "/home/steve")
    monkeypatch.setenv("LANG", "en_US.UTF-8")
    monkeypatch.setenv("SOMETHING_FACET_SHAPED", "kept")

    ask()

    passed = seen["kwargs"]["env"]
    assert passed["HOME"] == "/home/steve"
    assert passed["LANG"] == "en_US.UTF-8"
    # Only the prefix is stripped, and only at the start of a name.
    assert passed["SOMETHING_FACET_SHAPED"] == "kept"


def test_the_request_still_travels_on_standard_input(monkeypatch) -> None:
    seen = answering(monkeypatch, ok_envelope())
    prompt = "Simplify $(touch /tmp/never) ; `id` && echo nope."

    ask(prompt=prompt)

    assert prompt not in " ".join(seen["argv"])
    assert json.loads(seen["kwargs"]["input"])["prompt"] == prompt


def test_the_timeout_is_still_the_callers(monkeypatch) -> None:
    seen = answering(monkeypatch, ok_envelope())

    ask(timeout=12.5)

    assert seen["kwargs"]["timeout"] == 12.5


# --- what a status line says -----------------------------------------------


def test_the_transport_report_states_what_would_actually_run() -> None:
    report = transport_report()

    assert report["transport"] == FACET_TRANSPORT
    assert report["command"] == list(FACET_COMMAND)
    assert report["helper"] == FACET_REMOTE_HELPER
    # A local transport names no host, because there is no other host in it.
    assert report["target"] == "this machine"
    assert "192.168" not in json.dumps(report)


# --- what the companion says when asked where a solve would run ------------


def test_health_names_the_transport_a_solve_would_use() -> None:
    """`health` loads no model and answers in a moment, which makes it the one
    place a topology question can be settled without spending a question."""
    from ethnos.hawkes_host import handle

    response = handle(
        {"protocol_version": 1, "operation": "health", "request_id": "r1"}
    )

    assert response.status == "ok"
    assert response.message == f"ethnos ready; facet transport {FACET_TRANSPORT}"


def test_health_refuses_rather_than_reads_green_on_a_bad_transport(
    monkeypatch,
) -> None:
    from ethnos import hawkes_host

    def unreadable() -> dict:
        raise FacetTransportError("FACET_TRANSPORT='shh' is not a Facet transport")

    monkeypatch.setattr("ethnos.facet_client.transport_report", unreadable)

    response = hawkes_host.handle(
        {"protocol_version": 1, "operation": "health", "request_id": "r1"}
    )

    assert response.status == "error"
    assert response.message.startswith("Facet transport misconfigured")
    assert response.answer is None


def test_that_refusal_carries_a_label_the_add_on_already_knows() -> None:
    """An unclassified refusal reaches the diagnostic ring as `unclassified`,
    which is the one thing a retained record must never say about a fault that
    has a name."""
    background = (
        pathlib.Path(__file__).resolve().parents[1] / "extension" / "background.js"
    ).read_text(encoding="utf-8")

    assert "facet-transport-misconfigured" in background
    assert "/^Facet transport misconfigured/i" in background
