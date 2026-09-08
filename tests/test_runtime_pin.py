"""One pin for the Facet runtime, quoted the same everywhere.

Facet owns exact solving, and this package imports `facet_runtime` as a path
dependency at `../facet-runtime`. So the runtime commit is not a nicety: a
checkout older than the pin does not answer more slowly, it fails to import.
That happened -- CI, the README, the migration checklist and the release
runbook all named a commit from before `ANSWER_FORMS`, `midpoint`, `linear`,
`quadrant` and `distance` existed, so a clean clone built from the published
instructions could not have run this suite at all.

The pin lives in `deploy/facet-runtime.pin` and nowhere else. These tests hold
every place that repeats it to that one value.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = PROJECT_ROOT / "deploy" / "facet-runtime.pin"
RUNTIME_ROOT = PROJECT_ROOT.parent / "facet-runtime"

#: Any full-length hex object name in prose. Short forms are checked separately,
#: because a seven-character prefix of the wrong commit reads as plausible.
FULL_SHA = re.compile(r"\b[0-9a-f]{40}\b")

#: Documents that quote the pin. Each is here because a reader follows it to a
#: shell command, not because it merely mentions Facet.
QUOTING_DOCUMENTS = (
    "README.md",
    "docs/MIGRATION.md",
    "docs/HAWKES_RELEASE_AUDIT.md",
    "extension/RELEASE.md",
)


def pinned_commit() -> str:
    lines = [
        line.strip()
        for line in PIN_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert len(lines) == 1, "the pin file holds exactly one commit"
    return lines[0]


def test_the_pin_is_one_full_object_name():
    commit = pinned_commit()

    assert FULL_SHA.fullmatch(commit), f"not a full 40-character object name: {commit}"


#: Where a commit is being named *as the runtime to check out*. The release
#: ledger legitimately records many other object names -- packaged-source
#: baselines, superseded candidates -- and those are not this pin.
RUNTIME_SHA_CONTEXTS = (
    re.compile(r"git -C facet-runtime checkout --detach ([0-9a-f]{40})"),
    re.compile(r"[Rr]equired Facet runtime \| `([0-9a-f]{40})`"),
    re.compile(r"[Ff]acet runtime commit\s*\n?`([0-9a-f]{40})`"),
    re.compile(r"fixes `facet-runtime` at companion commit\s*\n?`([0-9a-f]{40})`"),
    re.compile(r"runtime `([0-9a-f]{7,40})`"),
    re.compile(r"CI pins runtime `([0-9a-f]{7,40})`"),
)


@pytest.mark.parametrize("relative", QUOTING_DOCUMENTS)
def test_every_document_quotes_the_pinned_commit(relative):
    """A document may quote the pin or stay silent; it may not quote another."""
    commit = pinned_commit()
    text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")

    named = {
        found for pattern in RUNTIME_SHA_CONTEXTS for found in pattern.findall(text)
    }
    assert named, f"{relative} is listed as quoting the pin but names no runtime commit"

    wrong = {found for found in named if not commit.startswith(found)}
    assert wrong == set(), f"{relative} names a different runtime commit: {wrong}"


def test_continuous_integration_checks_out_the_pinned_runtime():
    """CI must read the pin rather than restate it, or this test cannot hold it."""
    workflow = (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").read_text()

    assert "repository: SteveFreeBSD/facet-runtime" in workflow
    assert "deploy/facet-runtime.pin" in workflow
    assert "ref: ${{ steps.runtime.outputs.ref }}" in workflow

    # Actions are themselves pinned by object name, so only the runtime
    # checkout step is held to reading the pin rather than restating one.
    _, _, runtime_step = workflow.partition("repository: SteveFreeBSD/facet-runtime")
    step, _, _ = runtime_step.partition("- uses: actions/setup-python")
    assert FULL_SHA.search(step) is None, "CI restates a commit instead of reading it"


def test_the_sibling_checkout_is_not_older_than_the_pin():
    """The runtime beside this checkout must contain what the pin requires.

    Skipped where the sibling is absent or does not know the commit -- a shallow
    clone is a fact about the clone, not a defect in the pin.
    """
    if not (RUNTIME_ROOT / ".git").exists():
        pytest.skip("no sibling facet-runtime checkout")

    commit = pinned_commit()
    known = subprocess.run(
        ["git", "-C", str(RUNTIME_ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        capture_output=True,
    )
    if known.returncode != 0:
        pytest.skip("the sibling checkout does not know the pinned commit")

    contains = subprocess.run(
        ["git", "-C", str(RUNTIME_ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True,
    )
    assert contains.returncode == 0, (
        f"../facet-runtime is behind the pin {commit[:7]}; "
        "check it out or lower the pin in the change that needs the older tree"
    )


def test_the_deployment_authority_points_at_the_pin_rather_than_copying_it():
    """One document explains the pin, and it explains where the pin lives.

    Restating the commit there would make a fifth copy of it for no reader's
    benefit: anyone reading that page already has the checkout the file is in.
    """
    text = (PROJECT_ROOT / "docs" / "RUNTIME_AND_DEPLOYMENT.md").read_text()

    assert "deploy/facet-runtime.pin" in text
    assert FULL_SHA.search(text) is None, "the deployment authority copies the pin"
