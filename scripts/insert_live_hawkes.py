#!/usr/bin/env python3
"""Invoke only Facet Insert for the reviewed answer in the live lesson."""

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


PAGE = "development/insert-reviewed.html"
STATE_KEY = "facetDevelopmentReviewedInsertion"


def _state(profile: Path) -> dict:
    _, reader = reload_helper._modules()
    value = reader.read_storage(reader.find_store(profile)).get(STATE_KEY)
    return value if isinstance(value, dict) else {}


def _settled_pair_insertion(profile: Path, started_ms: float) -> dict | None:
    """The paired pin and success record emitted by the existing Insert path."""
    entries = reload_helper._entries(profile)
    pins = {
        entry.get("run"): entry
        for entry in entries
        if entry.get("event") == "insertion-pinned"
        and float(entry.get("t", 0)) >= started_ms
        and entry.get("data", {}).get("fieldIds") == 2
        and entry.get("data", {}).get("answerParts") == 2
        and entry.get("data", {}).get("answerConnector") in {"and", "or"}
    }
    for entry in reversed(entries):
        data = entry.get("data", {})
        run = entry.get("run")
        if (
            entry.get("event") == "inserted"
            and float(entry.get("t", 0)) >= started_ms
            and run in pins
            and data.get("via") == "structured-fields"
            and data.get("fields") == 2
            and data.get("parts") == 2
        ):
            return {
                "run": run,
                "connector": pins[run]["data"]["answerConnector"],
                "settled": True,
            }
    return None


def main() -> int:
    reload_helper._ensure_project_python(Path(__file__))
    try:
        target = reload_helper._target()
        nonce = uuid.uuid4().hex
        started_ms = time.time() * 1000
        reload_helper._open_extension_page(target, PAGE, f"nonce={nonce}")
        deadline = time.monotonic() + 24.0
        state: dict = {}
        while time.monotonic() < deadline:
            time.sleep(0.15)
            state = _state(target.profile)
            if state.get("nonce") == nonce and state.get("phase") in {
                "completed",
                "refused",
            }:
                break
        else:
            raise reload_helper.ReloadRefused("the Insert proof did not answer")
        if state.get("addonId") != reload_helper.TARGET_ADDON_ID:
            raise reload_helper.ReloadRefused(
                "the Insert proof did not prove the target ID"
            )
        inserted = _settled_pair_insertion(target.profile, started_ms)
        if inserted is not None:
            state = {
                "addonId": reload_helper.TARGET_ADDON_ID,
                "nonce": nonce,
                "phase": "completed",
                "evidence": "paired diagnostic pin and settled Insert record",
                **inserted,
            }
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0 if state.get("phase") == "completed" else 1
    except reload_helper.ReloadRefused as error:
        print(f"insert refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
