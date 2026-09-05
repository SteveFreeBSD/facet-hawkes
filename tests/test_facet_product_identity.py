"""What the installed add-on calls itself, and what it no longer offers.

The compute migration finished in the code long before it finished on screen.
Facet had taken over routing -- exact mathematics, reasoning, and the two graph
specialists -- while the toolbar still said Ethnos, the button still said "Solve
with Ethnos", and Settings still asked the user to choose between the two as if
that choice still meant something. A product that describes an architecture it
no longer has is telling its user something false every time they open it.

So these are gates on the visible surface rather than on behaviour: the name in
every place a person reads one, the absence of a control for a decision the
browser no longer makes, and the absence of wording that still calls Facet
optional. Behaviour is covered elsewhere; what is asserted here is what someone
would see.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

PRODUCT = "Facet Hawkes Assistant"

#: Every file a user reads text out of, directly or through localization.
VISIBLE_SOURCES = (
    EXTENSION / "popup" / "popup.html",
    EXTENSION / "options" / "options.html",
    EXTENSION / "icons" / "icon.svg",
)


@pytest.fixture(scope="module")
def messages():
    return json.loads(
        (EXTENSION / "_locales" / "en" / "messages.json").read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def manifest():
    return json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))


# --- the name -------------------------------------------------------------


def test_the_add_on_names_itself_facet_wherever_a_name_is_shown(messages) -> None:
    """The add-ons list, the toolbar tooltip, the sidebar, and Settings."""
    assert messages["extensionName"]["message"] == PRODUCT
    assert messages["actionTitle"]["message"] == PRODUCT
    assert messages["optionsTitle"]["message"] == f"{PRODUCT} settings"


def test_the_toolbar_and_sidebar_take_their_names_from_the_catalogue(
    manifest,
) -> None:
    """So there is one place the product is named, and it is the one above."""
    assert manifest["name"] == "__MSG_extensionName__"
    assert manifest["action"]["default_title"] == "__MSG_actionTitle__"
    assert manifest["sidebar_action"]["default_title"] == "__MSG_extensionName__"


def test_the_main_button_says_facet(messages) -> None:
    """The one string a user reads before every single solve."""
    assert messages["popupSolveButton"]["message"] == "Solve with Facet"


def test_the_icon_carries_the_product_name_for_a_screen_reader() -> None:
    icon = (EXTENSION / "icons" / "icon.svg").read_text(encoding="utf-8")

    assert f'aria-label="{PRODUCT}"' in icon
    assert f"<title>{PRODUCT}</title>" in icon


def test_no_string_a_user_can_read_still_says_ethnos(messages) -> None:
    """Message *keys* may still say it -- see the identity audit -- text may not."""
    guilty = {
        key: entry["message"]
        for key, entry in messages.items()
        if "thnos" in entry["message"]
    }

    assert guilty == {}


@pytest.mark.parametrize("path", VISIBLE_SOURCES, ids=lambda p: p.name)
def test_no_markup_a_user_can_read_still_says_ethnos(path: Path) -> None:
    """Including the untranslated fallback text, which shows before i18n runs."""
    assert "Ethnos" not in path.read_text(encoding="utf-8")


def test_nothing_still_calls_facet_optional_or_experimental(messages) -> None:
    """Facet is the solver now, not a mode to opt into."""
    for key, entry in messages.items():
        text = f"{entry['message']} {entry.get('description', '')}".lower()
        if "facet" not in text:
            continue
        for stale in ("experimental", "optional", "opt in", "opt-in", "if you select"):
            assert stale not in text, f"{key}: {entry['message']}"


# --- the choice that is no longer a choice --------------------------------


def test_settings_offers_no_engine_to_choose() -> None:
    """Facet routes; there is nothing for the browser to select between."""
    options = (EXTENSION / "options" / "options.html").read_text(encoding="utf-8")

    assert "solveEngine" not in options
    assert "<select" not in options.split('id="pipeline"')[0]


def test_the_engine_strings_are_gone_from_the_catalogue(messages) -> None:
    assert not [key for key in messages if key.startswith("optionsSolveEngine")]


def test_the_retired_choice_cannot_reach_a_solve() -> None:
    """A stored `solveEngine` has nothing left to select, by construction.

    The browser sends a constant. Even a profile that still holds the old
    preference cannot put it into a request, because no code reads it and the
    schema no longer knows the key.
    """
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")
    settings = (EXTENSION / "common" / "settings.js").read_text(encoding="utf-8")

    assert 'const SOLVE_PIPELINE = "facet";' in background
    assert "solve_engine: pipeline," in background
    assert "solveEngine" not in background
    # Declared once, as something to clean up rather than something to read.
    assert 'OBSOLETE_SETTING_KEYS = Object.freeze(["solveEngine"])' in settings
    assert "solveEngine: {" not in settings


def test_the_settings_readout_names_all_three_facet_routes(messages) -> None:
    """What replaced the selector: a statement of what Facet actually does."""
    assert "Facet Exact" in messages["optionsPipelineExactValue"]["message"]
    assert "Facet Reasoning" in messages["optionsPipelineReasonerFacet"]["message"]
    graph = messages["optionsPipelineGraphValue"]["message"]
    assert "Facet Parabola Plan" in graph
    assert "Quadratic Regression" in graph


# --- the identity that stays ---------------------------------------------


def test_the_installed_identity_is_deliberately_unchanged(manifest) -> None:
    """Renaming these would orphan a profile and an installed native host.

    The add-on ID is what Firefox keys `storage.local` and an existing
    installation to, and `ethnos_hawkes` is the name of the native-messaging
    manifest already registered on disk. Both are internal, neither is shown to
    anyone, and changing either would cost a reinstall and a lost profile to buy
    nothing a user can see.
    """
    background = (EXTENSION / "background.js").read_text(encoding="utf-8")

    assert manifest["browser_specific_settings"]["gecko"]["id"] == "ethnos-hawkes@local"
    assert 'const NATIVE_HOST = "ethnos_hawkes";' in background
