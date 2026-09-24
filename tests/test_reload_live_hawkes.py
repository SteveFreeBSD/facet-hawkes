"""The normal-profile add-on reload bridge is exact and fail-closed."""

from __future__ import annotations

import importlib.util
import os
import re
import struct
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "reload_live_hawkes.py"
PAGE = ROOT / "extension" / "development" / "reload.js"
SPEC = importlib.util.spec_from_file_location("reload_live_hawkes", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_profile_scoped_firefox_service_is_deterministic(tmp_path):
    profile = tmp_path / "normal profile"
    profile.mkdir()

    service = MODULE._service_name(profile)

    assert service.startswith("org.mozilla.firefox.")
    assert service == MODULE._service_name(profile)
    assert all(character.isalnum() or character in "_." for character in service)


def test_busctl_status_pid_is_read_from_machine_output(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "_run",
        lambda arguments: MODULE.subprocess.CompletedProcess(
            arguments, 0, "PID=2690\nUID=1000\nComm=firefox\n", ""
        ),
    )

    assert MODULE._service_pid("org.mozilla.firefox.profile") == 2690


def test_firefox_remote_command_line_has_exact_argv_and_working_directory(tmp_path):
    arguments = ["firefox", "--new-tab", "moz-extension://uuid/development/reload.html"]

    packed = MODULE._pack_command_line(arguments, tmp_path)

    argc = struct.unpack_from("<I", packed)[0]
    offsets = struct.unpack_from(f"<{argc}I", packed, 4)
    start = 4 * (argc + 1)
    working = packed[start : packed.index(b"\0", start)].decode()
    argv = [packed[offset : packed.index(b"\0", offset)].decode() for offset in offsets]
    assert argc == 3
    assert working == str(tmp_path)
    assert argv == arguments


def test_only_a_temporary_target_uuid_is_accepted(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "prefs.js").write_text(
        'user_pref("extensions.webextensions.uuids", '
        '"{\\"ethnos-hawkes@local\\":\\"internal-uuid\\"}");\n',
        encoding="utf-8",
    )
    (profile / "extensions.json").write_text('{"addons": []}', encoding="utf-8")

    assert MODULE._temporary_uuid(profile) == "internal-uuid"

    (profile / "extensions.json").write_text(
        '{"addons": [{"id": "ethnos-hawkes@local"}]}', encoding="utf-8"
    )
    assert MODULE._temporary_uuid(profile) is None


def test_target_selection_refuses_zero_or_ambiguous_profiles(monkeypatch, tmp_path):
    profiles = [tmp_path / "one", tmp_path / "two"]
    for profile in profiles:
        profile.mkdir()
    monkeypatch.setattr(MODULE, "_manifest_id", lambda: MODULE.TARGET_ADDON_ID)
    monkeypatch.setattr(MODULE, "_profile_candidates", lambda: profiles)
    monkeypatch.setattr(MODULE, "_bus_services", lambda: set())

    with pytest.raises(MODULE.ReloadRefused, match="found 0"):
        MODULE._target()

    services = {MODULE._service_name(profile) for profile in profiles}
    monkeypatch.setattr(MODULE, "_bus_services", lambda: services)
    monkeypatch.setattr(MODULE, "_temporary_uuid", lambda profile: "internal-uuid")
    monkeypatch.setattr(MODULE, "_service_pid", lambda service: os.getpid())
    monkeypatch.setattr(MODULE, "_locked_pid", lambda profile: os.getpid())
    real_resolve = Path.resolve

    def resolve(path):
        if str(path).startswith("/proc/"):
            return Path("/usr/lib/firefox/firefox")
        return real_resolve(path)

    monkeypatch.setattr(Path, "resolve", resolve)
    with pytest.raises(MODULE.ReloadRefused, match="found 2"):
        MODULE._target()


def test_reload_page_uses_the_extension_native_api_and_checks_the_fixed_id():
    source = PAGE.read_text(encoding="utf-8")

    assert 'TARGET_ADDON_ID = "ethnos-hawkes@local"' in source
    assert "browser.runtime.id !== TARGET_ADDON_ID" in source
    assert "browser.runtime.reload()" in source
    assert "browser.storage.local.set" in source
    assert 'phase: "requested"' in source
    assert "browser.tabs.remove(tab.id)" in source
    assert "fetch(" not in source
    assert "hawkeslearning" not in source.lower()


def test_helper_has_no_gui_or_browser_launch_fallback():
    source = SCRIPT.read_text(encoding="utf-8")

    for forbidden in (
        "xdotool",
        "ydotool",
        "pyautogui",
        "spectacle",
        "about:debugging",
        "workspace.activeWindow",
        "subprocess.Popen",
    ):
        assert forbidden not in source
    assert 'REMOTE_INTERFACE = "org.mozilla.firefox"' in source
    assert 'TARGET_ADDON_ID = "ethnos-hawkes@local"' in source
    assert re.search(r'"busctl",\s*"--user",\s*"call"', source)
