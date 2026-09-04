"""Safety boundary for inspecting the owner's existing Firefox session."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_live_firefox.py"
SPEC = importlib.util.spec_from_file_location("inspect_live_firefox", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def window(resource_class: str, *, normal: bool = True, caption: str = "") -> dict:
    return {
        "resourceClass": resource_class,
        "normalWindow": normal,
        "caption": caption,
    }


def test_exactly_one_normal_firefox_window_is_accepted():
    firefox = window("firefox", caption="Hawkes — Mozilla Firefox")
    windows = [window("code"), window("plasmashell", normal=False), firefox]

    assert MODULE._one_firefox_window(windows) is firefox


@pytest.mark.parametrize("windows", [[], [window("firefox"), window("firefox")]])
def test_an_unnamed_target_among_zero_or_many_fails_closed(windows):
    with pytest.raises(MODULE.InspectionError, match="exactly one"):
        MODULE._one_firefox_window(windows)


def test_the_window_to_inspect_can_be_named_when_several_are_open():
    """The owner having their own browsing open beside the question is normal.

    Refusing outright made the supported entry point unusable in exactly the
    situation it exists for, and the way round it was to stop looking.
    """
    hawkes = window("firefox", caption="Lesson 1.5 | Hawkes Learning — Mozilla Firefox")
    windows = [window("firefox", caption="Minisforum HX 370 — Mozilla Firefox"), hawkes]

    assert MODULE._one_firefox_window(windows, "hawkes") is hawkes
    # Case-insensitive, and any distinguishing part of the title will do.
    assert MODULE._one_firefox_window(windows, "Lesson 1.5") is hawkes


def test_a_name_matching_more_than_one_window_still_fails_closed():
    """Focusing and photographing the wrong window is useless and an intrusion,
    so ambiguity is refused rather than guessed at."""
    windows = [
        window("firefox", caption="Hawkes Learning — one"),
        window("firefox", caption="Hawkes Learning — two"),
    ]

    with pytest.raises(MODULE.InspectionError, match="matching 'hawkes'"):
        MODULE._one_firefox_window(windows, "hawkes")

    with pytest.raises(MODULE.InspectionError, match="matching 'absent'"):
        MODULE._one_firefox_window(windows, "absent")


def test_a_non_normal_firefox_surface_is_not_a_browser_target():
    with pytest.raises(MODULE.InspectionError, match="found 0"):
        MODULE._one_firefox_window([window("firefox", normal=False)])


def test_script_has_no_browser_launch_or_navigation_code():
    source = SCRIPT.read_text(encoding="utf-8")
    compacted = " ".join(source.split())

    assert "firefox --" not in source
    assert "WebDriver:Navigate" not in source
    assert "OpenURL" not in source
    assert "Marionette" not in source
    assert "workspace.activeWindow = window" in source
    assert '"spectacle", "--activewindow"' in compacted
