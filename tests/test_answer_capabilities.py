"""A new exact family is not finished until this repository can enter it.

Facet owns what the answer is. Hawkes Assistant owns how it is entered. Every
recurring defect in this project has been in neither half but in a composition
neither half named: `(1,-4)` was enterable, `17/2` was enterable, and the
midpoint's `(17/2,-1/2)` was not -- discovered live, on coursework, after Facet
had been answering it correctly for a day.

`docs/ANSWER_CAPABILITIES.md` is the map. These tests make it binding: every
answer family Facet can emit must have a row there saying how it is entered, or
a row saying plainly that it is not supported. "Unsupported" is a finished
state. Discovering it live is not.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPABILITIES = PROJECT_ROOT / "docs" / "ANSWER_CAPABILITIES.md"


@pytest.fixture(scope="module")
def document() -> str:
    return CAPABILITIES.read_text(encoding="utf-8")


def rows(document: str, heading: str) -> list[list[str]]:
    """The table under one heading, as cells."""
    start = document.index(heading)
    end = document.find("\n## ", start + 1)
    section = document[start : end if end > 0 else len(document)]
    found = []
    for line in section.splitlines():
        if not line.startswith("|") or set(line) <= set("|- "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if cells[0].lower().startswith("semantic answer") or cells[0] == "Composition":
            continue
        found.append(cells)
    return found


def test_the_document_exists_and_names_the_boundary(document: str) -> None:
    """It is the first thing a future agent should read, so it has to say what
    it is for in its own words."""
    assert "Facet owns what the answer is" in document
    assert "Hawkes Assistant owns how it is entered" in document


def test_every_answer_form_facet_can_emit_has_a_row(document: str) -> None:
    """The binding assertion. `ANSWER_FORMS` is a closed set on Facet's side;
    a member with no row here is a family nothing has agreed to consume."""
    from facet_runtime.exact import ANSWER_FORMS

    supported = rows(document, "## The map")
    unsupported = rows(document, "## Unsupported compositions")
    covered = " ".join(cell for row in supported + unsupported for cell in row)

    missing = [form for form in ANSWER_FORMS if f"`{form}`" not in covered]
    assert missing == [], (
        f"{missing} can be emitted by facet-runtime and has no row in "
        f"{CAPABILITIES.name}. Add how it is entered, or add it to "
        "Unsupported compositions and say what happens when it arrives."
    )


def test_every_supported_row_names_a_mechanism_that_exists(document: str) -> None:
    """A row naming a function that has been renamed away is worse than no row:
    it reads as coverage and is a dead pointer."""
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (PROJECT_ROOT / "extension").rglob("*.js")
    )
    named = set()
    for row in rows(document, "## The map"):
        named.update(re.findall(r"`([A-Za-z][A-Za-z0-9_]+)`", row[5]))

    # Template names are the page's, not this repository's functions.
    templates = {"PBrace", "Fraction", "Radical", "IndexedRadical", "Exponent", "Mod"}
    missing = [
        name
        for name in sorted(named - templates)
        if not re.search(rf"\b{re.escape(name)}\b", sources)
    ]

    assert missing == [], f"named in the capability map but not in the code: {missing}"


def test_every_row_states_all_three_kinds_of_coverage(document: str) -> None:
    """Unit-tested, harness, live-proven. A blank is a claim nobody made."""
    verdicts = {"yes", "no", "partial", "n/a"}
    for row in rows(document, "## The map"):
        assert len(row) == 9, row
        for cell in row[-3:]:
            assert cell.lower() in verdicts, row


def test_the_ordered_pair_of_rationals_is_recorded_as_supported(
    document: str,
) -> None:
    """The composition the live midpoint defect exposed. It is the row this
    whole page was written around, so it is asserted by name."""
    row = next(row for row in rows(document, "## The map") if "(17/2,-1/2)" in row[1])

    assert row[2] == "`ordered-pair`"
    assert "planCommaList" in row[5]
    assert row[-3].lower() == "yes"


def test_the_decimal_form_is_recorded_as_deliberately_unsupported(
    document: str,
) -> None:
    """Making the exact form enterable must not read as making the decimal one
    enterable. The refusal is the correct behaviour and is written down."""
    row = next(
        row for row in rows(document, "## Unsupported compositions") if "8.5" in row[1]
    )

    assert "Refused" in row[2]


def test_the_documentation_index_points_at_it(document: str) -> None:
    """A page nobody is sent to is a page nobody reads first."""
    index = (PROJECT_ROOT / "docs" / "README.md").read_text(encoding="utf-8")

    assert "ANSWER_CAPABILITIES.md" in index
