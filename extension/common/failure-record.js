"use strict";

/**
 * What a failure leaves behind after everybody has gone home.
 *
 * The diagnostic ring answers "what just happened" and answers it well, but it
 * is two hundred entries shared by every context, and a solve costs a dozen of
 * them. By the time an agent is asked to look at a refusal from an hour ago,
 * the entries that explain it have been pushed out by ordinary use — so the
 * only way to triage one was for a high-reasoning agent to sit attached to the
 * session and catch it live. That is not a diagnostic tool, it is a vigil.
 *
 * So a run that ends in an explicitly diagnostic terminal state — it failed,
 * the companion refused it, or it produced an answer this editor will not take
 * — additionally writes one bounded record here, outside the ring and immune
 * to it. The record is assembled from the values the event page is holding at
 * that moment rather than scraped back out of the log, which is what makes it
 * independent of {@link module:common/log~setLogLevel}: information already
 * proven useful in diagnosing a live failure is kept whether or not anyone
 * remembered to turn diagnostics up beforehand.
 *
 * Four rules, and they are the same four that make a log acceptable in
 * something that reads a student's coursework:
 *
 *  1. **Never the work.** Every field is built by name through
 *     {@link SAFE_RECORD_KEYS} and the projections below, so a caller cannot
 *     widen it by passing more. Question text, answer text, the contents of
 *     the answer box, credentials and screenshots have no path in — not at any
 *     level, not in debug mode, not ever. Shapes, counts, the page's own
 *     vocabulary and the add-on's own state are what is kept.
 *  2. **Never off-machine.** `storage.local` only. There is no transport in
 *     this add-on and this module does not add one.
 *  3. **Bounded and erasable.** {@link MAX_RECORDS} records, {@link MAX_GROUPS}
 *     groups, {@link MAX_AGE_MS} of history and {@link MAX_BYTES} of storage,
 *     whichever binds first; oldest evicted; Settings clears the lot along
 *     with the ring.
 *  4. **Never observable.** Writing a record starts no timer, opens no port,
 *     and is never awaited by the operation that failed. It cannot wake or
 *     hold open a suspended event page, and it cannot change when anything
 *     else happens.
 *
 * Records are for detail and are evicted first; groups are for counting and
 * outlive them, so "this has now happened eleven times" survives long after
 * the eleven records have gone. `scripts/triage_hawkes_failures.py` reads both
 * from the profile, offline, with no browser running.
 */

/** Where the ledger lives in `storage.local`. One key, one object. */
export const FAILURE_STORAGE_KEY = "failures";

/** Shape of the stored object. A reader that sees another number stops. */
export const LEDGER_VERSION = 1;

/** Fingerprint algorithm. Prefixed onto every fingerprint so a change to the
 *  fields below cannot silently merge two eras of grouping. */
export const FINGERPRINT_VERSION = "f1";

/** Full records kept. Roughly a fortnight of a bad week; a few tens of KB. */
export const MAX_RECORDS = 40;

/**
 * Distinct fingerprints counted.
 *
 * Deliberately larger than {@link MAX_RECORDS}. A group is a few hundred bytes
 * and a record is a couple of kilobytes, and the whole point of separating them
 * is that "this has now happened eleven times" should outlive the eleven
 * records. A cap equal to the record cap would evict the two together.
 */
export const MAX_GROUPS = 64;

/** History kept. Older than this is another month's problem, not this one's. */
export const MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000;

/** Storage the whole ledger may occupy, serialized. Records go first. */
export const MAX_BYTES = 96 * 1024;

/** Representative run ids kept per group: the first, then the most recent. */
export const MAX_RUNS_PER_GROUP = 5;

/** Build markers kept per group, so "still happening after the fix" is visible. */
export const MAX_MARKERS_PER_GROUP = 4;

/** Longest string kept in any record field. Beyond this it is a payload. */
const MAX_FIELD = 48;

/** Longest stage trail kept, matching the event page's own bound. */
const MAX_STAGES = 24;

/** Editors described per record, matching the add-on's own answer bound. */
const MAX_EDITORS = 5;

/** Native-host request ids listed per record. A run makes a handful of calls. */
const MAX_HOST_IDS = 6;

/**
 * Every key a stored record may have.
 *
 * The projections below already build records by name, so this is the second
 * of two locks rather than the first. It exists because the first one is a
 * function somebody will edit: a field spread in from a reply, or a `...rest`
 * added for convenience, is exactly how a redaction rule gets lost, and this
 * turns that into a dropped field instead of a stored answer.
 */
export const SAFE_RECORD_KEYS = Object.freeze([
  "at",
  // `answerShape`, not `answer`. The field holds a length and two verdicts,
  // never the answer -- and the offline sanitizer reduces anything called
  // `answer` to its length on sight, exactly as `common/log.js` does. A field
  // that means one thing and is named the other loses that argument silently.
  "answerShape",
  "build",
  "editor",
  "errorKey",
  "evidence",
  "fingerprint",
  "generation",
  "host",
  "outcome",
  "phase",
  "refusal",
  "route",
  "run",
  "runtime",
  "solve",
  "stage",
  "stages",
  "stoppedIn",
  "target",
  "traits",
]);

/** One string, bounded and stripped of anything that is not a scalar. */
function bounded(value, limit = MAX_FIELD) {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value !== "string") {
    return "";
  }
  return value.length > limit ? value.slice(0, limit) : value;
}

/** One integer, or null. Counts and identifiers, never measurements of work. */
function integer(value) {
  return Number.isFinite(value) ? Math.trunc(value) : null;
}

/** The names of the templates a control offers, as one stable word. */
function templateNames(templates) {
  if (!templates || typeof templates !== "object") {
    return "";
  }
  return Object.entries(templates)
    .filter(([, offered]) => offered === true)
    .map(([name]) => name)
    .sort()
    .join("+");
}

/** Which slots a dynamic control publishes, and what each of them accepts.
 *
 *  Slot names and their character sets are the page's vocabulary for its own
 *  editor — the same material `answer-parts-unplaceable` has always logged —
 *  and they are what says whether an answer had anywhere to go. What the
 *  student typed into the control is a different field entirely and is not
 *  read here.
 */
function slotSummary(slots) {
  if (!slots || typeof slots !== "object") {
    return null;
  }
  const out = {};
  for (const name of Object.keys(slots).sort()) {
    out[name] = bounded(slots[name]);
  }
  return out;
}

/**
 * One answer control, as the page describes itself.
 *
 * `text` — what is currently typed in the box — and nothing else that could
 * carry the student's work is read. `name` is the control's own identifier,
 * which the ring has always carried as `editorNames`.
 */
export function controlEvidence(editor) {
  if (!editor || typeof editor !== "object") {
    return null;
  }
  return {
    kind: bounded(editor.kind) || "none",
    ok: editor.ok === true,
    code: bounded(editor.code),
    name: bounded(editor.name, 32),
    enabled: editor.enabled === true,
    maxLength: integer(editor.maxLength),
    allowed: bounded(editor.allowedCharacters),
    templates: templateNames(editor.templates),
    slots: slotSummary(editor.slots),
  };
}

/**
 * The complete safe description of what this question offered as an editor.
 *
 * Kept by default rather than behind the debug level, because it is the field
 * that has decided every insertion failure looked at so far: a refusal naming
 * `answer-needs-template` means fraction, radical, exponent or parentheses,
 * against an unknown character set, and without the control's own answer to
 * that the diagnosis needed a screenshot of the owner's coursework to reach a
 * guess.
 */
/**
 * The shape of the page's own control collection, in counts.
 *
 * Beside the control that was chosen, how many there were to choose from. A
 * record saying "one textbox" against a page showing five boxes cannot say
 * which of four faults that was; these counts can, and none of them is a
 * control's contents, its name or its character set.
 */
function collectionEvidence(collection) {
  if (!collection || typeof collection !== "object") {
    return null;
  }
  return {
    branch: bounded(collection.branch, 24),
    controls: integer(collection.controls),
    controlKeys: integer(collection.controlKeys),
    dataKeys: integer(collection.dataKeys),
    paired: integer(collection.paired),
    described: integer(collection.described),
    usable: integer(collection.usable),
    focused: integer(collection.focused),
  };
}

export function editorEvidence(editor) {
  const described = controlEvidence(editor);
  if (described === null) {
    return { kind: "none", ok: false, count: 0, controls: [], collection: null };
  }
  const children = Array.isArray(editor.editors)
    ? editor.editors.slice(0, MAX_EDITORS).map(controlEvidence).filter(Boolean)
    : [];
  return {
    ...described,
    count: children.length || 1,
    controls: children,
    collection: collectionEvidence(editor.collection),
  };
}

/** What the add-on could read of the question, in shapes and verdicts only. */
export function questionEvidence(evidence) {
  if (!evidence || typeof evidence !== "object") {
    return null;
  }
  return {
    read: bounded(evidence.read) || "unread",
    expressions: integer(evidence.expressions),
    graph: bounded(evidence.graph, 16),
    table: bounded(evidence.table, 16),
    // Why a completion table was not read, when one was not. A count or a
    // named disagreement, bounded like every other code here; a cell of one
    // has no path into this record and no name to arrive under.
    answerTable: bounded(evidence.answerTable, 48),
    promptChars: integer(evidence.promptChars),
    // A digest of the question, never the question. The ring already carries
    // this as `signature`; it is here so two records can be recognized as the
    // same question without either of them holding it.
    signature: bounded(evidence.signature, 96),
  };
}

/** Where Facet sent the question, and what answered it. */
export function routeEvidence(certainty) {
  if (!certainty || typeof certainty !== "object") {
    return null;
  }
  return {
    source: bounded(certainty.source),
    answeredBy: bounded(certainty.answered_by ?? certainty.answeredBy),
    facetInvoked: Boolean(certainty.facet_invoked ?? certainty.facetInvoked),
    router: bounded(certainty.router ?? certainty.facetRouter),
    method: bounded(certainty.method ?? certainty.facetMethod),
    reading: bounded(certainty.reading ?? certainty.facetReading),
    insertable: certainty.insertable === true,
  };
}

/** Which machine and model answered, when one did. */
export function runtimeEvidence(certainty) {
  if (!certainty || typeof certainty !== "object") {
    return null;
  }
  return {
    runtime: bounded(certainty.runtime),
    model: bounded(certainty.model),
    requestedBackend: bounded(certainty.requested_backend ?? certainty.requestedBackend),
    backend: bounded(certainty.actual_backend ?? certainty.backend),
    device: bounded(certainty.device),
    fallback: Boolean(certainty.fallback),
  };
}

/**
 * UTF-8 bytes, without depending on a platform encoder.
 *
 * The character sets a Hawkes control publishes contain radicals and dashes
 * outside ASCII, so folding code units rather than bytes would make the
 * fingerprint depend on how the string happened to be stored -- and two
 * occurrences of one fault would fall into two groups depending on which
 * build of Firefox wrote them. Written out rather than taken from a platform
 * encoder so that the same folding runs identically under the offline
 * harnesses, which have no `TextEncoder`.
 */
export function utf8Bytes(value) {
  const out = [];
  for (const symbol of String(value)) {
    const code = symbol.codePointAt(0);
    if (code < 0x80) {
      out.push(code);
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code < 0x10000) {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    } else {
      out.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f)
      );
    }
  }
  return out;
}

/**
 * FNV-1a, 64-bit, as sixteen hex characters.
 *
 * A grouping key, not a proof: it says "these two failures look like the same
 * failure", and nothing depends on it being hard to collide deliberately. It
 * is folded here rather than through `crypto.subtle` because that is
 * asynchronous, and this runs on the path of a failure that has already
 * happened — a record that has to await a digest is a record that can be lost
 * to the event page unloading in between.
 */
export function fold(value) {
  const prime = 0x100000001b3n;
  const mask = 0xffffffffffffffffn;
  let hash = 0xcbf29ce484222325n;
  for (const byte of utf8Bytes(value)) {
    hash = ((hash ^ BigInt(byte)) * prime) & mask;
  }
  return hash.toString(16).padStart(16, "0");
}

/** Characters sorted and de-duplicated, so two orderings are one group. */
function normalizedSet(value) {
  return [...new Set(bounded(value))].sort().join("");
}

/**
 * The fields two occurrences of the same failure have in common.
 *
 * Deliberately not in here: run ids, generations, timestamps, elapsed times,
 * window/tab/frame ids, the question's digest, its prompt length, its
 * expression count, the answer's length and the build marker. Every one of
 * those changes between two instances of one fault, and including any of them
 * would produce a ledger of groups of one — which is the thing this exists to
 * stop. The marker is recorded per group instead, so "still happening on the
 * build that was meant to fix it" stays answerable.
 */
export function fingerprintFields(record) {
  const editor = record.editor ?? {};
  const controls = Array.isArray(editor.controls) && editor.controls.length
    ? editor.controls
    : [editor];
  const evidence = record.evidence ?? {};
  const route = record.route ?? {};
  const runtime = record.runtime ?? {};
  const answer = record.answerShape ?? {};
  const notInsertable = record.traits?.notInsertable ?? {};
  return [
    // Which rules folded this, not which build ran: a fingerprint has to
    // survive the fix it is waiting for, or a group cannot show one.
    ["algorithm", FINGERPRINT_VERSION],
    ["outcome", bounded(record.outcome)],
    ["errorKey", bounded(record.errorKey)],
    ["refusal", bounded(record.refusal)],
    ["phase", bounded(record.phase)],
    ["stoppedIn", bounded(record.stoppedIn)],
    ["stages", (record.stages ?? []).join(">")],
    ["editorKind", bounded(editor.kind)],
    ["editorOk", String(editor.ok === true)],
    ["editorCode", bounded(editor.code)],
    ["editorCount", String(editor.count ?? 0)],
    ["editorEnabled", controls.map((one) => String(one?.enabled === true)).join(",")],
    ["editorTemplates", controls.map((one) => bounded(one?.templates)).join(",")],
    ["editorAllowed", controls.map((one) => normalizedSet(one?.allowed)).join(",")],
    ["editorSlots", controls
      .map((one) => Object.keys(one?.slots ?? {}).sort().join("+"))
      .join(",")],
    ["evidenceRead", bounded(evidence.read)],
    ["evidenceGraph", bounded(evidence.graph)],
    ["evidenceTable", bounded(evidence.table)],
    ["routeSource", bounded(route.source)],
    ["routeAnsweredBy", bounded(route.answeredBy)],
    ["routeRouter", bounded(route.router)],
    ["routeMethod", bounded(route.method)],
    ["facetInvoked", String(route.facetInvoked === true)],
    ["runtime", bounded(runtime.runtime)],
    ["model", bounded(runtime.model)],
    ["backend", bounded(runtime.backend)],
    ["answerParts", String(answer.parts ?? 0)],
    ["answerDirectFit", (answer.directFit ?? []).join(",")],
    ["answerPlannedFit", (answer.plannedFit ?? []).join(",")],
    ["notInsertableEditor", bounded(notInsertable.editor)],
    ["notInsertablePlan", bounded(notInsertable.plan)],
  ];
}

/** The exact string folded into a fingerprint. Mirrored in the triage tool. */
export function fingerprintInput(record) {
  return fingerprintFields(record)
    .map(([name, value]) => `${name}=${value}`)
    .join("\n");
}

/** A stable name for this kind of failure. */
export function fingerprint(record) {
  return `${FINGERPRINT_VERSION}:${fold(fingerprintInput(record))}`;
}

/**
 * Assemble one record from what the event page is holding.
 *
 * Every field is named. Nothing is spread in, and the result is filtered
 * through {@link SAFE_RECORD_KEYS} before it is returned, so the only way to
 * add something to a stored record is to add it here and to that list.
 */
export function buildFailureRecord(input = {}) {
  const stages = Array.isArray(input.stages)
    ? input.stages.slice(0, MAX_STAGES).map((stage) => bounded(stage, 32))
    : [];
  const solve = input.solve && typeof input.solve === "object" ? input.solve : null;
  const record = {
    run: bounded(input.run, 32),
    generation: bounded(input.generation, 32),
    at: integer(input.at) ?? 0,
    outcome: bounded(input.outcome, 24) || "failed",
    errorKey: bounded(input.errorKey, 48),
    refusal: bounded(input.refusal, 48),
    phase: bounded(input.phase, 24),
    stage: bounded(input.stage, 32),
    stages,
    stoppedIn: bounded(input.stage, 32) || stages[stages.length - 1] || "",
    target: {
      window: integer(input.windowId),
      tab: integer(input.tabId),
      frame: integer(input.frameId),
      fields: integer(input.fields) ?? 0,
    },
    editor: editorEvidence(input.editor),
    evidence: questionEvidence(input.evidence),
    route: routeEvidence(input.certainty),
    runtime: runtimeEvidence(input.certainty),
    answerShape: {
      // A length is a shape and is what says "the solver answered nothing"
      // apart from "the editor refused what it answered". It is never the
      // answer, and it is not one of the fingerprint's fields.
      length: integer(input.answerLength) ?? 0,
      parts: integer(input.answerParts) ?? 0,
      directFit: Array.isArray(input.directFit)
        ? input.directFit.slice(0, MAX_EDITORS).map((code) => bounded(code, 32))
        : [],
      plannedFit: Array.isArray(input.plannedFit)
        ? input.plannedFit.slice(0, MAX_EDITORS).map((code) => bounded(code, 32))
        : [],
    },
    host: {
      // Request ids are `<run>.<n>` all the way through the companion and into
      // Facet, so a count is a complete list of them and a grep target.
      requests: integer(input.hostRequests) ?? 0,
      ids: (() => {
        const run = bounded(input.run, 32);
        const made = integer(input.hostRequests) ?? 0;
        const ids = [];
        for (let index = 1; index <= Math.min(made, MAX_HOST_IDS); index += 1) {
          ids.push(`${run}.${index}`);
        }
        return run ? ids : [];
      })(),
    },
    // The run that produced the answer this one was trying to place, and what
    // answered it. An insertion is its own gesture and its own run, and by the
    // time it fails the solve's own entries may be long out of the ring.
    solve: solve
      ? {
        run: bounded(solve.run, 32),
        route: routeEvidence(solve.certainty),
        runtime: runtimeEvidence(solve.certainty),
        answerLength: integer(solve.answerLength) ?? 0,
      }
      : null,
    build: {
      marker: bounded(input.marker, 16),
      version: bounded(input.version, 16),
    },
    traits: {
      outcome: bounded(input.outcome, 24) || "failed",
      errorKey: bounded(input.errorKey, 48),
      events: Array.isArray(input.events)
        ? [...new Set(input.events.map((name) => bounded(name, 48)))].sort()
        : [],
      evidenceRefused: input.evidenceRefused === true,
      notInsertable: input.notInsertable && typeof input.notInsertable === "object"
        ? {
          editor: bounded(input.notInsertable.editor, 32),
          plan: bounded(input.notInsertable.plan, 32),
        }
        : null,
    },
  };
  record.fingerprint = fingerprint(record);
  const safe = {};
  for (const key of SAFE_RECORD_KEYS) {
    if (record[key] !== undefined) {
      safe[key] = record[key];
    }
  }
  return safe;
}

/** An empty ledger, and the shape every reader may assume. */
export function blankLedger() {
  return {
    version: LEDGER_VERSION,
    records: [],
    groups: [],
    dropped: { age: 0, count: 0, bytes: 0 },
  };
}

/** Whatever was in storage, as a ledger, without trusting any of it. */
function normalize(stored) {
  const blank = blankLedger();
  if (!stored || typeof stored !== "object" || stored.version !== LEDGER_VERSION) {
    return blank;
  }
  return {
    version: LEDGER_VERSION,
    records: Array.isArray(stored.records) ? stored.records.filter(Boolean) : [],
    groups: Array.isArray(stored.groups) ? stored.groups.filter(Boolean) : [],
    dropped: {
      age: integer(stored.dropped?.age) ?? 0,
      count: integer(stored.dropped?.count) ?? 0,
      bytes: integer(stored.dropped?.bytes) ?? 0,
    },
  };
}

/**
 * Enforce every bound, oldest first, and say how much was let go.
 *
 * Age, then count, then size — in that order, because an expired record is
 * worthless whatever the count is, and a record dropped for size is one the
 * count would have kept. The counters are cumulative and are the ledger's own
 * account of what it is no longer able to show.
 */
export function pruneLedger(stored, now = Date.now()) {
  const ledger = normalize(stored);
  const cutoff = now - MAX_AGE_MS;
  const dropped = { ...ledger.dropped };

  const fresh = ledger.records.filter((record) => (record?.at ?? 0) >= cutoff);
  dropped.age += ledger.records.length - fresh.length;
  const groups = ledger.groups.filter((group) => (group?.lastSeen ?? 0) >= cutoff);

  fresh.sort((left, right) => (left.at ?? 0) - (right.at ?? 0));
  const counted = fresh.slice(-MAX_RECORDS);
  dropped.count += fresh.length - counted.length;

  groups.sort((left, right) => (left.lastSeen ?? 0) - (right.lastSeen ?? 0));
  const keptGroups = groups.slice(-MAX_GROUPS);

  let records = counted;
  let size = JSON.stringify({ ...ledger, records, groups: keptGroups, dropped }).length;
  while (size > MAX_BYTES && records.length > 0) {
    records = records.slice(1);
    dropped.bytes += 1;
    size = JSON.stringify({ ...ledger, records, groups: keptGroups, dropped }).length;
  }

  return { version: LEDGER_VERSION, records, groups: keptGroups, dropped };
}

/**
 * Add one occurrence: a record for the detail, a group for the count.
 *
 * Pure, so the whole eviction and de-duplication story can be asserted without
 * a browser. The group carries the traits offline classification needs, which
 * is what lets a count outlive every record that produced it.
 */
export function mergeFailure(stored, record, now = Date.now()) {
  const ledger = pruneLedger(stored, now);
  const mark = record.fingerprint;
  const previous = ledger.groups.find((one) => one.fingerprint === mark) ?? null;
  const runs = [...new Set([...(previous?.runs ?? []), record.run].filter(Boolean))];
  const group = {
    fingerprint: mark,
    count: (integer(previous?.count) ?? 0) + 1,
    firstSeen: integer(previous?.firstSeen) ?? record.at,
    lastSeen: record.at,
    firstRun: bounded(previous?.firstRun, 32) || record.run,
    // The first occurrence is named by `firstRun`; these are the most recent,
    // which are the ones whose records are most likely to still exist.
    runs: runs.slice(-MAX_RUNS_PER_GROUP),
    markers: [...new Set([
      ...(previous?.markers ?? []),
      record.build?.marker,
    ].filter(Boolean))].slice(-MAX_MARKERS_PER_GROUP),
    generations: [...new Set([
      ...(previous?.generations ?? []),
      record.generation,
    ].filter(Boolean))].slice(-MAX_RUNS_PER_GROUP),
    errorKey: record.errorKey,
    outcome: record.outcome,
    stoppedIn: record.stoppedIn,
    editorKind: record.editor?.kind ?? "none",
    traits: record.traits,
  };
  return pruneLedger(
    {
      ...ledger,
      records: [...ledger.records, record],
      groups: [...ledger.groups.filter((one) => one.fingerprint !== mark), group],
    },
    now
  );
}

/**
 * Writes in flight, so two failures a moment apart cannot lose one another.
 *
 * Read-modify-write on a key nobody owns is the same hazard the log's flush
 * has, and the same answer: chain, rather than race. Not a timer and not a
 * listener — a settled chain holds nothing open.
 */
let writing = Promise.resolve();

/**
 * Keep one failure. Never awaited by the operation that failed.
 *
 * Storage being unavailable must cost the record and nothing else: a browser
 * that cannot write diagnostics still has to finish telling the user what went
 * wrong.
 */
export function recordFailure(record) {
  writing = writing.then(async () => {
    try {
      const stored = await browser.storage.local.get(FAILURE_STORAGE_KEY);
      const merged = mergeFailure(stored?.[FAILURE_STORAGE_KEY], record, record.at);
      await browser.storage.local.set({ [FAILURE_STORAGE_KEY]: merged });
    } catch {
      // Nothing to do and nothing to say: the ring already holds the entry
      // that this record was going to elaborate on.
    }
  });
  return writing;
}

/** The ledger as stored, pruned for reading but not rewritten by reading it. */
export async function readFailures(now = Date.now()) {
  try {
    const stored = await browser.storage.local.get(FAILURE_STORAGE_KEY);
    return pruneLedger(stored?.[FAILURE_STORAGE_KEY], now);
  } catch {
    return blankLedger();
  }
}

/** Forget every retained failure, records and counts alike. */
export async function clearFailures() {
  try {
    await browser.storage.local.remove(FAILURE_STORAGE_KEY);
  } catch {
    // The ledger is capped anyway; a failed clear leaves a bounded ledger.
  }
}
