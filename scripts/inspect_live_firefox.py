#!/usr/bin/env python3
"""Inspect the owner's already-running Firefox without driving the website.

This is the normal-profile counterpart to ``scripts/live_browser.py``.
It never launches Firefox, opens a URL, changes a profile, or sends page input.
On KDE Wayland it can briefly focus the one existing Firefox window, capture
that window through Spectacle, and restore whichever window was active.

    python3 scripts/inspect_live_firefox.py status
    python3 scripts/inspect_live_firefox.py shot
    python3 scripts/inspect_live_firefox.py inspect

``inspect`` prints status and takes a screenshot. Screenshots default to /tmp;
inspect them locally, then delete them because a Hawkes page is coursework.
"""

from __future__ import annotations

import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


EXTENSION_ID = "ethnos-hawkes@local"
FIREFOX_CLASS = "firefox"
WINDOW_MARKER_PREFIX = "ETHNOS_EXISTING_FIREFOX_"


class InspectionError(RuntimeError):
    """A safe inspection prerequisite was not satisfied."""


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _require_commands(*names: str) -> None:
    missing = [name for name in names if shutil.which(name) is None]
    if missing:
        raise InspectionError(f"required command not found: {', '.join(missing)}")


def _kwin_windows() -> list[dict[str, object]]:
    """Return KWin's windows without changing focus or desktop state."""
    _require_commands("qdbus6", "journalctl")
    marker = WINDOW_MARKER_PREFIX + uuid.uuid4().hex
    plugin = "ethnos-window-scan-" + uuid.uuid4().hex
    script = f"""
const marker = {json.dumps(marker)};
for (const window of workspace.windowList()) {{
  print(JSON.stringify({{
    marker,
    handle: String(window.internalId),
    caption: String(window.caption || ""),
    resourceClass: String(window.resourceClass || ""),
    pid: Number(window.pid || 0),
    normalWindow: Boolean(window.normalWindow),
    minimized: Boolean(window.minimized),
    active: Boolean(window.active),
  }}));
}}
"""
    started = int(time.time()) - 1
    with tempfile.TemporaryDirectory(prefix="ethnos-kwin-scan-") as directory:
        script_path = Path(directory) / "scan.js"
        script_path.write_text(script, encoding="utf-8")
        try:
            _run(
                [
                    "qdbus6",
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.loadScript",
                    str(script_path),
                    plugin,
                ]
            )
            _run(
                [
                    "qdbus6",
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.start",
                ]
            )
            time.sleep(0.25)
        finally:
            _run(
                [
                    "qdbus6",
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.unloadScript",
                    plugin,
                ],
                check=False,
            )

    journal = _run(
        [
            "journalctl",
            "--user",
            "--since",
            f"@{started}",
            "--no-pager",
            "-o",
            "cat",
        ]
    ).stdout
    windows: list[dict[str, object]] = []
    for line in journal.splitlines():
        if marker not in line:
            continue
        start = line.find("{")
        if start < 0:
            continue
        try:
            item = json.loads(line[start:])
        except json.JSONDecodeError:
            continue
        if item.get("marker") == marker:
            item.pop("marker", None)
            windows.append(item)
    if not windows:
        raise InspectionError(
            "KWin returned no windows; live inspection is unavailable"
        )
    return windows


def _one_firefox_window(windows: list[dict[str, object]]) -> dict[str, object]:
    matches = [
        window
        for window in windows
        if str(window.get("resourceClass", "")).lower() == FIREFOX_CLASS
        and window.get("normalWindow")
    ]
    if len(matches) != 1:
        captions = [str(window.get("caption", "")) for window in matches]
        raise InspectionError(
            f"expected exactly one normal Firefox window, found {len(matches)}: {captions}"
        )
    return matches[0]


def _focus_window(handle: str) -> None:
    """Activate exactly one previously enumerated KWin handle."""
    plugin = "ethnos-window-focus-" + uuid.uuid4().hex
    script = f"""
const wanted = {json.dumps(handle)};
for (const window of workspace.windowList()) {{
  if (String(window.internalId) === wanted) {{
    workspace.activeWindow = window;
    break;
  }}
}}
"""
    with tempfile.TemporaryDirectory(prefix="ethnos-kwin-focus-") as directory:
        script_path = Path(directory) / "focus.js"
        script_path.write_text(script, encoding="utf-8")
        try:
            _run(
                [
                    "qdbus6",
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.loadScript",
                    str(script_path),
                    plugin,
                ]
            )
            _run(
                [
                    "qdbus6",
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.start",
                ]
            )
            time.sleep(0.35)
        finally:
            _run(
                [
                    "qdbus6",
                    "org.kde.KWin",
                    "/Scripting",
                    "org.kde.kwin.Scripting.unloadScript",
                    plugin,
                ],
                check=False,
            )


def _profile_candidates() -> list[Path]:
    configured = os.environ.get("ETHNOS_FIREFOX_PROFILE")
    if configured:
        return [Path(configured).expanduser()]

    roots = [
        Path.home() / ".config" / "mozilla" / "firefox",
        Path.home() / ".mozilla" / "firefox",
    ]
    profiles: list[Path] = []
    for root in roots:
        ini = root / "profiles.ini"
        if ini.is_file():
            parser = configparser.ConfigParser()
            parser.read(ini, encoding="utf-8")
            preferred: list[Path] = []
            others: list[Path] = []
            for section in parser.sections():
                if not section.startswith("Profile") or not parser.has_option(
                    section, "Path"
                ):
                    continue
                raw = Path(parser.get(section, "Path"))
                path = (
                    root / raw
                    if parser.getboolean(section, "IsRelative", fallback=True)
                    else raw
                )
                (
                    preferred
                    if parser.getboolean(section, "Default", fallback=False)
                    else others
                ).append(path)
            profiles.extend(preferred + others)
        elif root.is_dir():
            profiles.extend(path.parent for path in root.glob("*/extensions.json"))
    return profiles


def _extension_status() -> dict[str, object]:
    for profile in _profile_candidates():
        addons_path = profile / "extensions.json"
        if not addons_path.is_file():
            continue
        try:
            addons = json.loads(addons_path.read_text(encoding="utf-8")).get(
                "addons", []
            )
        except (json.JSONDecodeError, OSError):
            continue
        for addon in addons:
            if addon.get("id") == EXTENSION_ID:
                return {
                    "profile": str(profile),
                    "id": addon.get("id"),
                    "version": addon.get("version"),
                    "active": addon.get("active"),
                    "userDisabled": addon.get("userDisabled"),
                    "appDisabled": addon.get("appDisabled"),
                    "signedState": addon.get("signedState"),
                    "path": addon.get("path"),
                }
    return {"id": EXTENSION_ID, "installed": False}


def _matching_processes(needles: tuple[str, ...]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            command = (
                (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode().strip()
            )
        except (OSError, UnicodeDecodeError):
            continue
        if command and any(needle in command for needle in needles):
            found.append({"pid": int(entry.name), "command": command})
    return sorted(found, key=lambda item: int(item["pid"]))


def status() -> dict[str, object]:
    windows = _kwin_windows()
    firefox = _one_firefox_window(windows)
    active = next((window for window in windows if window.get("active")), None)
    return {
        "mode": "existing-normal-firefox-read-only",
        "firefox": firefox,
        "previouslyActive": {
            "caption": active.get("caption"),
            "resourceClass": active.get("resourceClass"),
        }
        if active
        else None,
        "extension": _extension_status(),
        "nativeHosts": _matching_processes(
            ("ethnos.hawkes_host", "ethnos-hawkes-host")
        ),
    }


def shot(output: Path | None = None) -> Path:
    """Capture the one Firefox window and restore the previous active window."""
    _require_commands("spectacle")
    windows = _kwin_windows()
    firefox = _one_firefox_window(windows)
    previous = next((window for window in windows if window.get("active")), None)
    if output is None:
        descriptor, name = tempfile.mkstemp(
            prefix="ethnos-firefox-live-", suffix=".png"
        )
        os.close(descriptor)
        output = Path(name)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        _focus_window(str(firefox["handle"]))
        _run(
            [
                "spectacle",
                "--activewindow",
                "--background",
                "--nonotify",
                "--output",
                str(output),
            ]
        )
    finally:
        if previous and previous.get("handle") != firefox.get("handle"):
            _focus_window(str(previous["handle"]))

    if not output.is_file() or output.stat().st_size == 0:
        raise InspectionError("Spectacle did not produce a Firefox screenshot")
    output.chmod(0o600)
    return output


def main() -> int:
    if len(sys.argv) not in (2, 3) or sys.argv[1] not in {"status", "shot", "inspect"}:
        print(
            f"usage: {sys.argv[0]} {{status|shot [output.png]|inspect}}",
            file=sys.stderr,
        )
        return 2
    command = sys.argv[1]
    try:
        if command in {"status", "inspect"}:
            print(json.dumps(status(), indent=2))
        if command in {"shot", "inspect"}:
            target = Path(sys.argv[2]) if len(sys.argv) == 3 else None
            print(f"screenshot: {shot(target)}")
            print("delete the screenshot after inspection; it may contain coursework")
    except (InspectionError, subprocess.SubprocessError, OSError) as error:
        print(f"inspection refused: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
