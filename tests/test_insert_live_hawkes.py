"""The live Insert proof invokes Facet only and cannot grade Hawkes work."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "extension" / "development" / "insert-reviewed.js"
BACKGROUND = ROOT / "extension" / "background.js"
SCRIPT = ROOT / "scripts" / "insert_live_hawkes.py"


def load_script():
    spec = importlib.util.spec_from_file_location("insert_live_hawkes", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extension_page_is_exactly_scoped_to_existing_solve_insert_contract():
    source = PAGE.read_text(encoding="utf-8")

    assert 'TARGET_ADDON_ID = "ethnos-hawkes@local"' in source
    assert "candidates.length !== 1" in source
    assert "browser.tabs.getCurrent()" in source
    assert 'type: "ethnos:development-insert-pair"' in source
    assert "targetTabId: target.id" in source
    for forbidden in (
        ".click(",
        ".submit(",
        "Submit Answer",
        "tabs.update",
        "tabs.create",
        'type: "ethnos:insert"',
        'type: "ethnos:solve"',
        "ethnos:reset",
        "Try Similar",
        "location.href =",
    ):
        assert forbidden not in source

    background = BACKGROUND.read_text(encoding="utf-8")
    assert 'case "ethnos:development-insert-pair"' in background
    assert "await browser.tabs.remove(helperTabId)" in background
    assert "the exact lesson tab was not proved" in background
    assert "state = { ...blankState(), windowId: asking }" in background
    assert "await prepare(asking, targetTabId)" in background
    assert "browser.tabs.update" not in background
    assert "await solve(asking)" in background
    assert "await insert()" in background
    assert 'state.phase !== "inserted"' in background


def test_cli_reuses_the_proved_normal_profile_target_without_gui_input():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "reload_helper._target()" in source
    assert "reload_helper._open_extension_page" in source
    assert 'PAGE = "development/insert-reviewed.html"' in source
    for forbidden in ("xdotool", "ydotool", "pyautogui", "about:debugging"):
        assert forbidden not in source


def test_cli_correlates_the_existing_insert_pin_with_its_settled_record(monkeypatch):
    module = load_script()
    entries = [
        {
            "t": 1200,
            "run": "pair-run",
            "event": "insertion-pinned",
            "data": {"fieldIds": 2, "answerParts": 2, "answerConnector": "and"},
        },
        {
            "t": 1500,
            "run": "another-run",
            "event": "inserted",
            "data": {"via": "structured-fields", "fields": 2, "parts": 2},
        },
        {
            "t": 1600,
            "run": "pair-run",
            "event": "inserted",
            "data": {"via": "structured-fields", "fields": 2, "parts": 2},
        },
    ]
    monkeypatch.setattr(module.reload_helper, "_entries", lambda _profile: entries)

    assert module._settled_pair_insertion(Path("/unused"), 1000) == {
        "run": "pair-run",
        "connector": "and",
        "settled": True,
    }
    assert module._settled_pair_insertion(Path("/unused"), 1700) is None
