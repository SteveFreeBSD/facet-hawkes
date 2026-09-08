from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", flags=re.MULTILINE)
FENCED_BLOCK = re.compile(r"^```.*?^```", flags=re.MULTILINE | re.DOTALL)


def _prose(text: str) -> str:
    """Markdown with fenced code removed.

    A shell comment at the start of a line inside a code block is not a
    heading. Nothing here trips on that today; the sibling repository did, and
    the two checks are easier to trust when they agree.
    """
    return FENCED_BLOCK.sub("", text)


REMOVED_LEGACY_DOCS = {
    "CODE_REVIEW.md",
    "CTO_REVIEW.md",
    "MERGE_READINESS.md",
    "caspian-optimization-report-2026-07-11.md",
    "erosion.md",
}


def _markdown_files() -> list[Path]:
    """Every Markdown file a reader is pointed at.

    `AGENTS.md` and `extension/` were outside this sweep, so a link that rotted
    there rotted silently -- which is exactly the archaeology this suite exists
    to prevent. The extension changelog is included too: it is long, but a
    dangling link in it is still a dangling link.
    """
    return [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "AGENTS.md",
        *sorted((PROJECT_ROOT / "docs").rglob("*.md")),
        *sorted((PROJECT_ROOT / "extension").glob("*.md")),
        *sorted((PROJECT_ROOT / "benchmarks").glob("*.md")),
        *sorted((PROJECT_ROOT / "examples").glob("*.md")),
    ]


def _heading_anchors(path: Path) -> set[str]:
    anchors = set()
    counts: dict[str, int] = {}
    for heading in MARKDOWN_HEADING.findall(_prose(path.read_text(encoding="utf-8"))):
        slug = re.sub(r"[^\w\- ]", "", heading.lower())
        slug = re.sub(r"\s+", "-", slug.strip())
        duplicate_index = counts.get(slug, 0)
        counts[slug] = duplicate_index + 1
        anchors.add(slug if duplicate_index == 0 else f"{slug}-{duplicate_index}")
    return anchors


def test_local_markdown_links_resolve():
    broken = []
    for source in _markdown_files():
        for raw_target in MARKDOWN_LINK.findall(source.read_text(encoding="utf-8")):
            if "://" in raw_target or raw_target.startswith("mailto:"):
                continue
            target, _, anchor = raw_target.partition("#")
            target_path = source if not target else source.parent / target
            resolved = target_path.resolve()
            if not resolved.exists():
                broken.append(f"{source.relative_to(PROJECT_ROOT)} -> {target}")
            elif anchor and resolved.suffix == ".md":
                if anchor not in _heading_anchors(resolved):
                    broken.append(f"{source.relative_to(PROJECT_ROOT)} -> {raw_target}")

    assert broken == []


def test_active_docs_do_not_reference_removed_legacy_packets():
    references = []
    for source in _markdown_files():
        text = source.read_text(encoding="utf-8")
        for legacy_name in REMOVED_LEGACY_DOCS:
            if legacy_name in text:
                references.append(
                    f"{source.relative_to(PROJECT_ROOT)} -> {legacy_name}"
                )

    assert references == []


def test_markdown_files_have_one_top_level_heading():
    failures = []
    for source in _markdown_files():
        headings = re.findall(
            r"^#\s+(.+?)\s*$",
            _prose(source.read_text(encoding="utf-8")),
            flags=re.MULTILINE,
        )
        if len(headings) != 1:
            failures.append(f"{source.relative_to(PROJECT_ROOT)}: {len(headings)} H1s")

    assert failures == []


#: Wording that describes a topology, a host or a product name this system no
#: longer has. A document may *narrate* any of it -- saying what was replaced is
#: how a reader learns not to go looking for it -- but it may not assert it.
SUPERSEDED_WORDING = {
    "the remote machine": "there is one machine; see docs/CURRENT_STATE.md",
    "two-machine": "there is one machine; see docs/CURRENT_STATE.md",
    "second machine": "there is one machine; see docs/CURRENT_STATE.md",
    "Ethnos Hawkes Assistant": "the product is Facet Hawkes Assistant",
    "Ethnos only": "the solver-preference setting was removed in 0.44.0",
}

#: What tells narration apart from assertion, checked in the same paragraph.
#: Deliberately short: a longer list would let an assertion through by
#: accident, which is the failure this test exists to catch.
RETIREMENT_CUES = (
    "no longer",
    "is gone",
    "was the earlier",
    "used to",
    "until 2026",
    "read like evidence of",
    "renamed from",
    "historical",
    "superseded",
)

#: A changelog is a dated record by construction: every entry describes the
#: build its heading names, and rewriting one to match today would destroy the
#: only thing it is for.
NARRATION_BY_CONSTRUCTION = {"CHANGELOG.md"}


def test_active_documents_do_not_assert_a_superseded_topology():
    offenders = []
    for source in _markdown_files():
        if source.parent.name == "history" or source.name in NARRATION_BY_CONSTRUCTION:
            continue
        text = source.read_text(encoding="utf-8")
        if any(marker in text[:2000] for marker in ("**Superseded", "**Historical")):
            continue
        # A phrase inside a command is an argument, not a claim: the sweep in
        # the verification checklist greps for exactly these words.
        for paragraph in _prose(text).split("\n\n"):
            lowered = paragraph.lower()
            if any(cue in lowered for cue in RETIREMENT_CUES):
                continue
            for phrase, why in SUPERSEDED_WORDING.items():
                if phrase in paragraph:
                    offenders.append(
                        f"{source.relative_to(PROJECT_ROOT)}: {phrase!r} -- {why}"
                    )

    assert offenders == []
