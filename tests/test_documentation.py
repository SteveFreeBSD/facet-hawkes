from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", flags=re.MULTILINE)
REMOVED_LEGACY_DOCS = {
    "CODE_REVIEW.md",
    "CTO_REVIEW.md",
    "MERGE_READINESS.md",
    "caspian-optimization-report-2026-07-11.md",
    "erosion.md",
}


def _markdown_files() -> list[Path]:
    return [
        PROJECT_ROOT / "README.md",
        *sorted((PROJECT_ROOT / "docs").rglob("*.md")),
        *sorted((PROJECT_ROOT / "benchmarks").glob("*.md")),
        *sorted((PROJECT_ROOT / "examples").glob("*.md")),
    ]


def _heading_anchors(path: Path) -> set[str]:
    anchors = set()
    counts: dict[str, int] = {}
    for heading in MARKDOWN_HEADING.findall(path.read_text(encoding="utf-8")):
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
            r"^#\s+(.+?)\s*$", source.read_text(encoding="utf-8"), flags=re.MULTILINE
        )
        if len(headings) != 1:
            failures.append(f"{source.relative_to(PROJECT_ROOT)}: {len(headings)} H1s")

    assert failures == []
