"use strict";

/**
 * One diagnostic log, shared by every context in the add-on.
 *
 * Until now every failure path here was a bare `catch {}`. That is fine for a
 * finished add-on and useless for one under development: a panel that throws
 * mid-render simply stops updating, and nothing anywhere says why. This module
 * exists so that every context — panel, event page, settings — writes to the
 * same bounded ring, and so an uncaught error becomes a visible, exportable
 * record instead of a silent freeze.
 *
 * Three rules follow from the add-on's zero-footprint promise, and are what
 * make a log acceptable in something that reads a student's coursework:
 *
 *  1. **Never the work.** Answers, displayed notation, recognized problem text
 *     and screenshots are never written, at any level. Their *shapes* are —
 *     `{answerLength: 4}` tells you what you need to debug an insertion
 *     without recording what the answer was. {@link redact} enforces this on
 *     every payload rather than trusting each call site.
 *  2. **Never off-machine.** `storage.local` only. There is no transport in
 *     this add-on and this module does not add one.
 *  3. **Bounded and erasable.** {@link RING_LIMIT} entries, oldest dropped,
 *     and one call clears the lot.
 */

/** Where the ring lives in `storage.local`. */
export const LOG_STORAGE_KEY = "diagnostics";

/**
 * The lock every context takes before touching that key.
 *
 * Extension pages share one origin, so one named lock covers the event page,
 * the panel and the settings page together. See {@link exclusively}.
 */
export const LOG_LOCK_NAME = "ethnos:diagnostics";

/** Entries kept. Roughly a full session of solving; a few tens of kilobytes. */
export const RING_LIMIT = 200;

/** Severities, most severe first. `off` writes nothing at all. */
export const LEVELS = ["off", "error", "warn", "info", "debug"];

/** Payload keys that carry the user's coursework rather than the add-on's state. */
const SENSITIVE = new Set([
  "answer",
  "displayText",
  "problemText",
  "problem",
  "screenshot",
  "screenshot_png_base64",
  "detail",
  "stageDetail",
  "entered",
  "value",
]);

/** Longest string kept in a payload; anything longer is truncated with a mark. */
const MAX_STRING = 160;

let scope = "unknown";
let threshold = LEVELS.indexOf("info");
let sequence = 0;
/** This load of this context, so entries from two of them never merge. */
let generation = "";
/** The user operation currently in flight, or "" between operations. */
let run = "";

/** Entries written but not yet flushed to storage. */
let pending = [];
let flushTimer = null;
/** The write in progress, if there is one. @type {Promise<void> | null} */
let flushing = null;

/**
 * Replace a value with something safe to keep.
 *
 * Exported because it is the rule that keeps a student's coursework out of a
 * file they may be invited to paste into a bug report, and a rule like that is
 * worth asserting directly rather than trusting each call site to respect.
 *
 * Sensitive keys are reduced to a length, so the log can still answer "was the
 * answer empty?" without holding the answer. Everything else is truncated,
 * and anything that is not a primitive is described rather than serialized —
 * a payload must never be able to drag a DOM node or a whole reply into
 * storage.
 */
export function redact(value, key = "") {
  if (SENSITIVE.has(key)) {
    if (typeof value === "string") {
      return { length: value.length };
    }
    return value === null || value === undefined ? value : { present: true };
  }
  if (typeof value === "string") {
    return value.length > MAX_STRING ? `${value.slice(0, MAX_STRING)}…` : value;
  }
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return value;
  }
  if (value === undefined) {
    return undefined;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 8).map((entry) => redact(entry));
  }
  if (value instanceof Error) {
    return describeError(value);
  }
  if (typeof value === "object") {
    const out = {};
    for (const [name, inner] of Object.entries(value).slice(0, 16)) {
      out[name] = redact(inner, name);
    }
    return out;
  }
  return String(value);
}

/**
 * An error as a plain object.
 *
 * The stack is kept because it is the whole point of logging an error, but the
 * `moz-extension://<uuid>/` prefix is stripped from it: that UUID is unique per
 * profile, and a diagnostic the user is invited to paste into a bug report
 * should not carry it.
 */
export function describeError(error) {
  if (!(error instanceof Error)) {
    return { message: String(error) };
  }
  const stack = typeof error.stack === "string"
    ? error.stack.replace(/moz-extension:\/\/[0-9a-fA-F-]+\//g, "/").split("\n").slice(0, 6)
    : [];
  return { name: error.name, message: error.message, stack };
}

/**
 * Name the user operation everything logged from now on belongs to.
 *
 * The ring records what happened but not what it happened *to*: two panels,
 * two windows, a re-prepare mid-solve and a retry all interleave, and
 * reconstructing which `solved` belonged to which `solve-started` was done by
 * reading timestamps and hoping. A run id is carried on the entries instead,
 * and the same id is what the native host and Facet are asked under.
 *
 * @param {string} id an identifier, or "" to stop attributing entries
 */
export function setRun(id) {
  run = typeof id === "string" ? id.slice(0, 32) : "";
}

/** The operation entries are currently attributed to, or "". */
export function currentRun() {
  return run;
}

/** A fresh operation id: sortable by time, unique enough within a session. */
export function newRunId() {
  const stamp = Date.now().toString(36);
  const noise = Math.floor(Math.random() * 0xffff)
    .toString(16)
    .padStart(4, "0");
  return `r${stamp}${noise}`;
}

/** Queue one entry and schedule a flush. */
function write(level, event, data) {
  const rank = LEVELS.indexOf(level);
  if (rank < 1 || rank > threshold) {
    return;
  }
  sequence += 1;
  const entry = {
    t: Date.now(),
    seq: sequence,
    level,
    scope,
    // `seq` restarts whenever a non-persistent event page is unloaded, so on
    // its own it interleaves two lifetimes into nonsense. The generation says
    // which lifetime an entry came from, which is also the answer to "did the
    // event page go away in the middle of this?".
    ...(generation ? { gen: generation } : {}),
    ...(run ? { run } : {}),
    event,
    ...(data === undefined ? {} : { data: redact(data) }),
  };
  pending.push(entry);

  // Mirrored to the extension console so `about:debugging` shows it live,
  // which is where you are while developing. Storage is for afterwards.
  const method = level === "error" ? "error" : level === "warn" ? "warn" : "log";
  console[method](`[ethnos:${scope}] ${event}`, entry.data ?? "");

  if (flushTimer === null) {
    flushTimer = setTimeout(flush, 250);
  }
}

/**
 * Append the queued entries to the stored ring.
 *
 * Read-modify-write, because two contexts can be logging at once and neither
 * owns the key -- so it is done under a lock the whole origin shares. See
 * {@link exclusively} for what happened without one.
 *
 * The returned promise settles only once everything queued at the time of the
 * call has actually been written. A second call during a write therefore waits
 * for that write and then performs its own, rather than resolving straight
 * away -- which is what made `await flushLog()` followed by `readLog()` miss
 * the newest entries, exactly where it matters: copying the log after a
 * failure.
 */
/**
 * Run one read-modify-write of the ring with every other context shut out.
 *
 * The write below is read-modify-write, and `flushing` serialises it only
 * within one context. Each context loads its own copy of this module, so the
 * event page and the panel hold different `flushing` promises and neither
 * excludes the other: both read the same stored array, both append their own
 * batch to it, and the second `set` overwrites the first. The entries are not
 * dropped by the ring's own bound -- they never reach it.
 *
 * That is not hypothetical. On 2026-09-07 the event page logged `solved`,
 * `answer-retained` and `answer-not-insertable`, the panel logged
 * `panel-rendered` a few milliseconds later, and the stored ring came back
 * with `seq` running 9, 13 and 15, 19 -- three entries missing from each gap,
 * every one of them the background's. Reading that log said a solve had
 * produced no answer at all, and an afternoon went into a defect that had not
 * happened. A diagnostic that silently loses the record it was consulted for
 * is worse than none.
 *
 * Web Locks is the browser's own answer to this and is shared across the
 * origin's contexts. Where it is unavailable the write proceeds as before --
 * an unlocked append still beats refusing to log.
 */
async function exclusively(work) {
  const locks = globalThis.navigator?.locks;
  if (typeof locks?.request !== "function") {
    return work();
  }
  return locks.request(LOG_LOCK_NAME, work);
}

function flush() {
  if (flushTimer !== null) {
    clearTimeout(flushTimer);
    flushTimer = null;
  }
  if (flushing !== null) {
    return flushing.then(() => (pending.length > 0 ? flush() : undefined));
  }
  if (pending.length === 0) {
    return Promise.resolve();
  }
  const batch = pending;
  pending = [];
  flushing = (async () => {
    try {
      await exclusively(async () => {
        const stored = await browser.storage.local.get(LOG_STORAGE_KEY);
        const existing = Array.isArray(stored?.[LOG_STORAGE_KEY])
          ? stored[LOG_STORAGE_KEY]
          : [];
        // Ordered by time on the way in, so an interleaved write from the
        // event page and the panel still reads in the right order. Sorting
        // was never the problem; reading a value another context was about to
        // replace was.
        const merged = [...existing, ...batch]
          .sort((left, right) => left.t - right.t || left.seq - right.seq)
          .slice(-RING_LIMIT);
        await browser.storage.local.set({ [LOG_STORAGE_KEY]: merged });
      });
    } catch {
      // Storage being unavailable must never fail the operation being logged.
      // The console mirror above already carried the entry.
    }
  })();
  const settled = flushing.then(() => {
    flushing = null;
    if (pending.length > 0 && flushTimer === null) {
      flushTimer = setTimeout(flush, 250);
    }
  });
  return settled;
}

export const log = {
  error: (event, data) => write("error", event, data),
  warn: (event, data) => write("warn", event, data),
  info: (event, data) => write("info", event, data),
  debug: (event, data) => write("debug", event, data),
};

/** Everything currently stored, oldest first. */
export async function readLog() {
  try {
    const stored = await browser.storage.local.get(LOG_STORAGE_KEY);
    return Array.isArray(stored?.[LOG_STORAGE_KEY]) ? stored[LOG_STORAGE_KEY] : [];
  } catch {
    return [];
  }
}

/** Forget everything, including anything queued but not yet written. */
export async function clearLog() {
  pending = [];
  try {
    await browser.storage.local.remove(LOG_STORAGE_KEY);
  } catch {
    // Nothing to do; the ring is capped anyway.
  }
}

/** One entry as a line of text, for the clipboard. */
export function formatEntry(entry) {
  const stamp = new Date(entry.t).toISOString().slice(11, 23);
  const payload = entry.data === undefined ? "" : ` ${JSON.stringify(entry.data)}`;
  const operation = entry.run ? ` [${entry.run}]` : "";
  return `${stamp} ${entry.level.padEnd(5)} ${entry.scope.padEnd(10)}${operation} ${entry.event}${payload}`;
}

/**
 * Name this context and start logging.
 *
 * Installs the handlers that catch what nothing else does: an uncaught
 * exception and a rejected promise nobody awaited. `popup.js` throwing inside
 * `render` used to leave the panel frozen at "Checking…" with no trace
 * anywhere; now it leaves a record and, through `onFatal`, a visible one.
 *
 * @param {string} name context tag, e.g. "panel" or "background"
 * @param {{level?: string, onFatal?: (info: object) => void,
 *   generation?: string}} [options]
 */
export function initLog(name, { level = "info", onFatal, generation: mark = "" } = {}) {
  scope = name;
  generation = typeof mark === "string" ? mark.slice(0, 32) : "";
  setLogLevel(level);

  const fatal = (event, info) => {
    log.error(event, info);
    // Flush now rather than in 250ms: whatever just threw may be about to
    // take the context with it.
    flush();
    try {
      onFatal?.(info);
    } catch {
      // A failing error handler must not recurse.
    }
  };

  const target = typeof window === "undefined" ? self : window;
  target.addEventListener("error", (event) => {
    fatal("uncaught-error", {
      message: event.message,
      source: String(event.filename ?? "").replace(/moz-extension:\/\/[0-9a-fA-F-]+\//g, "/"),
      line: event.lineno,
      column: event.colno,
      error: event.error ? describeError(event.error) : undefined,
    });
  });
  target.addEventListener("unhandledrejection", (event) => {
    fatal("unhandled-rejection", { error: describeError(event.reason) });
  });
}

/** Raise or lower what gets kept. Applied to later entries, not stored ones. */
export function setLogLevel(level) {
  const rank = LEVELS.indexOf(level);
  threshold = rank < 0 ? LEVELS.indexOf("info") : rank;
}

/** Write anything queued immediately, e.g. as a page is going away. */
export function flushLog() {
  return flush();
}
