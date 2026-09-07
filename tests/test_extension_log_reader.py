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
    assert (
        reader.snappy_decompress(_literal(b"event-page-loaded")) == b"event-page-loaded"
    )


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
        _pair(3, 0xFFF10000)  # header
        + _pair(0, reader.TAG_OBJECT)
        + _string("level")
        + _string("warn")
        + _string("scope")
        + _string("background")
        + _string("event")
        + _string("failed")
        + _string("seq")
        + _pair(7, reader.TAG_INT32)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    assert reader.Clone(clone).read() == {
        "level": "warn",
        "scope": "background",
        "event": "failed",
        "seq": 7,
    }


def _int(value: int) -> bytes:
    return _pair(value, reader.TAG_INT32)


def _backref(index: int) -> bytes:
    return _pair(index, reader.TAG_BACK_REFERENCE_OBJECT)


def test_an_object_that_appears_twice_is_read_back_from_the_table():
    """Firefox writes a repeated object once and points at it afterwards. A
    ledger group and the runs inside it share their fingerprint object, so
    this is the ordinary shape of the stored value, not an exotic one."""
    clone = (
        _pair(3, 0xFFF10000)  # header -- object 0 is the outer object
        + _pair(0, reader.TAG_OBJECT)
        + _string("first")
        + _pair(0, reader.TAG_OBJECT)  # object 1
        + _string("code")
        + _string("refused")
        + _pair(0, reader.TAG_END_OF_KEYS)
        + _string("second")
        + _backref(1)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    decoded = reader.Clone(clone).read()

    assert decoded == {"first": {"code": "refused"}, "second": {"code": "refused"}}
    # The same object, as it was in the browser -- not a second copy.
    assert decoded["first"] is decoded["second"]


def test_an_array_element_can_refer_back_to_an_object_outside_it():
    """The table is numbered across the whole value, so an index counts
    containers opened before this one as well as inside it."""
    clone = (
        _pair(3, 0xFFF10000)
        + _pair(0, reader.TAG_OBJECT)  # object 0
        + _string("group")
        + _pair(0, reader.TAG_OBJECT)  # object 1
        + _string("kind")
        + _string("field-refused")
        + _pair(0, reader.TAG_END_OF_KEYS)
        + _string("runs")
        + _pair(0, reader.TAG_ARRAY)  # object 2
        + _int(0)
        + _backref(1)
        + _int(1)
        + _backref(1)
        + _pair(0, reader.TAG_END_OF_KEYS)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    decoded = reader.Clone(clone).read()

    assert decoded["runs"] == [{"kind": "field-refused"}, {"kind": "field-refused"}]
    assert decoded["runs"][0] is decoded["group"]
    assert decoded["runs"][1] is decoded["group"]


def test_an_array_is_in_the_table_before_the_elements_it_contains():
    """Registering a container only once it is complete would number every
    object inside it one too low, and each reference would then resolve to
    whatever happened to be read just before the value it names."""
    clone = (
        _pair(3, 0xFFF10000)
        + _pair(0, reader.TAG_ARRAY)  # object 0
        + _int(0)
        + _pair(0, reader.TAG_OBJECT)  # object 1
        + _string("run")
        + _string("r2f8xk91c4")
        + _pair(0, reader.TAG_END_OF_KEYS)
        + _int(1)
        + _backref(1)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    decoded = reader.Clone(clone).read()

    assert decoded == [{"run": "r2f8xk91c4"}, {"run": "r2f8xk91c4"}]
    assert decoded[0] is decoded[1]


def test_a_reference_to_an_object_that_was_never_read_is_refused():
    """Fail closed. A back reference past the end of the table means the bytes
    are not the clone they claim to be, and inventing an entry there would put
    a line in a diagnostic log that the browser never wrote."""
    clone = (
        _pair(3, 0xFFF10000)
        + _pair(0, reader.TAG_OBJECT)  # object 0, and the only one
        + _string("failure")
        + _backref(4)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    with pytest.raises(reader.Unreadable, match="back reference to object 4"):
        reader.Clone(clone).read()


def test_a_reference_to_an_object_still_being_opened_is_refused():
    """The first container is index 0, so index 1 inside it names something
    that has not been reached yet."""
    clone = (
        _pair(3, 0xFFF10000)
        + _pair(0, reader.TAG_OBJECT)  # object 0
        + _string("self")
        + _backref(1)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )

    with pytest.raises(reader.Unreadable, match="only 1 have been read"):
        reader.Clone(clone).read()


def test_each_value_gets_its_own_table():
    """`storage.local` is several rows, each its own clone. Indexes from one
    row must not resolve against objects decoded from another."""
    row = (
        _pair(3, 0xFFF10000)
        + _pair(0, reader.TAG_OBJECT)
        + _string("seq")
        + _int(1)
        + _pair(0, reader.TAG_END_OF_KEYS)
    )
    reader.Clone(row).read()

    with pytest.raises(reader.Unreadable):
        reader.Clone(
            _pair(3, 0xFFF10000) + _pair(0, reader.TAG_OBJECT)
            + _string("borrowed")
            + _backref(1)
            + _pair(0, reader.TAG_END_OF_KEYS)
        ).read()


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
