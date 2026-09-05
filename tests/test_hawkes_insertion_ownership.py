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
    "common/editor-rules.js",
    "common/editor-plan.js",
    "common/frames.js",
    "common/page-actions.js",
    "common/settings.js",
    "background.js",
)

HARNESS = """
globalThis.__H = { timers: [], calls: [], pending: [], logged: [] };
const __H = globalThis.__H;

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
    local: {
      get: () => Promise.resolve({}),
      set: () => Promise.resolve(),
      remove: () => Promise.resolve(),
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
    get: (id) => Promise.resolve({ id, windowId: __H.tabWindow[id] }),
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
ENTERED_OK = {"ok": True, "code": "native-input", "answer": "3y"}
PAIR_INSPECT = {
    "ready": True,
    "code": "paired-answer-fields",
    "fieldId": "QBase1_input\u001fQBase2_input",
    "fieldIds": ["QBase1_input", "QBase2_input"],
}
PAIR_EDITOR = {
    "ok": True,
    "code": "described-pair",
    "kind": "pair",
    "editors": [
        {**EDITOR_OK, "allowedCharacters": "0123456789-"},
        {**EDITOR_OK, "allowedCharacters": "0123456789-"},
    ],
}
PAIR_ENTERED = {
    "ok": True,
    "code": "native-input-pair",
    "entered": ["-1", "5"],
}
STRUCTURED_PAIR_EDITOR = {
    "ok": True,
    "code": "described-pair",
    "kind": "pair",
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
              signature: questionSignature("txtAns1", {json.dumps(QUESTION_A)}),
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
            or call["func"] == "enterPlainAnswerParts"
        ]

    def said(self, event):
        return [row for row in self.json("__H.logged") if row.get("event") == event]


@pytest.fixture
def page():
    source = "\n".join(
        IMPORT_LINE.sub("", (EXTENSION / name).read_text()).replace("export ", "")
        for name in MODULES
    )
    context = quickjs.Context()
    context.eval(HARNESS)
    context.eval(source)
    context.eval(CAPTURE_LOG)
    return Page(context)


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
    page.answer(INSPECT_OK)  # the isolated-world prelude
    page.answer(ENTERED_OK)  # the entry itself
    page.answer(QUESTION_A)  # finishInsertion's rebase read

    assert page.writes, "an undisturbed insertion wrote nothing"
    assert all(w["tabId"] == 11 and w["frameId"] == 0 for w in page.writes)
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == "3y"


def test_two_roots_reach_only_the_two_fields_pinned_with_the_question(page):
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solved", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input\\u001fQBase2_input",
          fieldIds: ["QBase1_input", "QBase2_input"],
          editor: {json.dumps(PAIR_EDITOR)},
          answer: "y = -1 or y = 5", displayText: "y = -1 or y = 5",
          answerParts: ["-1", "5"],
          signature: questionSignature(
            "QBase1_input\\u001fQBase2_input", {json.dumps(QUESTION_A)}
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

    writes = [call for call in page.writes if call["func"] == "enterPlainAnswerParts"]
    assert len(writes) == 1
    assert writes[0]["tabId"] == 11
    assert writes[0]["frameId"] == 0
    assert writes[0]["args"][0] == ["-1", "5"]
    assert writes[0]["args"][1] == ["QBase1_input", "QBase2_input"]
    assert page.json("state.phase") == "inserted"
    assert page.json("state.placedText") == "y = -1 or y = 5"


def test_facet_parts_use_the_same_pinned_two_field_transaction(page):
    page.run(
        f"""
        state = {{
          ...blankState(), phase: "solving", windowId: 1, tabId: 11, frameId: 0,
          fieldId: "QBase1_input\u001fQBase2_input",
          fieldIds: ["QBase1_input", "QBase2_input"],
          editor: {json.dumps(PAIR_EDITOR)},
          signature: questionSignature(
            "QBase1_input\u001fQBase2_input", {json.dumps(QUESTION_A)}
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

    writes = [call for call in page.writes if call["func"] == "enterPlainAnswerParts"]
    assert len(writes) == 1
    assert writes[0]["args"][:2] == [
        ["-1", "5"],
        ["QBase1_input", "QBase2_input"],
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
          editor: {json.dumps(STRUCTURED_PAIR_EDITOR)},
          answer: {json.dumps(display)}, displayText: {json.dumps(display)},
          answerParts: {json.dumps(parts)},
          signature: questionSignature(
            "QBase1_input\u001fQBase2_input", {json.dumps(QUESTION_A)}
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
            "code": "entered-pair",
            "entered": ["-4-6i7", "-4+6i7"],
            "enteredFields": ["QBase1_input", "QBase2_input"],
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
          signature: questionSignature("txtAns1", {json.dumps(QUESTION_A)}),
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
          signature: questionSignature("txtAns1", {json.dumps(QUESTION_A)}),
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
