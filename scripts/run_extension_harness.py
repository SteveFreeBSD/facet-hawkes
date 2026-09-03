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
from harness.marionette import Marionette, MarionetteError, launch  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"

# Toolbar button id Firefox derives from the add-on id.
ACTION_BUTTON = "#ethnos-hawkes_local-BAP"

FOCUSED_FIELD = '<input id="answer" type="text"><script>answer.focus()</script>'

# One Hawkes answer control, named as Hawkes names them so the question probe's
# "everything above the answer area" boundary is computed the way it is live.
HAWKES_FIELD = (
    '<div>Answer</div>'
    '<input id="txtAns1" class="qbaseCSS" type="text">'
    '<script>txtAns1.focus()</script>'
)

# The polynomial, as MathJax leaves it in the document. The probe reads this
# rather than a screenshot, and `questionSignature` returns null without it.
POLYNOMIAL = (
    '<math xmlns="http://www.w3.org/1998/Math/MathML"><mrow>'
    '<mo>-</mo><mn>3</mn><msup><mi>x</mi><mn>11</mn></msup>'
    '<mo>-</mo><msup><mi>x</mi><mn>13</mn></msup>'
    '<mo>+</mo><mn>5</mn>'
    '<mo>+</mo><mn>2</mn><msup><mi>x</mi><mn>12</mn></msup>'
    '</mrow></math>'
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
        else f'<div>{marker} : {instruction}</div>'
    )
    return (
        "<!doctype html><title>hawkes</title>"
        "<div>Consider the following polynomial.</div>"
        f"{POLYNOMIAL}{step}{HAWKES_FIELD}"
    )


class Scenario:
    """One page shape, and what the popup is expected to say about it."""

    def __init__(self, name, pages, expect_enabled, expect_fragment, distinct=None):
        self.name = name
        self.pages = pages
        self.expect_enabled = expect_enabled
        self.expect_fragment = expect_fragment
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
                "same-origin-frame.html":
                    f'<!doctype html><title>same</title><iframe src="{site}/child.html"></iframe>',
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
                "top-with-foreign-frame.html":
                    f'<!doctype html><title>mixed</title>'
                    f'<iframe src="{foreign}/blank.html"></iframe>{FOCUSED_FIELD}',
                "blank.html": "<!doctype html><title>blank</title><p>unrelated</p>",
            },
            expect_enabled=False,
            expect_fragment="Answer field found",
        ),
        Scenario(
            "cross-origin-editor",
            {
                "cross-origin-editor.html":
                    f'<!doctype html><title>cross</title><iframe src="{foreign}/editor.html"></iframe>',
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
            {"hawkes-step-two.html": hawkes_step(
                "Step 2 of 3 : Identify the degree of the polynomial.", split=False)},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-inline",
        ),
        Scenario(
            "hawkes-step-three",
            {"hawkes-step-three.html": hawkes_step(
                "Step 3 of 3 : Identify the leading coefficient.", split=False)},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-inline",
        ),
        Scenario(
            "hawkes-step-two-split",
            {"hawkes-step-two-split.html": hawkes_step(
                "Step 2 of 3 : Identify the degree of the polynomial.", split=True)},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="steps-split",
        ),
        Scenario(
            "hawkes-step-three-split",
            {"hawkes-step-three-split.html": hawkes_step(
                "Step 3 of 3 : Identify the leading coefficient.", split=True)},
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
            {"hawkes-short-coefficient.html":
                hawkes_short_step("Identify the leading coefficient.")},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="short-instructions",
        ),
        Scenario(
            "hawkes-detached-degree",
            {"hawkes-detached-degree.html":
                hawkes_detached_short_step("Identify the degree.")},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="detached-short",
        ),
        Scenario(
            "hawkes-detached-constant",
            {"hawkes-detached-constant.html":
                # Both instructions in this group must be short enough for the
                # old rule to drop, or the longer one survives it and the pages
                # differ for the wrong reason -- which is exactly how an
                # earlier version of this fixture passed its own negative
                # control.
                hawkes_detached_short_step("Find the constant.")},
            expect_enabled=False,
            expect_fragment="Answer field found",
            distinct="detached-short",
        ),
        Scenario(
            "no-field-focused",
            {"no-field-focused.html": "<!doctype html><title>none</title><p>no field here</p>"},
            expect_enabled=False,
            expect_fragment="click the empty Hawkes answer box",
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
        scenarios.append(Scenario(
            name,
            {f"{name}.html": path.read_text(encoding="utf-8")},
            expect_enabled=False,
            # Captured markup carries whatever state the page was in. What is
            # under test is the signature, so the status is only required to
            # show the field was found at all.
            expect_fragment="Answer field found",
            distinct=f"captured-{group}" if dash else None,
        ))
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
                reports[token] = json.loads(query.get("data", ["{}"])[0])
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
    # The foreign origin serves the same directory on a different host name.
    build_test_extension(extension, site, report_origin)

    reports: dict[str, dict] = {}
    servers = [make_server(web, "127.0.0.1", site_port, reports),
               make_server(web, "127.0.0.1", report_port, reports),
               make_server(web, "127.0.0.2", foreign_port, reports)]

    profile = tempfile.mkdtemp(prefix="ethnos-profile-")
    marionette_port = free_port()
    process = launch(profile, port=marionette_port, headless=headless)
    marionette = Marionette(port=marionette_port)

    failures = 0
    signatures: dict[str, str | None] = {}
    try:
        marionette.connect()
        marionette.new_session()
        marionette.install_addon(extension)
        time.sleep(2)

        for scenario in scenarios:
            page = f"{scenario.name}.html"
            marionette.set_context("content")
            marionette.navigate(f"{site}/{page}")
            time.sleep(1.6)

            report = open_popup_and_wait(marionette, reports, page)
            signatures[scenario.name] = (report or {}).get("signature")
            failures += judge(scenario, report)

        failures += judge_distinct(scenarios, signatures)
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

    checks = len(scenarios) + len({s.distinct for s in scenarios if s.distinct})
    print(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


def open_popup_and_wait(marionette, reports, page, attempts=3):
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
        except MarionetteError:
            pass
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            for url, report in reports.items():
                if url.endswith(page):
                    return report
            time.sleep(0.2)
    return None


def close_open_panels(marionette) -> None:
    """Dismiss any open browser panel.

    The toolbar button toggles, so a popup left open from the previous scenario
    would swallow the next click -- and because the panel overlays the button,
    that click can land on the popup's own Insert button instead.
    """
    try:
        marionette.execute("""
          for (const panel of document.querySelectorAll("panel")) {
            try { panel.hidePopup(); } catch (error) { /* not open */ }
          }
          return true;
        """)
    except MarionetteError:
        pass


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
            say(f"FAIL {group}: steps share one signature, so they are one "
                f"question to the add-on: {seen}")
            failures += 1
            continue
        say(f"ok   {group}: {len(names)} steps, {len(set(seen.values()))} signatures")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--scenario", help="run only this scenario")
    parser.add_argument("--show", action="store_true",
                        help="Render the browser instead of running it headless.")
    parser.add_argument("--headless", action="store_true",
                        help="MOZ_HEADLESS instead of a virtual display")
    args = parser.parse_args()
    if not shutil.which("firefox"):
        print("firefox is not installed", file=sys.stderr)
        return 2
    # Headless by default. This drives a real browser on a developer's desktop,
    # and the alternative is windows appearing over whatever they are doing.
    return run(args.scenario, headless=not args.show)


if __name__ == "__main__":
    raise SystemExit(main())
