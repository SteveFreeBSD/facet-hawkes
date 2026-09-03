"""A minimal Marionette client.

Marionette is Firefox's built-in automation server, so driving the browser
needs no geckodriver, no Selenium, and no WebDriver install — just a socket and
a length-prefixed JSON protocol. It is used here only to run the extension
against local fixtures in a throwaway profile.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time

WEBDRIVER_ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"

# Prefs for a profile that starts fast, stays quiet, and phones nobody.
PROFILE_PREFS = (
    'user_pref("browser.shell.checkDefaultBrowser", false);',
    'user_pref("browser.startup.homepage", "about:blank");',
    'user_pref("browser.aboutwelcome.enabled", false);',
    'user_pref("datareporting.policy.dataSubmissionEnabled", false);',
    'user_pref("toolkit.telemetry.enabled", false);',
    'user_pref("app.update.enabled", false);',
    'user_pref("extensions.autoDisableScopes", 0);',
)


class MarionetteError(RuntimeError):
    """A command was rejected by Marionette."""


class Marionette:
    """Speaks the `<length>:<json>` protocol on Marionette's TCP port."""

    def __init__(self, host: str = "127.0.0.1", port: int = 2828) -> None:
        self.address = (host, port)
        self.socket: socket.socket | None = None
        self.message_id = 0
        self._buffer = b""

    def connect(self, timeout: float = 60.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                connection = socket.create_connection(self.address, timeout=5)
            except OSError:
                time.sleep(0.4)
                continue
            connection.settimeout(120)
            self.socket = connection
            self._buffer = b""
            return self._receive()
        raise TimeoutError("Marionette never accepted a connection")

    def _receive(self):
        while b":" not in self._buffer:
            self._buffer += self._read_chunk()
        length, _, rest = self._buffer.partition(b":")
        expected = int(length)
        while len(rest) < expected:
            rest += self._read_chunk()
        self._buffer = rest[expected:]
        return json.loads(rest[:expected])

    def _read_chunk(self) -> bytes:
        chunk = self.socket.recv(65536)
        if not chunk:
            raise ConnectionError("Marionette closed the connection")
        return chunk

    def send(self, command: str, params: dict | None = None):
        self.message_id += 1
        payload = json.dumps([0, self.message_id, command, params or {}]).encode()
        self.socket.sendall(f"{len(payload)}:".encode() + payload)
        while True:
            message = self._receive()
            if isinstance(message, list) and message[0] == 1 and message[1] == self.message_id:
                _, _, error, result = message
                if error:
                    raise MarionetteError(f"{command}: {error.get('message', error)}")
                return result

    # Conveniences ---------------------------------------------------------

    def new_session(self) -> dict:
        return self.send("WebDriver:NewSession", {"capabilities": {}})

    def set_context(self, context: str) -> None:
        """`content` for pages, `chrome` for browser UI such as the toolbar."""
        self.send("Marionette:SetContext", {"value": context})

    def navigate(self, url: str) -> None:
        self.send("WebDriver:Navigate", {"url": url})

    def execute(self, script: str, args: list | None = None):
        return self.send("WebDriver:ExecuteScript", {"script": script, "args": args or []})

    def install_addon(self, path: str, temporary: bool = True) -> str:
        return self.send("Addon:Install", {"path": path, "temporary": temporary})["value"]

    def click(self, css: str) -> None:
        found = self.send("WebDriver:FindElement", {"using": "css selector", "value": css})
        inner = found.get("value", found) if isinstance(found, dict) else found
        self.send("WebDriver:ElementClick", {"id": inner[WEBDRIVER_ELEMENT_KEY]})

    def disconnect(self) -> None:
        """Drop the socket, leaving the browser running."""
        if self.socket:
            try:
                self.socket.close()
            except OSError:
                pass
            self.socket = None

    def quit(self) -> None:
        """Shut the browser down, then drop the socket."""
        try:
            self.send("Marionette:Quit", {})
        except (MarionetteError, OSError, ConnectionError):
            pass
        self.disconnect()


def launch(profile_dir: str, port: int, headless: bool = False) -> subprocess.Popen:
    """Start Firefox on a throwaway profile with Marionette listening."""
    os.makedirs(profile_dir, exist_ok=True)
    with open(os.path.join(profile_dir, "user.js"), "w", encoding="utf-8") as handle:
        handle.write(f'user_pref("marionette.port", {port});\n')
        handle.write("\n".join(PROFILE_PREFS) + "\n")

    # Distribution builds may ship without Marionette: CachyOS's `firefox-pure`
    # 155 strips the remote agent entirely, so `--marionette` is reported as an
    # unrecognized flag and no port is ever opened. Point this at a build that
    # has it -- Mozilla's own release tarball does, and needs no root:
    #
    #     export ETHNOS_FIREFOX="$HOME/.local/opt/firefox-mozilla/firefox"
    binary = os.environ.get("ETHNOS_FIREFOX", "firefox")
    command = [
        binary,
        "--profile", profile_dir,
        "--no-remote",          # never attach to the user's running Firefox
        "--new-instance",
        "--marionette",
        "--remote-allow-system-access",  # required for chrome context since FF 136
        "about:blank",
    ]
    environment = dict(os.environ)
    # `xvfb-run` sets DISPLAY, and on a Wayland session Firefox ignores it: it
    # reads WAYLAND_DISPLAY, connects to the real compositor, and every window
    # opens on the user's actual screens. Observed exactly that way. Dropping
    # the Wayland handle forces the X11 backend, so the virtual display given
    # by xvfb-run is the one that gets used.
    environment.pop("WAYLAND_DISPLAY", None)
    environment["MOZ_ENABLE_WAYLAND"] = "0"
    if headless:
        environment["MOZ_HEADLESS"] = "1"
    return subprocess.Popen(
        command, env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
