#!/usr/bin/env python3
"""A visible Firefox with the add-on installed, that both of us can work with.

The user drives it by hand; Marionette lets the assistant read back what the
popup and page actually contain. It runs on a throwaway profile as a separate
instance, so the user's own Firefox, profile, and sessions are untouched.

    python3 scripts/live_browser.py start     # launch, install the add-on
    python3 scripts/live_browser.py popup     # read the open popup panel
    python3 scripts/live_browser.py page      # read the focused field's shape
    python3 scripts/live_browser.py stop
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.marionette import (  # noqa: E402
    Marionette,
    MarionetteError,
    action_button_selector,
    launch,
    pin_action_to_toolbar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
STATE_DIR = Path(os.environ.get("ETHNOS_LIVE_DIR", "/tmp/ethnos-live-browser"))
PROFILE = STATE_DIR / "profile"
PORT_FILE = STATE_DIR / "port"
ADDON_ID = json.loads((EXTENSION_DIR / "manifest.json").read_text())[
    "browser_specific_settings"
]["gecko"]["id"]
PANEL_VIEW = "PanelUI-webext-ethnos-hawkes_local-BAV"
ACTION_BUTTON = action_button_selector(ADDON_ID)


def connect() -> Marionette:
    port = int(PORT_FILE.read_text().strip())
    marionette = Marionette(port=port)
    marionette.connect(timeout=20)
    try:
        marionette.new_session()
    except MarionetteError:
        pass  # a session from a previous command is fine to reuse
    return marionette


def start() -> int:
    """Launch the browser, reusing the profile if there is one.

    The profile is deliberately kept across restarts: it holds the lesson
    login, and wiping it on every start meant signing in again after each
    crash. Use `stop` to discard it.
    """
    if PORT_FILE.exists():
        try:
            marionette = connect()
            marionette.disconnect()
            print("already running; use 'stop' first", file=sys.stderr)
            return 1
        except Exception:
            # A stale port file from a browser that is no longer there.
            print("clearing a stale session")
            PORT_FILE.unlink(missing_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    launch(str(PROFILE), port=port, headless=False)
    PORT_FILE.write_text(str(port))
    marionette = connect()
    try:
        # Deliberately NOT disabling popup autohide. It makes the panel stay
        # open for inspection, but it also breaks the normal click-the-toolbar-
        # button-again-to-close behaviour, which is confusing to use. Set it by
        # hand for a debugging session and unset it afterwards.
        marionette.set_context("content")
        addon = marionette.install_addon(str(EXTENSION_DIR))
        version = json.loads((EXTENSION_DIR / "manifest.json").read_text())["version"]
        print(f"installed {addon} version {version}")
        # Firefox files a new add-on's action under the unified extensions
        # button and builds no toolbar node for it, so `insert` below would
        # find nothing to click. Pin it, as a person would.
        marionette.set_context("chrome")
        placement = pin_action_to_toolbar(marionette, ADDON_ID)
        print(f"action moved from {placement['before']} to {placement['after']}")
        print("a Firefox window is open on your display, on a throwaway profile")
    finally:
        marionette.disconnect()
    return 0


def popup() -> int:
    """Read the toolbar popup or the already-open remote sidebar."""
    marionette = connect()
    try:
        marionette.set_context("chrome")
        print(
            json.dumps(
                _panel_state(marionette) or {"error": "panel is not open"}, indent=2
            )
        )
    finally:
        marionette.disconnect()
    return 0


def page() -> int:
    """Report the focused field's shape, without reading lesson text."""
    marionette = connect()
    try:
        marionette.set_context("content")
        out = marionette.execute("""
          const a = document.activeElement;
          return JSON.stringify({
            url: location.origin + location.pathname,
            frames: window.frames.length,
            tag: a && a.tagName,
            type: a && a.getAttribute && a.getAttribute("type"),
            role: a && a.getAttribute && a.getAttribute("role"),
            editable: a && a.isContentEditable,
            cls: String((a && a.className) || "").slice(0, 200),
            id: a && a.id,
            iframeSrc: a && a.tagName === "IFRAME" ? new URL(a.src, location.href).origin : null,
            leak: typeof window.ethnosHawkes,
          });
        """)
        print(json.dumps(json.loads(out["value"]), indent=2))
    finally:
        marionette.disconnect()
    return 0


def stop() -> int:
    if PORT_FILE.exists():
        try:
            marionette = connect()
            marionette.send("Marionette:Quit", {})
            marionette.quit()
        except Exception:
            subprocess.run(["pkill", "-f", str(PROFILE)], check=False)
        PORT_FILE.unlink(missing_ok=True)
    shutil.rmtree(PROFILE, ignore_errors=True)
    print("stopped")
    return 0


def field() -> int:
    """Report every candidate answer field, across same-origin frames.

    Used to read back what an insertion actually put in the editor, which is
    the one thing the offline harness cannot check.
    """
    marionette = connect()
    try:
        marionette.set_context("content")
        out = marionette.execute("""
          const SELECTOR = 'input:not([type]),input[type="text"],input[type="search"],'
            + 'input[type="number"],textarea,[contenteditable="true"],[role="textbox"],'
            + '.mq-editable-field,.mathquill-editable';
          const seen = [];
          function scan(win, label) {
            let doc;
            try { doc = win.document; } catch (error) { 
              seen.push({ frame: label, unreadable: true }); return;
            }
            for (const el of doc.querySelectorAll(SELECTOR)) {
              seen.push({
                frame: label,
                tag: el.tagName,
                id: el.id || null,
                cls: String(el.className || "").slice(0, 90),
                value: (el.value !== undefined ? el.value : el.textContent || "").slice(0, 120),
                focused: doc.activeElement === el,
              });
            }
            for (let i = 0; i < win.frames.length; i++) {
              scan(win.frames[i], label + "/" + i);
            }
          }
          scan(window, "top");
          return JSON.stringify(seen.slice(0, 25));
        """)
        print(json.dumps(json.loads(out["value"]), indent=2))
    finally:
        marionette.disconnect()
    return 0


def watch() -> int:
    """Poll for an open panel and print it as soon as one appears.

    The panel closes when the window loses focus, so the user cannot open it
    and then switch to a terminal. This catches it while it is still up.
    """
    marionette = connect()
    try:
        marionette.set_context("chrome")
        marionette.execute(
            'Services.prefs.setBoolPref("ui.popup.disable_autohide", true); return true;'
        )
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            state = _panel_state(marionette)
            if state:
                print(json.dumps(state, indent=2), flush=True)
                return 0
            time.sleep(0.4)
        print("no panel appeared within the wait", flush=True)
        return 1
    finally:
        marionette.disconnect()


def shot(out_path: str = "") -> int:
    """Screenshot the live page, so the current question can be read directly."""
    import base64

    target = Path(out_path) if out_path else STATE_DIR / "question.png"
    marionette = connect()
    try:
        marionette.set_context("content")
        result = marionette.send(
            "WebDriver:TakeScreenshot",
            {"id": None, "full": False, "hash": False, "scroll": False},
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(result["value"]))
        print(f"{target} ({target.stat().st_size} bytes)")
    finally:
        marionette.disconnect()
    return 0


LAUNCHER = PROJECT_ROOT / "deploy" / "firefox" / "ethnos-hawkes-host"
DESCRIBE_JS = EXTENSION_DIR / "content" / "hawkes-describe.js"
EDITOR_JS = EXTENSION_DIR / "content" / "hawkes-editor.js"
RULES_JS = EXTENSION_DIR / "common" / "editor-rules.js"


def _ask_host(png: bytes, prompt: str, timeout: int = 900) -> dict:
    """Speak to the native host exactly as Firefox does."""
    import base64
    import struct

    payload = {
        "protocol_version": 1,
        "operation": "solve_hawkes_problem",
        "request_id": "harness",
        "origin": "https://learn.hawkeslearning.com",
        "problem": {
            "prompt_text": prompt,
            "screenshot_png_base64": base64.b64encode(png).decode(),
        },
    }
    body = json.dumps(payload).encode()
    process = subprocess.Popen(
        [str(LAUNCHER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, err = process.communicate(struct.pack("=I", len(body)) + body, timeout=timeout)
    if len(out) < 4:
        return {"status": "error", "message": err.decode()[-400:] or "no reply"}
    (length,) = struct.unpack("=I", out[:4])
    return json.loads(out[4 : 4 + length])


def _run_page_script(marionette, path: Path, tail: str = "") -> dict:
    """Evaluate one shipped content script in the page and return its value."""
    source = path.read_text(encoding="utf-8")
    wrapped = "return JSON.stringify((function(){ %s })());" % (
        f"const __r = eval({json.dumps(source)}); {tail} return __r;"
        if not tail
        else f"eval({json.dumps(source)}); {tail}"
    )
    return json.loads(marionette.execute(wrapped)["value"])


def _fits(answer: str, editor: dict) -> dict:
    """Run the shipped insertability rules, the same ones the popup uses."""
    import re as _re

    try:
        import quickjs
    except ImportError:
        return {"insertable": True, "note": "quickjs missing; rules not checked"}
    source = _re.sub(r"^export ", "", RULES_JS.read_text(), flags=_re.MULTILINE)
    context = quickjs.Context()
    context.eval(source)
    return json.loads(
        context.eval(
            f"JSON.stringify(answerFitsEditor({json.dumps(answer)}, {json.dumps(editor)}))"
        )
    )


def solve_current(insert: bool = True) -> int:
    """Screenshot the live question, solve it with Ethnos, and place the answer.

    One command for the whole loop, using the shipped host and the shipped
    content scripts so it exercises the real pipeline rather than a copy. It
    never presses Submit or Check.
    """
    import base64
    import time

    marionette = connect()
    try:
        marionette.set_context("content")
        shot = marionette.send(
            "WebDriver:TakeScreenshot",
            {"id": None, "full": False, "hash": False, "scroll": False},
        )
        png = base64.b64decode(shot["value"])
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        (STATE_DIR / "question.png").write_bytes(png)
        print(
            f"screenshot  {len(png)} bytes -> {STATE_DIR / 'question.png'}", flush=True
        )

        editor = _run_page_script(marionette, DESCRIBE_JS)
        print(f"editor      {json.dumps(editor)}", flush=True)

        started = time.monotonic()
        reply = _ask_host(png, "Answer the Hawkes question shown.")
        print(
            f"ethnos      {time.monotonic() - started:.0f}s  status={reply.get('status')}",
            flush=True,
        )
        if reply.get("status") != "ready":
            print(f"refused     {reply.get('message', '')[:300]}")
            return 1

        print(f"problem     {reply.get('problem_text', '')[:200]}")
        answer_payload = reply.get("answer") or {}
        certainty = reply.get("certainty") or {}
        print(
            f"answer      display={answer_payload.get('display_text')!r} "
            f"keys={answer_payload.get('keyboard_entry')!r}"
        )
        print(
            f"certainty   source={certainty.get('source')} "
            f"transcription={certainty.get('transcription')} "
            f"insertable={certainty.get('insertable')}"
        )
        if not certainty.get("insertable"):
            print(f"refused     transcription disputed: {certainty.get('issues')}")
            return 1

        # Same preference order as the popup: displayed maths, then ASCII.
        chosen, verdict = None, None
        for candidate in (
            answer_payload.get("display_text"),
            answer_payload.get("keyboard_entry"),
        ):
            if not candidate:
                continue
            check = _fits(candidate, editor)
            if chosen is None:
                chosen, verdict = candidate, check
            if check.get("insertable"):
                chosen, verdict = candidate, check
                break
        print(f"chosen      {chosen!r} -> {json.dumps(verdict)}")
        if not verdict or not verdict.get("insertable"):
            print("refused     the editor would reject this; enter it with the keypad")
            return 1
        if not insert:
            return 0

        outcome = _run_page_script(
            marionette,
            EDITOR_JS,
            tail=f"return ethnosHawkes.insertAnswer({json.dumps(chosen)});",
        )
        time.sleep(1.2)
        state = json.loads(
            marionette.execute(r"""
          const box = document.querySelector('input.qbaseCSS, input[id$="_input"]');
          const dialog = document.getElementById("PracticecustomMessageBox");
          const up = dialog ? dialog.getBoundingClientRect().height > 0 : false;
          return JSON.stringify({ boxId: box && box.id, value: box && box.value,
            dialog: up ? dialog.innerText.replace(/\s+/g, " ").slice(0, 120) : null });
        """)["value"]
        )
        print(f"inserted    {json.dumps(outcome)}")
        print(f"readback    {json.dumps(state)}")
        return 0 if outcome.get("ok") and not state.get("dialog") else 1
    finally:
        marionette.disconnect()


def _panel_state(marionette):
    """Read either panel form, including Firefox's remote sidebar browser."""
    source = """
      const text = (sel) => document.querySelector(sel)?.textContent?.trim() ?? null;
      const insert = document.querySelector("#insert");
      return JSON.stringify({
        kind: location.search.includes("sidebar=1") ? "sidebar" : "popup",
        answer: text("#answer"), status: text("#status"), detail: text("#detail"),
        insertEnabled: insert ? !insert.disabled : null,
      });
    """
    out = marionette.execute(
        """
      const view = document.getElementById(%r);
      const frame = view && view.querySelector("browser");
      const doc = frame && frame.contentDocument;
      if (doc?.querySelector("#status")) {
        const text = (sel) => doc.querySelector(sel)?.textContent?.trim() ?? null;
        const insert = doc.querySelector("#insert");
        return JSON.stringify({kind: "popup", answer: text("#answer"),
          status: text("#status"), detail: text("#detail"),
          insertEnabled: insert ? !insert.disabled : null});
      }

      // Firefox hosts extension sidebars in a remote top-level browser. Its
      // contentDocument is intentionally unavailable to chrome JS, so execute
      // the read through the same Marionette actor that WebDriver uses.
      const sidebar = document.querySelector("#sidebar");
      const remote = sidebar?.contentDocument?.querySelector("#webext-panels-browser");
      const global = remote?.browsingContext?.currentWindowGlobal;
      if (!global || !remote.currentURI?.spec.includes("/popup/popup.html?sidebar=1")) {
        return "";
      }
      return global.getActor("MarionetteCommands").executeScript(
        %s, [], {timeout: 5000, newSandbox: true}
      );
    """
        % (PANEL_VIEW, json.dumps(source))
    )
    return json.loads(out["value"]) if out["value"] else None


def insert() -> int:
    """Open the panel, review it, click Insert, and read the field back.

    Never touches Submit or Check -- the add-on has no way to, and neither does
    this. The inserted value is trivially clearable by the user.
    """
    marionette = connect()
    try:
        marionette.set_context("chrome")
        marionette.execute(
            'Services.prefs.setBoolPref("ui.popup.disable_autohide", true); return true;'
        )
        marionette.execute("""
          for (const panel of document.querySelectorAll("panel")) {
            try { panel.hidePopup(); } catch (error) {}
          }
          return true;
        """)
        marionette.click(ACTION_BUTTON)

        state = None
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = _panel_state(marionette)
            if state and state.get("status"):
                break
            time.sleep(0.3)
        print("panel before insert:", json.dumps(state, indent=2), flush=True)
        if not state or not state.get("insertEnabled"):
            print("insert is not enabled; stopping here", flush=True)
            return 1

        marionette.execute(
            """
          const view = document.getElementById(%r);
          view.querySelector("browser").contentDocument.querySelector("#insert").click();
          return true;
        """
            % PANEL_VIEW
        )
        time.sleep(2.5)
        print(
            "panel after insert:",
            json.dumps(_panel_state(marionette), indent=2),
            flush=True,
        )
    finally:
        marionette.disconnect()
    return 0


def go(url: str) -> int:
    """Point the window at a URL, so the user need not type or search for it."""
    marionette = connect()
    try:
        marionette.set_context("content")
        marionette.navigate(url)
        print(f"navigated to {url}")
    finally:
        marionette.disconnect()
    return 0


COMMANDS = {
    "start": start,
    "popup": popup,
    "page": page,
    "field": field,
    "watch": watch,
    "insert": insert,
    "shot": shot,
    "solve": solve_current,
    "stop": stop,
}

if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "go":
        raise SystemExit(go(sys.argv[2]))
    if len(sys.argv) in (2, 3) and sys.argv[1] == "shot":
        raise SystemExit(shot(sys.argv[2] if len(sys.argv) == 3 else ""))
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(
            f"usage: {sys.argv[0]} {{{'|'.join(COMMANDS)}|go <url>}}", file=sys.stderr
        )
        raise SystemExit(2)
    raise SystemExit(COMMANDS[sys.argv[1]]())
