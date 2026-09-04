"""The add-on looks like part of Firefox, and keeps looking like it.

The palette is Acorn's -- the design system Firefox itself is built in -- so
the panel reads as browser furniture rather than as a web page that happens to
be inside one. These tests pin the parts of that which are easy to undo by
accident: the single source for each colour, the high-contrast fallback, and
the two accessibility rules that are invisible until someone needs them.
"""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
THEME = EXTENSION_DIR / "common" / "theme.css"

STYLESHEETS = (
    THEME,
    EXTENSION_DIR / "popup" / "popup.css",
    EXTENSION_DIR / "options" / "options.css",
)

TOKEN = re.compile(r"^\s*(--[a-z-]+):\s*(.+?);", re.MULTILINE)


def _block(source: str, opener: str) -> str:
    """The body of the first brace-delimited block introduced by `opener`."""
    start = source.index(opener) + len(opener)
    depth = 1
    for offset in range(start, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                return source[start:offset]
    raise AssertionError(f"unterminated block after {opener!r}")


def _colour_tokens(body: str) -> dict[str, str]:
    return {
        name: value
        for name, value in TOKEN.findall(body)
        if name
        not in {
            "--radius",
            "--radius-card",
            "--control-height",
            "--font",
            "--font-mono",
            "--font-math",
            "--panel-width",
        }
    }


def test_each_colour_has_one_definition_that_switches_with_the_scheme():
    """A light block plus a dark override is two places to forget."""
    source = THEME.read_text()
    tokens = _colour_tokens(_block(source, ":root {"))

    assert tokens, "the theme defines no colours"
    for name, value in tokens.items():
        assert value.startswith("light-dark(") or value.startswith("var("), (
            f"{name} is a single fixed colour; use light-dark() so it follows the theme"
        )
    # `light-dark()` needs this to resolve, and it is what stops Firefox
    # painting a light form control on a dark panel.
    assert "color-scheme: light dark;" in source
    # The pair is the definition, so there is no second place to keep in step.
    assert "@media (prefers-color-scheme" not in source


def test_high_contrast_mode_replaces_every_colour():
    """Firefox honours forced-colors, and a token it misses shows through."""
    source = THEME.read_text()
    declared = set(_colour_tokens(_block(source, ":root {")))
    forced = set(_colour_tokens(_block(source, "@media (forced-colors: active) {")))

    missing = {name for name in declared if name not in forced}
    assert missing == set(), f"not replaced under forced-colors: {sorted(missing)}"


def test_the_palette_is_firefox_s_own():
    source = THEME.read_text()

    # Acorn's accent pair, its in-content text pair, and Firefox's panel
    # surfaces -- the values the browser draws its own chrome with.
    for colour in ("#0060df", "#00ddff", "#15141a", "#fbfbfe", "#2b2a33", "#1c1b22"):
        assert colour in source, f"{colour} is not in the palette"
    # 2px at 2px offset is Firefox's focus ring, and it is never suppressed.
    assert "outline: 2px solid var(--focus)" in source
    assert "outline-offset: 2px" in source
    assert "outline: none" not in source
    assert "outline: 0" not in source


def test_no_animation_runs_unless_the_user_allows_motion():
    for path in STYLESHEETS:
        source = path.read_text()
        for match in re.finditer(r"transition:", source):
            preceding = source[: match.start()]
            opened = preceding.rfind("@media (prefers-reduced-motion: no-preference)")
            assert opened != -1, f"{path.name}: a transition outside a motion query"
            # Still inside that query, rather than after it closed.
            assert preceding.count("{", opened) > preceding.count("}", opened), (
                f"{path.name}: a transition after the motion query closed"
            )


def test_both_pages_declare_their_scheme_before_the_stylesheet_loads():
    """Otherwise a dark-theme popup opens as a white rectangle and then repaints."""
    for page in ("popup/popup.html", "options/options.html"):
        markup = (EXTENSION_DIR / page).read_text()
        declaration = markup.index('name="color-scheme"')
        stylesheet = markup.index('rel="stylesheet"')
        assert declaration < stylesheet, f"{page}: the scheme is declared too late"


def test_the_panel_width_is_a_preference_rather_than_a_constant():
    css = (EXTENSION_DIR / "popup" / "popup.css").read_text()
    script = (EXTENSION_DIR / "popup" / "popup.js").read_text()

    assert "width: var(--panel-width)" in css
    assert "--panel-width" in script
    # Firefox clamps a popup at 600px tall and would otherwise scroll it in a
    # scrollbar of its own.
    assert "max-height: 600px" in css


def test_the_panel_still_keeps_one_shape():
    """0.22.0's decision, which the new regions must not undo."""
    css = (EXTENSION_DIR / "popup" / "popup.css").read_text()

    # An answer box that resized with its content, and a status line that
    # collapsed when short, moved everything below them on every state change.
    # The answer area, now stated border-box so the row of padding reserved for
    # its chips comes out of this height rather than adding to it. The rendered
    # height is what it has always been: 84 content + 20 padding + 2 border.
    assert "box-sizing: border-box" in css
    assert "min-height: 106px" in css  # the answer area
    assert "min-height: 32px" in css  # two lines reserved for the status
    assert "grid-template-columns: 1fr 1fr" in css  # two buttons, never four
    # The copy affordance is positioned out of flow so it reserves no row.
    assert "position: absolute" in css
