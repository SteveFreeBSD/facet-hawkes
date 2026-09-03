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
def test_zero_or_multiple_firefox_windows_fail_closed(windows):
    with pytest.raises(MODULE.InspectionError, match="exactly one"):
        MODULE._one_firefox_window(windows)


def test_a_non_normal_firefox_surface_is_not_a_browser_target():
    with pytest.raises(MODULE.InspectionError, match="found 0"):
        MODULE._one_firefox_window([window("firefox", normal=False)])


def test_script_has_no_browser_launch_or_navigation_code():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "firefox --" not in source
    assert "WebDriver:Navigate" not in source
    assert "OpenURL" not in source
    assert "Marionette" not in source
    assert "workspace.activeWindow = window" in source
    assert '"spectacle", "--activewindow"' in source
