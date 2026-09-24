#!/usr/bin/env python3
"""Reload the existing temporary Facet add-on in normal-profile Firefox.

This command never launches Firefox, drives its GUI, or addresses a coursework
tab.  It resolves the one running Firefox D-Bus service from its encoded
profile path, proves that profile holds the temporary ``ethnos-hawkes@local``
add-on, opens a one-shot page in that extension origin, and lets the extension
call Firefox's own ``browser.runtime.reload()``.  The page removes itself.

Afterwards the existing diagnostic marker proves that a new event-page
generation is running the source in this checkout.
"""

from __future__ import annotations

import argparse
import base64
import importlib.util
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"
TARGET_ADDON_ID = "ethnos-hawkes@local"
RELOAD_STATE_KEY = "facetDevelopmentReload"
SERVICE_PREFIX = "org.mozilla.firefox."
REMOTE_PATH = "/org/mozilla/firefox/Remote"
REMOTE_INTERFACE = "org.mozilla.firefox"
RELOAD_PAGE = "development/reload.html"
WAIT_SECONDS = 12.0


class ReloadRefused(RuntimeError):
    """A precondition was not proved; no reload request was sent."""


@dataclass(frozen=True)
class Target:
    profile: Path
    service: str
    pid: int
    extension_uuid: str


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=check, text=True, capture_output=True)


def _ensure_project_python() -> None:
    """The marker comparison is mandatory, so QuickJS is mandatory too."""
    if importlib.util.find_spec("quickjs") is not None:
        return
    project_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    if not project_python.is_file():
        raise ReloadRefused(
            "QuickJS is unavailable and .venv/bin/python does not exist; "
            "run `uv sync --extra dev` first"
        )
    if Path(sys.executable).absolute() == project_python.absolute():
        raise ReloadRefused(
            "the project interpreter cannot import QuickJS; run `uv sync --extra dev`"
        )
    os.execv(
        str(project_python),
        [str(project_python), str(Path(__file__).resolve()), *sys.argv[1:]],
    )


def _manifest_id() -> str:
    try:
        manifest = json.loads(
            (EXTENSION_DIR / "manifest.json").read_text(encoding="utf-8")
        )
        return str(manifest["browser_specific_settings"]["gecko"]["id"])
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ReloadRefused(
            f"the extension manifest could not be read: {error}"
        ) from error


def _service_name(profile: Path) -> str:
    encoded = base64.b64encode(os.fsencode(str(profile.resolve()))).decode("ascii")
    safe = re.sub(r"[^A-Za-z0-9_]", "_", encoded)
    return SERVICE_PREFIX + safe


def _bus_services() -> set[str]:
    if shutil.which("busctl") is None:
        raise ReloadRefused("busctl is required to address the running Firefox session")
    result = _run(["busctl", "--user", "--no-pager", "--no-legend", "list"])
    return {
        line.split()[0]
        for line in result.stdout.splitlines()
        if line.split() and line.split()[0].startswith(SERVICE_PREFIX)
    }


def _service_pid(service: str) -> int:
    result = _run(["busctl", "--user", "status", service])
    match = re.search(r"^PID=(\d+)\b", result.stdout, re.MULTILINE)
    if match is None:
        raise ReloadRefused(f"Firefox D-Bus service {service} published no process ID")
    return int(match.group(1))


def _locked_pid(profile: Path) -> int | None:
    lock = profile / "lock"
    if not lock.is_symlink():
        return None
    match = re.search(r"\+(\d+)$", os.readlink(lock))
    return int(match.group(1)) if match else None


def _temporary_uuid(profile: Path) -> str | None:
    """The UUID only when the target is present and absent from installed XPIs."""
    try:
        prefs = (profile / "prefs.js").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = re.search(r'"extensions\.webextensions\.uuids",\s*"(.*)"\);', prefs)
    if match is None:
        return None
    try:
        mapping = json.loads(match.group(1).replace('\\"', '"'))
    except json.JSONDecodeError:
        return None
    internal = mapping.get(TARGET_ADDON_ID)
    if not isinstance(internal, str) or not re.fullmatch(
        r"[A-Za-z0-9-]{8,80}", internal
    ):
        return None
    try:
        installed = json.loads(
            (profile / "extensions.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        installed = {}
    if any(one.get("id") == TARGET_ADDON_ID for one in installed.get("addons", [])):
        return None
    return internal


def _profile_candidates() -> list[Path]:
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import inspect_live_firefox as inspector

    return [path.resolve() for path in inspector._profile_candidates() if path.is_dir()]


def _target() -> Target:
    if _manifest_id() != TARGET_ADDON_ID:
        raise ReloadRefused(f"manifest add-on ID is not the required {TARGET_ADDON_ID}")
    services = _bus_services()
    candidates: list[Target] = []
    for profile in _profile_candidates():
        service = _service_name(profile)
        if service not in services:
            continue
        internal = _temporary_uuid(profile)
        if internal is None:
            continue
        pid = _service_pid(service)
        if _locked_pid(profile) != pid:
            continue
        try:
            executable = Path(f"/proc/{pid}/exe").resolve()
        except OSError:
            continue
        if "firefox" not in executable.name.lower():
            continue
        candidates.append(Target(profile, service, pid, internal))
    if len(candidates) != 1:
        names = [str(candidate.profile) for candidate in candidates]
        raise ReloadRefused(
            "expected one running normal Firefox profile with the temporary "
            f"{TARGET_ADDON_ID} add-on, found {len(candidates)}: {names}"
        )
    return candidates[0]


def _modules():
    scripts = str(Path(__file__).resolve().parent)
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import observe_live_hawkes as observer
    import read_extension_log as reader

    return observer, reader


def _entries(profile: Path) -> list[dict]:
    _, reader = _modules()
    return reader.read_entries(reader.find_store(profile))


def _reload_state(profile: Path) -> dict:
    _, reader = _modules()
    state = reader.read_storage(reader.find_store(profile)).get(RELOAD_STATE_KEY)
    return state if isinstance(state, dict) else {}


def _last_event(entries: list[dict], name: str) -> dict | None:
    found = [entry for entry in entries if entry.get("event") == name]
    return found[-1] if found else None


def _marker(entry: dict | None) -> str:
    value = entry.get("data", {}).get("marker") if entry else None
    return str(value) if value else "none"


def _pack_command_line(arguments: list[str], working_directory: Path) -> bytes:
    """Firefox nsUnixRemoteServer's documented little-endian argv buffer."""
    if not arguments or any("\0" in item for item in arguments):
        raise ReloadRefused("the Firefox remote command line is invalid")
    argc = len(arguments)
    prefix = 4 * (argc + 1)
    body = os.fsencode(str(working_directory)) + b"\0"
    offsets = []
    for argument in arguments:
        offsets.append(prefix + len(body))
        body += os.fsencode(argument) + b"\0"
    return struct.pack(f"<{argc + 1}I", argc, *offsets) + body


def _open_reload_page(target: Target, nonce: str) -> None:
    url = f"moz-extension://{target.extension_uuid}/{RELOAD_PAGE}?nonce={nonce}"
    payload = _pack_command_line(["firefox", "--new-tab", url], PROJECT_ROOT)
    # busctl's `ay` syntax is a count followed by each byte.  Addressing the
    # already-owned profile service cannot launch a browser or reach another
    # profile, and the only URL is inside the proved target extension origin.
    _run(
        [
            "busctl",
            "--user",
            "call",
            target.service,
            REMOTE_PATH,
            REMOTE_INTERFACE,
            "OpenURL",
            "ay",
            str(len(payload)),
            *(str(byte) for byte in payload),
        ]
    )


def _wait_for_reload(
    target: Target, previous_load: dict | None, expected_marker: str, nonce: str
) -> tuple[bool, str, str]:
    previous_t = float(previous_load.get("t", 0)) if previous_load else 0.0
    previous_generation = str(previous_load.get("gen", "")) if previous_load else ""
    deadline = time.monotonic() + WAIT_SECONDS
    current_marker = "none"
    reason = "no new event-page generation appeared"
    while time.monotonic() < deadline:
        time.sleep(0.2)
        try:
            entries = _entries(target.profile)
            acknowledgement = _reload_state(target.profile)
        except Exception as error:  # noqa: BLE001 - keep polling a flushing store
            reason = f"the diagnostic store could not yet be read: {error}"
            continue
        load = _last_event(entries, "event-page-loaded")
        if load is None or float(load.get("t", 0)) <= previous_t:
            continue
        if previous_generation and str(load.get("gen", "")) == previous_generation:
            continue
        if not (
            acknowledgement.get("addonId") == TARGET_ADDON_ID
            and acknowledgement.get("nonce") == nonce
            and acknowledgement.get("phase") == "completed"
            and acknowledgement.get("generation") == load.get("gen")
        ):
            reason = "the new event page has not acknowledged this reload request"
            continue
        markers = [
            entry
            for entry in entries
            if entry.get("event") == "build-marker"
            and entry.get("gen") == load.get("gen")
            and float(entry.get("t", 0)) >= float(load.get("t", 0))
        ]
        if not markers:
            reason = "the new event page has not published its build marker"
            continue
        current_marker = _marker(markers[-1])
        if current_marker != expected_marker:
            return True, current_marker, "the reloaded add-on does not match this tree"
        observer, _ = _modules()
        verdict = observer.code_verdict(
            markers[-1].get("data", {}),
            observer.working_tree_marker(),
            load,
            {"temporary": True},
        )
        if verdict.get("verdict") != "running-this-tree":
            return (
                True,
                current_marker,
                str(verdict.get("why", "marker verification failed")),
            )
        return True, current_marker, "running build matches the working tree"
    return False, current_marker, reason


def _print_result(
    *, reloaded: bool, previous: str, current: str, running: bool, reason: str
) -> None:
    print(f"reloaded: {'yes' if reloaded else 'no'}")
    print(f"previous marker: {previous}")
    print(f"current marker: {current}")
    print(f"running-this-tree: {'yes' if running else 'no'}")
    print(f"reason: {reason}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args()
    previous_marker = "none"
    current_marker = "none"
    try:
        _ensure_project_python()
        target = _target()
        observer, _ = _modules()
        tree = observer.working_tree_marker()
        if not tree.get("computed"):
            raise ReloadRefused(str(tree.get("why", "working-tree marker unavailable")))
        entries = _entries(target.profile)
        previous_load = _last_event(entries, "event-page-loaded")
        previous_marker = _marker(_last_event(entries, "build-marker"))
        nonce = uuid.uuid4().hex
        _open_reload_page(target, nonce)
        reloaded, current_marker, reason = _wait_for_reload(
            target, previous_load, str(tree["marker"]), nonce
        )
        running = (
            reloaded
            and current_marker == tree["marker"]
            and reason.startswith("running build")
        )
        _print_result(
            reloaded=reloaded,
            previous=previous_marker,
            current=current_marker,
            running=running,
            reason=reason,
        )
        return 0 if running else 1
    except (ReloadRefused, subprocess.CalledProcessError) as error:
        detail = (
            error.stderr.strip()
            if isinstance(error, subprocess.CalledProcessError)
            else str(error)
        )
        _print_result(
            reloaded=False,
            previous=previous_marker,
            current=current_marker,
            running=False,
            reason=detail or type(error).__name__,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
