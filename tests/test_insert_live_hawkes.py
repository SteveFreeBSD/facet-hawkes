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
    assert 'type: "ethnos:development-insert-reviewed"' in source
    assert "targetTabId: target.id" in source
    for forbidden in (
        ".click(",
        ".submit(",
        "Submit Answer",
        "tabs.create",
        'type: "ethnos:insert"',
        'type: "ethnos:solve"',
        "ethnos:reset",
        "Try Similar",
        "location.href =",
    ):
        assert forbidden not in source
    assert "tabs.update" not in source

    background = BACKGROUND.read_text(encoding="utf-8")
    assert 'case "ethnos:development-insert-reviewed"' in background
    assert "await browser.tabs.remove(helperTabId)" not in background
    assert "Keep\n            // the helper and its port alive" in background
    assert "the exact lesson tab was not proved" in background
    assert "state = { ...blankState(), windowId: asking }" in background
    assert "await prepare(asking, targetTabId)" in background
    assert (
        "browser.tabs.highlight({ windowId: asking, tabs: target.index })" in background
    )
    assert "browser.tabs.update(targetTabId, { url:" not in background
    assert "developmentInsertInFlight = true" in background
    assert "developmentInsertInFlight = false" in background
    assert "await solve(asking)" in background
    assert "await insert()" in background
    assert 'state.phase !== "inserted"' in background


def test_internal_page_keeps_the_event_page_alive_until_insert_finishes():
    source = PAGE.read_text(encoding="utf-8")

    assert "browser.storage.onChanged.addListener" in source
    assert '["completed", "refused"].includes(value?.phase)' in source
    assert "setTimeout(closeThisTab, 8000)" in source


def test_cli_reuses_the_proved_normal_profile_target_without_gui_input():
    source = SCRIPT.read_text(encoding="utf-8")

    assert "reload_helper._target()" in source
    assert "reload_helper._open_extension_page" in source
    assert 'PAGE = "development/insert-reviewed.html"' in source
    for forbidden in ("xdotool", "ydotool", "pyautogui", "about:debugging"):
        assert forbidden not in source


def test_cli_correlates_a_structured_pair_pin_with_its_settled_record(monkeypatch):
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

    assert module._settled_insertion(Path("/unused"), 1000) == {
        "run": "pair-run",
        "via": "structured-fields",
        "fields": 2,
        "parts": 2,
        "connector": "and",
        "settled": True,
    }
    assert module._settled_insertion(Path("/unused"), 1700) is None


def test_cli_correlates_a_single_structured_answer(monkeypatch):
    module = load_script()
    entries = [
        {
            "t": 1200,
            "run": "single-run",
            "event": "insertion-pinned",
            "data": {"fieldIds": 1, "answerParts": 0, "answerConnector": ""},
        },
        {
            "t": 1600,
            "run": "single-run",
            "event": "inserted",
            "data": {"via": "structured", "answerLength": 15},
        },
    ]
    monkeypatch.setattr(module.reload_helper, "_entries", lambda _profile: entries)

    assert module._settled_insertion(Path("/unused"), 1000) == {
        "run": "single-run",
        "via": "structured",
        "fields": 1,
        "parts": 0,
        "connector": "",
        "settled": True,
    }
