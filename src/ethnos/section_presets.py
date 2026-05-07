"""Manual section-label presets for known course documents."""

from __future__ import annotations

from dataclasses import dataclass


SECTION_LABELS = {
    "front_matter",
    "book_intro",
    "chapter_content",
    "chapter_references",
    "further_reading",
    "contributor_bios",
    "licensing",
    "review_statement",
    "accessibility",
    "version_history",
    "blank_or_artifact",
    "unknown",
}

CONTENT_ROLES = {"core", "support", "admin", "artifact", "unknown"}


@dataclass(frozen=True)
class SectionRange:
    start: int
    end: int
    section_label: str
    content_role: str
    confidence: float = 1.0


@dataclass(frozen=True)
class SectionPreset:
    name: str
    page_ranges: tuple[SectionRange, ...]
    chunk_ranges: tuple[SectionRange, ...]


ETHICS_PRESET = SectionPreset(
    name="ethics",
    page_ranges=(
        SectionRange(1, 16, "front_matter", "admin"),
        SectionRange(17, 19, "book_intro", "core"),
        SectionRange(20, 20, "blank_or_artifact", "artifact"),
        SectionRange(21, 30, "chapter_content", "core"),
        SectionRange(31, 31, "chapter_references", "support"),
        SectionRange(32, 41, "chapter_content", "core"),
        SectionRange(42, 43, "chapter_references", "support"),
        SectionRange(44, 52, "chapter_content", "core"),
        SectionRange(53, 53, "chapter_references", "support"),
        SectionRange(54, 60, "chapter_content", "core"),
        SectionRange(61, 61, "chapter_references", "support"),
        SectionRange(62, 67, "chapter_content", "core"),
        SectionRange(68, 69, "chapter_references", "support"),
        SectionRange(70, 79, "chapter_content", "core"),
        SectionRange(80, 80, "chapter_references", "support"),
        SectionRange(81, 89, "chapter_content", "core"),
        SectionRange(90, 91, "chapter_references", "support"),
        SectionRange(92, 102, "chapter_content", "core"),
        SectionRange(103, 103, "chapter_references", "support"),
        SectionRange(104, 104, "further_reading", "support"),
        SectionRange(105, 106, "blank_or_artifact", "artifact"),
        SectionRange(107, 109, "contributor_bios", "admin"),
        SectionRange(110, 111, "unknown", "admin"),
        SectionRange(112, 113, "licensing", "admin"),
        SectionRange(114, 114, "review_statement", "admin"),
        SectionRange(115, 116, "accessibility", "admin"),
        SectionRange(117, 118, "version_history", "admin"),
    ),
    chunk_ranges=(
        SectionRange(1, 8, "front_matter", "admin"),
        SectionRange(9, 11, "book_intro", "core"),
        SectionRange(12, 19, "chapter_content", "core"),
        SectionRange(20, 20, "chapter_references", "support"),
        SectionRange(21, 29, "chapter_content", "core"),
        SectionRange(30, 30, "chapter_references", "support"),
        SectionRange(31, 39, "chapter_content", "core"),
        SectionRange(40, 40, "chapter_references", "support"),
        SectionRange(41, 49, "chapter_content", "core"),
        SectionRange(50, 50, "chapter_references", "support"),
        SectionRange(51, 57, "chapter_content", "core"),
        SectionRange(58, 58, "chapter_references", "support"),
        SectionRange(59, 67, "chapter_content", "core"),
        SectionRange(68, 68, "chapter_references", "support"),
        SectionRange(69, 77, "chapter_content", "core"),
        SectionRange(78, 78, "chapter_references", "support"),
        SectionRange(79, 90, "chapter_content", "core"),
        SectionRange(91, 91, "chapter_references", "support"),
        SectionRange(92, 92, "further_reading", "support"),
        SectionRange(93, 95, "contributor_bios", "admin"),
        SectionRange(96, 96, "licensing", "admin"),
        SectionRange(97, 97, "review_statement", "admin"),
        SectionRange(98, 99, "accessibility", "admin"),
        SectionRange(100, 100, "version_history", "admin"),
    ),
)

PRESETS = {"ethics": ETHICS_PRESET}


def get_section_preset(name: str) -> SectionPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown section preset {name!r}. Available presets: {available}") from exc
