"""The button the isolated harness presses, and what happens when it is gone.

Firefox 155 files a newly installed add-on's action under
`unified-extensions-area` and builds no toolbar node for it. The harness clicks
one fixed selector, `#ethnos-hawkes_local-BAP`, and swallowed the resulting
"unable to locate element" -- so it retried three times, opened no popup, and
reported *every* popup scenario as "the popup never reported": 2 of 19 checks
passing, and seventeen lines blaming an add-on that was never exercised.

Two things are pinned here. The selector is derived from the manifest rather
than written down twice, and a button that cannot be pressed is a harness fault
with its own name -- never a verdict on the add-on.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The same module object the harness itself imports, so an exception raised
# there is the exception caught here. Loading the file twice under two names
# gives two unrelated `ActionButtonMissing` classes and a test that can only
# ever fail.
sys.path.insert(0, str(ROOT / "scripts"))
from harness import marionette  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "run_extension_harness", ROOT / "scripts/run_extension_harness.py"
)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)


class FakeMarionette:
    """A browser that answers `pin_action_to_toolbar`'s one script.

    `areas` maps a CustomizableUI widget id to the area holding it, and
    `nodes` is the set of selectors the browser document would resolve --
    which, as in Firefox, only includes a widget once it is somewhere visible.
    """

    NAVBAR = "nav-bar"

    def __init__(self, areas, *, has_customizable_ui=True, builds_node=True):
        self.areas = dict(areas)
        self.has_customizable_ui = has_customizable_ui
        self.builds_node = builds_node
        self.clicked: list[str] = []

    def execute(self, script, args=None):
        widget, selector = args
        if not self.has_customizable_ui:
            return {"value": {"error": "this window exposes no CustomizableUI"}}
        before = self.areas.get(widget)
        if before is None:
            return {"value": {"error": f"{widget} is not a registered widget"}}
        if before != self.NAVBAR:
            self.areas[widget] = self.NAVBAR
        node = self.builds_node and self.areas[widget] == self.NAVBAR
        return {
            "value": {
                "before": before,
                "after": self.areas[widget],
                "node": node,
                "selector": selector,
            }
        }


def test_the_selector_is_derived_from_the_manifest_not_written_down_twice():
    """A renamed add-on must not leave the harness clicking a stale id."""
    manifest = json.loads(
        (ROOT / "extension/manifest.json").read_text(encoding="utf-8")
    )
    addon_id = manifest["browser_specific_settings"]["gecko"]["id"]

    assert harness.ADDON_ID == addon_id
    assert harness.ACTION_BUTTON == marionette.action_button_selector(addon_id)


def test_gecko_widget_ids_match_the_ones_firefox_builds():
    assert marionette.widget_id("ethnos-hawkes@local") == "ethnos-hawkes_local"
    assert (
        marionette.action_button_selector("ethnos-hawkes@local")
        == "#ethnos-hawkes_local-BAP"
    )
    assert (
        marionette.action_widget_id("ethnos-hawkes@local")
        == "ethnos-hawkes_local-browser-action"
    )


def test_an_action_in_the_extensions_area_is_moved_to_the_toolbar():
    """The Firefox 155 arrangement, and the whole of the repair."""
    widget = marionette.action_widget_id("ethnos-hawkes@local")
    browser = FakeMarionette({widget: "unified-extensions-area"})

    placement = marionette.pin_action_to_toolbar(browser, "ethnos-hawkes@local")

    assert placement["before"] == "unified-extensions-area"
    assert placement["after"] == "nav-bar"
    assert browser.areas[widget] == "nav-bar"


def test_an_action_already_in_the_toolbar_is_left_where_it_is():
    widget = marionette.action_widget_id("ethnos-hawkes@local")
    browser = FakeMarionette({widget: "nav-bar"})

    placement = marionette.pin_action_to_toolbar(browser, "ethnos-hawkes@local")

    assert placement["before"] == placement["after"] == "nav-bar"


def test_a_button_that_never_appears_is_named_rather_than_blamed_on_the_addon():
    """The failure this file exists for.

    A browser that places the widget but builds no node leaves the harness with
    nothing to press. That must raise here, at the one place that knows why,
    rather than surface later as thirteen scenarios reporting a silent popup.
    """
    widget = marionette.action_widget_id("ethnos-hawkes@local")
    browser = FakeMarionette({widget: "unified-extensions-area"}, builds_node=False)

    with pytest.raises(marionette.ActionButtonMissing) as failure:
        marionette.pin_action_to_toolbar(browser, "ethnos-hawkes@local")

    assert "no clickable toolbar action" in str(failure.value)


def test_a_browser_without_customizable_ui_is_named_too():
    browser = FakeMarionette({}, has_customizable_ui=False)

    with pytest.raises(marionette.ActionButtonMissing) as failure:
        marionette.pin_action_to_toolbar(browser, "ethnos-hawkes@local")

    assert "CustomizableUI" in str(failure.value)


def test_an_unregistered_widget_is_named_too():
    browser = FakeMarionette({})

    with pytest.raises(marionette.ActionButtonMissing) as failure:
        marionette.pin_action_to_toolbar(browser, "ethnos-hawkes@local")

    assert "not a registered widget" in str(failure.value)


class UnclickableBrowser:
    """A browser whose toolbar has no such element, as Firefox 155's had none."""

    def set_context(self, context):
        pass

    def execute(self, script, args=None):
        return {"value": 0}  # no panel is open, so nothing is waited for

    def click(self, css):
        raise marionette.MarionetteError(
            f"WebDriver:FindElement: Unable to locate element: {css}"
        )


def test_a_missing_button_stops_the_run_instead_of_failing_every_scenario():
    """`open_popup_and_wait` used to swallow this and return None.

    None reads as "the popup never reported", which is a statement about the
    add-on. It was not one: nothing had been opened.
    """
    with pytest.raises(marionette.ActionButtonMissing) as failure:
        harness.open_popup_and_wait(UnclickableBrowser(), {}, "top.html")

    assert harness.ACTION_BUTTON in str(failure.value)


def test_a_sidebar_report_cannot_answer_for_the_toolbar_popup():
    """Firefox opens a temporarily installed add-on's sidebar by itself.

    The sidebar is the same document as the popup and reports the same tab, but
    it was never granted `activeTab` -- so a sidebar report standing in for the
    popup's would quietly measure the wrong surface.
    """
    reports = {
        "sidebar:http://127.0.0.1:1/top.html": {"sidebar": True, "status": "sidebar"},
    }
    wait = {"attempts": 1, "window": 0.05}

    assert (
        harness.open_popup_and_wait(_QuietBrowser(), reports, "top.html", **wait)
        is None
    )

    reports["http://127.0.0.1:1/top.html"] = {"sidebar": False, "status": "popup"}
    found = harness.open_popup_and_wait(_QuietBrowser(), reports, "top.html", **wait)
    assert found["status"] == "popup"


class _QuietBrowser(UnclickableBrowser):
    def click(self, css):
        return None
