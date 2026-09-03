"""Release-grade installation checks for the Firefox native companion."""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALLER_PATH = PROJECT_ROOT / "deploy" / "firefox" / "install_native_host.py"


def _installer():
    spec = importlib.util.spec_from_file_location("ethnos_native_installer", INSTALLER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_install_check_and_uninstall_are_scoped_and_reversible(tmp_path, monkeypatch):
    installer = _installer()
    install_dir = tmp_path / "share" / "ethnos-hawkes"
    launcher = install_dir / "ethnos-hawkes-host"
    manifest_dir = tmp_path / "mozilla" / "native-messaging-hosts"
    manifest = manifest_dir / "ethnos_hawkes.json"

    monkeypatch.setattr(installer, "INSTALL_DIR", install_dir)
    monkeypatch.setattr(installer, "LAUNCHER", launcher)
    monkeypatch.setattr(installer, "MANIFEST_DIR", manifest_dir)
    monkeypatch.setattr(installer, "MANIFEST", manifest)

    assert installer.install(write=True) == 0
    assert launcher.is_file()
    assert os.access(launcher, os.X_OK)
    assert json.loads(manifest.read_text()) == installer.manifest_body()
    assert installer.check() == 0

    # Uninstall removes only the two generated files and their now-empty
    # private directory, never the source-tree launcher.
    source_launcher = PROJECT_ROOT / "deploy" / "firefox" / "ethnos-hawkes-host"
    assert source_launcher.is_file()
    assert installer.uninstall(write=True) == 0
    assert not launcher.exists()
    assert not manifest.exists()
    assert source_launcher.is_file()


def test_dry_run_never_writes(tmp_path, monkeypatch):
    installer = _installer()
    monkeypatch.setattr(installer, "INSTALL_DIR", tmp_path / "install")
    monkeypatch.setattr(installer, "LAUNCHER", tmp_path / "install" / "host")
    monkeypatch.setattr(installer, "MANIFEST_DIR", tmp_path / "manifests")
    monkeypatch.setattr(installer, "MANIFEST", tmp_path / "manifests" / "host.json")

    assert installer.install(write=False) == 0
    assert not installer.LAUNCHER.exists()
    assert not installer.MANIFEST.exists()
