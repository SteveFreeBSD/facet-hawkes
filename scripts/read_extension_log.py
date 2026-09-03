#!/usr/bin/env python3
"""Read the Hawkes add-on's diagnostic log straight out of a Firefox profile.

The add-on keeps a bounded, redacted ring in `storage.local` and shows it under
Settings -> Diagnostics, where **Copy** puts it on the clipboard. That is the
supported path and it stays authoritative. This is for the case the copy button
cannot serve: reading the log while triaging, without asking the person using
the browser to stop and fetch it -- and without touching their session at all.

It reads the profile on disk. It never launches, drives, or connects to
Firefox, and it opens a throwaway copy of the database so a running browser is
undisturbed.

What it decodes, and why by hand:

* `storage.local` for an extension is IndexedDB, whose values Firefox stores
  Snappy-compressed. `snappy_decompress` below is the raw format, about sixty
  lines, so this script needs nothing that is not in the standard library.
* The decompressed value is a Firefox structured clone: 64-bit little-endian
  word pairs of `(data, tag)`, with strings and numbers inline. Only the tags
  this log actually contains are handled; anything else is reported rather
  than guessed at.

Usage::

    python3 scripts/read_extension_log.py
    python3 scripts/read_extension_log.py --grep window
    python3 scripts/read_extension_log.py --level warn --last 40
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path

ADDON_ID = "ethnos-hawkes@local"

# Firefox writes the profile under ~/.mozilla, or under XDG config when the
# build is compiled that way -- CachyOS's `firefox-pure` is, which is why the
# obvious path finds nothing on this machine.
PROFILE_ROOTS = (
    Path.home() / ".mozilla" / "firefox",
    Path.home() / ".config" / "mozilla" / "firefox",
)

# js/public/StructuredClone.h. Only what this log contains.
TAG_BOOLEAN = 0xFFFF0002
TAG_INT32 = 0xFFFF0003
TAG_STRING = 0xFFFF0004
TAG_ARRAY = 0xFFFF0007
TAG_OBJECT = 0xFFFF0008
TAG_END_OF_KEYS = 0xFFFF0013
TAG_NULL = 0xFFFF0000
TAG_UNDEFINED = 0xFFFF0001
TAG_FLOOR = 0xFFF00000  # anything below this is a NaN-boxed double


class Unreadable(Exception):
    """The log could not be read; the message says how far it got."""


def snappy_decompress(data: bytes) -> bytes:
    """Raw Snappy, as Firefox stores IndexedDB values."""
    pos, shift, expected = 0, 0, 0
    while True:
        byte = data[pos]
        pos += 1
        expected |= (byte & 0x7F) << shift
        if not byte & 0x80:
            break
        shift += 7

    out = bytearray()
    while pos < len(data):
        tag = data[pos]
        pos += 1
        kind = tag & 0x03
        if kind == 0:
            count = tag >> 2
            if count < 60:
                count += 1
            else:
                width = count - 59
                count = int.from_bytes(data[pos:pos + width], "little") + 1
                pos += width
            out += data[pos:pos + count]
            pos += count
            continue
        if kind == 1:
            count = 4 + ((tag >> 2) & 0x07)
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            count = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 2], "little")
            pos += 2
        else:
            count = (tag >> 2) + 1
            offset = int.from_bytes(data[pos:pos + 4], "little")
            pos += 4
        start = len(out) - offset
        if start < 0:
            raise Unreadable("snappy copy points before the start of the output")
        for index in range(count):
            out.append(out[start + index])

    if len(out) != expected:
        raise Unreadable(f"snappy length mismatch: {len(out)} != {expected}")
    return bytes(out)


class Clone:
    """A reader for the subset of Firefox's structured clone this log uses."""

    def __init__(self, raw: bytes) -> None:
        self.raw = raw
        self.pos = 0

    def pair(self) -> tuple[int, int]:
        if self.pos + 8 > len(self.raw):
            raise Unreadable("ran off the end of the clone")
        data, tag = struct.unpack_from("<II", self.raw, self.pos)
        self.pos += 8
        return data, tag

    def string(self, data: int) -> str:
        latin1 = bool(data & 0x80000000)
        length = data & 0x7FFFFFFF
        width = length if latin1 else length * 2
        chars = self.raw[self.pos:self.pos + width]
        # Every value is 8-byte aligned.
        self.pos += (width + 7) & ~7
        return chars.decode("latin-1" if latin1 else "utf-16-le", errors="replace")

    def value(self, data: int, tag: int):
        if tag < TAG_FLOOR:
            return struct.unpack("<d", struct.pack("<II", data, tag))[0]
        if tag == TAG_STRING:
            return self.string(data)
        if tag == TAG_INT32:
            return struct.unpack("<i", struct.pack("<I", data))[0]
        if tag == TAG_BOOLEAN:
            return bool(data)
        if tag == TAG_NULL:
            return None
        if tag == TAG_UNDEFINED:
            return None
        if tag == TAG_OBJECT:
            return self.collection(as_list=False)
        if tag == TAG_ARRAY:
            return self.collection(as_list=True)
        raise Unreadable(f"unhandled structured-clone tag 0x{tag:08X}")

    def collection(self, *, as_list: bool):
        """Read key/value pairs until the end marker; arrays key by index."""
        items: dict = {}
        while True:
            data, tag = self.pair()
            if tag == TAG_END_OF_KEYS:
                break
            key = self.value(data, tag)
            data, tag = self.pair()
            items[key] = self.value(data, tag)
        if not as_list:
            return items
        return [items[k] for k in sorted(items, key=lambda k: int(k))]

    def read(self):
        # Header pair, then the value itself.
        self.pair()
        data, tag = self.pair()
        return self.value(data, tag)


def find_profile(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.is_dir():
            raise Unreadable(f"no such profile directory: {path}")
        return path
    candidates = [
        entry
        for root in PROFILE_ROOTS
        if root.is_dir()
        for entry in root.iterdir()
        if (entry / "prefs.js").is_file()
    ]
    if not candidates:
        raise Unreadable(
            "no Firefox profile found under "
            + " or ".join(str(root) for root in PROFILE_ROOTS)
        )
    # The one used most recently, which is the one being debugged.
    return max(candidates, key=lambda entry: (entry / "prefs.js").stat().st_mtime)


def find_store(profile: Path) -> Path:
    """The add-on's IndexedDB file, via the UUID Firefox assigned it."""
    prefs = (profile / "prefs.js").read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'"extensions\.webextensions\.uuids",\s*"(.*)"\);', prefs)
    if not match:
        raise Unreadable("this profile records no extension UUIDs")
    uuids = json.loads(match.group(1).replace('\\"', '"'))
    uuid = uuids.get(ADDON_ID)
    if not uuid:
        raise Unreadable(f"{ADDON_ID} is not installed in {profile.name}")
    found = sorted(
        (profile / "storage" / "default").glob(
            f"moz-extension+++{uuid}*/idb/*.sqlite"
        )
    )
    if not found:
        raise Unreadable("the add-on has written no storage yet")
    return max(found, key=lambda path: path.stat().st_size)


def read_entries(store: Path) -> list[dict]:
    """Copy the database first: Firefox may be running and holding it."""
    with tempfile.TemporaryDirectory(prefix="ethnos-log-") as work:
        copy = Path(work) / "store.sqlite"
        shutil.copy(store, copy)
        rows = sqlite3.connect(copy).execute("select data from object_data").fetchall()

    entries: list[dict] = []
    for (blob,) in rows:
        if not blob:
            continue
        value = Clone(snappy_decompress(bytes(blob))).read()
        for candidate in _log_arrays(value):
            entries.extend(candidate)
    # By time, not by `seq`: the sequence counter restarts whenever the
    # non-persistent event page is unloaded, so sorting by it interleaves
    # separate sessions into nonsense.
    entries.sort(key=lambda entry: (entry.get("t", 0), entry.get("seq", 0)))
    return entries


def _log_arrays(value):
    """Find the ring wherever `storage.local` happens to have nested it."""
    if isinstance(value, list):
        if value and isinstance(value[0], dict) and "event" in value[0]:
            yield value
        return
    if isinstance(value, dict):
        for nested in value.values():
            yield from _log_arrays(nested)


def format_entry(entry: dict) -> str:
    """The same line Settings -> Diagnostics copies, from `common/log.js`."""
    stamp = ""
    when = entry.get("t")
    if isinstance(when, (int, float)):
        from datetime import datetime, timezone

        stamp = datetime.fromtimestamp(when / 1000, timezone.utc).strftime(
            "%H:%M:%S.%f"
        )[:-3]
    payload = ""
    if "data" in entry:
        payload = " " + json.dumps(entry["data"], separators=(",", ":"), default=str)
    return (
        f"{stamp} {str(entry.get('level', '')):5} "
        f"{str(entry.get('scope', '')):10} {entry.get('event', '')}{payload}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--profile", help="Profile directory; default is the newest.")
    parser.add_argument("--grep", help="Only lines matching this (case-insensitive).")
    parser.add_argument("--level", choices=("debug", "info", "warn", "error"),
                        help="Only this level and worse.")
    parser.add_argument("--last", type=int, help="Only the last N lines.")
    parser.add_argument("--json", action="store_true", help="Emit raw entries.")
    args = parser.parse_args()

    try:
        profile = find_profile(args.profile)
        entries = read_entries(find_store(profile))
    except Unreadable as error:
        print(f"cannot read the log: {error}", file=sys.stderr)
        return 1

    order = ("debug", "info", "warn", "error")
    if args.level:
        floor = order.index(args.level)
        entries = [e for e in entries
                   if e.get("level") in order[floor:]]
    lines = [format_entry(entry) for entry in entries]
    if args.grep:
        needle = args.grep.lower()
        keep = [i for i, line in enumerate(lines) if needle in line.lower()]
        entries = [entries[i] for i in keep]
        lines = [lines[i] for i in keep]
    if args.last:
        entries, lines = entries[-args.last:], lines[-args.last:]

    if args.json:
        print(json.dumps(entries, indent=2, default=str))
        return 0
    print(f"# {profile.name}: {len(lines)} entries", file=sys.stderr)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
