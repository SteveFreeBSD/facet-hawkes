#!/usr/bin/env python3
"""Render `docs/ANSWER_CAPABILITIES.md`'s tables from the JSON authority.

The prose on that page is worth keeping and worth reading. Its *tables* are
data, and hand-maintained data beside a machine-readable copy of the same facts
drifts -- which is the failure this whole gate exists to end, applied to itself.

So the tables are generated between markers, the prose around them is not
touched, and `tests/test_answer_compatibility.py` fails when the rendered form
differs from what is checked in.

    python3 scripts/render_answer_capabilities.py            # check, exit 1 on drift
    python3 scripts/render_answer_capabilities.py --write    # regenerate
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ethnos.answer_capabilities import AUTHORITY, load  # noqa: E402

DOCUMENT = AUTHORITY.parent / "ANSWER_CAPABILITIES.md"
SUPPORTED_START = "<!-- generated:supported -->"
SUPPORTED_END = "<!-- /generated:supported -->"
UNSUPPORTED_START = "<!-- generated:unsupported -->"
UNSUPPORTED_END = "<!-- /generated:unsupported -->"


def supported_table(authority) -> str:
    lines = [
        "| Semantic answer | `form` | Notation | Example | Physical topology "
        "| Insertion mechanism | Unit | Harness | Live | Entry id |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in authority.supported():
        notation = "+".join(entry.notation) if entry.notation else "*plan*"
        mechanism = " → ".join(f"`{name}`" for name in entry.mechanism)
        lines.append(
            f"| {entry.semantic} | `{entry.form}` | {notation} | `{entry.example}` "
            f"| {entry.topology} | {mechanism} | {entry.coverage['unit']} "
            f"| {entry.coverage['harness']} | {entry.coverage['live']} "
            f"| `{entry.id}` |"
        )
    return "\n".join(lines)


def unsupported_table(authority) -> str:
    lines = [
        "| Composition | Example | Why | What happens now | Entry id |",
        "|---|---|---|---|---|",
    ]
    for entry in authority.unsupported():
        lines.append(
            f"| {entry.semantic} | `{entry.example}` | {entry.why} "
            f"| Refused as `{entry.refusal}` | `{entry.id}` |"
        )
    return "\n".join(lines)


def rendered(document: str, authority) -> str:
    for start, end, table in (
        (SUPPORTED_START, SUPPORTED_END, supported_table(authority)),
        (UNSUPPORTED_START, UNSUPPORTED_END, unsupported_table(authority)),
    ):
        head, _, rest = document.partition(start)
        _, _, tail = rest.partition(end)
        document = f"{head}{start}\n{table}\n{end}{tail}"
    return document


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate in place")
    arguments = parser.parse_args()

    current = DOCUMENT.read_text(encoding="utf-8")
    wanted = rendered(current, load())
    if current == wanted:
        print(f"{DOCUMENT.name} is up to date with {AUTHORITY.name}")
        return 0
    if arguments.write:
        DOCUMENT.write_text(wanted, encoding="utf-8")
        print(f"rewrote {DOCUMENT.name} from {AUTHORITY.name}")
        return 0
    print(
        f"{DOCUMENT.name} has drifted from {AUTHORITY.name}. "
        "Run: python3 scripts/render_answer_capabilities.py --write",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
