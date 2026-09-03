from ethnos.section_presets import (
    PRESETS,
    CONTENT_ROLES,
    SECTION_LABELS,
    get_section_preset,
)


def _assert_contiguous(ranges, *, expected_start: int, expected_end: int) -> None:
    current = expected_start
    for section_range in ranges:
        assert section_range.start == current
        assert section_range.end >= section_range.start
        assert section_range.section_label in SECTION_LABELS
        assert section_range.content_role in CONTENT_ROLES
        current = section_range.end + 1
    assert current == expected_end + 1


def test_known_section_presets_have_contiguous_ranges():
    expectations = {
        "ethics": {"pages": (1, 118), "chunks": (1, 100)},
        "history": {"pages": (1, 464), "chunks": (1, 157)},
        "precalc": {"pages": (1, 1094), "chunks": (1, 609)},
    }

    assert set(expectations) <= set(PRESETS)
    for preset_name, bounds in expectations.items():
        preset = get_section_preset(preset_name)
        _assert_contiguous(
            preset.page_ranges,
            expected_start=bounds["pages"][0],
            expected_end=bounds["pages"][1],
        )
        _assert_contiguous(
            preset.chunk_ranges,
            expected_start=bounds["chunks"][0],
            expected_end=bounds["chunks"][1],
        )
