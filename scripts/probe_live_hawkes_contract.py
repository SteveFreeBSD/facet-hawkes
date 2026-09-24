#!/usr/bin/env python3
"""Read the current Hawkes control contract through the temporary add-on.

The helper reuses the reload helper's exact normal-profile target proof and
Firefox D-Bus transport.  It opens only an internal extension page, which
performs one read-only MAIN-world snapshot of the unique Hawkes lesson tab.
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import reload_live_hawkes as reload_helper  # noqa: E402


PROBE_PAGE = "development/probe.html"
PROBE_STATE_KEY = "facetDevelopmentContractProbe"
WAIT_SECONDS = 10.0


def _probe_state(profile: Path) -> dict:
    _, reader = reload_helper._modules()
    state = reader.read_storage(reader.find_store(profile)).get(PROBE_STATE_KEY)
    return state if isinstance(state, dict) else {}


def run() -> int:
    reload_helper._ensure_project_python(Path(__file__))
    try:
        target = reload_helper._target()
        nonce = uuid.uuid4().hex
        reload_helper._open_extension_page(target, PROBE_PAGE, f"nonce={nonce}")
        deadline = time.monotonic() + WAIT_SECONDS
        state: dict = {}
        while time.monotonic() < deadline:
            time.sleep(0.15)
            state = _probe_state(target.profile)
            if state.get("nonce") == nonce and state.get("phase") in {
                "completed",
                "refused",
            }:
                break
        else:
            raise reload_helper.ReloadRefused("the extension probe did not answer")
        if state.get("addonId") != reload_helper.TARGET_ADDON_ID:
            raise reload_helper.ReloadRefused("the probe did not prove the target ID")
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0 if state.get("phase") == "completed" else 1
    except reload_helper.ReloadRefused as error:
        print(f"probe refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
