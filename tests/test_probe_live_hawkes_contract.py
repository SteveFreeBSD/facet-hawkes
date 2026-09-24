"""The normal-profile Hawkes contract probe is read-only and fail-closed."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "probe_live_hawkes_contract.py"
PAGE = ROOT / "extension" / "development" / "probe.js"
MAIN = ROOT / "extension" / "development" / "probe-main.js"


def test_probe_uses_one_exact_lesson_tab_and_main_world_read_only_snapshot():
    source = PAGE.read_text(encoding="utf-8")

    assert 'TARGET_ADDON_ID = "ethnos-hawkes@local"' in source
    assert "candidates.length !== 1" in source
    assert 'world: "MAIN"' in source
    assert "browser.scripting.executeScript" in source
    assert 'files: ["/development/probe-main.js"]' in source
    assert "quant_wp_UI" not in source
    assert "browser.storage.local.remove(PROBE_STATE_KEY)" in source
    for forbidden in (".click(", ".submit(", "dispatchEvent", "location.href ="):
        assert forbidden not in source

    main = MAIN.read_text(encoding="utf-8")
    assert "quant_wp_UI" in main
    assert "controlsCollectionData" in main
    assert "QDyTextBoxObjects" in main
    for forbidden in (".click(", ".submit(", "dispatchEvent", "location.href ="):
        assert forbidden not in main


def test_helper_reuses_the_proved_normal_profile_target_and_has_no_gui_fallback():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "reload_helper._target()" in source
    assert "reload_helper._ensure_project_python(Path(__file__))" in source
    assert "reload_helper._open_extension_page" in source
    assert 'PROBE_PAGE = "development/probe.html"' in source
    for forbidden in (
        "xdotool",
        "ydotool",
        "pyautogui",
        "spectacle",
        "about:debugging",
    ):
        assert forbidden not in source
