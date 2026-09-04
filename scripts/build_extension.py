#!/usr/bin/env python3
"""Validate and package the Ethnos Hawkes Firefox extension.

This repository-specific validator supplements Mozilla's `web-ext lint`: it
enforces the project's narrower permission and zero-persistent-site-footprint
contracts, then writes a reproducible unsigned XPI for AMO validation/signing
or temporary loading through `about:debugging`.

Usage::

    python3 scripts/build_extension.py --check      # validate only
    python3 scripts/build_extension.py              # validate and package
    python3 scripts/build_extension.py --icons      # also re-render PNG icons
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
DIST_DIR = PROJECT_ROOT / "dist"

# Only these suffixes are shipped; anything else in the tree is developer
# material that has no business inside a signed add-on.
PACKAGED_SUFFIXES = {".json", ".js", ".css", ".html", ".png"}
EXCLUDED_NAMES = {"README.md", "CHANGELOG.md", "TESTING.md"}
EXCLUDED_DIR_NAMES = {"node_modules", "__pycache__", ".git"}

ICON_SIZES = (16, 32, 48, 96, 128)

VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")
MESSAGE_PLACEHOLDER = re.compile(r"__MSG_([A-Za-z0-9_]+)__")
JS_MESSAGE_CALL = re.compile(r"""\bmessage\(\s*["']([A-Za-z0-9_]+)["']\s*[,)]""")
JS_STRING_LITERAL = re.compile(r"""["']([A-Za-z0-9_]+)["']""")
DATA_I18N = re.compile(r"""data-i18n="([A-Za-z0-9_]+)\"""")
DATA_I18N_ATTR = re.compile(r"""data-i18n-attr="([^"]+)\"""")

# Capabilities this add-on has promised not to have. Each is matched against
# every shipped script; a hit is a build failure, not a warning.
FORBIDDEN_TOKENS = (
    "eval(",
    "new Function(",
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
    "document.write",
    "tabs.update",
    "tabs.create",
    "window.location =",
    "location.href =",
    "XMLHttpRequest",
    "fetch(",
    ".submit()",
    ".click()",
    # Page-observable footprints: the host page must not be able to detect the
    # add-on by reading a marker, an injected node, a stylesheet, or messages.
    # A DOM message channel with the page, specifically. Extension port
    # messaging is a different mechanism and is how the panel and the
    # background talk; it never reaches page script.
    "window.postMessage",
    "contentWindow.postMessage",
    "runtime.getURL",
    "document.head.append",
    "adoptedStyleSheets",
    "insertCSS",
    # Crossing Firefox's content-script isolation boundary. Ordinary DOM access
    # needs none of these, and each one is observable from the page.
    "wrappedJSObject",
    "exportFunction",
    "cloneInto",
    # Chrome-isms: this add-on targets Firefox's promise-based namespace.
    "chrome.",
)

# Anything under content/ is injected into the Hawkes page, so it carries extra
# rules: read from `window`, never write to it, and add nothing to the DOM.
CONTENT_DIR = Path("content")
CONTENT_SCRIPT_FORBIDDEN = (
    # An injected script must never be able to reach Ethnos, capture the tab,
    # or open a connection: the page it runs in is not trusted. Nor may it use
    # any form of postMessage, which the page could intercept.
    "postMessage",
    "sendNativeMessage",
    "connectNative",
    "captureVisibleTab",
    "window.__",
    "window[",
    "document.createElement",
    "createTextNode",
    "attachShadow",
    "setAttribute",
    "classList",
    "style.",
    "appendChild",
    ".append(",
    ".prepend(",
    ".before(",
    ".after(",
    # Patching a built-in is exactly what prototype-tampering checks look for.
    ".prototype.",
    "defineProperty",
)

ALLOWED_PERMISSIONS = ["activeTab", "nativeMessaging", "scripting", "storage"]


class ValidationError(Exception):
    """Raised when the extension tree violates a shipping requirement."""


def _load_manifest() -> dict:
    return json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))


def _load_messages(manifest: dict) -> dict:
    locale = manifest["default_locale"]
    path = EXTENSION_DIR / "_locales" / locale / "messages.json"
    if not path.is_file():
        raise ValidationError(f"missing message catalogue for default_locale {locale}")
    return json.loads(path.read_text(encoding="utf-8"))


def packaged_files() -> list[Path]:
    """Return the shipped files, sorted, as paths relative to the extension."""
    files = []
    for path in sorted(EXTENSION_DIR.rglob("*")):
        if not path.is_file():
            continue
        if any(
            part in EXCLUDED_DIR_NAMES for part in path.relative_to(EXTENSION_DIR).parts
        ):
            continue
        if path.name in EXCLUDED_NAMES or path.suffix not in PACKAGED_SUFFIXES:
            continue
        files.append(path.relative_to(EXTENSION_DIR))
    return files


def _check_manifest(manifest: dict, problems: list[str]) -> None:
    if manifest.get("manifest_version") != 3:
        problems.append("manifest_version must be 3")
    if not VERSION_PATTERN.match(str(manifest.get("version", ""))):
        problems.append("version must look like 1.2.3")
    if manifest.get("host_permissions") != ["*://learn.hawkeslearning.com/*"]:
        # One host, declared. Broader than activeTab and deliberately so:
        # activeTab is granted only by the toolbar button, which left the
        # sidebar with no access at all and made the add-on nag for a
        # permission it needs to do anything. Anything wider than this single
        # origin is still a build failure.
        problems.append(
            'host_permissions must be exactly ["*://learn.hawkeslearning.com/*"]'
        )
    if manifest.get("permissions") != ALLOWED_PERMISSIONS:
        problems.append(f"permissions must be exactly {ALLOWED_PERMISSIONS}")
    if "content_scripts" in manifest:
        problems.append("content scripts must be injected on demand, not declared")
    if "web_accessible_resources" in manifest:
        # Any exposed resource is a probe target. Firefox randomizes the
        # moz-extension UUID per profile, so a page cannot guess the URL, but it
        # can read one the add-on hands it. Exposing nothing closes that path.
        problems.append("web_accessible_resources must stay absent")
    background = manifest.get("background")
    if background is not None:
        # Firefox MV3 offers non-persistent event pages, not Chrome's service
        # workers. One exists so a solve survives the popup closing; it must
        # stay a plain event page and must not be made persistent.
        if background.get("scripts") != ["background.js"]:
            problems.append("background must be exactly ['background.js']")
        if background.get("type") != "module":
            # Static imports are the documented way to share code with an event
            # page; dynamic import() in a classic background script is not.
            problems.append("background must declare type 'module'")
        if background.get("persistent"):
            problems.append("the background page must stay non-persistent")
        if "service_worker" in background:
            problems.append(
                "service_worker is Chrome's model; Firefox uses event pages"
            )
    if manifest.get("permissions") != ALLOWED_PERMISSIONS:
        pass  # already reported above
    for key in ("declarative_net_request", "webRequest", "chrome_settings_overrides"):
        if key in manifest:
            problems.append(f"{key} must stay absent; this add-on touches no requests")

    gecko = manifest.get("browser_specific_settings", {}).get("gecko", {})
    if not gecko.get("id"):
        problems.append("browser_specific_settings.gecko.id is required for signing")
    if not gecko.get("strict_min_version"):
        problems.append(
            "browser_specific_settings.gecko.strict_min_version is required"
        )
    collection = gecko.get("data_collection_permissions", {}).get("required")
    if collection != ["websiteContent"]:
        problems.append(
            "gecko.data_collection_permissions.required must be "
            '["websiteContent"] because native messaging processes the question'
        )

    csp = manifest.get("content_security_policy", {}).get("extension_pages", "")
    if "script-src 'self'" not in csp:
        problems.append("extension_pages CSP must pin script-src to 'self'")


def _check_referenced_paths(manifest: dict, problems: list[str]) -> None:
    referenced = set()
    for size in ICON_SIZES:
        referenced.add(manifest.get("icons", {}).get(str(size)))
    referenced.update(manifest.get("action", {}).get("default_icon", {}).values())
    referenced.add(manifest.get("action", {}).get("default_popup"))
    referenced.add(manifest.get("options_ui", {}).get("page"))

    for reference in sorted(filter(None, referenced)):
        if not (EXTENSION_DIR / reference).is_file():
            problems.append(f"manifest references missing file: {reference}")

    for size in ICON_SIZES:
        if str(size) not in manifest.get("icons", {}):
            problems.append(f"icons is missing the {size}px entry")


def _check_localization(manifest: dict, messages: dict, problems: list[str]) -> None:
    manifest_text = (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")
    # `resolved` holds names that must exist in the catalogue; `mentioned` also
    # counts names passed around as plain literals, such as the reason-code map
    # in popup.js, so that the unused check does not report false positives.
    resolved: set[str] = set(MESSAGE_PLACEHOLDER.findall(manifest_text))
    mentioned: set[str] = set(resolved)

    for path in packaged_files():
        if path.suffix not in {".html", ".js"}:
            continue
        text = (EXTENSION_DIR / path).read_text(encoding="utf-8")
        if path.suffix == ".html":
            names = set(DATA_I18N.findall(text))
            for group in DATA_I18N_ATTR.findall(text):
                for pair in group.split(","):
                    _, _, name = pair.partition(":")
                    if name.strip():
                        names.add(name.strip())
            resolved |= names
            mentioned |= names
        else:
            resolved.update(JS_MESSAGE_CALL.findall(text))
            mentioned.update(JS_STRING_LITERAL.findall(text))

    for name in sorted(resolved - set(messages)):
        problems.append(f"message '{name}' is used but not defined in the catalogue")
    for name in sorted(set(messages) - mentioned):
        problems.append(f"message '{name}' is defined but never used")
    for name, entry in sorted(messages.items()):
        if not entry.get("message"):
            problems.append(f"message '{name}' has no text")
        if not entry.get("description"):
            problems.append(f"message '{name}' has no translator description")


def _check_scripts(problems: list[str]) -> None:
    for path in packaged_files():
        if path.suffix not in {".js", ".html"}:
            continue
        text = (EXTENSION_DIR / path).read_text(encoding="utf-8")
        for token in FORBIDDEN_TOKENS:
            if token in text:
                problems.append(f"{path}: forbidden construct {token!r}")
        if path.suffix == ".html":
            if re.search(r"<script(?![^>]*\bsrc=)", text):
                problems.append(f"{path}: inline <script> is blocked by the page CSP")
            if re.search(r"\son[a-z]+=", text):
                problems.append(
                    f"{path}: inline event handler is blocked by the page CSP"
                )
        if path.parts[0] == CONTENT_DIR.name:
            for token in CONTENT_SCRIPT_FORBIDDEN:
                if token in text:
                    problems.append(
                        f"{path}: {token!r} would leave a page-detectable footprint"
                    )


INJECTED_PATH = re.compile(r"""_SCRIPT = ["']([^"']+)["']""")

# The two files allowed to run in the page's own world, and nothing else.
# Hawkes drives its editor through page-owned JavaScript, so reading the rules
# and building structure both require it.
MAIN_WORLD_SCRIPT = Path("content/hawkes-describe.js")  # reads only
MAIN_WORLD_WRITER = Path("common/page-actions.js")  # the one writer


def _check_main_world(problems: list[str]) -> None:
    """The page-world probe must read and never write."""
    path = EXTENSION_DIR / MAIN_WORLD_SCRIPT
    if not path.is_file():
        problems.append(f"{MAIN_WORLD_SCRIPT} is missing")
        return
    text = path.read_text(encoding="utf-8")
    # It reads the editor model; it must not call into it or assign to it.
    # Assignment is matched rather than the bare name, so a comparison such as
    # `boxValue === undefined` is not mistaken for a write.
    writes = (
        (r"keyPadButtonClick\s*\(", "presses a keypad template"),
        (r"\bfocusedElementIndex\s*=(?!=)", "moves the editor's focus"),
        (r"\bboxValue\s*=(?!=)", "assigns a box value"),
        (r"\.click\s*\(", "clicks a page element"),
        (r"\bdispatchEvent\s*\(", "dispatches an event"),
        (r"\.value\s*=(?!=)", "assigns an input value"),
    )
    for pattern, what in writes:
        if re.search(pattern, text):
            problems.append(
                f"{MAIN_WORLD_SCRIPT}: {what}; the page-world probe is read-only"
            )
    _check_main_world_writer(problems)

    # No other script may reach the page model.
    allowed = {MAIN_WORLD_SCRIPT, MAIN_WORLD_WRITER}
    for other in packaged_files():
        if other.suffix != ".js" or other in allowed:
            continue
        if "quant_wp_UI" in (EXTENSION_DIR / other).read_text(encoding="utf-8"):
            problems.append(
                f"{other}: only {MAIN_WORLD_SCRIPT} and {MAIN_WORLD_WRITER} "
                f"may touch the page model"
            )


def _check_main_world_writer(problems: list[str]) -> None:
    """The page-world writer builds answers, and may do nothing else.

    It calls the editor's own `keyPadButtonClick` because that is the only way
    to load a template. That is a deliberate, bounded capability: it may type
    into answer boxes and press named templates, and it may not click page
    elements, navigate, submit, or evaluate anything.
    """
    path = EXTENSION_DIR / MAIN_WORLD_WRITER
    if not path.is_file():
        problems.append(f"{MAIN_WORLD_WRITER} is missing")
        return
    text = path.read_text(encoding="utf-8")

    forbidden = (
        (r"\beval\s*\(", "evaluates code"),
        (r"\bnew Function\s*\(", "builds a function from text"),
        (r"\.click\s*\(", "clicks a page element"),
        (r"\bsubmit\b", "references submission"),
        (r"location\s*[.=]", "touches navigation"),
        (r"\bfetch\s*\(|XMLHttpRequest", "makes a request"),
        (r"innerHTML|outerHTML|insertAdjacentHTML", "writes markup"),
    )
    for pattern, what in forbidden:
        if re.search(pattern, text):
            problems.append(f"{MAIN_WORLD_WRITER}: {what}; it may only enter answers")

    # The single page method it is allowed to call.
    if "keyPadButtonClick" not in text:
        problems.append(
            f"{MAIN_WORLD_WRITER}: expected to press templates via the editor"
        )
    if "func: enterPlan" not in (EXTENSION_DIR / "background.js").read_text(
        encoding="utf-8"
    ):
        problems.append("background.js must pass enterPlan as the injected function")


def _check_injected_paths(problems: list[str]) -> None:
    """Injected file paths must be root-absolute and must exist.

    Firefox resolves `scripting.executeScript` file paths against the calling
    document, not the extension root, so a bare "content/x.js" from
    popup/popup.html silently becomes "popup/content/x.js" and throws at
    injection time -- inside a frame, where only the returned error shows it.
    """
    for path in packaged_files():
        if path.suffix != ".js":
            continue
        text = (EXTENSION_DIR / path).read_text(encoding="utf-8")
        for reference in INJECTED_PATH.findall(text):
            if not reference.startswith("/"):
                problems.append(
                    f"{path}: injected path {reference!r} must start with '/' or it "
                    f"resolves against the calling document"
                )
                continue
            if not (EXTENSION_DIR / reference.lstrip("/")).is_file():
                problems.append(f"{path}: injected path {reference!r} does not exist")


# The cadence tuning that `common/cadence.js` and the MAIN-world copy inside
# `common/page-actions.js` must agree on, note for note. The copy exists because
# `executeScript` serialises `enterPlan` into the page's own world, where it can
# close over no extension code -- so the only thing standing between the two is
# a check. Each pattern is written to match both spellings of the same value;
# the capture groups are compared, not the surrounding text.
CADENCE_TUNING = (
    ("fallback tempo", r"tempoBpm: (\d+)"),
    ("fallback window", r"durationMinMs: (\d+),\s*\n\s*durationMaxMs: (\d+)"),
    ("fallback beat shape", r"rhythmWeights: (?:Object\.freeze\()?\[([^\]]+)\]"),
    (
        "fallback feel",
        r"swingRatio: ([\d.]+),\s*\n\s*variationRatio: ([\d.]+),"
        r"\s*\n\s*symbolRestRatio: ([\d.]+)",
    ),
    ("beat-shape weight bounds", r"bounded\(w(?:eight)?, ([\d.]+), ([\d.]+), (\d+)\)"),
    ("tempo bounds", r"\.tempoBpm, (\d+), (\d+)"),
    ("duration bounds", r"\.duration(?:Min|Max)Ms, (\d+), (\d+)"),
    ("swing bounds", r"\.swingRatio, (\d+), ([\d.]+)"),
    ("variation bounds", r"\.variationRatio, (\d+), ([\d.]+)"),
    ("structural-rest bounds", r"\.symbolRestRatio, (\d+), (\d+)"),
    ("swing lift and drop", r"1 - \w+\.swingRatio \* ([\d.]+)"),
    ("structural-rest multipliers", r"symbolRestRatio(?: \* ([\d.]+))?;"),
    ("variation spread", r"\* (\d+)\) - (\d+)\) \* \w+\.variationRatio"),
    ("beat length", r"(\d+) / \w+\.tempoBpm"),
    ("weight floor", r"Math\.max\((\d+), (?:totalWeight|total)\)"),
    ("tempo/window blend", r"\* (0\.\d+)\) \+ \(\w+ \* (0\.\d+)\)"),
)


def _check_cadence_copies(problems: list[str]) -> None:
    """The MAIN-world score must stay note-for-note identical to the shared one.

    `enterPlan` is serialised into the page's own world, so it carries its own
    copy of the bounded score builder and can import nothing. That copy is
    deliberate and documented; a copy nobody compares is how a retuned tempo
    range reaches plain entry and silently misses structured entry.
    """
    shared = (EXTENSION_DIR / "common" / "cadence.js").read_text(encoding="utf-8")
    injected = (EXTENSION_DIR / "common" / "page-actions.js").read_text(
        encoding="utf-8"
    )
    for label, pattern in CADENCE_TUNING:
        here = re.findall(pattern, shared)
        there = re.findall(pattern, injected)
        if not here or not there:
            problems.append(
                f"cadence {label} could not be read from both common/cadence.js "
                f"and the MAIN-world copy in common/page-actions.js"
            )
        elif here != there:
            problems.append(
                f"the MAIN-world cadence copy in common/page-actions.js has "
                f"drifted from common/cadence.js: {label} is {there} there and "
                f"{here} in the shared score"
            )


def _check_shared_constants(problems: list[str]) -> None:
    """The content scripts are self-contained, so their copies must not drift."""
    config = (EXTENSION_DIR / "common" / "config.js").read_text(encoding="utf-8")
    editor = (EXTENSION_DIR / "content" / "hawkes-editor.js").read_text(
        encoding="utf-8"
    )

    for name in (
        "MAX_ANSWER_LENGTH",
        "ANSWER_PATTERN",
    ):
        shared = re.search(rf"\b{name} = (.+);", config)
        content = re.search(rf"\b{name} = (.+);", editor)
        if not shared or not content:
            problems.append(f"could not read {name} from both copies to compare")
        elif shared.group(1) != content.group(1):
            problems.append(
                f"content/hawkes-editor.js {name} ({content.group(1)}) has drifted "
                f"from common/config.js ({shared.group(1)})"
            )

    # The prelude checks a full origin; the popup checks the hostname half.
    hostname = re.search(r'ALLOWED_HOSTNAME = "([^"]+)"', config)
    origin = re.search(r'ALLOWED_ORIGIN = "https://([^"]+)"', editor)
    if not hostname or not origin:
        problems.append("could not read the allowed host from both copies")
    elif hostname.group(1) != origin.group(1):
        problems.append(
            f"content script origin ({origin.group(1)}) has drifted from "
            f"ALLOWED_HOSTNAME ({hostname.group(1)})"
        )


# Names that read like message catalogue keys. The panel's view module returns
# keys as plain literals rather than calling `message()`, so the localization
# check cannot see them; this pattern is how they are found instead.
MESSAGE_KEY = re.compile(
    r"""["'']((?:status|error|popup|stage|panel|options|logLevel)[A-Z][A-Za-z0-9_]*)["'']"""
)

# `const`/`let`, including a simple destructuring pattern.
DECLARATION = re.compile(
    r"\b(?:const|let)\s+(\{[^{}]*\}|\[[^\[\]]*\]|[A-Za-z_$][\w$]*)"
)
IDENTIFIER = re.compile(r"[A-Za-z_$][\w$]*")


def _blank_literals(source: str) -> str:
    """Replace comments and string bodies with spaces, keeping every offset.

    Offsets have to survive so the positions found in the blanked text still
    point at the real source. Only the *contents* go; the quotes and the
    newlines stay, so line structure and brace nesting are untouched.
    """
    out = list(source)
    index = 0
    length = len(source)
    while index < length:
        char = source[index]
        if char == "/" and index + 1 < length and source[index + 1] == "/":
            while index < length and source[index] != "\n":
                out[index] = " "
                index += 1
        elif char == "/" and index + 1 < length and source[index + 1] == "*":
            while index < length and not (
                source[index] == "*" and source[index + 1 : index + 2] == "/"
            ):
                if source[index] != "\n":
                    out[index] = " "
                index += 1
            for offset in range(index, min(index + 2, length)):
                out[offset] = " "
            index += 2
        elif char in "\"'`":
            quote = char
            index += 1
            while index < length and source[index] != quote:
                if source[index] == "\\":
                    out[index] = " "
                    index += 1
                    if index < length and source[index] != "\n":
                        out[index] = " "
                elif source[index] != "\n":
                    out[index] = " "
                index += 1
            index += 1
        else:
            index += 1
    return "".join(out)


def _check_declaration_order(problems: list[str]) -> None:
    """No `const` or `let` may be read above its own declaration.

    JavaScript hoists the binding but leaves it uninitialized until the
    declaration runs, so reading it first is a `ReferenceError` every single
    time -- not a subtle bug, a total one. 0.22.0 shipped exactly that in
    `popup.js`: `render()` read a `const` it declared thirty-eight lines below,
    so every render threw and the panel silently stopped updating. Nothing in
    the suite noticed, because it was all textual assertions over source.

    Only same-block, same-nesting reads are reported. A reference inside a
    nested function is legal -- it runs when the function is called, by which
    time the declaration has -- and distinguishing "runs later" from "runs now"
    is not something a build check should be guessing at. The narrow rule is
    the one that is always a bug, and `tests/test_hawkes_panel.py` executes the
    panel to cover the rest.
    """
    for path in packaged_files():
        if path.suffix != ".js":
            continue
        source = (EXTENSION_DIR / path).read_text(encoding="utf-8")
        blanked = _blank_literals(source)

        # Give every brace pair an identity, so "the same block" is exact
        # rather than merely "the same depth".
        block_of: list[int] = [0] * (len(blanked) + 1)
        parens: list[int] = [0] * (len(blanked) + 1)
        stack = [0]
        next_block = 1
        depth = 0
        for offset, char in enumerate(blanked):
            if char == "{":
                stack.append(next_block)
                next_block += 1
            block_of[offset] = stack[-1]
            parens[offset] = depth
            if char == "}" and len(stack) > 1:
                stack.pop()
            elif char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)

        for match in DECLARATION.finditer(blanked):
            # A for-head or a catch parameter declares into the loop, not into
            # the surrounding block.
            if parens[match.start()] > 0:
                continue
            block = block_of[match.start()]
            names = [
                name
                for name in IDENTIFIER.findall(match.group(1))
                if name not in {"of", "in"}
            ]
            for name in names:
                for use in re.finditer(
                    rf"\b{re.escape(name)}\b", blanked[: match.start()]
                ):
                    if block_of[use.start()] != block:
                        continue
                    if use.start() > 0 and blanked[use.start() - 1] in ".":
                        continue  # a property that happens to share the name
                    line = source.count("\n", 0, use.start()) + 1
                    declared = source.count("\n", 0, match.start()) + 1
                    problems.append(
                        f"{path}:{line}: {name!r} is read before its declaration on "
                        f"line {declared}; that is a ReferenceError every time"
                    )
                    break


# Which script each extension page loads, so a selector can be checked against
# the markup it will actually run against.
PAGE_SELECTOR = re.compile(
    r"""(?:querySelector\(|getElementById\()["']#?([A-Za-z][\w-]*)["']"""
)
HTML_ID = re.compile(r"""\bid="([^"]+)\"""")
PAGE_SCRIPT = re.compile(r"""<script[^>]*\bsrc="([^"]+)\"""")


def _check_element_ids(problems: list[str]) -> None:
    """Every id a page script looks up must exist in that page.

    `document.querySelector("#gone")` returns null, and the first property
    assignment onto it throws -- the same total failure as a use-before-declare,
    reached by renaming an element instead. Cheap to rule out.
    """
    for path in packaged_files():
        if path.suffix != ".html":
            continue
        markup = (EXTENSION_DIR / path).read_text(encoding="utf-8")
        available = set(HTML_ID.findall(markup))
        for reference in PAGE_SCRIPT.findall(markup):
            script = (EXTENSION_DIR / path).parent / reference
            if not script.is_file():
                problems.append(f"{path}: script {reference!r} does not exist")
                continue
            body = script.read_text(encoding="utf-8")
            for name in sorted(set(PAGE_SELECTOR.findall(body))):
                if name not in available:
                    problems.append(
                        f"{script.relative_to(EXTENSION_DIR)}: no element with id "
                        f"{name!r} in {path}"
                    )


def _check_view_message_keys(messages: dict, problems: list[str]) -> None:
    """Keys returned as data must exist too.

    `common/panel-view.js` decides what the panel says and returns catalogue
    keys rather than text, so the panel localizes `message(view.status.key)` --
    a call the localization check cannot follow. A key that is only ever named
    here would otherwise reach the panel as its own name on screen.
    """
    path = Path("common/panel-view.js")
    source = (EXTENSION_DIR / path).read_text(encoding="utf-8")
    for name in sorted(set(MESSAGE_KEY.findall(source))):
        if name not in messages:
            problems.append(
                f"{path}: returns message key {name!r}, which is not defined"
            )


def _check_undefined_constants(problems: list[str]) -> None:
    """Every SHOUTING_CASE name a script uses must be declared or imported.

    `QUESTION_SCRIPT` was used in `background.js` and declared nowhere. A module
    throws `ReferenceError` on such a name, `readQuestion` caught it and logged
    a warning, and the add-on fell back to the screenshot and its two vision
    readers on every question -- silently, for as long as the constant was
    missing. The reader worked when run from the harness, which loads the file
    itself, so tests and live probes both looked fine. This is the second bug of
    the shape "a name background.js reads is not there"; the first was a const
    read before its declaration, which `_check_declaration_order` now catches.
    """
    for path in sorted(EXTENSION_DIR.rglob("*.js")):
        source = path.read_text(encoding="utf-8")
        blanked = _blank_literals(source)
        used = set(re.findall(r"\b([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b", blanked))
        if not used:
            continue
        declared = set(
            re.findall(r"(?:const|let|var|function|class)\s+([A-Z][A-Z0-9_]*)", blanked)
        )
        declared |= set(
            re.findall(r"^\s*([A-Z][A-Z0-9_]+)\s*[,}]", blanked, re.MULTILINE)
        )
        for statement in re.findall(r"import\s*\{([^}]*)\}", blanked):
            declared |= {
                name.split(" as ")[-1].strip()
                for name in statement.split(",")
                if name.strip()
            }
        # Names the platform provides, and ones used as object keys only.
        allowed = {"NaN", "Infinity", "URL_SEARCH_PARAMS"}
        missing = sorted(
            name
            for name in used - declared - allowed
            if not re.search(rf"[.\[\"']\s*{re.escape(name)}", blanked)
        )
        if missing:
            problems.append(
                f"{path.relative_to(EXTENSION_DIR)} uses undeclared constant(s): "
                f"{', '.join(missing)}"
            )


def validate() -> list[str]:
    """Return a list of problems; an empty list means the tree is shippable."""
    problems: list[str] = []
    manifest = _load_manifest()
    _check_manifest(manifest, problems)
    _check_referenced_paths(manifest, problems)
    messages = _load_messages(manifest)
    _check_localization(manifest, messages, problems)
    _check_view_message_keys(messages, problems)
    _check_scripts(problems)
    _check_declaration_order(problems)
    _check_undefined_constants(problems)
    _check_element_ids(problems)
    _check_shared_constants(problems)
    _check_cadence_copies(problems)
    _check_injected_paths(problems)
    _check_main_world(problems)
    return problems


def render_icons() -> None:
    """Re-render the PNG icon set from the SVG source."""
    converter = shutil.which("rsvg-convert")
    if converter is None:
        raise ValidationError("rsvg-convert is required to re-render icons")
    source = EXTENSION_DIR / "icons" / "icon.svg"
    for size in ICON_SIZES:
        target = EXTENSION_DIR / "icons" / f"icon-{size}.png"
        subprocess.run(
            [
                converter,
                "-w",
                str(size),
                "-h",
                str(size),
                "-o",
                str(target),
                str(source),
            ],
            check=True,
        )
        print(f"rendered {target.relative_to(PROJECT_ROOT)}")


def build(output_dir: Path = DIST_DIR) -> Path:
    """Write a reproducible XPI and return its path."""
    manifest = _load_manifest()
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"ethnos-hawkes-{manifest['version']}-unsigned.xpi"

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in packaged_files():
            # A fixed timestamp keeps the archive byte-identical between builds.
            info = zipfile.ZipInfo(path.as_posix(), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (EXTENSION_DIR / path).read_bytes())
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="validate without packaging"
    )
    parser.add_argument(
        "--icons", action="store_true", help="re-render PNG icons first"
    )
    parser.add_argument("--out", type=Path, default=DIST_DIR, help="output directory")
    args = parser.parse_args(argv)

    try:
        if args.icons:
            render_icons()
        problems = validate()
    except (ValidationError, json.JSONDecodeError, OSError) as error:
        print(f"extension validation failed: {error}", file=sys.stderr)
        return 2

    if problems:
        print("extension validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    files = packaged_files()
    print(f"validated {len(files)} packaged files")
    if args.check:
        return 0

    target = build(args.out)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"wrote {target}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
