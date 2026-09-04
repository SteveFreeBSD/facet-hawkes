#!/usr/bin/env python3
"""Fixed stdin bridge from Ethnos on caspian to the local Facet CLI."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MAX_REQUEST_BYTES = 16 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
FACET_EXECUTABLE = "/home/steve/.local/bin/facet"
FACET_ROOT = "/home/steve/apps/facet-runtime"
EXPECTED_OPERATION = "solve_hawkes_with_facet"


def _parse_request(raw: bytes) -> str:
    if len(raw) > MAX_REQUEST_BYTES:
        raise ValueError("request exceeds the bridge size limit")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != {
        "protocol_version",
        "operation",
        "prompt",
    }:
        raise ValueError(
            "request must contain exactly protocol_version, operation, prompt"
        )
    if payload["protocol_version"] != 1:
        raise ValueError("unsupported bridge protocol version")
    if payload["operation"] != EXPECTED_OPERATION:
        raise ValueError("unsupported bridge operation")
    prompt = payload["prompt"]
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    if len(prompt.encode("utf-8")) > 12 * 1024:
        raise ValueError("prompt exceeds the bridge size limit")
    return prompt


def _read_request() -> str:
    return _parse_request(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))


def main() -> int:
    try:
        prompt = _read_request()
        executable = Path(FACET_EXECUTABLE)
        if not executable.is_file():
            raise FileNotFoundError(f"Facet executable is missing: {executable}")
        completed = subprocess.run(
            [str(executable), "run", prompt, "--backend", "gpu"],
            cwd=FACET_ROOT,
            text=True,
            capture_output=True,
            timeout=180,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip()[:400]
            raise RuntimeError(
                f"Facet exited with status {completed.returncode}"
                f"{': ' + detail if detail else ''}"
            )
        encoded = completed.stdout.encode("utf-8")
        if len(encoded) > MAX_RESPONSE_BYTES:
            raise ValueError("Facet response exceeds the bridge size limit")
        sys.stdout.write(completed.stdout)
        return 0
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        ValueError,
    ) as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
