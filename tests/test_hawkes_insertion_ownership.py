"""The event page's insertion, executed, against a second window taking over.

Every other `background.js` test reads the file as text. That is enough for
"does this call exist" and useless for "what happens when two things interleave"
-- and interleaving is exactly where the wrong-target insertion lived: an
insertion begun for window A could be pointed at window B while it was awaiting,
then validate B's question against B's signature, agree with itself, and write
A's reviewed answer into B's answer box.

So this runs the real `background.js` under QuickJS with a fake `browser` and a
pumped job queue, and drives the sequence that produced it.

The modules are concatenated rather than imported because QuickJS here has no
module loader. That also puts every top-level declaration in one scope, which is
what lets the scenario call `insert()` and `prepare()` directly and stop between
their awaits -- and why everything the harness owns lives on one `__H` object
rather than as bare globals, `log.js` having its own `pending` and `timers`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION = PROJECT_ROOT / "extension"

quickjs = pytest.importorskip("quickjs", reason="pip install quickjs")

IMPORT_LINE = re.compile(r"^import\s[\s\S]*?;\s*$", re.MULTILINE)

# Dependency order. `background.js` last; it declares the functions under test.
MODULES = (
    "common/config.js",
    "common/log.js",
    "common/build-marker.js",
    "common/answer-session.js",
    "common/editor-rules.js",
    "common/editor-plan.js",
    "common/failure-record.js",
    "common/frames.js",
    "common/cadence.js",
    "common/cadence-audio.js",
    "common/cadence-session.js",
    "common/transport.js",
    "common/page-actions.js",
    "common/table-actions.js",
    "common/graph-actions.js",
    "common/settings.js",
    "background.js",
)

HARNESS = """
globalThis.__H = {
  timers: [], calls: [], pending: [], logged: [], localStored: {}, intervals: [],
};
const __H = globalThis.__H;

// The question watcher runs on an interval. Held rather than fired, so a test
// drives exactly one tick and settles its reads itself -- the same contract
// the injection mock below keeps.
globalThis.setInterval = (fn, ms) => {
  __H.intervals.push({ id: __H.intervals.length + 1, fn, ms: ms || 0 });
  return __H.intervals.length;
};
globalThis.clearInterval = (id) => {
  const keep = __H.intervals.filter((entry) => entry.id !== id);
  __H.intervals.length = 0;
  for (const entry of keep) { __H.intervals.push(entry); }
};
__H.tick = () => {
  for (const entry of [...__H.intervals]) { entry.fn(); }
  return __H.intervals.length;
};

// Timers carry their delay so the pump can run the short retry sleeps without
// firing the 15-second injection deadline, which would abort every held call.
globalThis.setTimeout = (fn, ms) => __H.timers.push({ fn, ms: ms || 0 });
globalThis.clearTimeout = () => {};
__H.runShortTimers = () => {
  const keep = [];
  let fired = 0;
  for (const timer of __H.timers) {
    if (timer.ms <= 1000) { timer.fn(); fired += 1; } else { keep.push(timer); }
  }
  __H.timers.length = 0;
  for (const timer of keep) { __H.timers.push(timer); }
  return fired;
};

globalThis.crypto = { randomUUID: () => "test-uuid", getRandomValues: (a) => a };
globalThis.performance = { now: () => 0 };
// `log.js` mirrors every entry to the console. Without this the first log call
// throws into a rejected promise and the failure looks like silence.
globalThis.console = {
  log: () => {}, info: () => {}, warn: () => {}, error: () => {}, debug: () => {},
};
// Enough of `URL` for the one site check. QuickJS has no URL, and without this
// every tab reads as the wrong site.
globalThis.URL = class {
  constructor(href) {
    const match = /^([a-z]+:)\\/\\/([^/?#]+)/i.exec(String(href));
    if (!match) { throw new TypeError("invalid url"); }
    this.href = String(href);
    this.protocol = match[1].toLowerCase();
    this.hostname = match[2].split(":")[0].toLowerCase();
  }
};
// `initLog` attaches its crash handlers to the worker global.
globalThis.self = globalThis;
globalThis.addEventListener = () => {};

__H.tabWindow = { 11: 1, 22: 2 };
__H.windowTab = { 1: 11, 2: 22 };

globalThis.browser = {
  runtime: {
    onConnect: { addListener: () => {} },
    getManifest: () => ({ version: "test" }),
  },
  storage: {
    // A real store, not a stub. The event page keeps its bounded ledger of
    // failed runs in `storage.local`, and a harness that swallowed every write
    // would let a test assert a record was kept when nothing was written.
    local: {
      get: (key) => Promise.resolve(
        Object.prototype.hasOwnProperty.call(__H.localStored, key)
          ? { [key]: __H.localStored[key] }
          : {}
      ),
      set: (patch) => { Object.assign(__H.localStored, patch); return Promise.resolve(); },
      remove: (key) => { delete __H.localStored[key]; return Promise.resolve(); },
    },
    session: {
      get: (key) => Promise.resolve(
        Object.prototype.hasOwnProperty.call(__H.sessionStored, key)
          ? { [key]: __H.sessionStored[key] }
          : {}
      ),
      set: (patch) => { Object.assign(__H.sessionStored, patch); return Promise.resolve(); },
      remove: (key) => { delete __H.sessionStored[key]; return Promise.resolve(); },
    },
    onChanged: { addListener: () => {} },
  },
  permissions: { contains: () => Promise.resolve(true) },
  windows: { onRemoved: { addListener: () => {} } },
  tabs: {
    onActivated: { addListener: () => {} },
    onAttached: { addListener: () => {} },
    onDetached: { addListener: () => {} },
    onRemoved: { addListener: () => {} },
    onUpdated: { addListener: () => {} },
    // `active` as Firefox reports it: whether this is the tab its window shows.
    get: (id) => Promise.resolve({
      id, windowId: __H.tabWindow[id], active: __H.windowTab[__H.tabWindow[id]] === id,
    }),
    query: ({ windowId }) => Promise.resolve([
      { id: __H.windowTab[windowId], windowId,
        url: "https://learn.hawkeslearning.com/Portal/Lesson/lesson_practice" },
    ]),
    captureVisibleTab: () => Promise.resolve(""),
  },
  scripting: {
    // Never resolves on its own: the scenario decides when the page answers,
    // which is what holds an insertion open between its awaits.
    executeScript: (injection) => {
      const frames = injection.target.frameIds;
      const record = {
        tabId: injection.target.tabId,
        frameId: Array.isArray(frames) ? frames[0] : null,
        file: (injection.files || []).join(","),
        func: injection.func ? injection.func.name : "",
        // Which world the injection asked for. The page's own model lives in
        // one of them and nowhere else, so this is not a detail.
        world: injection.world || "isolated",
        args: injection.args || [],
      };
      __H.calls.push(record);
      return new Promise((resolve) => __H.pending.push({ record, resolve }));
    },
  },
};

__H.settleAll = (result) => {
  const outstanding = __H.pending.splice(0, __H.pending.length);
  for (const entry of outstanding) {
    entry.resolve([{ frameId: entry.record.frameId ?? 0, result }]);
  }
  return outstanding.length;
};

// Answer only the injections aimed at one tab. Letting B's prepare run to
// completion while A stays parked is what reproduces the defect: A then
// resumes into a state that fully describes B.
__H.settleFor = (tabId, result) => {
  const keep = [];
  const matched = [];
  for (const entry of __H.pending) {
    (entry.record.tabId === tabId ? matched : keep).push(entry);
  }
  __H.pending.length = 0;
  for (const entry of keep) { __H.pending.push(entry); }
  for (const entry of matched) {
    entry.resolve([{ frameId: entry.record.frameId ?? 0, result }]);
  }
  return matched.length;
};
"""

CAPTURE_LOG = """
for (const level of ["error", "warn", "info", "debug"]) {
  const original = log[level];
  log[level] = (event, data) => {
    __H.logged.push({ level, event, data: data || {} });
    return original(event, data);
  };
}
"""

INSPECT_OK = {"ready": True, "code": "focused-answer-field", "fieldId": "txtAns1"}
EDITOR_OK = {
    "ok": True,
    "code": "described",
    "kind": "dynamic",
    "enabled": True,
    "allowedCharacters": "0123456789y",
    "maxLength": 16,
    "slots": {"base": "0123456789y"},
    "templates": {
        "fraction": False,
        "radical": False,
        "exponent": False,
        "parentheses": False,
        "absoluteValue": False,
    },
}
QUESTION_A = {"promptText": "Question A.", "expressions": ["a^2"]}
QUESTION_B = {"promptText": "Question B.", "expressions": ["b^2"]}
ENTERED_OK = {
    "ok": True,
    "code": "entered",
    "entered": "3y",
    "transport": "hawkes-dynamic-keypad",
}
#: A question whose several answers are plain boxes rather than dynamic ones.
#: Its parts are typed into the boxes as they stand, each through the control
#: the page has selected, by the page-world writer a completion table shares.
PLAIN_FIELD_EDITOR = {
    **EDITOR_OK,
    "kind": "textbox",
    "allowedCharacters": "0123456789-",
}
PAIR_INSPECT = {
    "ready": True,
    "code": "multi-answer-fields",
    "fieldId": "QBase1_input\u001fQBase2_input",
    "fieldIds": ["QBase1_input", "QBase2_input"],
}
PAIR_EDITOR = {
    "ok": True,
    "code": "described-multi",
    "kind": "multi",
    "editors": [PLAIN_FIELD_EDITOR, PLAIN_FIELD_EDITOR],
}
#: The same two-field question, drawn with Hawkes' dynamic editors instead.
#: Both parts are directly typeable and both still go through the editor.
DYNAMIC_PAIR_EDITOR = {
    "ok": True,
    "code": "described-multi",
    "kind": "multi",
    "editors": [
        {**EDITOR_OK, "allowedCharacters": "0123456789-"},
        {**EDITOR_OK, "allowedCharacters": "0123456789-"},
    ],
}
PAIR_ENTERED = {
    "ok": True,
    "code": "entered-answer-fields",
    "fields": ["QBase1_input", "QBase2_input"],
    "settled": 2,
    "models": 2,
}
FOUR_FIELD_IDS = [f"QBase{index}_input" for index in range(1, 5)]
FOUR_INSPECT = {
    "ready": True,
    "code": "multi-answer-fields",
    "fieldId": "\u001f".join(FOUR_FIELD_IDS),
    "fieldIds": FOUR_FIELD_IDS,
}
FOUR_EDITOR = {
    "ok": True,
    "code": "described-multi",
    "kind": "multi",
    "editors": [PLAIN_FIELD_EDITOR for _ in range(4)],
}
FOUR_ENTERED = {
    "ok": True,
    "code": "entered-answer-fields",
    "fields": FOUR_FIELD_IDS,
    "settled": 4,
    "models": 4,
}
STRUCTURED_PAIR_EDITOR = {
    "ok": True,
    "code": "described-multi",
    "kind": "multi",
    "editors": [
        {
            **EDITOR_OK,
            "allowedCharacters": "+-0123456789i",
            "slots": {
                "base": "+-0123456789i",
                "numerator": "+-0123456789i",
                "denominator": "0123456789",
            },
            "templates": {**EDITOR_OK["templates"], "fraction": True},
        },
        {
            **EDITOR_OK,
            "allowedCharacters": "+-0123456789i",
            "slots": {
                "base": "+-0123456789i",
                "numerator": "+-0123456789i",
                "denominator": "0123456789",
            },
            "templates": {**EDITOR_OK["templates"], "fraction": True},
        },
    ],
}
COMMA_EDITOR = {
    **EDITOR_OK,
    "allowedCharacters": "0123456789-+,",
    "slots": {
        "base": "0123456789-+,",
        "numerator": "0123456789-+",
        "denominator": "0123456789",
        "radicand": "0123456789",
    },
    "templates": {**EDITOR_OK["templates"], "fraction": True, "radical": True},
}


class Page:
    """The running event page, plus the levers the scenario needs."""

    def __init__(self, context):
        self.context = context

    def run(self, script):
        return self.context.eval(script)

    def json(self, expression):
        return json.loads(self.context.eval(f"JSON.stringify({expression})"))

    def pump(self):
        """Settle microtasks, firing only the short retry sleeps."""
        for _ in range(200):
            while self.context.execute_pending_job():
                pass
            if not self.context.eval("__H.runShortTimers()"):
                break
        while self.context.execute_pending_job():
            pass

    def answer(self, result):
        """Let every held injection return `result`, then settle."""
        self.run(f"__H.settleAll({json.dumps(result)});")
        self.pump()

    def answer_tab(self, tab_id, result):
        """Answer only the injections aimed at one tab, then settle."""
        settled = self.run(f"__H.settleFor({tab_id}, {json.dumps(result)});")
        self.pump()
        return settled

    def own_window_a(self, answer="3y"):
        """Put window A in the state a reviewed answer leaves behind."""
        self.run(
            f"""
            state = {{
              ...blankState(),
              phase: "solved",
              windowId: 1, tabId: 11, frameId: 0, fieldId: "txtAns1",
              editor: {json.dumps(EDITOR_OK)},
              answer: {json.dumps(answer)},
              displayText: {json.dumps(answer)},
              entryText: {json.dumps(answer)},
              signature: questionSignature({json.dumps(QUESTION_A)}),
            }};
            """
        )

    @property
    def writes(self):
        """Injections that actually change a page: the two entry functions."""
        return [
            call
            for call in self.json("__H.calls")
            if call["func"] in {"enterPlainAnswer", "enterPlan"}
            or call["func"] == "enterOwnedFields"
        ]

    def said(self, event):
        return [row for row in self.json("__H.logged") if row.get("event") == event]


def make_page(session_storage=None):
    source = "\n".join(
        IMPORT_LINE.sub("", (EXTENSION / name).read_text()).replace("export ", "")
        for name in MODULES
    )
    context = quickjs.Context()
    context.eval(HARNESS)
    context.eval(f"__H.sessionStored = {json.dumps(session_storage or {})};")
    context.eval(source)
    context.eval(CAPTURE_LOG)
    return Page(context)


@pytest.fixture
def page():
    return make_page()


def remembered_session(page):
    """Store the fixture's solved state through the shipped update path."""
    page.own_window_a()
    page.run("update({});")
    page.pump()
    stored = page.json("__H.sessionStored")
    assert stored["answerSession"]["state"]["answer"] == "3y"
    return stored


def test_the_harness_actually_runs_the_event_page(page):
    """Guards the rest: a harness that silently failed to load would make every
    "nothing was written" assertion below pass for the wrong reason."""
    page.own_window_a()
    assert page.json("state.phase") == "solved"

    page.run("insert();")
    page.pump()

    assert page.json("state.phase") == "inserting"
    assert page.json("__H.calls.length") >= 1, "insert() reached the page"


def test_an_undisturbed_insertion_writes_to_its_own_target(page):
    """The invariant must not be upheld by refusing everything."""
    page.own_window_a()
    page.run("insert();")
    page.pump()
    page.answer(EDITOR_OK)  # describeEditor
    page.answer(QUESTION_A)  # the signature re-check
    page.answer(ENTERED_OK)  # the entry itself, in the page's own world
    page.answer(QUESTION_A)  # finishInsertion's rebase read

    assert page.writes, "an undisturbed insertion wrote nothing"
    assert all(w["tabId"] == 11 and w["frameId"] == 0 for w in page.writes)
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == "3y"


def test_a_restarted_event_page_restores_only_after_the_live_question_matches(page):
    restarted = make_page(remembered_session(page))

    restarted.run("prepare(1);")
    restarted.pump()
    restarted.answer(INSPECT_OK)
    restarted.answer(EDITOR_OK)
    restarted.answer(QUESTION_A)

    assert restarted.json("state.phase") == "solved"
    assert restarted.json("state.answer") == "3y"
    assert restarted.json("state.displayText") == "3y"
    assert restarted.writes == [], "restoring an answer must never touch Hawkes"
    assert restarted.said("answer-session-restored")


def test_a_restarted_event_page_discards_an_answer_for_a_changed_question(page):
    restarted = make_page(remembered_session(page))

    restarted.run("prepare(1);")
    restarted.pump()
    restarted.answer(INSPECT_OK)
    restarted.answer(EDITOR_OK)
    restarted.answer(QUESTION_B)

    assert restarted.json("state.phase") == "ready"
    assert restarted.json("state.answer") == ""
    assert restarted.json("state.displayText") == ""
    assert restarted.json("__H.sessionStored") == {}
    assert restarted.writes == []
    discarded = restarted.said("answer-session-discarded")
    assert discarded and discarded[-1]["data"]["why"] == "question-changed"


def test_a_matching_question_in_another_tab_does_not_claim_the_answer(page):
    restarted = make_page(remembered_session(page))
    restarted.run("__H.windowTab[1] = 22;")

    restarted.run("prepare(1);")
    restarted.pump()
    restarted.answer(INSPECT_OK)
    restarted.answer(EDITOR_OK)
    restarted.answer(QUESTION_A)

    assert restarted.json("state.tabId") == 22
    assert restarted.json("state.phase") == "ready"
    assert restarted.json("state.answer") == ""
    assert restarted.json("__H.sessionStored") == {}
    assert restarted.writes == []


def test_two_roots_reach_only_the_two_fields_pinned_with_the_question(page):
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input\\u001fQBase2_input",
          fieldIds: ["QBase1_input", "QBase2_input"],
          fieldIdentity: "separated",
          editor: {json.dumps(PAIR_EDITOR)},
          answer: "y = -1 or y = 5", displayText: "y = -1 or y = 5",
          answerParts: ["-1", "5"],
          signature: questionSignature(
            {json.dumps(QUESTION_A)}
          ),
        }};
        insert();
        """
    )
    page.pump()
    page.answer(PAIR_EDITOR)
    page.answer(QUESTION_A)
    page.answer(PAIR_INSPECT)
    page.answer(PAIR_ENTERED)
    page.answer(QUESTION_A)

    writes = [call for call in page.writes if call["func"] == "enterOwnedFields"]
    assert len(writes) == 1
    assert writes[0]["tabId"] == 11
    assert writes[0]["frameId"] == 0
    assert writes[0]["args"][0] == ["-1", "5"]
    assert writes[0]["args"][1] == ["QBase1_input", "QBase2_input"]
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == "y = -1 or y = 5"

    # The page's own world, because these boxes are page-owned controls: an
    # isolated writer can focus one and cannot select it, and its parts arrive
    # cumulative and crossed between the boxes.
    assert writes[0]["world"] == "MAIN"
    assert writes[0]["args"][3] == "fields"


@pytest.mark.parametrize(
    ("pinned", "live", "why"),
    [
        ("separated", [], "the wording that joined them stopped saying so"),
        (
            "editor-corroborated",
            ["QBase1_input", "QBase2_input"],
            "wording appeared that was not there when the answer was reviewed",
        ),
    ],
)
def test_the_proof_those_boxes_are_one_answer_is_revalidated_before_the_write(
    page, pinned, live, why
):
    """Not just *which* boxes, but *how* they were shown to be one answer.

    The isolated writer used to re-derive this for itself between parts. It
    now runs in the page's own world, where the separator rule does not exist,
    so the proof is revalidated at the gate that already holds every other
    part of the pinned identity -- and a separator appearing is as much a
    change as one going.
    """
    # The same two boxes either way -- the sweep still offers them as
    # candidates when the wording is gone -- so the ids agree and the one thing
    # that moved is the proof.
    inspected = {
        **PAIR_INSPECT,
        "fieldIds": live,
        "multiFieldEvidence": {
            "fields": 2,
            "fieldIds": ["QBase1_input", "QBase2_input"],
        },
    }
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input\u001fQBase2_input",
          fieldIds: ["QBase1_input", "QBase2_input"],
          fieldIdentity: {json.dumps(pinned)},
          editor: {json.dumps(PAIR_EDITOR)},
          answer: "y = -1 or y = 5", displayText: "y = -1 or y = 5",
          answerParts: ["-1", "5"],
          signature: questionSignature(
            {json.dumps(QUESTION_A)}
          ),
        }};
        insert();
        """
    )
    page.pump()
    page.answer(PAIR_EDITOR)
    page.answer(QUESTION_A)
    page.answer(inspected)

    assert page.writes == [], why
    assert page.json("state.errorKey") == "errorQuestionChanged"
    changed = page.said("answer-fields-changed-before-insert")
    assert changed and changed[-1]["data"]["wasIdentity"] == pinned
    # Refused for the proof and nothing else: the boxes are the same two.
    assert changed[-1]["data"]["nowFields"] == ["QBase1_input", "QBase2_input"]
    assert changed[-1]["data"]["nowIdentity"] != pinned


def test_a_re_read_of_the_same_question_adopts_its_proof_with_its_fields(page):
    """The ids and the proof that they are one answer come from one read.

    A re-prepare of the same question re-reads the fields, and used to keep the
    proof from before. Fresh ids beside a held proof described no read at all:
    the insertion revalidates both against the page, so an unchanged page was
    refused as a changed question -- and every later prepare kept the same
    held proof, so nothing short of dropping the answer got it back.
    """
    pair = ["QBase1_input", "QBase2_input"]
    # The same two boxes, shown without the "or" between them: the sweep
    # offers them as candidates, and the editor model corroborates the count.
    corroborated = {
        "ready": True,
        "code": "focused-answer-field",
        "via": "focused-field",
        "fieldId": "QBase1_input",
        "fieldKind": "native",
        "suppliedSubject": "",
        "multiFieldEvidence": {
            "fields": 2,
            "separatorCandidates": 0,
            "separators": 0,
            "fieldIds": pair,
        },
    }
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: {json.dumps("QBase1_input" + chr(0x1F) + "QBase2_input")},
          fieldIds: {json.dumps(pair)},
          fieldIdentity: "separated",
          editor: {json.dumps(PAIR_EDITOR)},
          answer: "y = -1 or y = 5", displayText: "y = -1 or y = 5",
          answerParts: ["-1", "5"],
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        prepare(1);
        """
    )
    page.pump()
    page.answer(corroborated)  # the all-frame field read
    page.answer(PAIR_EDITOR)  # describeEditor
    page.answer(QUESTION_A)  # the question, unchanged

    assert page.json("state.phase") == "solved", "a good answer was discarded"
    assert page.json("state.answerParts") == ["-1", "5"]
    assert page.json("state.fieldIds") == pair
    assert page.json("state.fieldIdentity") == "editor-corroborated"

    # And the page it was read from takes the answer.
    page.run("insert();")
    page.pump()
    page.answer(PAIR_EDITOR)  # describeEditor
    page.answer(QUESTION_A)  # the signature re-check
    page.answer(corroborated)  # the fields, revalidated

    writes = [call for call in page.writes if call["func"] == "enterOwnedFields"]
    assert len(writes) == 1
    assert writes[0]["args"][:2] == [["-1", "5"], pair]
    assert page.said("answer-fields-changed-before-insert") == []


def test_facet_parts_use_the_same_pinned_two_field_transaction(page):
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input\u001fQBase2_input",
          fieldIds: ["QBase1_input", "QBase2_input"],
          fieldIdentity: "separated",
          editor: {json.dumps(PAIR_EDITOR)},
          signature: questionSignature(
            {json.dumps(QUESTION_A)}
          ),
        }};
        acceptReply({{
          status: "ready",
          problem_text: "Find both intercepts.",
          answer: {{
            display_text: "y = -1 or y = 5", keyboard_entry: "", parts: ["-1", "5"]
          }},
          certainty: {{
            source: "Facet · GPU", answered_by: "facet", facet_invoked: true,
            insertable: true, model: "gpt-oss:20b", runtime: "Ollama 0.33.2"
          }},
        }});
        """
    )
    page.pump()

    assert page.json("state.source") == "Facet · GPU"
    assert page.json("state.answerParts") == ["-1", "5"]

    page.run("insert();")
    page.pump()
    page.answer(PAIR_EDITOR)
    page.answer(QUESTION_A)
    page.answer(PAIR_INSPECT)
    page.answer(PAIR_ENTERED)
    page.answer(QUESTION_A)

    writes = [call for call in page.writes if call["func"] == "enterOwnedFields"]
    assert len(writes) == 1
    assert writes[0]["args"][:2] == [
        ["-1", "5"],
        ["QBase1_input", "QBase2_input"],
    ]
    assert page.json("state.phase") == "inserted"


def test_four_facet_parts_use_the_same_pinned_multi_field_transaction(page):
    field_id = "\u001f".join(FOUR_FIELD_IDS)
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: {json.dumps(field_id)}, fieldIds: {json.dumps(FOUR_FIELD_IDS)},
          fieldIdentity: "separated",
          editor: {json.dumps(FOUR_EDITOR)},
          signature: questionSignature(
            {json.dumps(QUESTION_A)}
          ),
        }};
        acceptReply({{
          status: "ready",
          problem_text: "Find every solution.",
          answer: {{
            display_text: "y = -2 or y = 2 or y = -3 or y = 3",
            keyboard_entry: "", parts: ["-2", "2", "-3", "3"]
          }},
          certainty: {{
            source: "Facet · GPU", answered_by: "facet", facet_invoked: true,
            insertable: true, model: "gpt-oss:20b", runtime: "Ollama 0.33.2"
          }},
        }});
        """
    )
    page.pump()

    assert page.json("state.answerParts") == ["-2", "2", "-3", "3"]
    page.run("insert();")
    page.pump()
    page.answer(FOUR_EDITOR)
    page.answer(QUESTION_A)
    page.answer(FOUR_INSPECT)
    page.answer(FOUR_ENTERED)
    page.answer(QUESTION_A)

    writes = [call for call in page.writes if call["func"] == "enterOwnedFields"]
    assert len(writes) == 1
    assert writes[0]["args"][:2] == [
        ["-2", "2", "-3", "3"],
        FOUR_FIELD_IDS,
    ]
    assert page.json("state.phase") == "inserted"


def test_two_fraction_roots_run_two_preflighted_plans_on_the_pinned_editors(page):
    display = "z = (-4 - 6i)/7 or z = (-4 + 6i)/7"
    parts = ["(-4-6*i)/7", "(-4+6*i)/7"]
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input\u001fQBase2_input",
          fieldIds: ["QBase1_input", "QBase2_input"],
          fieldIdentity: "separated",
          editor: {json.dumps(STRUCTURED_PAIR_EDITOR)},
          answer: {json.dumps(display)}, displayText: {json.dumps(display)},
          answerParts: {json.dumps(parts)},
          signature: questionSignature(
            {json.dumps(QUESTION_A)}
          ),
        }};
        insert();
        """
    )
    page.pump()
    page.answer(STRUCTURED_PAIR_EDITOR)
    page.answer(QUESTION_A)
    page.answer(PAIR_INSPECT)
    page.answer(
        {
            "ok": True,
            "code": "entered-fields",
            "entered": ["-4-6i7", "-4+6i7"],
            "enteredFields": ["QBase1_input", "QBase2_input"],
            "completed": 2,
        }
    )
    page.answer(QUESTION_A)

    writes = [call for call in page.writes if call["func"] == "enterPlan"]
    assert len(writes) == 1
    assert writes[0]["args"][2] == ["QBase1_input", "QBase2_input"]
    assert writes[0]["args"][0] == [
        [
            {"op": "template", "name": "Fraction"},
            {"op": "type", "text": "-4-6i"},
            {"op": "slot", "name": "denominator"},
            {"op": "type", "text": "7"},
        ],
        [
            {"op": "template", "name": "Fraction"},
            {"op": "type", "text": "-4+6i"},
            {"op": "slot", "name": "denominator"},
            {"op": "type", "text": "7"},
        ],
    ]
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == display


def test_two_roots_use_one_pinned_editor_when_the_question_requests_a_comma(page):
    display = "y = (-3 + √17)/2 or y = (-√17 - 3)/2"
    parts = ["(-3+sqrt(17))/2", "(-sqrt(17)-3)/2"]
    prompt = (
        "Solve the following quadratic equation using the quadratic formula. "
        "Separate multiple answers with a comma if necessary."
    )
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "txtAns1", editor: {json.dumps(COMMA_EDITOR)},
          problemText: {json.dumps(prompt)},
          answer: {json.dumps(display)}, displayText: {json.dumps(display)},
          answerParts: {json.dumps(parts)},
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        insert();
        """
    )
    page.pump()
    page.answer(COMMA_EDITOR)
    page.answer(QUESTION_A)
    page.answer({"ok": True, "code": "entered", "entered": "-3+172,-17-32"})
    page.answer(QUESTION_A)

    writes = [call for call in page.writes if call["func"] == "enterPlan"]
    assert len(writes) == 1
    assert writes[0]["tabId"] == 11
    assert writes[0]["frameId"] == 0
    assert writes[0]["args"][0] == [
        {"op": "template", "name": "Fraction"},
        {"op": "type", "text": "-3+"},
        {"op": "template", "name": "Radical"},
        {"op": "type", "text": "17"},
        {"op": "slot", "name": "denominator"},
        {"op": "type", "text": "2"},
        {"op": "base"},
        {"op": "type", "text": ","},
        {"op": "template", "name": "Fraction"},
        {"op": "type", "text": "-"},
        {"op": "template", "name": "Radical"},
        {"op": "type", "text": "17"},
        {"op": "base"},
        {"op": "type", "text": "-3"},
        {"op": "slot", "name": "denominator"},
        {"op": "type", "text": "2"},
    ]
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == display


def test_comma_editor_surfaces_the_exact_character_hawkes_rejects(page):
    """The executor's refusal detail must reach the panel unchanged.

    The live failure used to render ``does not accept: .`` because this branch
    discarded the executor detail and supplied no localization argument.
    """
    display = "y = (-3 + √17)/2 or y = (-√17 - 3)/2"
    prompt = (
        "Solve using the quadratic formula. "
        "Separate multiple answers with a comma if necessary."
    )
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "txtAns1", editor: {json.dumps(COMMA_EDITOR)},
          problemText: {json.dumps(prompt)},
          answer: {json.dumps(display)}, displayText: {json.dumps(display)},
          answerParts: ["(-3+sqrt(17))/2", "(-sqrt(17)-3)/2"],
          signature: questionSignature({json.dumps(QUESTION_A)}),
        }};
        insert();
        """
    )
    page.pump()
    page.answer(COMMA_EDITOR)
    page.answer(QUESTION_A)
    page.answer(
        {
            "ok": False,
            "code": "answer-has-rejected-characters",
            "detail": ",",
        }
    )

    assert page.json("state.phase") == "failed"
    assert page.json("state.errorKey") == "errorAnswerRejected"
    assert page.json("state.errorArgs") == [","]
    assert page.json("state.detail") == ","


def test_a_second_window_taking_over_mid_insertion_writes_nothing_to_it(page):
    """A insert -> B prepare -> A resumes.

    The defect: `insert()` re-read `state.tabId` after its awaits, so once
    `prepare(2)` had replaced the global identity the question re-check read
    B's question, compared it against B's signature, matched, and the write
    landed in tab 22.
    """
    page.own_window_a()
    page.run("insert();")
    page.pump()
    assert page.json("__H.pending.length") >= 1, "A is waiting on the page"
    assert page.writes == [], "nothing written yet"

    # B's sidebar opens and prepares. Only B's tab answers, so B's prepare runs
    # all the way to a settled, fully described window-B state while A is still
    # parked on its first await -- the exact shape of the live failure.
    page.run("prepare(2);")
    page.pump()
    page.answer_tab(22, INSPECT_OK)
    page.answer_tab(22, EDITOR_OK)
    page.answer_tab(22, QUESTION_B)
    assert page.json("state.windowId") == 2, "B owns the state"
    assert page.json("state.tabId") == 22
    b_signature = page.json("state.signature")
    assert b_signature, "B has a real question signature to validate against"

    # Now A resumes. Unpinned, its question re-check read B's tab, compared
    # B's question to B's signature, agreed, and wrote into tab 22.
    page.answer_tab(11, EDITOR_OK)
    page.answer(QUESTION_B)
    page.answer(QUESTION_B)

    # 1. Nothing reached window B's tab.
    assert [w for w in page.writes if w["tabId"] == 22] == [], (
        "A's reviewed answer reached window B's tab"
    )
    # 2. A did not silently continue against the changed identity either.
    assert page.writes == [], "the abandoned insertion still wrote somewhere"
    # 3. It said so.
    assert page.said("insertion-target-changed"), page.json("__H.logged")


def test_the_abandonment_is_precise_and_fail_closed(page):
    """Ownership alone changes -- same question, same tab reachable -- and the
    insertion must still stop, naming both windows rather than guessing."""
    page.own_window_a()
    page.run("insert();")
    page.pump()
    page.run("update({ ...blankState(), phase: 'checking', windowId: 2, tabId: 22 });")
    page.pump()
    page.answer(EDITOR_OK)
    page.answer(QUESTION_A)

    assert page.writes == [], "A wrote after its target changed hands"
    reasons = page.said("insertion-target-changed")
    assert reasons, page.json("__H.logged")
    assert reasons[0]["data"]["wasWindow"] == 1
    assert reasons[0]["data"]["nowWindow"] == 2


def test_the_failure_is_reported_only_into_the_window_it_belongs_to(page):
    """Fail-closed, but not onto somebody else's panel.

    While the state still describes window A the abandonment is a visible
    error; once another window owns the state, saying anything into it would
    put A's failure on B's panel.
    """
    page.own_window_a()
    page.run("insert();")
    page.pump()
    # Same window, changed question identity: A's own panel should be told.
    page.run("update({ signature: 'SOMETHING-ELSE' });")
    page.pump()
    page.answer(EDITOR_OK)
    page.answer(QUESTION_A)

    assert page.writes == []
    assert page.json("state.errorKey") == "errorInsertionAbandoned"


# --- work that is not an insertion, returning after window B took over ---------

#: The native host, held the way the page is: a reply goes back only when the
#: scenario sends one. QuickJS has no `AbortController`, and `solve()` needs one.
NATIVE_HOST = """
globalThis.AbortController = class {
  constructor() {
    const listeners = [];
    this.signal = {
      aborted: false,
      addEventListener: (_, fn) => listeners.push(fn),
      removeEventListener: () => {},
    };
    this.abort = () => {
      if (!this.signal.aborted) {
        this.signal.aborted = true;
        listeners.splice(0).forEach((fn) => fn());
      }
    };
  }
};
__H.native = [];
browser.runtime.connectNative = () => {
  const port = { listeners: [] };
  port.onMessage = { addListener: (fn) => port.listeners.push(fn) };
  port.onDisconnect = { addListener: () => {} };
  port.postMessage = (request) => { port.request = request; __H.native.push(port); };
  port.disconnect = () => {};
  return port;
};
__H.reply = (body) => {
  const port = __H.native.shift();
  port.listeners.forEach((fn) => fn({
    protocol_version: PROTOCOL_VERSION, request_id: port.request.request_id, ...body,
  }));
};
"""


def window_b_takes_over(page):
    """B's sidebar asks, and B's prepare settles while A is still parked."""
    page.run("claim(2);")
    page.pump()
    for result in (INSPECT_OK, EDITOR_OK, QUESTION_B):
        page.answer_tab(22, result)
    assert page.json("[state.windowId, state.tabId]") == [2, 22], "B owns the state"
    return page.json("state.signature")


def solving_window_a(page):
    """A's solve, past its health check and waiting on A's page."""
    page.run(NATIVE_HOST)
    page.run("settingsReady.then(() => { settings.autoSolve = false; });")
    page.pump()
    page.own_window_a()
    page.run("update({ phase: 'ready', answer: '', displayText: '', entryText: '' });")
    page.run("solve(1);")
    page.pump()
    page.run("__H.reply({ status: 'ok' });")
    page.pump()


def test_a_prepare_returning_after_another_window_took_over_writes_nothing(page):
    """A re-prepare -> B claims and settles -> A's page reads come back.

    Nothing cancels a prepare, so A's wrote tab 11, A's question and A's
    carried answer under window 2's id: B's panel was offered A's answer with
    Insert enabled, and the watcher, reading tab 11 against tab 11's own
    signature, never saw anything to correct.
    """
    page.run("settingsReady.then(() => { settings.autoSolve = false; });")
    page.pump()
    page.own_window_a()
    page.run("prepare(1);")
    page.pump()
    b_signature = window_b_takes_over(page)

    for result in (INSPECT_OK, EDITOR_OK, QUESTION_A):
        page.answer_tab(11, result)

    shown = page.json("stateFor(2)")
    assert [shown["windowId"], shown["tabId"]] == [2, 22]
    assert shown["signature"] == b_signature
    assert shown["answer"] == "", "window B's panel was offered window A's answer"
    assert shown["phase"] == "ready"


def test_a_cancelled_solve_leaves_its_reading_out_of_the_window_that_took_over(page):
    """A solve's read returned, wrote its signature, and only then checked."""
    solving_window_a(page)
    b_signature = window_b_takes_over(page)

    page.answer_tab(11, QUESTION_A)

    assert page.json("[state.windowId, state.tabId]") == [2, 22]
    assert page.json("state.signature") == b_signature


def test_a_cancelled_solve_puts_no_capture_failure_on_another_windows_panel(page):
    """A crop that failed for A's cancelled solve was B's panel's error."""
    solving_window_a(page)
    page.run("settings.cropCapture = true;")
    # An unreadable question falls back to a capture, after the read's retries.
    for _ in range(12):
        if "measureQuestionBounds" in page.json("__H.pending.map(p => p.record.func)"):
            break
        page.answer_tab(11, {"promptText": "", "expressions": []})
    else:
        pytest.fail("A's solve never reached its capture")
    window_b_takes_over(page)

    page.answer_tab(11, None)

    assert page.json("[state.windowId, state.tabId]") == [2, 22]
    assert page.json("[state.phase, state.errorKey]") == ["ready", ""]


def test_an_insertion_finishing_after_another_window_took_over_records_nothing(page):
    """Audit F06: A's post-insertion read returned after B had prepared.

    B went from `ready` to `inserted`, with A's answer as its placed text and
    A's question as its signature.
    """
    page.own_window_a()
    page.run("settingsReady.then(() => { settings.autoSolve = false; });")
    page.run("insert();")
    page.pump()
    for result in (EDITOR_OK, QUESTION_A, ENTERED_OK):
        page.answer(result)
    b_signature = window_b_takes_over(page)
    assert page.json("state.phase") == "ready"

    page.answer_tab(11, QUESTION_A)  # finishInsertion's read comes back

    assert page.json("[state.windowId, state.tabId, state.phase]") == [2, 22, "ready"]
    assert page.json("state.placedText") == ""
    assert page.json("state.signature") == b_signature
    assert page.said("insertion-finished-after-ownership-change")


# --- a picture is of the question it is sent beside ----------------------------

#: A markup reading the host declines, so the solve falls back to a picture.
#: `during` runs while that first request is out -- which is when focus, the tab
#: in front, or the question itself can move. Every capture is recorded, and the
#: synthetic image names the window it was taken of.
MARKUP_DECLINED = """
settings.cropCapture = false;
__H.currentWindow = 1;
__H.requests = [];
askEthnos = async (operation, extra) => {
  __H.requests.push({ operation, extra });
  if (operation === "health") return { status: "ok" };
  if (extra.solve_engine === "facet") {
    DURING;
    return { status: "unsupported", message: "synthetic markup declined" };
  }
  return { status: "unsupported", message: "synthetic image declined" };
};
browser.tabs.captureVisibleTab = (...args) => {
  __H.captureArgs = args;
  // Firefox's own overload: a window left out means the current one.
  const windowId = Number.isInteger(args[0]) ? args[0] : __H.currentWindow;
  return Promise.resolve("synthetic-image-from-window-" + windowId);
};
"""


def solve_falling_back_to_a_picture(page, during, reread=QUESTION_A):
    page.run(NATIVE_HOST)
    page.pump()
    page.own_window_a()
    page.run(MARKUP_DECLINED.replace("DURING", during) + "solve(1);")
    page.pump()
    page.answer(QUESTION_A)  # the solve's own read
    page.answer(reread)  # the read after the picture, when there is one
    return [
        request["extra"]["problem"].get("screenshot_png_base64")
        for request in page.json("__H.requests")
        if request["operation"] == "solve_hawkes_problem"
    ]


def test_a_capture_is_taken_of_the_questions_own_window(page):
    """Audit F01: focus moved to window 2, and window 2's picture was sent."""
    images = solve_falling_back_to_a_picture(page, "__H.currentWindow = 2")

    assert page.json("__H.captureArgs[0]") == 1
    assert images == ["", "synthetic-image-from-window-1"]


def test_no_picture_is_sent_once_another_tab_is_in_front(page):
    images = solve_falling_back_to_a_picture(
        page, "__H.windowTab[1] = 12; __H.tabWindow[12] = 1"
    )

    assert images == [""], "a picture of whatever was in front was sent"
    assert page.json("state.errorKey") == "errorCaptureMoved"


def test_no_picture_is_sent_when_the_question_changed_under_it(page):
    """Hawkes swaps a question in place, with no navigation to cancel anything."""
    images = solve_falling_back_to_a_picture(page, "", reread=QUESTION_B)

    assert images == [""], "the next question's picture went beside this one's words"
    assert page.json("state.errorKey") == "errorCaptureMoved"


def test_the_target_is_pinned_before_anything_can_yield(page):
    """L1's synchronous claim and the pin are the same moment, and nothing on
    the write path reads mutable ownership state afterwards."""
    background = (EXTENSION / "background.js").read_text()
    body = background.split("async function insert()", 1)[1].split("\n/**", 1)[0]

    assert body.index("pinInsertionTarget()") < body.index("await ")
    assert body.index('update({ phase: "inserting" })') < body.index("await ")

    after_first_await = body[body.index("await settingsReady") :]
    reads = set(re.findall(r"state\.\w+", after_first_await))
    assert reads <= {"state.phase"}, f"insert() still reads live ownership: {reads}"
