"""No test may reach the real Facet host.

`test_a_facet_failure_claims_no_answer_source_at_all` patched a seam the solve
path no longer used, so it made a live SSH call to the Facet machine on every
run. It passed anyway, because the call failed and a failed call was what the
test was asserting -- and it would have kept passing while proving nothing.

This refuses the fixed Facet argv of either transport, and only those, so a test
that has lost its seam says so instead of quietly starting the real helper --
over the network on the SSH transport, and as a local subprocess on the default
one, which is the quieter of the two failures and the easier to miss. Tests that
mean to exercise the whole path use `facet_loopback.facet`, which runs the real
Facet in-process.
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.fixture(autouse=True)
def no_live_facet(monkeypatch):
    from ethnos.facet_client import FACET_LOCAL_COMMAND, FACET_SSH_COMMAND

    real_run = subprocess.run
    refused = {
        FACET_LOCAL_COMMAND: "as a local subprocess",
        FACET_SSH_COMMAND: "over SSH",
    }

    def guarded(argv, *args, **kwargs):
        how = refused.get(tuple(argv))
        if how is not None:
            raise AssertionError(
                f"this test started the real Facet helper {how}. Use "
                "facet_loopback.facet(monkeypatch), or patch the seam the code "
                "under test actually calls."
            )
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)
