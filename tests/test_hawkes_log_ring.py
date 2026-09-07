"""Two contexts, one ring, and the entries that used to fall out of it.

`common/log.js` appends to one `storage.local` key by read-modify-write, and
its `flushing` promise serialises that only within a single context. Each
context loads its own copy of the module, so the event page and the panel hold
different promises and neither excludes the other: both read the same array,
both append their own batch, and the second write overwrites the first.

Live, on 2026-09-07, that cost a diagnosis. The event page logged `solved`,
`answer-retained` and `answer-not-insertable`; the panel logged `panel-rendered`
a few milliseconds later; and the stored ring came back with `seq` running
9, 13 and 15, 19 -- three of the background's entries missing from each gap.
Read back, that log said a solve had produced no answer at all, and the defect
it pointed at had not happened.

Both contexts are modelled here against one shared fake storage whose reads and
writes really do interleave, so the loss is reproducible and the fix is
demonstrable rather than asserted.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_JS = PROJECT_ROOT / "extension" / "common" / "log.js"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

#: One shared page world: storage both contexts write to, a clock, and stubs
#: for the things a module loaded outside a browser still reaches for.
WORLD = """
globalThis.__store = {};
globalThis.console = {log(){}, warn(){}, error(){}};
// Timers are never allowed to drive a flush here; each one is asked for
// explicitly, so the interleaving under test is the one written down.
globalThis.setTimeout = () => 0;
globalThis.clearTimeout = () => {};
// A read and a write that each take a couple of turns, which is what lets two
// contexts both read before either writes -- the whole shape of a lost update.
const settle = () => Promise.resolve().then(() => {}).then(() => {});
globalThis.browser = {
  storage: {
    local: {
      async get(key) { await settle(); return {[key]: globalThis.__store[key]}; },
      async set(pairs) { await settle(); Object.assign(globalThis.__store, pairs); },
      async remove(key) { await settle(); delete globalThis.__store[key]; },
    },
  },
};
"""

#: The Web Locks API, with the one guarantee this depends on: exclusive by
#: name, and queued rather than refused.
LOCKS = """
globalThis.navigator = {
  locks: {
    _chain: Promise.resolve(),
    request(name, work) {
      const run = this._chain.then(() => work());
      this._chain = run.then(() => {}, () => {});
      return run;
    },
  },
};
"""


def context(*, locks: bool):
    """A world holding two independent copies of the module, as two pages do."""
    source = LOG_JS.read_text()
    # No module loader here, so each context becomes a closure returning the
    # handful of names this test drives. Two of them share the world above,
    # exactly as the event page and the panel share one origin.
    body = re.sub(r"^export ", "", source, flags=re.MULTILINE)
    factory = (
        "globalThis.makeContext = () => {\n"
        + body
        + "\n  return {log, flushLog, readLog};\n};"
    )
    js = quickjs.Context()
    js.eval(WORLD)
    if locks:
        js.eval(LOCKS)
    js.eval(factory)
    return js


def drain(js):
    """Run every queued job to completion."""
    for _ in range(20000):
        if not js.execute_pending_job():
            break


def stored_events(js) -> list[str]:
    raw = js.eval("JSON.stringify(globalThis.__store.diagnostics ?? [])")
    return [entry["event"] for entry in json.loads(raw)]


#: What the event page wrote, and what the panel wrote a moment later.
BACKGROUND_EVENTS = ["solved", "answer-retained", "answer-not-insertable"]
PANEL_EVENT = "panel-rendered"


def run_both(js) -> list[str]:
    """Both contexts log, then both flush, with their writes interleaved."""
    js.eval("globalThis.A = makeContext(); globalThis.B = makeContext();")
    for event in BACKGROUND_EVENTS:
        js.eval(f"A.log.info({json.dumps(event)})")
    js.eval(f"B.log.info({json.dumps(PANEL_EVENT)})")
    js.eval("globalThis.done = Promise.all([A.flushLog(), B.flushLog()]);")
    drain(js)
    return stored_events(js)


def test_without_a_shared_lock_one_contexts_entries_are_lost() -> None:
    """The live defect, reproduced: the panel's write erases the event page's.

    This is what the stored ring actually looked like on 2026-09-07 -- and why
    `solved` was missing from a run that had certainly solved.
    """
    kept = run_both(context(locks=False))

    assert PANEL_EVENT in kept
    assert [event for event in BACKGROUND_EVENTS if event in kept] == []


def test_a_shared_lock_keeps_every_entry_both_contexts_wrote() -> None:
    """The fix, against the same interleaving."""
    kept = run_both(context(locks=True))

    for event in [*BACKGROUND_EVENTS, PANEL_EVENT]:
        assert event in kept, event
    assert len(kept) == len(BACKGROUND_EVENTS) + 1


def test_the_entries_still_read_back_in_the_order_they_happened() -> None:
    """Ordering was never the problem, and must not become one."""
    js = context(locks=True)
    kept = run_both(js)

    raw = json.loads(js.eval("JSON.stringify(globalThis.__store.diagnostics)"))
    stamps = [(entry["t"], entry["seq"]) for entry in raw]
    assert stamps == sorted(stamps)
    assert kept[-1] == PANEL_EVENT or kept[0] in BACKGROUND_EVENTS


def test_logging_still_works_where_the_browser_has_no_lock_api() -> None:
    """An unlocked append still beats refusing to log."""
    js = context(locks=False)
    js.eval("globalThis.A = makeContext();")
    js.eval("A.log.info('solved')")
    js.eval("globalThis.done = A.flushLog();")
    drain(js)

    assert stored_events(js) == ["solved"]


def test_the_ring_is_still_bounded() -> None:
    """The lock must not turn a bounded ring into an unbounded one."""
    js = context(locks=True)
    js.eval("globalThis.A = makeContext();")
    js.eval("for (let n = 0; n < 250; n += 1) { A.log.info('tick'); }")
    js.eval("globalThis.done = A.flushLog();")
    drain(js)

    limit = int(
        re.search(r"RING_LIMIT = (\d+)", LOG_JS.read_text()).group(1)
    )
    assert len(stored_events(js)) == limit


def test_the_lock_is_named_once_and_shared_by_every_context() -> None:
    """One origin, one name; a per-context name would exclude nobody."""
    source = LOG_JS.read_text()

    assert 'export const LOG_LOCK_NAME = "ethnos:diagnostics";' in source
    assert "navigator?.locks" in source
    assert "locks.request(LOG_LOCK_NAME" in source
