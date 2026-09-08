#!/usr/bin/env python3
"""Drive the Hawkes add-on in a real Firefox against local fixtures.

`scripts/build_extension.py` checks the tree statically and
`tests/test_hawkes_frames.py` exercises the frame decision under QuickJS.
Neither can tell you whether Firefox actually injects where it is asked, which
is the class of bug that shipped in 0.7.0: `scripting.executeScript` resolves
file paths against the *calling document*, so a bare "content/x.js" from
popup.html silently became "popup/content/x.js".

This harness closes that gap. It builds a throwaway copy of the add-on pointed
at a local origin, installs it temporarily in a throwaway Firefox profile via
Marionette, clicks the real toolbar button so `activeTab` is granted the way it
is in normal use, and reads back what the popup actually displayed.

It never touches the user's profile, their running Firefox, or the real Hawkes
site: fixtures are served from localhost and the browser is a separate instance
on a temporary profile.

It runs headless by default. On a Wayland session `xvfb-run` alone does *not*
isolate Firefox -- it sets DISPLAY, and Firefox reads WAYLAND_DISPLAY and opens
its windows on the real compositor, over whatever the developer is doing. The
launcher drops that handle; headless removes the question entirely.

The packaged browser may not support this at all. `firefox-pure` 155 ships with
Marionette stripped out, so `--marionette` is an unrecognized flag and no port
opens. Point `ETHNOS_FIREFOX` at a build that has it; Mozilla's release tarball
does and needs no root::

    export ETHNOS_FIREFOX="$HOME/.local/opt/firefox-mozilla/firefox"

Usage::

    python3 scripts/run_extension_harness.py
    python3 scripts/run_extension_harness.py --scenario top
    python3 scripts/run_extension_harness.py --show      # watch it work
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.marionette import (  # noqa: E402
    ActionButtonMissing,
    Marionette,
    MarionetteError,
    action_button_selector,
    launch,
    pin_action_to_toolbar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"

ADDON_ID = json.loads((EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8"))[
    "browser_specific_settings"
]["gecko"]["id"]

# Toolbar button id Firefox derives from the add-on id. The node only exists
# once the action is placed in a visible area; see `pin_action_to_toolbar`.
ACTION_BUTTON = action_button_selector(ADDON_ID)

FOCUSED_FIELD = '<input id="answer" type="text"><script>answer.focus()</script>'

# One Hawkes answer control, named as Hawkes names them so the question probe's
# "everything above the answer area" boundary is computed the way it is live.
HAWKES_FIELD = (
    "<div>Answer</div>"
    '<input id="txtAns1" class="qbaseCSS" type="text">'
    "<script>txtAns1.focus()</script>"
)

# The polynomial, as MathJax leaves it in the document. The probe reads this
# rather than a screenshot, and `questionSignature` returns null without it.
POLYNOMIAL = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow>'
    "<mo>-</mo><mn>3</mn><msup><mi>x</mi><mn>11</mn></msup>"
    "<mo>-</mo><msup><mi>x</mi><mn>13</mn></msup>"
    "<mo>+</mo><mn>5</mn>"
    "<mo>+</mo><mn>2</mn><msup><mi>x</mi><mn>12</mn></msup>"
    "</mrow></math>"
)


def hawkes_short_step(instruction: str) -> str:
    """A page whose step marker appears twice, as Hawkes prints it.

    Once in the header beside the question number, once at the head of the
    instruction. Both pages in this group carry the *same* header and the same
    "Step 2 of 3" marker, and differ only in a short instruction -- so their
    signatures can only differ if that instruction is read.

    Live, they were not. The header was taken as the step, `Identify the
    degree.` was dropped for being exactly twenty characters, and the page's
    radio-button note was picked up as the instruction instead.
    """
    return (
        "<!doctype html><title>hawkes</title>"
        "<div>Question 5 of 14, &nbsp;Step 2 of 3</div>"
        "<div>Consider the following polynomial.</div>"
        f"{POLYNOMIAL}"
        f'<div><span class="stepLabel">Step 2 of 3 :</span> {instruction}</div>'
        "<div>Selecting a radio button will replace the entered answer value(s) "
        "with the radio button value. If the radio button is not selected, the "
        "entered answer is used.</div>"
        f"{HAWKES_FIELD}"
    )


def hawkes_detached_short_step(instruction: str) -> str:
    """The step marker in an element of its own, and a short instruction below.

    Sharper than `hawkes_short_step`: with the marker carrying no verb, the
    only way these pages can be told apart is by reading the instruction
    itself. That isolates the length cutoff, which the other group does not --
    preferring the instruction-bearing step line is enough to distinguish those
    even when the instruction is dropped.
    """
    return (
        "<!doctype html><title>hawkes</title>"
        "<div>Question 5 of 14, &nbsp;Step 2 of 3</div>"
        f"{POLYNOMIAL}"
        '<div><span class="stepLabel">Step 2 of 3 :</span></div>'
        f"<div>{instruction}</div>"
        "<div>Selecting a radio button will replace the entered answer value(s) "
        "with the radio button value.</div>"
        f"{HAWKES_FIELD}"
    )


def hawkes_step(step_line: str, *, split: bool) -> str:
    """A multi-step Hawkes question, in one of two plausible markup shapes.

    The real markup is not in this repository, and a fixture written from a
    guess can only confirm the guess. Two shapes are served instead -- the step
    marker inline with its instruction, and the marker in an element of its own
    -- so what is demonstrated is that the probe distinguishes the steps in
    either, rather than that it distinguishes them in the one shape I imagined.
    """
    marker, _, instruction = step_line.partition(" : ")
    step = (
        f'<div><span class="stepLabel">{marker} :</span> {instruction}</div>'
        if split
        else f"<div>{marker} : {instruction}</div>"
    )
    return (
        "<!doctype html><title>hawkes</title>"
        "<div>Consider the following polynomial.</div>"
        f"{POLYNOMIAL}{step}{HAWKES_FIELD}"
    )


class Scenario:
    """One page shape, and what the popup is expected to say about it."""

    def __init__(
        self,
        name,
        pages,
        expect_enabled,
        expect_fragment,
        distinct=None,
        focuses=True,
    ):
        self.name = name
        self.pages = pages
        self.expect_enabled = expect_enabled
        self.expect_fragment = expect_fragment
        #: Whether this fixture focuses something as it loads. Every one does
        #: except the page that exists to have nothing focused, and the panel
        #: must not be opened until that focus has landed.
        self.focuses = focuses
        #: Scenarios sharing a `distinct` group must each produce a different,
        #: non-null question signature. This is how the multi-step case is
        #: checked: Hawkes keeps one prompt and one expression across every
        #: step of a question and changes only the step line, so if that line
        #: is not read, two steps are literally the same question -- and the
        #: previous step's answer stays on the card, insertable, against the
        #: next step's box.
        self.distinct = distinct


def build_scenarios(site: str, foreign: str) -> list[Scenario]:
    return [
        Scenario(
            "top",
            {"top.html": f"<!doctype html><title>top</title>{FOCUSED_FIELD}"},
            expect_enabled=False,
            expect_fragment="Answer field found",
        ),
        Scenario(
            "same-origin-frame",
            {
                "same-origin-frame.html": f'<!doctype html><title>same</title><iframe src="{site}/child.html"></iframe>',
                "child.html": f"<!doctype html><title>child</title>{FOCUSED_FIELD}",
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
        ),
        Scenario(
            # The editor is reachable, but the page also carries an unrelated
            # cross-origin frame -- an ad, an embed, analytics.
            "top-with-foreign-frame",
            {
                "top-with-foreign-frame.html": f"<!doctype html><title>mixed</title>"
                f'<iframe src="{foreign}/blank.html"></iframe>{FOCUSED_FIELD}',
                "blank.html": "<!doctype html><title>blank</title><p>unrelated</p>",
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
        ),
        Scenario(
            "cross-origin-editor",
            {
                "cross-origin-editor.html": f'<!doctype html><title>cross</title><iframe src="{foreign}/editor.html"></iframe>',
                "editor.html": f"<!doctype html><title>editor</title>{FOCUSED_FIELD}",
            },
            expect_enabled=False,
            expect_fragment="no permission to reach",
        ),
        # The live failure this exists for: lesson 1.3 question 7, steps 2 and
        # 3. Both read "Identify the ...", which matched no verb in the old
        # probe, so neither reported an instruction -- and with one prompt and
        # one polynomial shared across every step, their signatures were equal.
        # The panel held step 2's answer against step 3's empty box, and the
        # signature re-check before insertion compared the same blind value.
        Scenario(
            "hawkes-step-two",
            {
                "hawkes-step-two.html": hawkes_step(
                    "Step 2 of 3 : Identify the degree of the polynomial.", split=False
                )
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-inline",
        ),
        Scenario(
            "hawkes-step-three",
            {
                "hawkes-step-three.html": hawkes_step(
                    "Step 3 of 3 : Identify the leading coefficient.", split=False
                )
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-inline",
        ),
        Scenario(
            "hawkes-step-two-split",
            {
                "hawkes-step-two-split.html": hawkes_step(
                    "Step 2 of 3 : Identify the degree of the polynomial.", split=True
                )
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-split",
        ),
        Scenario(
            "hawkes-step-three-split",
            {
                "hawkes-step-three-split.html": hawkes_step(
                    "Step 3 of 3 : Identify the leading coefficient.", split=True
                )
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-split",
        ),
        # Both carry the same header and the same step marker, so only the
        # short instruction can tell them apart.
        Scenario(
            "hawkes-short-degree",
            {"hawkes-short-degree.html": hawkes_short_step("Identify the degree.")},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="short-instructions",
        ),
        Scenario(
            "hawkes-short-coefficient",
            {
                "hawkes-short-coefficient.html": hawkes_short_step(
                    "Identify the leading coefficient."
                )
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="short-instructions",
        ),
        Scenario(
            "hawkes-detached-degree",
            {
                "hawkes-detached-degree.html": hawkes_detached_short_step(
                    "Identify the degree."
                )
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="detached-short",
        ),
        Scenario(
            "hawkes-detached-constant",
            {
                "hawkes-detached-constant.html":
                # Both instructions in this group must be short enough for the
                # old rule to drop, or the longer one survives it and the pages
                # differ for the wrong reason -- which is exactly how an
                # earlier version of this fixture passed its own negative
                # control.
                hawkes_detached_short_step("Find the constant.")
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="detached-short",
        ),
        Scenario(
            "no-field-focused",
            {
                "no-field-focused.html": "<!doctype html><title>none</title><p>no field here</p>"
            },
            expect_enabled=False,
            expect_fragment="click the empty Hawkes answer box",
            focuses=False,
        ),
    ]


CAPTURED_DOM = PROJECT_ROOT / "benchmarks" / "hawkes_dom"


def captured_scenarios() -> list[Scenario]:
    """Scenarios built from real question markup, when any has been captured.

    Everything above is a fixture written from a description of Hawkes' markup,
    which can only ever confirm the description. These run the shipped content
    scripts against markup saved from the page itself, so they check the add-on
    against Hawkes rather than against an account of it.

    Files sharing everything before the last dash form a group whose members
    must each produce a different question signature. See the README beside
    them; nothing there is committed, because it is coursework.
    """
    if not CAPTURED_DOM.is_dir():
        return []
    scenarios = []
    for path in sorted(CAPTURED_DOM.glob("*.html")):
        name = f"captured-{path.stem}"
        group, dash, _ = path.stem.rpartition("-")
        scenarios.append(
            Scenario(
                name,
                {f"{name}.html": path.read_text(encoding="utf-8")},
                expect_enabled=False,
                # Captured markup carries whatever state the page was in. What is
                # under test is the signature, so the status is only required to
                # show the field was found at all.
                expect_fragment="Answer field found",
                distinct=f"captured-{group}" if dash else None,
            )
        )
    return scenarios


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def make_server(directory: str, host: str, port: int, reports: dict):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def log_message(self, *args):
            pass

        def end_headers(self):
            self.send_header("Access-Control-Allow-Origin", "*")
            super().end_headers()

        def do_GET(self):
            if self.path.startswith("/result"):
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                token = query.get("token", [""])[0]
                report = json.loads(query.get("data", ["{}"])[0])
                # The sidebar and the popup are the same document and report
                # the same tab, so the surface is part of the key: otherwise
                # whichever spoke last would erase the other.
                reports[f"{'sidebar:' if report.get('sidebar') else ''}{token}"] = (
                    report
                )
                self.send_response(204)
                self.end_headers()
                return
            super().do_GET()

    server = http.server.ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def build_test_extension(target: str, site: str, report_origin: str) -> None:
    """Copy the add-on, repointed at the fixture origin.

    Only the origin constants and the HTTPS check change, plus a reporting hook
    that posts what the panel shows. Everything under test -- the content
    scripts, the frame selection, the injection paths -- is the shipped code.
    """
    shutil.copytree(EXTENSION_DIR, target)

    # background.js is in this list because the tab gate lives there, not in
    # the panel. Patching only the content scripts left every scenario failing
    # on `errorWrongSite`, and the `url.protocol` rewrite below was aimed at
    # popup.js long after that check had moved.
    for relative in ("content/hawkes-editor.js", "common/config.js", "background.js"):
        path = Path(target) / relative
        source = path.read_text(encoding="utf-8")
        source = source.replace('"https://learn.hawkeslearning.com"', f'"{site}"')
        source = source.replace('"learn.hawkeslearning.com"', '"127.0.0.1"')
        source = source.replace('url.protocol !== "https:"', 'url.protocol !== "http:"')
        path.write_text(source, encoding="utf-8")

    # Automatic solving is off in the harness. What is under test here is where
    # Firefox injects and which frame is chosen; there is no native host in a
    # throwaway profile, so letting a solve start would only race the report
    # against a connection failure.
    settings = Path(target) / "common/settings.js"
    source = settings.read_text(encoding="utf-8")
    source = source.replace(
        'autoSolve: { kind: "boolean", fallback: true }',
        'autoSolve: { kind: "boolean", fallback: false }',
    )
    settings.write_text(source, encoding="utf-8")

    popup = Path(target) / "popup/popup.js"
    source = popup.read_text(encoding="utf-8")
    source += f"""
// Harness only: report what the panel ended up showing. Keyed by the inspected
// tab's URL -- the popup is its own document, so it cannot see the page's
// query string, and a late report from a previous scenario must not be
// mistaken for this one.
setTimeout(async () => {{
  let token = "";
  try {{
    const [tab] = await browser.tabs.query({{ active: true, currentWindow: true }});
    token = (tab && tab.url) || "";
  }} catch {{}}
  fetch("{report_origin}/result?" + new URLSearchParams({{
    token,
    data: JSON.stringify({{
      // Which surface is speaking. Firefox opens a temporarily installed
      // add-on's sidebar by itself, and the sidebar is this same document --
      // so without this a sidebar that was never granted activeTab could
      // answer for the toolbar popup that was.
      sidebar: inSidebar,
      status: document.querySelector("#status").textContent.trim(),
      detail: document.querySelector("#detail").textContent.trim(),
      enabled: !document.querySelector("#insert").disabled,
      // The question fingerprint the event page derived from this page. Two
      // steps of one question differ only in their step line, so this is the
      // value that decides whether they are the same question.
      signature: (current && current.signature) || null,
    }}),
  }}));
}}, 3200);
"""
    popup.write_text(source, encoding="utf-8")

    manifest_path = Path(target) / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # Reporting only. Deliberately NOT the fixture origin, so page access can
    # come from activeTab alone -- the grant the real add-on relies on.
    manifest["host_permissions"] = ["http://localhost/*"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run(selected: str | None, headless: bool = True) -> int:
    site_port, report_port, foreign_port = free_port(), free_port(), free_port()
    site = f"http://127.0.0.1:{site_port}"
    report_origin = f"http://localhost:{report_port}"
    # A distinct loopback host: covered by neither the fixture origin nor the
    # reporting host permission, so this frame is genuinely unreachable.
    foreign = f"http://127.0.0.2:{foreign_port}"

    scenarios = build_scenarios(site, foreign) + captured_scenarios()
    if selected:
        scenarios = [s for s in scenarios if s.name == selected]
        if not scenarios:
            print(f"no scenario named {selected!r}", file=sys.stderr)
            return 2

    root = tempfile.mkdtemp(prefix="ethnos-harness-")
    web = os.path.join(root, "web")
    extension = os.path.join(root, "extension")
    os.makedirs(web)

    for scenario in scenarios:
        for name, body in scenario.pages.items():
            Path(web, name).write_text(body, encoding="utf-8")
    shutil.copyfile(PROJECT_ROOT / "tests/fixtures/graph.html", Path(web, "graph.html"))
    shutil.copyfile(
        PROJECT_ROOT / "tests/fixtures/plot-points.html", Path(web, "plot-points.html")
    )
    for scatter in (
        "scatter.html",
        "scatter-unreadable.html",
        "scatter-on-axis.html",
        "scatter-translated.html",
    ):
        shutil.copyfile(PROJECT_ROOT / "tests/fixtures" / scatter, Path(web, scatter))
    for table in (
        "table.html",
        "table-thead.html",
        "table-mathjax.html",
        "table-completion.html",
    ):
        shutil.copyfile(PROJECT_ROOT / "tests/fixtures" / table, Path(web, table))
    # The foreign origin serves the same directory on a different host name.
    build_test_extension(extension, site, report_origin)

    reports: dict[str, dict] = {}
    servers = [
        make_server(web, "127.0.0.1", site_port, reports),
        make_server(web, "127.0.0.1", report_port, reports),
        make_server(web, "127.0.0.2", foreign_port, reports),
    ]

    profile = tempfile.mkdtemp(prefix="ethnos-profile-")
    marionette_port = free_port()
    process = launch(profile, port=marionette_port, headless=headless)
    marionette = Marionette(port=marionette_port)

    failures = 0
    unreachable = ""
    signatures: dict[str, str | None] = {}
    try:
        marionette.connect()
        marionette.new_session()
        marionette.install_addon(extension)
        time.sleep(2)

        # Before anything is judged, make sure the button this harness presses
        # is actually there. Firefox 155 files a new add-on's action under
        # `unified-extensions-area` and builds no toolbar node for it, so every
        # click below found nothing and every scenario reported "the popup
        # never reported" -- a browser layout change, described seventeen times
        # as an add-on failure.
        marionette.set_context("chrome")
        placement = pin_action_to_toolbar(marionette, ADDON_ID)
        say(
            f"ok   toolbar: {ADDON_ID} action moved from "
            f"{placement['before']} to {placement['after']}"
        )

        for scenario in scenarios:
            page = f"{scenario.name}.html"
            # Close the previous scenario's panel and hand the page back the
            # focus before the next one loads. A fixture focuses its own answer
            # box as it loads, and a panel holding system focus is enough to
            # stop that happening -- see `load`, which checks rather than
            # assumes it did.
            marionette.set_context("chrome")
            close_open_panels(marionette)
            focus_content(marionette)
            marionette.set_context("content")
            load(marionette, site, page, scenario.focuses)

            report = open_popup_and_wait(marionette, reports, page)
            signatures[scenario.name] = (report or {}).get("signature")
            failures += judge(scenario, report)

        failures += judge_distinct(scenarios, signatures)
        if not selected:
            failures += judge_graph(marionette, site)
            failures += judge_plot_points(marionette, site)
            failures += judge_scatter(marionette, site)
            failures += judge_unreadable_scatter(marionette, site)
            failures += judge_on_axis_scatter(marionette, site)
            failures += judge_translated_scatter(marionette, site)
            failures += judge_table(marionette, site)
            failures += judge_table_completion(marionette, site)
    except ActionButtonMissing as error:
        # A harness fault, not a verdict on the add-on. Reported as such and
        # scored as nothing, because nothing was measured.
        unreachable = str(error)
    finally:
        marionette.quit()
        process.terminate()
        try:
            process.wait(timeout=15)
        except Exception:
            process.kill()
        for server in servers:
            server.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(root, ignore_errors=True)

    if unreachable:
        say(f"\nHARNESS FAULT: {unreachable}")
        say(
            "Nothing was checked. The add-on's action is not in this Firefox's "
            "toolbar, so no scenario was ever exercised."
        )
        return 2

    checks = (
        len(scenarios)
        + len({s.distinct for s in scenarios if s.distinct})
        + (0 if selected else 9)
    )
    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


def judge_translated_scatter(marionette, site):
    """The dots sit in a translated group, as they do live.

    `getBBox` reports an element's own user space, so a dot inside a
    `translate(...)` group and the grid around it are measured in different
    spaces. Subtracting the grid's `getBBox` origin then puts every point out
    by that origin in axis units -- live, by exactly 1.43 -- which looks like a
    real disagreement and refuses the whole figure. Client rects put both in
    one space whatever transforms lie between.
    """
    marionette.set_context("content")
    marionette.navigate(f"{site}/scatter-translated.html")
    source = (PROJECT_ROOT / "extension/content/hawkes-question.js").read_text()
    result = marionette.execute("return " + source[source.index("(() => {") :])["value"]
    expected = [{"x": "-5", "y": "5"}, {"x": "-2", "y": "-4"}, {"x": "-1", "y": "5"}]
    if result.get("graphPoints") != expected:
        say(f"FAIL scatter-translated: {result.get('graphPoints')}")
        say(f"     refusal: {(result.get('evidence') or {}).get('graph', '')!r}")
        return 1
    say("ok   scatter-translated: dots in a translated group read correctly")
    return 0


def judge_on_axis_scatter(marionette, site):
    """A point on an axis is still a point.

    Hawkes drops a clause whose offset is zero: a point on the vertical axis is
    described only as "A dot drawn 5 units below the origin", and the origin
    itself has neither clause. Requiring both clauses refused every such point,
    which `scatter.html` never contained and lesson 3.3's live figure did --
    the add-on read no points at all, took a picture instead, and spent
    forty-five seconds on a model for a question Facet answers exactly.
    """
    marionette.set_context("content")
    marionette.navigate(f"{site}/scatter-on-axis.html")
    source = (PROJECT_ROOT / "extension/content/hawkes-question.js").read_text()
    result = marionette.execute("return " + source[source.index("(() => {") :])["value"]
    expected = [
        {"x": "0", "y": "-5"},
        {"x": "4", "y": "0"},
        {"x": "0", "y": "0"},
        {"x": "-3", "y": "2"},
    ]
    if result.get("graphPoints") != expected:
        say(f"FAIL scatter-on-axis: {result.get('graphPoints')}")
        say(f"     refusal: {(result.get('evidence') or {}).get('graph', '')!r}")
        return 1
    say(
        "ok   scatter-on-axis: points on either axis, and at the origin, read "
        "from the clauses Hawkes actually writes"
    )
    return 0


def judge_unreadable_scatter(marionette, site):
    """A figure question whose points refuse must still state its instruction.

    Live, on lesson 3.3's regression question, the SVG reader refused -- the
    point descriptions are worded differently from the sentence
    `scatter.html` guessed -- and the prompt then came out as eleven
    characters: "Step 1 of 2", and nothing else. Hawkes writes such a question
    as a bare text node beside a `div` holding the graph, and every container
    was being skipped, so the only element the instruction lived in was skipped
    with them. A question that states no task reaches a model as a picture with
    nothing to do about it.

    Two things are pinned. The refusal is named, with the wording it did not
    recognise and no coordinates in it. And the instruction survives anyway.
    """
    marionette.set_context("content")
    marionette.navigate(f"{site}/scatter-unreadable.html")
    source = (PROJECT_ROOT / "extension/content/hawkes-question.js").read_text()
    result = marionette.execute("return " + source[source.index("(() => {") :])["value"]
    problems = []
    if result.get("graphPoints"):
        problems.append("unrecognised point descriptions were accepted")
    reason = (result.get("evidence") or {}).get("graph", "")
    if not reason.startswith("point-desc-unrecognised:"):
        problems.append(f"refusal not named: {reason!r}")
    if any(character.isdigit() for character in reason):
        problems.append(f"the named refusal carries question data: {reason!r}")
    prompt = result.get("promptText", "")
    if "quadratic regression" not in prompt:
        problems.append(f"the instruction was lost: {prompt!r}")
    if problems:
        say(f"FAIL scatter-unreadable: {'; '.join(problems)}")
        return 1
    say(
        f"ok   scatter-unreadable: refusal named ({reason}), and the "
        "instruction survived into the prompt"
    )
    return 0


def judge_table(marionette, site):
    """A word problem whose numbers are in a table, read as a table.

    Two things are under test and neither can be checked without a browser.
    The table has to come back as columns and rows rather than as a run of
    numbers in the middle of a sentence -- `table.rows`, `table.tHead` and
    `cell.tagName` are layout, not string handling. And the prompt has to still
    contain the sentence that says what to do: flattened, this page's table
    pushes "fit a curve ... and maximize" past the length limit, so the
    question arrives stating a situation and asking nothing.

    The real markup is not in this repository, and a fixture written from a
    guess can only confirm the guess. Three shapes are served -- a header row
    of `th` cells, a `thead` declaring the row without them, and prices left in
    the document by MathJax -- so what is demonstrated is that the probe reads
    any of them, rather than that it reads the one I imagined.

    The third is not imagined. Live, a cell holding $80 came back as
    "$\u206280$\u206280": MathJax leaves the glyphs a reader sees *and* a
    hidden MathML copy for assistive technology, `textContent` returns both,
    and the host refused the result as not a number.
    """
    failures = 0
    for page in ("table.html", "table-thead.html", "table-mathjax.html"):
        failures += judge_one_table(marionette, site, page)
    return failures


def judge_one_table(marionette, site, page):
    marionette.set_context("content")
    marionette.navigate(f"{site}/{page}")
    source = (PROJECT_ROOT / "extension/content/hawkes-question.js").read_text()
    result = marionette.execute("return " + source[source.index("(() => {") :])["value"]
    problems = []
    if result.get("dataTable") != {
        "columns": ["Price per Photo", "Number of Photos Sold", "Revenue"],
        "rows": [["$56", "4", "$224"], ["$52", "5", "$260"], ["$24", "12", "$288"]],
    }:
        problems.append(f"table read as {result.get('dataTable')}")
    prompt = result.get("promptText", "")
    if "quadratic regression" not in prompt or "maximize her revenue" not in prompt:
        problems.append("the prompt lost the sentence that says what to do")
    if "$56" in prompt or "$224" in prompt:
        problems.append("the table was flattened into the prompt as well")
    if result.get("graphPoints") != [
        {"x": "4", "y": "224"},
        {"x": "5", "y": "260"},
        {"x": "12", "y": "288"},
    ]:
        problems.append(f"plotted points read as {result.get('graphPoints')}")
    if problems:
        say(f"FAIL {page}: {'; '.join(problems)}")
        say(f"     prompt: {prompt[:200]}")
        return 1
    say(
        f"ok   {page}: columns and rows read from the page's own table, kept "
        "out of the prompt, and the same numbers read again off the plot"
    )
    return 0


def judge_table_completion(marionette, site):
    """The table a question is answered *in*, read in a real browser.

    `tests/test_hawkes_answer_table.py` reads the same fixture through a DOM
    assembled in Python, which is exact about structure and synthetic about
    layout. This is the other half: Firefox lays the table out, MathJax's
    assistive copy sits where MathJax puts it, and the blanks are numbered from
    where the boxes actually are.

    A value is typed into every box before the second reading. Nothing a
    student has entered may come back as part of the question, and the only
    way to be sure of that is to have entered something.
    """
    marionette.set_context("content")
    marionette.navigate(f"{site}/table-completion.html")
    source = (PROJECT_ROOT / "extension/content/hawkes-question.js").read_text()
    probe = "return " + source[source.index("(() => {") :]
    result = marionette.execute(probe)["value"]
    problems = []
    table = result.get("answerTable")
    if table is None:
        problems.append(f"refused as {result.get('evidence', {}).get('answerTable')}")
    else:
        if table.get("columns") != ["x", "y"]:
            problems.append(f"columns read as {table.get('columns')}")
        blanks = [
            cell["blank"] for row in table["rows"] for cell in row if "blank" in cell
        ]
        if blanks != [1, 2, 3, 4, 5]:
            problems.append(f"blanks numbered {blanks}")
        given = [
            cell.get("text") or cell.get("mathml", "")
            for row in table["rows"]
            for cell in row
            if "blank" not in cell
        ]
        if [value for value in given if value.startswith("<math")] and not all(
            "msqrt" in value for value in given if value.startswith("<math")
        ):
            problems.append("a radical cell lost its root")
        if [value for value in given if not value.startswith("<math")] != [
            "0",
            "64",
            "25",
        ]:
            problems.append(f"stated values read as {given}")
    marionette.execute(
        "for (const box of document.querySelectorAll('input.qbaseCSS'))"
        " box.value = '999';"
    )
    entered = marionette.execute(probe)["value"]
    if "999" in json.dumps(entered):
        problems.append("what was typed into a box was read back as the question")
    if problems:
        say(f"FAIL table-completion.html: {'; '.join(problems)}")
        return 1
    say(
        "ok   table-completion.html: five blanks numbered in reading order, the "
        "stated cells read exactly, and nothing read out of an answer box"
    )
    return 0


def judge_scatter(marionette, site):
    marionette.set_context("content")
    marionette.navigate(f"{site}/scatter.html")
    source = (PROJECT_ROOT / "extension/content/hawkes-question.js").read_text()
    result = marionette.execute("return " + source[source.index("(() => {") :])["value"]
    expected = [{"x": "-5", "y": "5"}, {"x": "-2", "y": "-4"}, {"x": "-1", "y": "5"}]
    if (
        result.get("graphPoints") != expected
        or "quadratic regression" not in result["promptText"]
        or "Zoom" in result["promptText"]
    ):
        say(f"FAIL scatter extraction: {result}")
        return 1
    marionette.execute(
        "document.querySelector('g.point desc').textContent = 'A dot drawn 4 units left of and 5 units above the origin.';"
    )
    stale = marionette.execute("return " + source[source.index("(() => {") :])["value"]
    if stale.get("graphPoints"):
        say("FAIL scatter: mismatched SVG/description accepted")
        return 1
    say(
        "ok   scatter: exact SVG coordinates and instruction; mismatched description refused"
    )
    return 0


def judge_plot_points(marionette, site):
    """A plotting graph, plotted the way Hawkes requires one to be.

    The fixture sets its `plotted` flag from the space key and from nothing
    else, exposes `isAllGraphObjectsPlotted()`, and builds its answer out of
    what is plotted -- which is what the page's own graph code does. Driven by
    arrows alone it reproduces the live failure exactly: four points on screen
    at the four right coordinates, every coordinate read back correct, and an
    answer the page calls incomplete.

    So this asserts on what the page would accept, not on what the model holds.
    """
    source = (
        (PROJECT_ROOT / "extension/common/graph-actions.js")
        .read_text()
        .replace("export function", "function")
        .replace("https://learn.hawkeslearning.com", site)
    )
    plan = {
        "kind": "points",
        "points": [
            {"x": "3", "y": "2"},
            {"x": "-9", "y": "4"},
            {"x": "-8", "y": "-7"},
            {"x": "1", "y": "-5"},
        ],
    }
    wanted = sorted([[3, 2], [-9, 4], [-8, -7], [1, -5]])
    marionette.set_context("content")
    marionette.navigate(f"{site}/plot-points.html")
    result = marionette.execute(
        source
        + """
      const probe = graphOperation();
      if (!probe.ok) return {probe};
      const outcome = graphOperation(
        {snapshot: probe.snapshot, plan: """
        + json.dumps(plan)
        + """});
      const model = Object.values(window.quant_wp_UI.controlsCollection)[0];
      return {probe: probe.ok, context: probe.context, outcome,
              graded: window.plottedPoints(),
              accepts: Object.values(window.quant_wp_UI.controlsCollection)[0]
                .isAllGraphObjectsPlotted(),
              model: model.allGraphObjects().map(p => [p.x, p.y]),
              forbidden: window.forbiddenEvents};
    """
    )["value"]
    problems = []
    if not result.get("probe"):
        problems.append(f"describe refused: {result.get('probe')}")
    elif result["context"]["family"] != "points" or result["context"]["count"] != 4:
        problems.append(f"described the wrong graph: {result['context']}")
    if result.get("outcome", {}).get("code") != "graph-plotted":
        problems.append(f"actuation refused: {result.get('outcome')}")
    if result.get("forbidden"):
        problems.append(f"forbidden keys: {result['forbidden']}")
    if sorted(result.get("model", [])) != wanted:
        problems.append(f"model landed on {sorted(result.get('model', []))}")
    # The two that matter, and the two nothing was checking. A point can sit at
    # the right coordinate, drawn, and still not be plotted as far as the page
    # is concerned -- which is the whole of the live failure.
    if sorted(result.get("graded", [])) != wanted:
        problems.append(
            f"the page plotted only {sorted(result.get('graded', []))}, "
            "so a point at the right coordinate was never plotted"
        )
    if result.get("accepts") is not True:
        problems.append("the page does not consider every object plotted")
    if problems:
        say(f"FAIL plot-points: {'; '.join(problems)}")
        return 1
    say(
        "ok   plot-points: four stated points stepped onto the grid, plotted "
        "with the key the page sets its own flag from, and accepted as complete"
    )
    return 0


def judge_graph(marionette, site):
    """Isolated SVG keyboard/model fixture: real DOM events, no Facet stub claims."""
    source = (
        (PROJECT_ROOT / "extension/common/graph-actions.js")
        .read_text()
        .replace("export function", "function")
        .replace("https://learn.hawkeslearning.com", site)
    )
    plan = {
        "kind": "parabola",
        "orientation": "vertical",
        "opening": "up",
        "vertex": {"x": "3", "y": "-1"},
        "points": [{"x": "4", "y": "0"}, {"x": "2", "y": "0"}],
    }
    for mode in ["success", "normalizes", "stale", "replaced", "during", "invalid"]:
        marionette.set_context("content")
        marionette.navigate(f"{site}/graph.html")
        result = marionette.execute(
            source
            + """
          const mode = """
            + json.dumps(mode)
            + """;
          if(mode === 'normalizes') {
            const model = Object.values(window.quant_wp_UI.controlsCollection)[0];
            const graphXML = model.graphXML;
            const userAnswer = model.userAnswer;
            let normalized = false;
            model.graphXML = () => graphXML().replace('<parabola>', `<parabola><equation><a>${normalized ? '0' : 'undefined'}</a><b>${normalized ? '0' : 'undefined'}</b><c>${normalized ? '0' : 'undefined'}</c></equation>`);
            model.userAnswer = () => { normalized = true; return userAnswer(); };
          }
          const probe = graphOperation();
          const offered = {snapshot: probe.snapshot, plan: """
            + json.dumps(plan)
            + """, coefficients: ["1","-6","8"]};
          if(mode === 'stale') document.getElementById('partInformation').textContent = 'new question';
          if(mode === 'replaced') document.getElementById('a1').id = 'replacement';
          if(mode === 'during') window.replaceDuringMove = true;
          if(mode === 'invalid') offered.plan.vertex.x = '4';
          const result = graphOperation(offered);
          return {probe: probe.ok, result, events: window.graphEvents, forbidden: window.forbiddenEvents};
        """
        )["value"]
        ok = result["probe"] and not result["forbidden"]
        if mode in {"success", "normalizes"}:
            ok = (
                ok
                and result["result"].get("code") == "graph-verified"
                and result["result"]["events"] == 8
            )
            ok = ok and all(event["i"] == 0 for event in result["events"])
        else:
            ok = ok and not result["result"]["ok"]
            ok = ok and len(result["events"]) == (1 if mode == "during" else 0)
        if not ok:
            say(f"FAIL graph {mode}: {result}")
            return 1
    say(
        "ok   graph: SVG keyboard placement, exact readback, invalid geometry and stale/replaced controls refused; no grading/navigation events"
    )
    return 0


def open_popup_and_wait(marionette, reports, page, attempts=3, window=6.0):
    """Click the toolbar button until this scenario's report arrives.

    The button toggles, so a stale open popup can swallow the first click.
    Reports are keyed by the inspected tab's URL, which makes a late report
    from a previous scenario impossible to mistake for this one.
    """
    for _ in range(attempts):
        marionette.set_context("chrome")
        close_open_panels(marionette)
        try:
            marionette.click(ACTION_BUTTON)
        except MarionetteError as error:
            # Not swallowed. A click that cannot find the button proves nothing
            # about the add-on, and reporting it as a scenario failure is how a
            # Firefox toolbar change came to look like seventeen product bugs.
            raise ActionButtonMissing(f"{ACTION_BUTTON} could not be clicked: {error}")
        deadline = time.monotonic() + window
        while time.monotonic() < deadline:
            for key, report in reports.items():
                url = key.removeprefix("sidebar:")
                if url.endswith(page) and not report.get("sidebar"):
                    return report
            time.sleep(0.2)
    # Say what did arrive. "The popup never reported" on its own is the least
    # useful sentence this harness can print -- it was the whole of the Firefox
    # 155 diagnosis for a week -- so the reports that exist are named, which
    # distinguishes a popup that did not open from one that reported late or
    # answered for the wrong page.
    say(
        f"     after {attempts} clicks on {ACTION_BUTTON}, reports held: "
        f"{sorted(reports) or 'nothing at all'}"
    )
    return None


def load(marionette, site, page, focuses: bool) -> None:
    """Put one fixture on screen, with its own focus actually landed.

    A cross-origin child cannot take focus while the window it is in does not
    have any: Firefox ignores the `focus()` call outright rather than deferring
    it, so the parent never records the frame as focused and the panel, opened
    next, truthfully reports that nothing is. That is a statement about a page
    that had not finished happening, and it failed `cross-origin-editor` about
    one run in seven.

    Giving the content area focus and loading again does not fix it, because
    the call was ignored rather than deferred. So when the page's own focus has
    not landed, the harness clicks the answer box itself, in whichever frame
    holds it -- which is what the add-on documents a person doing, and what the
    scenario has always meant.
    """
    marionette.set_context("content")
    marionette.navigate(f"{site}/{page}")
    time.sleep(1.6)
    if not focuses or wait_for_focus(marionette, timeout=2.0):
        return
    if not click_answer_field(marionette):
        say(f"     {page}: nothing took focus, and no answer box could be clicked")


def click_answer_field(marionette) -> bool:
    """Click the fixture's answer box, in whichever frame holds it.

    Marionette can enter a cross-origin child; the add-on cannot, and that
    asymmetry is the point. The driver puts the caret where a person would have
    put it, and what is then under test is whether the add-on can reach it.
    """
    frames = marionette.execute("return window.frames.length")["value"]
    for index in [None, *range(frames)]:
        try:
            if index is not None:
                marionette.switch_to_frame(index)
            marionette.click("#answer")
            clicked = True
        except MarionetteError:
            clicked = False
        finally:
            marionette.switch_to_top()
        if clicked and wait_for_focus(marionette, timeout=2.0):
            return True
    return False


def wait_for_focus(marionette, timeout: float = 5.0) -> bool:
    """Let the fixture's own focus land before the panel is opened.

    Every fixture focuses its answer box as it loads. A cross-origin child does
    it from a document that is still arriving, so the parent records the frame
    as focused a moment after the parent itself is ready -- and a panel opened
    in that gap truthfully reports that nothing is focused, on a page that had
    not finished happening. Waiting for the precondition is the fix; without it
    `cross-origin-editor` failed about one run in seven.

    Called in content context. Returns whether anything ended up focused; a
    page that focuses nothing is a real scenario and one of them is deliberate,
    so this reports rather than raises.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            focused = marionette.execute(
                "const active = document.activeElement;"
                "return active === null ? '' : active.tagName;"
            )["value"]
        except MarionetteError:
            return False
        if focused not in ("", "BODY", "HTML"):
            return True
        time.sleep(0.15)
    return False


def focus_content(marionette) -> None:
    """Put system focus back on the page area.

    Called in chrome context, before a fixture is loaded.
    """
    try:
        marionette.execute("gBrowser.selectedBrowser.focus(); return true;")
    except MarionetteError:
        pass


def close_open_panels(marionette, timeout: float = 3.0) -> None:
    """Dismiss any open browser panel, and wait until it has gone.

    The toolbar button toggles, so a popup left open from the previous scenario
    would swallow the next click -- and because the panel overlays the button,
    that click can land on the popup's own Insert button instead.

    Hiding is not instant. Asking a panel to hide and clicking in the same
    breath leaves the click landing while it is still going away, which is the
    same swallowed click by a slower route, so this returns only once no panel
    reports itself open or showing.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            open_panels = marionette.execute("""
              let open = 0;
              for (const panel of document.querySelectorAll("panel")) {
                if (panel.state === "open" || panel.state === "showing") {
                  open += 1;
                  try { panel.hidePopup(); } catch (error) { /* already going */ }
                }
              }
              return open;
            """)["value"]
        except MarionetteError:
            return
        if not open_panels:
            return
        time.sleep(0.15)


def judge(scenario, report) -> int:
    if report is None:
        say(f"FAIL {scenario.name}: the popup never reported")
        return 1
    status, detail = report.get("status", ""), report.get("detail", "")
    problems = []
    if scenario.expect_fragment.lower() not in status.lower():
        problems.append(f"expected status to contain {scenario.expect_fragment!r}")
    if report.get("enabled") is not scenario.expect_enabled:
        problems.append(f"expected insert enabled={scenario.expect_enabled}")
    if problems:
        say(f"FAIL {scenario.name}: {'; '.join(problems)}")
        say(f"     status: {status}")
        if detail:
            say(f"     detail: {detail}")
        return 1
    say(f"ok   {scenario.name}: {status}")
    return 0


def say(text: str) -> None:
    print(text, flush=True)


def judge_distinct(scenarios, signatures) -> int:
    """Two steps of one question must not be the same question.

    Checked across scenarios rather than within one, because that is the shape
    of the failure: each page on its own looked entirely correct.
    """
    groups: dict[str, list] = {}
    for scenario in scenarios:
        if scenario.distinct:
            groups.setdefault(scenario.distinct, []).append(scenario.name)

    failures = 0
    for group, names in groups.items():
        if len(names) < 2:
            say(f"     {group}: only {len(names)} page, nothing to compare it with")
            continue
        seen = {name: signatures.get(name) for name in names}
        missing = [name for name, value in seen.items() if not value]
        if missing:
            say(f"FAIL {group}: no question signature reported by {', '.join(missing)}")
            failures += 1
            continue
        if len(set(seen.values())) != len(names):
            say(
                f"FAIL {group}: steps share one signature, so they are one "
                f"question to the add-on: {seen}"
            )
            failures += 1
            continue
        say(f"ok   {group}: {len(names)} steps, {len(set(seen.values()))} signatures")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", help="run only this scenario")
    parser.add_argument(
        "--show",
        action="store_true",
        help="Render the browser instead of running it headless.",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="MOZ_HEADLESS instead of a virtual display",
    )
    args = parser.parse_args()
    if not shutil.which("firefox"):
        print("firefox is not installed", file=sys.stderr)
        return 2
    # Headless by default. This drives a real browser on a developer's desktop,
    # and the alternative is windows appearing over whatever they are doing.
    return run(args.scenario, headless=not args.show)


if __name__ == "__main__":
    raise SystemExit(main())
