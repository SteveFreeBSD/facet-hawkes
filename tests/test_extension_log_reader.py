"""Decoding the add-on's diagnostic ring out of a Firefox profile.

Settings -> Diagnostics -> Copy stays the supported path. This reader exists
for triage: reading the log without asking the person using the browser to stop
and fetch it. It decodes two formats by hand -- raw Snappy, and the subset of
Firefox's structured clone the log uses -- so both are pinned here.
"""

from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "read_extension_log.py"
spec = importlib.util.spec_from_file_location("read_extension_log", SCRIPT)
reader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reader)


def _literal(payload: bytes) -> bytes:
    """A Snappy stream of one literal, which is the simplest valid encoding."""
    assert len(payload) < 60
    return bytes([len(payload), (len(payload) - 1) << 2]) + payload


def test_snappy_reads_a_plain_literal():
    assert reader.snappy_decompress(_literal(b"event-page-loaded")) == b"event-page-loaded"


def test_snappy_follows_a_back_reference():
    """Copies are why a regex over the compressed bytes returns fragments: the
    repeated text is a pointer, not characters."""
    # Literal "abcd", then copy 4 bytes from offset 4 -> "abcdabcd".
    stream = bytes([8, (4 - 1) << 2]) + b"abcd" + bytes([0x01 | ((4 - 4) << 2), 4])

    assert reader.snappy_decompress(stream) == b"abcdabcd"


def test_snappy_refuses_a_stream_that_does_not_produce_its_declared_length():
    with pytest.raises(reader.Unreadable):
        reader.snappy_decompress(bytes([99, (4 - 1) << 2]) + b"abcd")


def _pair(data: int, tag: int) -> bytes:
    return struct.pack("<II", data, tag)


def _string(text: str) -> bytes:
    raw = text.encode("latin-1")
    padded = raw + b"\0" * ((-len(raw)) % 8)
    return _pair(0x80000000 | len(raw), reader.TAG_STRING) + padded


def test_a_log_entry_decodes_to_its_fields():
    """One entry, shaped exactly as `common/log.js` writes it."""
    clone = (
        _pair(3, 0xFFF10000)                       # header
        + _pair(0, reader.TAG_OBJECT)
        + _string("level") + _string("warn")
        + _string("scope") + _string("background")
        + _string("event") + _string("failed")
        + _string("seq") + _pair(7, reader.TAG_INT32)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    assert reader.Clone(clone).read() == {
        "level": "warn", "scope": "background", "event": "failed", "seq": 7,
    }


def test_an_unknown_tag_is_reported_rather_than_guessed_at():
    """Only the tags this log contains are handled. A silently wrong decode of
    a diagnostic log is worse than no decode."""
    clone = _pair(3, 0xFFF10000) + _pair(0, 0xFFFF00FF)

    with pytest.raises(reader.Unreadable, match="unhandled structured-clone tag"):
        reader.Clone(clone).read()


def test_entries_are_ordered_by_time_not_by_sequence():
    """`seq` restarts whenever the non-persistent event page is unloaded, so
    ordering by it interleaves separate sessions into nonsense."""
    source = SCRIPT.read_text()

    assert 'entries.sort(key=lambda entry: (entry.get("t", 0)' in source


def test_the_running_browser_is_never_disturbed():
    """It reads a profile on disk and nothing else: no launch, no connection,
    and a copy of the database so a live Firefox keeps its lock."""
    source = SCRIPT.read_text()

    assert "shutil.copy(store, copy)" in source
    for forbidden in ("Popen", "marionette", "webdriver", "requests"):
        assert forbidden not in source
