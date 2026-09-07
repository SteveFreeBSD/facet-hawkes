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
* An object that appears more than once in the same value is written once and
  referred back to by position afterwards, so the reader keeps the table of
  objects it has opened and resolves those references through it.
* A row's key is stored in IndexedDB's own order-preserving encoding rather
  than as itself, so it is decoded too -- without it there is no way to say
  which `storage.local` key a row holds.

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
TAG_BACK_REFERENCE_OBJECT = 0xFFFF000D
TAG_END_OF_KEYS = 0xFFFF0013
TAG_NULL = 0xFFFF0000
TAG_UNDEFINED = 0xFFFF0001
TAG_FLOOR = 0xFFF00000  # anything below this is a NaN-boxed double

# dom/indexedDB/Key.cpp. IndexedDB does not store a row's key as itself; it
# stores an encoding that sorts the way the spec requires -- a type byte, then
# the key. Every `storage.local` key is a string, whose characters up to 0x7E
# are each stored one greater than they are.
KEY_TYPE_STRING = 0x30
KEY_ONE_BYTE_ADJUST = 1


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
                count = int.from_bytes(data[pos : pos + width], "little") + 1
                pos += width
            out += data[pos : pos + count]
            pos += count
            continue
        if kind == 1:
            count = 4 + ((tag >> 2) & 0x07)
            offset = ((tag >> 5) << 8) | data[pos]
            pos += 1
        elif kind == 2:
            count = (tag >> 2) + 1
            offset = int.from_bytes(data[pos : pos + 2], "little")
            pos += 2
        else:
            count = (tag >> 2) + 1
            offset = int.from_bytes(data[pos : pos + 4], "little")
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
        # Every object and array in the order it was opened. Firefox writes a
        # repeated object once and refers back to it by position in this
        # table, so the table is the only way to read the second appearance.
        self.objects: list = []

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
        chars = self.raw[self.pos : self.pos + width]
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
        if tag == TAG_BACK_REFERENCE_OBJECT:
            return self.backreference(data)
        raise Unreadable(f"unhandled structured-clone tag 0x{tag:08X}")

    def backreference(self, index: int):
        """An object that has already been read, named by its position.

        An index the table cannot answer means these bytes are not the clone
        they claim to be. Returning anything at that point -- an empty object,
        the nearest entry -- would put a line in a diagnostic log that the
        browser never wrote, so this stops instead.
        """
        if index >= len(self.objects):
            raise Unreadable(
                f"structured-clone back reference to object {index}, "
                f"but only {len(self.objects)} have been read"
            )
        return self.objects[index]

    def collection(self, *, as_list: bool):
        """Read key/value pairs until the end marker; arrays key by index.

        The container joins the object table before its children are read,
        which is the order SpiderMonkey numbers back references in. Filling it
        afterwards would shift every index a nested object refers to, and a
        child that refers back to something already open -- an ancestor, or an
        earlier sibling that contains one -- would resolve to the wrong value.
        """
        container: list | dict = [] if as_list else {}
        self.objects.append(container)
        indexed: dict = {}
        while True:
            data, tag = self.pair()
            if tag == TAG_END_OF_KEYS:
                break
            key = self.value(data, tag)
            data, tag = self.pair()
            value = self.value(data, tag)
            if as_list:
                indexed[key] = value
            else:
                container[key] = value
        if as_list:
            container.extend(indexed[k] for k in sorted(indexed, key=lambda k: int(k)))
        return container

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
        (profile / "storage" / "default").glob(f"moz-extension+++{uuid}*/idb/*.sqlite")
    )
    if not found:
        raise Unreadable("the add-on has written no storage yet")
    return max(found, key=lambda path: path.stat().st_size)


def decode_key(raw: bytes) -> str:
    """The `storage.local` name a row was stored under.

    The add-on writes ASCII identifiers -- `diagnostics`, `failures`,
    `facetLastSeen` -- so only the one-byte form is decoded here. A key using
    the multi-byte forms, or one that is not a string at all, is refused
    rather than approximated: a name that comes out nearly right would attach
    the wrong value to it, and a caller asking for the ledger would be handed
    something else without ever being told.
    """
    if not raw or raw[0] != KEY_TYPE_STRING:
        raise Unreadable(
            f"storage key {raw.hex()} is not an IndexedDB string key; "
            "this is not the add-on's storage"
        )
    body = raw[1:]
    if any(byte == 0 or byte & 0x80 for byte in body):
        raise Unreadable(
            f"storage key {raw.hex()} is not a plain ASCII name; "
            "refusing to guess at which key it is"
        )
    return bytes(byte - KEY_ONE_BYTE_ADJUST for byte in body).decode("ascii")


def decode_rows(store: Path) -> list[tuple[str, object]]:
    """Every row in the store as the key it was stored under and its value.

    Copies the database first: Firefox may be running and holding it. Reading
    a live profile through a copy is what makes every tool built on this one
    safe to point at the owner's session mid-question.
    """
    with tempfile.TemporaryDirectory(prefix="ethnos-log-") as work:
        copy = Path(work) / "store.sqlite"
        shutil.copy(store, copy)
        rows = (
            sqlite3.connect(copy).execute("select key, data from object_data").fetchall()
        )

    decoded: list[tuple[str, object]] = []
    for key, blob in rows:
        if not blob:
            continue
        decoded.append((decode_key(bytes(key)), Clone(snappy_decompress(bytes(blob))).read()))
    return decoded


def decode_values(store: Path) -> list:
    """Every value in the store, decoded, for callers that search rather than
    ask by name."""
    return [value for _, value in decode_rows(store)]


def read_storage(store: Path) -> dict:
    """`storage.local` under the names the add-on stored it under.

    The ring is one key in there; preferences and the retained failure ledger
    are others. Each is its own row, so this reads the row keys rather than
    merging the values together -- merging loses exactly the thing a caller
    comes here for, which is which key a value was stored under.
    """
    return dict(decode_rows(store))


def read_entries(store: Path) -> list[dict]:
    """The diagnostic ring, oldest first, wherever storage nested it."""
    entries: list[dict] = []
    for value in decode_values(store):
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
    parser.add_argument(
        "--level",
        choices=("debug", "info", "warn", "error"),
        help="Only this level and worse.",
    )
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
        entries = [e for e in entries if e.get("level") in order[floor:]]
    lines = [format_entry(entry) for entry in entries]
    if args.grep:
        needle = args.grep.lower()
        keep = [i for i, line in enumerate(lines) if needle in line.lower()]
        entries = [entries[i] for i in keep]
        lines = [lines[i] for i in keep]
    if args.last:
        entries, lines = entries[-args.last :], lines[-args.last :]

    if args.json:
        print(json.dumps(entries, indent=2, default=str))
        return 0
    print(f"# {profile.name}: {len(lines)} entries", file=sys.stderr)
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
