"""No test may reach the real Facet host.

`test_a_facet_failure_claims_no_answer_source_at_all` patched a seam the solve
path no longer used, so it made a live SSH call to the Facet machine on every
run. It passed anyway, because the call failed and a failed call was what the
test was asserting -- and it would have kept passing while proving nothing.

This refuses the fixed Facet argv, and only that argv, so a test that has lost
its seam says so instead of quietly going out over the network. Tests that mean
to exercise the whole path use `facet_loopback.facet`, which runs the real Facet
in-process.
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.fixture(autouse=True)
def no_live_facet(monkeypatch):
    from ethnos.facet_client import FACET_SSH_COMMAND

    real_run = subprocess.run

    def guarded(argv, *args, **kwargs):
        if tuple(argv) == FACET_SSH_COMMAND:
            raise AssertionError(
                "this test reached the real Facet host over SSH. Use "
                "facet_loopback.facet(monkeypatch), or patch the seam the code "
                "under test actually calls."
            )
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded)
