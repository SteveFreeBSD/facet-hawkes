"use strict";

/**
 * The solve outlives the popup.
 *
 * A solve takes the better part of a minute, and a popup panel closes the
 * moment anything else takes focus — taking its JavaScript context, and any
 * in-flight request, with it. So the work lives here instead, in a
 * non-persistent event page, and the popup is only a view onto this state.
 * Close it, reopen it, click elsewhere: the solve carries on and the panel
 * shows wherever it got to.
 *
 * This is the one resident context in the add-on, and it exists for that
 * reason alone. It holds no listener on any page, makes no network request,
 * and Firefox unloads it when idle.
 */

import {
  ALLOWED_HOST_PATTERN,
  MAX_ANSWER_PARTS,
  validateAnswer,
} from "/common/config.js";
import {
  ANSWER_SESSION_KEY,
  restoreSolvedAnswer,
  snapshotSolvedAnswer,
} from "/common/answer-session.js";
import {
  answerFitsEditor,
  insertErrorKey,
  isTableMapping,
  sameTableMapping,
  tableAnswerFits,
  tableAnswerVerdicts,
} from "/common/editor-rules.js";
import { planAnswerParts, planEntry } from "/common/editor-plan.js";
import { describeResults, selectAnswerFrame } from "/common/frames.js";
import { graphOperation } from "/common/graph-actions.js";
import { enterPlan } from "/common/page-actions.js";
import { enterTableCells } from "/common/table-actions.js";
import { collectSources, foldSources } from "/common/build-marker.js";
import { buildFailureRecord, recordFailure } from "/common/failure-record.js";
import {
  currentRun,
  describeError,
  initLog,
  log,
  newRunId,
  setLogLevel,
  setRun,
} from "/common/log.js";
import {
  defaultSettings,
  migrateSettings,
  onSettingsChanged,
  readSettings,
  resolveEntryCadence,
} from "/common/settings.js";

import "/common/cadence.js";
import {
  insertionInstrument, createCadencePresentation, attachCadencePort, observeCadence,
  finishIdleCadence, cancelCadence, beginCadenceRun, cadenceMeasurements,
} from "/common/cadence-session.js";

const NATIVE_HOST = "ethnos_hawkes";

/**
 * This load of this event page.
 *
 * The page is non-persistent: Firefox unloads it when idle and builds a fresh
 * one on the next message, resetting every module-level variable and the log's
 * own sequence counter with it. An operation that spans that boundary is a
 * different class of failure from one that does not, and until the two
 * lifetimes were labelled there was no way to tell them apart in the ring.
 */
const GENERATION = `g${Date.now().toString(36)}${Math.floor(Math.random() * 0xffff)
  .toString(16)
  .padStart(4, "0")}`;

/** This build's declared version. Read once; it cannot change under us. */
const MANIFEST_VERSION = browser.runtime.getManifest().version;

/**
 * Stages this run has passed through, oldest first.
 *
 * Stage transitions are logged at `debug`, which is off by default, so the
 * first failing stage was reconstructable only from a session that had been
 * turned up in advance -- which a live failure never is. The trail is kept
 * here instead and reported once, on the entry that ends the run.
 */
let runStages = [];

/** Native-host calls made in this run, so each request id says which it was. */
let runRequests = 0;

/** Longest trail kept. A run with more stages than this has other problems. */
const MAX_RUN_STAGES = 24;

/**
 * What this run has learned that a retained failure record would need.
 *
 * The ring is two hundred entries shared by every context, so by the time an
 * agent is asked about a refusal from an hour ago the entries explaining it
 * have been pushed out by ordinary use. A run that ends badly therefore keeps
 * one bounded record of its own, and the record is assembled from these --
 * values this page is already holding -- rather than scraped back out of the
 * log. That is what makes it independent of the log level: the evidence that
 * has actually diagnosed live failures is kept whether or not anyone thought
 * to turn diagnostics up first.
 */
let runFacts = blankRunFacts();

/**
 * The solve that produced the answer now held, kept across the run boundary.
 *
 * Solving and inserting are two gestures and therefore two runs, so by the
 * time an insertion fails, `runFacts` describes the insertion and knows
 * nothing about what answered the question. This is only ever read back when
 * its run id still matches `state.solveRun`, so it names the solve that
 * actually produced this answer rather than whichever one happened to be last.
 */
let lastSolve = null;

/** The running build's marker, once it has been folded. For the record. */
let buildMarker = "";

function blankRunFacts() {
  return {
    evidence: null,
    certainty: null,
    refusal: "",
    notInsertable: null,
    events: [],
  };
}

/** Note a diagnostic event this run saw, for the offline failure classes. */
function noteRunEvent(name) {
  if (!runFacts.events.includes(name) && runFacts.events.length < MAX_RUN_STAGES) {
    runFacts.events.push(name);
  }
}

/**
 * Start attributing everything that follows to one user operation.
 *
 * The id is carried on every log entry, and is what the native host and, in
 * turn, Facet are asked under -- so one browser gesture, one host process and
 * one Facet run share a name that can be grepped for.
 */
function startRun() {
  runStages = [];
  runRequests = 0;
  runFacts = blankRunFacts();
  setRun(newRunId());
}

/**
 * Which pipeline in the companion answers a question.
 *
 * Not a preference any more, and not a choice the browser is entitled to make.
 * Facet owns routing: it runs the deterministic solvers first, reaches a
 * reasoning model only for what those decline, and sends a parabola or a
 * regression to its own specialist. The browser asks for that and reads back
 * which route ran.
 *
 * `IMAGE_PIPELINE` is the companion's own reader, for a question the page
 * states as a picture rather than as mathematics -- there is nothing for Facet
 * to route in that case, because there is no expression to route. It is a
 * capability fallback, not an engine the user picks, and `"ethnos"` remains
 * its name on the wire because the native host and its protocol still use it.
 */
const SOLVE_PIPELINE = "facet";
const IMAGE_PIPELINE = "ethnos";
const PROTOCOL_VERSION = 1;

/** How long `health` may take. It loads no model, so this is a connectivity
 *  check rather than a solve, and is not worth a preference. */
const HEALTH_TIMEOUT_MS = 8000;

const CADENCE_SCRIPT = "/common/cadence.js";
const EDITOR_SCRIPT = "/content/hawkes-editor.js";
const INSPECT_SCRIPT = "/content/inspect-field.js";
const DESCRIBE_SCRIPT = "/content/hawkes-describe.js";
const QUESTION_SCRIPT = "/content/hawkes-question.js";
// How often an open panel checks whether the question has changed. The read
// is a same-frame DOM query costing a millisecond or so.
const QUESTION_WATCH_MS = 1500;

/**
 * @typedef {"idle" | "checking" | "ready" | "solving" | "solved" | "inserting"
 *   | "inserted" | "failed"} Phase
 */

/** Everything the panel needs to render itself, and nothing else. */
let state = blankState();

/**
 * A completed answer survives an idle event-page unload in memory only.
 *
 * Writes are serialized so a quick Solve -> Reset cannot let an older `set`
 * finish after the newer `remove`. The cache is only a candidate: `prepare()`
 * consumes it and applies the normal live signature check before the panel is
 * allowed to see the answer.
 */
let answerSessionPresent = false;
let answerSessionWrite = Promise.resolve();
const rememberedAnswerReady = readRememberedAnswer();
let rememberedAnswerConsumed = false;

/** @type {AbortController | null} */
let inFlight = null;

/**
 * Preferences, held in memory.
 *
 * Read once at load and kept current by `onSettingsChanged`, so a solve never
 * waits on storage and a change made in the settings page takes effect on the
 * next question rather than after a restart. `settingsReady` is awaited by the
 * operations that depend on a preference, for the case where the event page
 * has only just been woken.
 */
let settings = defaultSettings();
let settingsReady = refreshSettings();

async function refreshSettings() {
  settings = await readSettings();
  setLogLevel(settings.logLevel);
  // An upgraded profile can still hold a preference that was retired. It is
  // already inert -- nothing reads it -- so this is tidying rather than a
  // correction, and it must not delay the first solve.
  migrateSettings()
    .then((removed) => {
      if (removed.length > 0) {
        log.info("settings-migrated", { removed });
      }
    })
    .catch((error) => log.warn("settings-migration-failed", { error: describeError(error) }));
  return settings;
}

onSettingsChanged((changed) => {
  settings = { ...settings, ...changed };
  if ("logLevel" in changed) {
    setLogLevel(changed.logLevel);
  }
  insertionInstrument.setLevel(settings.entryMusicVolume / 100, settings.entryMusicMuted);
  if (!settings.entryMusicEnabled) { insertionInstrument.close(); }
  log.info("settings-changed", changed);
});

function blankState() {
  return {
    phase: /** @type {Phase} */ ("idle"),
    // Which browser window this state describes. One state exists at a time,
    // and it names the tab answers are read from and written to, so a request
    // from any other window has to re-establish it first.
    windowId: null,
    tabId: null,
    frameId: null,
    fieldId: "",
    fieldIds: [],
    // The browser's own mapping for a completion table: semantic blank N, and
    // the control occupying that cell. Read by the question reader, held here
    // across the solve, and re-read and compared before anything is written.
    // Never sent to the host, which is told the grid and nothing about boxes.
    tableTargets: [],
    editor: null,
    problemText: "",
    answer: "",
    displayText: "",
    entryText: "",
    answerParts: [],
    graphPlan: null,
    graphCoefficients: [],
    // What insertion put in the field, kept for the panel to show and for
    // nothing else. Never re-inserted, never offered to a later question.
    placedText: "",
    // Whether the host was told what the question asks. True until a solve
    // says otherwise, so nothing is ever cautioned about without cause.
    promptSeen: true,
    stage: "",
    stageDetail: "",
    signature: null,
    source: "",
    detail: "",
    errorKey: "",
    errorArgs: [],
    startedAt: 0,
    // Which run produced the answer now held. Solving and inserting are two
    // gestures and therefore two runs, and "what changed between the solve and
    // the insertion" is the question a lost insertion always raises. Carrying
    // the solve's id into the insertion's pinned snapshot is what joins them.
    // Not an ownership component: it names history, not the target.
    solveRun: "",
  };
}

/**
 * The open panels, keyed by the browser window each one belongs to.
 *
 * A port is used rather than `runtime.sendMessage` because a panel closes
 * whenever anything else takes focus. Sending to a closed popup leaves an
 * in-flight message Firefox reports as an aborted query; a port simply
 * disconnects, and its entry goes away.
 *
 * Keyed by window because Firefox gives every window its own sidebar. This was
 * one `panel` variable, and `panel = port` on each connection: opening a second
 * window's sidebar silently replaced the first, which then received no further
 * state and sat on whatever snapshot it had. It looked like a panel that would
 * no longer open.
 *
 * Keyed by port rather than by window because a sidebar's port carries no
 * sender tab: the window is only known once the panel announces it, and the
 * panel has to receive state from the moment it connects.
 *
 * @type {Map<browser.runtime.Port, {windowId: number | null}>}
 */
const panels = new Map();

/**
 * What one panel may be shown.
 *
 * One state exists at a time and it names the window it describes. Sending it
 * to every panel meant a sidebar in an unrelated window -- a chat, a docs tab,
 * anything -- displayed the Hawkes question, its answer, its source, and an
 * enabled Insert button. Seen live across two monitors: the answer to lesson
 * 1.3 question 2 sitting in the sidebar of a Discord window, offering to
 * insert itself.
 *
 * A panel that is not the state's window is shown a blank of its own, which is
 * exactly true for that window: nothing has been found or solved there. Acting
 * in it claims the state and prepares properly.
 */
function stateFor(windowId) {
  if (!Number.isInteger(state.windowId) || windowId === state.windowId) {
    return state;
  }
  return { ...blankState(), windowId: Number.isInteger(windowId) ? windowId : null };
}

async function readRememberedAnswer() {
  try {
    const stored = await browser.storage.session.get(ANSWER_SESSION_KEY);
    const answer = restoreSolvedAnswer(stored?.[ANSWER_SESSION_KEY]);
    answerSessionPresent = answer !== null;
    return answer;
  } catch (error) {
    log.debug("answer-session-unavailable", { message: String(error?.message ?? "") });
    return null;
  }
}

function syncRememberedAnswer(nextState) {
  const snapshot = snapshotSolvedAnswer(nextState);
  if (snapshot === null && !answerSessionPresent) {
    return;
  }
  answerSessionPresent = snapshot !== null;
  answerSessionWrite = answerSessionWrite
    .catch(() => undefined)
    .then(async () => {
      try {
        if (snapshot) {
          await browser.storage.session.set({ [ANSWER_SESSION_KEY]: snapshot });
        } else {
          await browser.storage.session.remove(ANSWER_SESSION_KEY);
        }
      } catch (error) {
        log.debug("answer-session-write-failed", {
          message: String(error?.message ?? ""),
        });
      }
    });
}

async function seedRememberedAnswer(windowId) {
  const remembered = await rememberedAnswerReady;
  if (!remembered || rememberedAnswerConsumed || state.phase !== "idle") {
    return false;
  }
  rememberedAnswerConsumed = true;
  if (remembered.windowId !== windowId) {
    syncRememberedAnswer(blankState());
    log.info("answer-session-discarded", { why: "window-changed" });
    return false;
  }
  state = { ...blankState(), ...remembered };
  log.info("answer-session-found", {
    windowId: remembered.windowId,
    tabId: remembered.tabId,
    answerLength: String(remembered.displayText || remembered.answer || "").length,
  });
  return true;
}

function update(changes) {
  if (
    typeof changes.stage === "string"
    && changes.stage
    && changes.stage !== state.stage
    && runStages.length < MAX_RUN_STAGES
  ) {
    runStages.push(changes.stage);
  }
  state = { ...state, ...changes };
  syncRememberedAnswer(state);
  for (const [port, entry] of panels) {
    try {
      port.postMessage({ type: "ethnos:state", state: stateFor(entry.windowId) });
    } catch {
      // Closed between the iteration and the post.
      panels.delete(port);
    }
  }
}

function fail(errorKey, { detail = "", args = [] } = {}) {
  const stopped = { phase: state.phase, stage: state.stage };
  log.warn("failed", {
    errorKey,
    ...stopped,
    // Where it got to, not just where it stopped. "failed at solving" is true
    // of a capture that never happened and of a model that answered nothing,
    // and the trail is what separates them.
    stages: runStages.join(">"),
  });
  update({ phase: "failed", errorKey, errorArgs: args, detail });
  retain("failed", { errorKey, ...stopped });
}

/**
 * Leave enough behind for the agent who is not here.
 *
 * Everything above assumes somebody is watching: the ring holds two hundred
 * entries shared by every context, a solve costs a dozen of them, and the
 * evidence that explains a refusal is gone within the hour. So a run ending in
 * a diagnostic terminal state -- it failed, the companion refused it, or it
 * produced an answer this editor will not take -- writes one bounded record
 * outside the ring, from the values this page is holding right now.
 *
 * Three properties matter more than the contents:
 *
 *  * It is never awaited. The panel has already been told; a diagnostic must
 *    not sit in front of the user being told, and an operation must not be
 *    able to fail because storage did.
 *  * It starts nothing. No timer, no port, no message, no alarm -- the four
 *    things that wake a suspended event page. It is one write in response to
 *    something that has already happened, so an unattended session behaves
 *    exactly as it would with this call removed.
 *  * It reads no page. Every field comes from state this page already held;
 *    nothing here goes back to the tab for more.
 *
 * `common/failure-record.js` owns what a record may contain. Coursework has no
 * path into one -- see the rules at the top of that file.
 */
function retain(outcome, { errorKey = "", phase = "", stage = "" } = {}) {
  const run = currentRun();
  if (!run) {
    // A record nothing can be correlated to is not worth a write. Every path
    // that reaches here from a user gesture has a run; the settings page's
    // health check mints its own.
    return;
  }
  const editor = state.editor;
  const solve = lastSolve && lastSolve.run && lastSolve.run === state.solveRun
    ? lastSolve
    : null;
  // `fail` is also what `initLog`'s fatal handler calls, so this runs while the
  // page is already in trouble. A diagnostic that could throw from there would
  // turn a reported failure into an unreported one.
  try {
    recordFailure(buildFailureRecord({
      run,
      generation: GENERATION,
      at: Date.now(),
      outcome,
      errorKey,
      refusal: runFacts.refusal,
      phase,
      stage,
      stages: runStages,
      windowId: state.windowId,
      tabId: state.tabId,
      frameId: state.frameId,
      fields: Array.isArray(state.fieldIds) && state.fieldIds.length
        ? state.fieldIds.length
        : (editor ? 1 : 0),
      editor,
      evidence: runFacts.evidence,
      certainty: runFacts.certainty,
      answerLength: String(state.displayText || state.answer || "").length,
      answerParts: Array.isArray(state.answerParts) ? state.answerParts.length : 0,
      directFit: runFacts.notInsertable?.directFit ?? [],
      plannedFit: runFacts.notInsertable?.plannedFit ?? [],
      hostRequests: runRequests,
      solve,
      marker: buildMarker,
      version: MANIFEST_VERSION,
      notInsertable: runFacts.notInsertable,
      evidenceRefused: runFacts.evidence?.read === "refused",
      events: runFacts.events,
    }));
  } catch (error) {
    log.debug("failure-record-unavailable", { error: describeError(error) });
  }
}

// Called synchronously through a pre-obtained background window reference in
// the panel's real Insert gesture. No async message pretends to carry activation.
globalThis.facetCadenceUnlock = () => {
  if (settings.entryMusicEnabled) {
    insertionInstrument.setLevel(settings.entryMusicVolume / 100, settings.entryMusicMuted);
    insertionInstrument.unlock();
  }
};

/** Build one score, then hand its offsets to the approved writer as plain data. */
async function runScoredEntry(target, steps, cadence, execute) {
  beginCadenceRun();
  cadence.score = ethnosCadence.planSemanticPhrase(steps.flat(), cadence);
  const options = { enabled: settings.entryMusicEnabled, genre: settings.entryGenre,
    voice: settings.entryVoice };
  let presentation;
  let succeeded = false;
  try {
    if (options.enabled) {
      // The panel already asked for a device inside its own Insert click. Ask
      // again here, because that call is best-effort: it needs a background-page
      // reference the panel may not have resolved yet, and a popup destroyed
      // mid-answer takes its copy with it. Firefox admits a newly created
      // AudioContext in an extension background page under its own autoplay
      // exemption, so this is the reliable half of the pair, not a second one.
      insertionInstrument.setLevel(settings.entryMusicVolume / 100, settings.entryMusicMuted);
      insertionInstrument.unlock();
    }
    if (cadence.score.notes.length && (options.enabled || panels.size > 0)) {
      try {
        presentation = createCadencePresentation(target, cadence.score, options, (cue) => {
          for (const [port, entry] of panels) {
            if (entry.windowId === target.windowId) {
              try { port.postMessage({ type: "ethnos:cadence", cue }); } catch { /* closed popup */ }
            }
          }
        }, () => ownsTarget(target));
        cadence.channel = presentation.channel;
        // Setup only; neither resume() nor an audio acknowledgement is awaited.
        // Failure costs the observer, never the approved insertion.
        let setupDeadline;
        try {
          await Promise.race([
            browser.scripting.executeScript({
              target: { tabId: target.tabId, frameIds: [target.frameId] },
              func: observeCadence,
              args: [presentation.channel, cadence.score.notes.length],
            }),
            new Promise((_, reject) => {
              setupDeadline = setTimeout(() => reject(new Error("audio-observer-unavailable")), 250);
            }),
          ]);
        } finally { clearTimeout(setupDeadline); }
      } catch { cadence.channel = undefined; presentation?.close(); }
    }
    // The observer's setup is an await: recheck ownership before any write.
    if (!ownsTarget(target)) {
      return [{ result: { ok: false, code: "answer-fields-changed" } }];
    }
    const result = await execute();
    succeeded = result?.[0]?.result?.ok === true;
    return result;
  } finally {
    presentation?.close(succeeded);
    // Numbers only: how late the browser woke each write against its own score
    // offset, how long the editor held the phrase building structure, and how
    // far ahead of the write the device scheduled its voice. No characters.
    const measured = cadenceMeasurements();
    if (measured) { log.info("cadence-performed", measured); }
  }
}

// --- page access -----------------------------------------------------------

const PAGE_TIMEOUT_MS = 15000;

/**
 * Inject one operation, with a deadline and a legible permission failure.
 *
 * `activeTab` is granted by the toolbar click and lasts until the tab
 * navigates. When it lapses, Firefox reports a missing host permission, which
 * on its own reads as a bug rather than as "click the button again".
 */
async function runOperation(target, operation, { world, alone = false } = {}) {
  return runInjection({
    target,
    files: alone ? [operation] : [CADENCE_SCRIPT, EDITOR_SCRIPT, operation],
    ...(world ? { world } : {}),
  });
}

/** Execute one Firefox script injection with the common deadline and errors. */
async function runInjection(injection) {
  let timer;
  try {
    return await Promise.race([
      browser.scripting.executeScript(injection),
      new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error("errorOperationTimeout")), PAGE_TIMEOUT_MS);
      }),
    ]);
  } catch (error) {
    const message = String(error?.message ?? error);
    if (permissionWithheld(error)) {
      throw new Error("errorTabAccessLost");
    }
    throw message.startsWith("error") ? error : new Error("errorNoBridge");
  } finally {
    clearTimeout(timer);
  }
}

/**
 * One-shot plain-text insertion, serialized by `scripting.executeScript`.
 *
 * The answer arrives as an argument from the event page instead of passing
 * through storage.local. `ethnosHawkes` is the isolated-world prelude injected
 * immediately beforehand; neither it nor this function is visible to page
 * JavaScript.
 */
async function enterPlainAnswer(answer, cadence) {
  if (typeof ethnosHawkes === "undefined") {
    return { ok: false, code: "prelude-missing" };
  }
  if (!ethnosHawkes.originAllowed()) {
    return { ok: false, code: "wrong-site" };
  }
  if (!ethnosHawkes.answerIsSupported(answer)) {
    return { ok: false, code: "answer-invalid" };
  }
  // Awaited: entry is paced character by character, so this is a promise.
  // Read without awaiting, `outcome.ok` is undefined and every insertion
  // reports a failure it did not have.
  const outcome = await ethnosHawkes.insertAnswer(answer, cadence);
  return { ok: outcome.ok, code: outcome.code, answer };
}

/** One-shot insertion for one exact multi-part answer shape. */
async function enterPlainAnswerParts(parts, fieldIds, cadence) {
  if (typeof ethnosHawkes === "undefined") {
    return { ok: false, code: "prelude-missing" };
  }
  if (!ethnosHawkes.originAllowed()) {
    return { ok: false, code: "wrong-site" };
  }
  return ethnosHawkes.insertAnswerParts(parts, fieldIds, cadence);
}

/**
 * The Hawkes tab of one specific window.
 *
 * `currentWindow` used to choose this, which in a background event page means
 * the most recently focused window -- not the window whose sidebar asked. With
 * two windows open, a solve started in one could read, and an insertion could
 * write to, the other one's tab.
 */
async function activeHawkesTab(windowId) {
  const [tab] = await browser.tabs.query(
    Number.isInteger(windowId)
      ? { active: true, windowId }
      : { active: true, currentWindow: true }
  );
  if (!tab || !Number.isInteger(tab.id)) {
    throw new Error("errorNoTab");
  }
  if (typeof tab.url !== "string") {
    // A URL this add-on cannot read. Which of the two reasons it is turns on
    // whether the one host it may see has been granted.
    const granted = await browser.permissions.contains({ origins: [ALLOWED_HOST_PATTERN] });
    if (!granted) {
      throw new Error("errorTabAccessLost");
    }
    // Granted, and still unreadable: whatever is in front cannot be Hawkes,
    // because a Hawkes URL is exactly what that grant makes readable. Saying
    // "no active tab was found" of a window plainly showing one sent people
    // looking for a missing tab instead of the wrong site -- reported from a
    // sidebar open beside a chat window.
    throw new Error("errorWrongSite");
  }
  let url;
  try {
    url = new URL(tab.url);
  } catch {
    throw new Error("errorWrongSite");
  }
  if (url.protocol !== "https:" || url.hostname !== "learn.hawkeslearning.com") {
    throw new Error("errorWrongSite");
  }
  return tab;
}

/**
 * Read the question as the page states it: the prompt and its MathML.
 *
 * Returns null when the page could not be read, which callers must treat as
 * "unknown question" rather than "no question".
 */
async function readQuestion(tabId, frameId, attempts = 6) {
  // MathJax leaves the MathML behind asynchronously, so a read can land before
  // the expression exists. An empty read used to count as success -- an empty
  // array is still an array -- and the solve fell through to the screenshot
  // and its two transcription readers, which is where "the two readers
  // disagreed" came from: a question that could have been read exactly.
  let last = null;
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (attempt > 0) {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    try {
      const [read] = await runOperation({ tabId, frameIds: [frameId] }, QUESTION_SCRIPT, {
        alone: true,
      });
      const question = read?.result;
      if (question && Array.isArray(question.expressions)) {
        last = question;
        if (readableQuestion(question)) {
          return question;
        }
      }
    } catch (error) {
      log.warn("question-read-failed", { attempt, error: describeError(error) });
    }
  }
  // Still nothing after waiting: this question really has no markup to read,
  // and the screenshot is the only way left.
  return last;
}

/**
 * A short digest, enough to tell two questions apart.
 *
 * The MathML runs to kilobytes and is only ever compared for equality, so it
 * is folded rather than stored. FNV-1a, which is small enough to read.
 */
function digest(value) {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return (hash >>> 0).toString(36);
}

/**
 * What identifies "the question now on screen".
 *
 * Hawkes swaps questions in place, so nothing navigates and no reset fires.
 * This used to be the answer control's id and its character rules -- but those
 * describe the *editor*, and two consecutive questions of the same kind
 * publish exactly the same ones. `cbrt(y^4)` followed by `7th-root(y^8)` both
 * report `QBase1_input` and `0123456789yz-+`, so the panel called them the
 * same question and offered the first answer for the second: `y^4` went into
 * the box for a question whose answer was `y^(8/7)`.
 *
 * The question's own text is what distinguishes questions. An unreadable
 * question returns null, and a null signature must never match another, so a
 * question we cannot identify is always re-solved rather than assumed stale.
 */
function questionSignature(question) {
  if (!readableQuestion(question)) {
    return null;
  }
  const content = `${question.promptText}\u0000${question.expressions.join("\u0000")}`
    + (question.graphPoints ? JSON.stringify(question.graphPoints) : "")
    // Two questions can share a prompt and differ only in their numbers, which
    // is exactly what a table of measurements is. Left out, the second would
    // be the first question to the panel, and the first answer would still be
    // on the card, insertable, against the second one's boxes.
    + (question.dataTable ? JSON.stringify(question.dataTable) : "");
  // The answer table's givens are the same kind of discriminator -- two rows
  // of a completion question differ only in those -- but the table is read
  // through the answer controls, and those are editor state. Clicking a cell
  // reveals a fraction's denominator box, at which point the reader refuses
  // the table and this component is simply absent. So it is kept beside the
  // question's own content rather than mixed into it, and compared only when
  // both readings have one; see `sameQuestionSignature`.
  const table = question.answerTable ? digest(JSON.stringify(question.answerTable)) : "";
  return `${digest(content)}|${content.length}|${table}`;
}

/**
 * Whether two signatures name the same question.
 *
 * The question's own content has to match exactly. The answer table's givens
 * have to match *when both readings state them*, and a reading that has none
 * is not evidence that the question changed -- it is evidence that the answer
 * controls were in a state the table reader would not read, which is what
 * happens the moment anyone clicks into a cell.
 *
 * Live, on 2026-09-07, that distinction was the whole defect: a correct
 * four-part answer was discarded and re-solved -- once through a reasoning
 * model, for twenty-five seconds -- because a revealed denominator box changed
 * the answer surface while the question on screen never moved.
 */
function sameQuestionSignature(left, right) {
  if (typeof left !== "string" || typeof right !== "string") {
    return false;
  }
  const [leftDigest, leftLength, leftTable = ""] = left.split("|");
  const [rightDigest, rightLength, rightTable = ""] = right.split("|");
  if (leftDigest !== rightDigest || leftLength !== rightLength) {
    return false;
  }
  return leftTable === "" || rightTable === "" || leftTable === rightTable;
}

/**
 * The answer boxes the page is showing, by id, from the field probe.
 *
 * One bounded read, used only to revalidate a mapping this question was
 * already reviewed against. It states no order and decides no target: the
 * mapping does both, and this says whether its cells are still there.
 */
async function sweptAnswerFields(tabId, frameId) {
  try {
    const reports = await runOperation({ tabId, frameIds: [frameId] }, INSPECT_SCRIPT);
    const found = reports.find((entry) => entry?.result?.multiFieldEvidence)?.result;
    const ids = found?.multiFieldEvidence?.fieldIds;
    return Array.isArray(ids) ? ids : [];
  } catch {
    return [];   // an unreadable page revalidates nothing
  }
}

/**
 * The mapping a question was reviewed against, still describing the page.
 *
 * A completion table's blanks are the page's own controls, and they are
 * re-found on every prepare -- but the reader that finds them refuses the
 * whole table for reasons that are about the editor and not about the
 * question: a cell showing two controls because someone clicked into it, for
 * one. Refusing to carry the mapping in that state cost the answer its Insert
 * button while the question, the mapping and the answer were all still right.
 *
 * So a mapping already validated for this same question is revalidated
 * instead of rediscovered: every cell it names must still be one of the answer
 * boxes the page is showing. A grid that was renumbered under us fails that,
 * which is the case the second reading existed to catch.
 */
function revalidatedTableTargets(retained, swept) {
  if (!isTableMapping(retained) || retained.length < 2) {
    return [];
  }
  const showing = new Set(Array.isArray(swept) ? swept : []);
  return retained.every((one) => showing.has(one.id)) ? retained : [];
}

/**
 * Whether the page stated this question rather than merely drawing it.
 *
 * Three ways it can: MathJax's MathML, the exact coordinates of a plotted
 * scatter, or a data table with its own column headings. Any one of them is
 * an exact reading and skips the screenshot entirely.
 */
function readableQuestion(question) {
  return Boolean(
    question
      && (question.expressions?.length > 0
        || question.graphPoints?.length >= 3
        || question.dataTable)
  );
}

/**
 * Read the editor's rules, retrying while it is still being built.
 *
 * Hawkes replaces its editor model when it swaps in the next question, and a
 * probe that lands in that gap sees nothing. Failing on the first read
 * reported "the answer editor could not be read" for an editor that was
 * simply a moment from existing.
 */
async function describeEditor(tabId, frameId, attempts = 5, isGraph = false) {
  if (isGraph) {
    const graph = await runInjection({ target: { tabId, frameIds: [frameId] }, world: "MAIN", func: graphOperation });
    return graph?.[0]?.result ?? { ok: false, code: "graph-missing" };
  }
  for (let attempt = 0; attempt < attempts; attempt += 1) {
    if (attempt > 0) {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    try {
      const [entry] = await runOperation({ tabId, frameIds: [frameId] }, DESCRIBE_SCRIPT, {
        world: "MAIN",
        alone: true,
      });
      const described = entry?.result;
      if (described?.ok) {
        return described;
      }
    } catch (error) {
      log.debug("describe-attempt-failed", { attempt, error: describeError(error) });
    }
  }
  // Whether the editor was read is the single fact that decides Insert, and it
  // was only ever recorded at debug level -- so a panel saying the editor could
  // not be read left nothing in the log to confirm or refute it. Triaging that
  // meant asking the owner to change a setting and reproduce.
  log.warn("editor-unreadable", { attempts });
  return { ok: false, code: "editor-model-missing" };
}

/**
 * The table mapping one question read produced, when it produced a usable one.
 *
 * Taken from the same read that produced the grid, never from a second one.
 * Blank N of that grid and entry N of this list are the same cell by
 * construction, and pairing them across two reads is exactly the mistake this
 * exists to make impossible.
 *
 * @returns {import("/common/editor-rules.js").TableTarget[]}
 */
function tableTargetsOf(question) {
  const blanks = question?.answerTargets?.blanks;
  if (!isTableMapping(blanks)) {
    return [];
  }
  // The grid and the mapping are two halves of one reading and must agree
  // about how many blanks there are before either is used.
  const numbered = Array.isArray(question?.answerTable?.rows)
    ? question.answerTable.rows
      .flatMap((row) => (Array.isArray(row) ? row : []))
      .filter((cell) => Number.isInteger(cell?.blank)).length
    : 0;
  return numbered === blanks.length ? blanks.map((blank) => ({ ...blank })) : [];
}

/**
 * The mapping in the shapes a log may hold.
 *
 * Control ids and cell coordinates; never a label, which is built from the
 * table's own stated values and is therefore coursework.
 */
function tableTargetShapes(targets) {
  return (targets ?? []).map((target) => ({
    blank: target.blank,
    id: target.id,
    row: target.row,
    column: target.column,
  }));
}

/**
 * Record one accepted mapping, in shapes.
 *
 * Ids and cell coordinates only. A blank's label is built from the table's own
 * stated values, so it stays on the panel and out of here.
 */
function noteTableTargets(targets, question, extra = {}) {
  if (targets.length < 2) {
    return;
  }
  log.info("table-targets-mapped", {
    blanks: targets.length,
    branch: question?.answerTargets?.branch ?? "",
    // Whether the page draws these blanks in the order the mathematics
    // numbers them. False is the live grid, and is why a geometric sweep
    // cannot be the thing that finds them.
    domOrderMatches: question?.answerTargets?.domOrderMatches === true,
    cells: tableTargetShapes(targets),
    ...extra,
  });
}

/** Preflight every answer part against this question's published editors. */
function multiEntryPlans(parts, editor) {
  if (!(
    Array.isArray(parts)
    && parts.length >= 2
    && parts.length <= MAX_ANSWER_PARTS
    && editor?.kind === "multi"
    && Array.isArray(editor.editors)
    && editor.editors.length === parts.length
    && parts.every((part) => validateAnswer(part).ok)
  )) {
    return null;
  }
  const direct = parts.map(
    (part, index) => answerFitsEditor(part, editor.editors[index]).insertable
  );
  const plans = parts.map((part, index) =>
    direct[index]
      ? { ok: true, steps: [{ op: "type", text: part }] }
      : planEntry(part, editor.editors[index])
  );
  return plans.every((plan) => plan.ok)
    ? { plans, plain: direct.every(Boolean) }
    : null;
}

function multiAnswerFits(parts, editor) {
  return multiEntryPlans(parts, editor) !== null;
}

/**
 * Why an answer's separate parts could not be placed, in shape only.
 *
 * `answer-parts` was the whole of the report: one word for a question Facet
 * had answered correctly and for at least four different disagreements between
 * the answer, the DOM's solution fields, and the editor model the page
 * published. Live that was indistinguishable from a question with no editor at
 * all.
 *
 * None of the answer's text appears here. Lengths, validity flags, and what
 * the page says about its own controls -- which is page metadata and is
 * already reported for the single-field case.
 */
function describePartsFailure(parts, editor, problemText, tableTargets = []) {
  const editors = Array.isArray(editor?.editors) ? editor.editors : [];
  const aligned = editors.length === parts.length;
  // The other way a page publishes several answers: one control per blank of
  // a completion table, found by the reader that accepted the table rather
  // than by the editor collection. Reported here in the same shape, because a
  // table answer that will not go in is now one of the things `answer-parts`
  // can mean.
  const cellFit = tableAnswerVerdicts(parts, tableTargets, editor);
  return {
    parts: parts.length,
    tableTargets: tableTargets.length,
    cellFit: (cellFit ?? []).map((verdict) => verdict.code ?? "ok"),
    cellMaxLength: tableTargets.map((target) => target.maxLength ?? null),
    partLengths: parts.map((part) => part.length),
    partsValid: parts.map((part) => validateAnswer(part).ok),
    editorKind: editor?.kind ?? "none",
    editorOk: Boolean(editor?.ok),
    editorCode: editor?.code ?? "",
    editorCount: editors.length,
    editorKinds: editors.map((one) => one?.kind ?? ""),
    editorEnabled: editors.map((one) => one?.enabled === true),
    editorMaxLength: editors.map((one) => one?.maxLength ?? null),
    allowed: editors.map((one) => String(one?.allowedCharacters ?? "").slice(0, 48)),
    templates: editors.map((one) =>
      Object.entries(one?.templates ?? {})
        .filter(([, on]) => on === true)
        .map(([name]) => name)
        .join("+")
    ),
    hasSlots: editors.map((one) => one?.slots !== null && one?.slots !== undefined),
    // The two ways a part can be entered, per part: typed straight in, or
    // built with keypad templates. Both failing is what `answer-parts` means.
    directFit: aligned
      ? parts.map((part, index) => answerFitsEditor(part, editors[index]).code ?? "ok")
      : [],
    plannedFit: aligned
      ? parts.map((part, index) => planEntry(part, editors[index]).code ?? "ok")
      : [],
    commaPrompt: /separate multiple answers with a comma/i.test(problemText ?? ""),
  };
}

/**
 * Why one answer could not be placed in one field, in shape only.
 *
 * The multi-part path has reported the page's own editor rules since
 * `answer-parts-unplaceable`; the single-field path reported two reason codes
 * and a length. Live, on lesson 3.3's "find the vertex", that left
 * `answer-needs-template` / `template-refused-by-question` meaning any of
 * fraction, radical, exponent or parentheses, against an unknown character
 * set -- and the diagnosis needed a screenshot of the owner's coursework to
 * get as far as a guess.
 *
 * The same data as `describePartsFailure`, for one editor: what the page says
 * about its own control, never what the answer says. A refusal detail is
 * carried only when it names a template; `answer-has-rejected-characters`
 * details the rejected characters themselves, which are the answer, so that
 * one is reduced to a count.
 */
function describeFieldFailure(answer, editor, fits, plan) {
  const templateCodes = new Set(["answer-needs-template", "template-refused-by-question"]);
  const named = (result) =>
    result && templateCodes.has(result.code) ? String(result.detail ?? "") : "";
  return {
    editorKind: editor?.kind ?? "none",
    editorOk: Boolean(editor?.ok),
    editorCode: editor?.code ?? "",
    editorEnabled: editor?.enabled === true,
    editorMaxLength: editor?.maxLength ?? null,
    allowed: String(editor?.allowedCharacters ?? "").slice(0, 48),
    templates: Object.entries(editor?.templates ?? {})
      .filter(([, on]) => on === true)
      .map(([name]) => name)
      .join("+"),
    hasSlots: editor?.slots !== null && editor?.slots !== undefined,
    // Which template each route said the question does not offer. A template
    // name is the editor's vocabulary, not the student's work.
    editorNeeds: named(fits),
    planNeeds: named(plan),
    rejectedCount:
      fits?.code === "answer-has-rejected-characters"
        ? [...new Set(String(fits.detail ?? ""))].length
        : 0,
  };
}

function commaAnswerPlan(parts, editor, problemText) {
  if (
    editor?.kind === "multi"
    || !/separate multiple answers with a comma/i.test(problemText ?? "")
    || !Array.isArray(parts)
    || parts.length !== 2
    || !parts.every((part) => validateAnswer(part).ok)
  ) {
    return null;
  }
  const plan = planAnswerParts(parts, editor);
  return plan.ok ? plan : null;
}

/**
 * The compact contract the host needs about how this page takes an answer.
 *
 * The described editor carries everything the browser needs to *enter* an
 * answer — character sets, templates, slots, field ids — and none of those
 * page details crosses to the host. What does change the required answer is
 * whether the page wants one value or several, how many values, whether it is
 * answered by typing at all, and whether a value is restricted to a signed
 * integer. The latter is a mathematical representation constraint, normalised
 * from the one exact textbox pattern Hawkes publishes for it.
 *
 * Anything unrecognised is reported as the single box, which is what every
 * version before this one implied and what the host still assumes when the
 * field is absent.
 */
function answerShapeOf(editor, answerTable = null, tableTargets = []) {
  // A validated completion table numbers its blanks in the order the
  // mathematics is read. Hawkes' live row-headed table publishes ten control
  // models (one for every value cell) even though the DOM has five answer
  // boxes, so that collection cannot define answer cardinality. The table can:
  // only the closed, sequential blank numbering emitted by our reader is used,
  // and only when the same reading also produced one control per blank -- a
  // count nothing can place is not a count worth asking the host for.
  const tableParts = (() => {
    if (
      editor?.kind !== "textbox"
      || !isTableMapping(tableTargets)
      || !Array.isArray(answerTable?.columns)
      || !Array.isArray(answerTable?.rows)
      || answerTable.columns.length < 2
      || answerTable.columns.length > 8
      || answerTable.rows.length < 2
      || answerTable.rows.length > 32
      || answerTable.rows.some(
        (row) => !Array.isArray(row) || row.length !== answerTable.columns.length
      )
    ) {
      return 0;
    }
    const blanks = answerTable.rows.flatMap((row) =>
      row
        .filter((cell) => cell && Number.isInteger(cell.blank))
        .map((cell) => cell.blank)
    );
    if (
      blanks.length < 2
      || blanks.length > MAX_ANSWER_PARTS
      || blanks.length !== tableTargets.length
      || blanks.some((blank, index) => blank !== index + 1)
    ) {
      return 0;
    }
    return blanks.length;
  })();
  if (editor?.kind === "graph") return { kind: "graph", graph: editor.context };
  if (
    editor?.kind === "multi"
    && Array.isArray(editor.editors)
    && editor.editors.length >= 2
    && editor.editors.length <= MAX_ANSWER_PARTS
  ) {
    const representations = editor.editors.map((one) =>
      one?.kind === "textbox"
      && one.allowedCharacters === "[0-9-]"
      && Number.isInteger(one.maxLength)
        ? { kind: "signed-integer", maxLength: one.maxLength }
        : null
    );
    return {
      kind: "multi",
      count: editor.editors.length,
      ...(representations.every(Boolean) ? { representations } : {}),
    };
  }
  if (tableParts > 0) return { kind: "multi", count: tableParts };
  if (editor?.kind === "option") {
    return { kind: "option" };
  }
  const representation = editor?.kind === "textbox"
    && editor.allowedCharacters === "[0-9-]"
    && Number.isInteger(editor.maxLength)
      ? { kind: "signed-integer", maxLength: editor.maxLength }
      : null;
  return { kind: "field", ...(representation ? { representations: [representation] } : {}) };
}

/**
 * The compact badge: which engine's answer this is, in two or three words.
 *
 * The host's own `source` is kept for anything it already names precisely --
 * "Facet · GPU" says where the work ran -- but "markup" and "symbolic" are
 * internal words for one thing a reader cares about: an exact solver answered,
 * and no model was involved. An older host that reports no engine keeps its
 * own wording rather than being relabelled on a guess.
 */
function answeredByBadge(certainty) {
  const source = certainty?.source ?? "";
  switch (certainty?.answered_by) {
    case "exact":
      // An exact answer is exact wherever it was computed. Facet names the
      // route it took, and that name is the honest badge; the companion's own
      // copy of the same solvers answers only on the picture path, and saying
      // so is what keeps the two distinguishable.
      return certainty?.facet_invoked ? source || "Facet Exact" : "Local exact";
    case "model":
      return "Local model";
    case "facet":
      return source || "Facet";
    default:
      return source;
  }
}

/**
 * The expandable provenance block: who did what, in the order it happened.
 *
 * Each layer is named separately on purpose. A solver is not a model, the
 * thing that read the picture is not the thing that answered, and what was
 * *asked* of a backend is not necessarily what the backend *did* — collapsing
 * any of those would make an answer look better sourced than it is.
 *
 * Plain labelled lines rather than message keys: this is diagnostic text in a
 * `<pre>`, and every note beside it has always been written the same way.
 */
function provenanceNotes(certainty) {
  const lines = [];
  const engine = certainty?.answered_by;
  if (engine) {
    lines.push(`Answered by: ${answeredByBadge(certainty)}`);
  } else {
    lines.push(`Source: ${certainty?.source ?? "unknown"}`);
  }
  if (certainty?.method) {
    lines.push(`${engine === "exact" ? "Method" : "Reasoner"}: ${certainty.method}`);
  }
  if (certainty?.router === "solved" || certainty?.router === "declined") {
    // Whose deterministic stage made the call. Facet owns the routing for every
    // question the page states as mathematics; the companion routes only what
    // it read from a picture.
    const router = certainty?.facet_invoked ? "Facet Exact" : "Local exact";
    const why =
      certainty.router === "declined" && certainty.router_detail
        ? ` (${certainty.router_detail})`
        : "";
    const verdict = certainty.router === "solved" ? "answered" : "declined";
    lines.push(`Router: ${router} ${verdict}${why}`);
  }
  if (engine !== "facet") {
    // Worth stating rather than leaving to inference: a question read from a
    // picture never reaches Facet at all, and this is the line that says so.
    lines.push(`Facet: ${certainty?.facet_invoked ? "invoked" : "not invoked"}`);
  }
  if (certainty?.runtime) {
    lines.push(`Runtime: ${certainty.runtime}`);
  }
  if (certainty?.requested_backend || certainty?.actual_backend) {
    const asked = certainty.requested_backend || "unspecified";
    const ran = certainty.actual_backend || "unknown";
    lines.push(
      asked === ran
        ? `Backend: ${ran}`
        : `Backend: ${asked} requested, ${ran} actual`
    );
  }
  if (certainty?.device) {
    lines.push(`Device: ${certainty.device}`);
  }
  if (typeof certainty?.fallback === "boolean") {
    lines.push(`Fallback: ${certainty.fallback ? "yes" : "none"}`);
  }
  if (certainty?.reading) {
    const read = certainty.reading === "mathml" ? "page MathML"
      : certainty.reading === "svg" ? "SVG point coordinates" : "screenshot";
    const transcription =
      certainty.reading === "screenshot" && certainty.transcription
        ? ` (${certainty.transcription})`
        : "";
    lines.push(`Question read: ${read}${transcription}`);
  }
  if (typeof certainty?.elapsed_ms === "number") {
    const ms = certainty.elapsed_ms;
    lines.push(`Elapsed: ${ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`}`);
  }
  return lines;
}

/**
 * Remember the reasoner Facet last actually used.
 *
 * The settings page has to describe the configured pipeline without asking
 * the network anything: waking an SSH connection and a model host to render a
 * preferences screen would be a real cost for a cosmetic line. So the last
 * observed run is kept, and the page presents it as the last observed run
 * rather than as a current fact.
 */
async function rememberFacetRun(certainty) {
  try {
    await browser.storage.local.set({
      facetLastSeen: {
        // Prefixed names on purpose. A test keeps the bare execution-config
        // keys out of this file entirely, because the browser must never name
        // one to the host. This is the opposite direction -- what the host
        // reported back, kept only so a label can be rendered later.
        facetModel: certainty.model ?? "",
        facetRuntime: certainty.runtime ?? "",
        facetDevice: certainty.device ?? "",
        facetBackend: certainty.actual_backend ?? "",
        at: Date.now(),
      },
    });
  } catch (error) {
    // Cosmetic. A settings page that cannot name the model is not a failure
    // worth losing a finished answer over.
    log.debug("facet-provenance-not-stored", { message: String(error?.message ?? "") });
  }
}

function sameStringArray(left, right) {
  return (
    Array.isArray(left)
    && Array.isArray(right)
    && left.length === right.length
    && left.every((value, index) => value === right[index])
  );
}

/**
 * The answer's fields, when two independent readings agree on them.
 *
 * `solutionFields()` finds the visible, editable, uniquely-identified boxes and
 * then requires the word "or" between them before it will call them one
 * answer -- a rule written for `x = ___ or x = ___`. Lesson 3.3's "find two
 * points" step labels its boxes "A:" and "B:", so those fields were discarded
 * and `fieldIds` arrived empty. The page was meanwhile saying "multi, two" the
 * other way, through its published editor model, which is what `answerShapeOf`
 * reads to ask Facet for two parts. Two correct parts and no field ids to put
 * them in is exactly the disagreement `errorEditorUnknown` reported, one gate
 * later, with nothing to say about which reading was wrong.
 *
 * Wording is the weaker evidence. Since a disabled control stopped being
 * counted, the editor model reports exactly the controls an answer can be
 * typed into, so when the DOM's count and the model's count agree, that
 * agreement is the stronger reading -- the discipline the data table already
 * uses, where the plotted points must agree with the table before either is
 * trusted.
 *
 * Disagreement is not an error here. It falls back to the single focused box,
 * which is what every version before this one did, so a question that really
 * does have one answer beside some other visible field keeps working.
 */
function answerFieldIds(choice, evidence, editor) {
  if (Array.isArray(choice?.fieldIds) && choice.fieldIds.length > 0) {
    return [...choice.fieldIds];
  }
  const candidates = evidence?.fieldIds;
  if (
    !Array.isArray(candidates)
    || candidates.length < 2
    || candidates.length > MAX_ANSWER_PARTS
    || !candidates.every((id) => typeof id === "string" && id !== "")
    || new Set(candidates).size !== candidates.length
  ) {
    return [];
  }
  return editor?.kind === "multi" && editor.editors?.length === candidates.length
    ? [...candidates]
    : [];
}

// --- the native companion --------------------------------------------------

/**
 * Ask the native host one named operation.
 *
 * `health` is answered without loading a model, which is what makes it worth
 * calling before a capture: an unregistered host is reported in a moment
 * rather than after a minute of waiting.
 */
async function askEthnos(operation, extra = {}, timeoutMs, onProgress, signal) {
  // Named after the run rather than at random. The companion passes this
  // through `safe_request_id` to Facet unchanged, so `grep r<id>` finds the
  // browser's log entries, the host's request and Facet's run in one search.
  // A run makes several calls -- health, then a solve, then perhaps an image
  // solve -- so the ordinal says which one, and each remains unique.
  runRequests += 1;
  const run = currentRun();
  const request = {
    protocol_version: PROTOCOL_VERSION,
    operation,
    request_id: run ? `${run}.${runRequests}` : crypto.randomUUID(),
    ...extra,
  };

  // A port rather than a one-shot message: the host reports each stage as it
  // begins, and a single reply cannot carry progress. A solve spends most of
  // its minute reading the image, so saying which reading is under way is the
  // difference between a progress line and a frozen one.
  let port;
  try {
    port = browser.runtime.connectNative(NATIVE_HOST);
  } catch {
    throw new Error("errorEthnosUnreachable");
  }

  let timer;
  let onAbort;
  try {
    return await new Promise((resolve, reject) => {
      timer = setTimeout(() => reject(new Error("errorEthnosTimeout")), timeoutMs);

      // Cancelling has to reject here, not merely set a flag. The `finally`
      // below then disconnects the port, Firefox closes the pipe, and the host
      // exits -- otherwise it keeps working and holding the model for the rest
      // of the minute while the panel says it stopped.
      if (signal) {
        if (signal.aborted) {
          reject(new Error("errorCancelled"));
          return;
        }
        onAbort = () => reject(new Error("errorCancelled"));
        signal.addEventListener("abort", onAbort, { once: true });
      }

      port.onMessage.addListener((reply) => {
        if (!reply || typeof reply !== "object") {
          reject(new Error("errorEthnosUnreachable"));
          return;
        }
        if (reply.protocol_version !== PROTOCOL_VERSION) {
          reject(new Error("errorEthnosVersion"));
          return;
        }
        if (reply.request_id !== request.request_id) {
          reject(new Error("errorEthnosVersion"));
          return;
        }
        if (reply.kind === "progress") {
          onProgress?.(reply);
          return;
        }
        resolve(reply);
      });

      // Disconnect without a reply means the host died or was never installed.
      port.onDisconnect.addListener(() => reject(new Error("errorEthnosUnreachable")));
      port.postMessage(request);
    });
  } finally {
    clearTimeout(timer);
    if (signal && onAbort) {
      signal.removeEventListener("abort", onAbort);
    }
    try {
      port.disconnect();
    } catch {
      // Already gone.
    }
  }
}

/**
 * Crop a screenshot to the vertical strip containing the question.
 *
 * The full viewport can contain account and navigation UI above the exercise.
 * It must never be the silent fallback for a failed crop: with privacy
 * cropping enabled, an uncertain boundary fails closed and sends nothing.
 *
 * @param {string} dataUrl
 * @param {{top: number, bottom: number}} bounds device-pixel boundaries
 * @returns {Promise<string|null>} a PNG data URL, or null if cropping fails
 */
async function cropToQuestion(dataUrl, bounds) {
  if (
    !bounds
    || !Number.isFinite(bounds.top)
    || !Number.isFinite(bounds.bottom)
    || bounds.top < 0
    || bounds.bottom - bounds.top < 80
  ) {
    return null;
  }
  try {
    // Decoded by hand rather than with a request API: the add-on makes no
    // requests at all, and the build enforces that none appears anywhere.
    const bitmap = await createImageBitmap(new Blob([decodeDataUrl(dataUrl)], {
      type: "image/png",
    }));
    const top = Math.min(Math.max(0, Math.round(bounds.top)), bitmap.height);
    const bottom = Math.min(Math.round(bounds.bottom), bitmap.height);
    const height = bottom - top;
    if (height < 80) {
      return null;
    }
    const canvas = new OffscreenCanvas(bitmap.width, height);
    canvas.getContext("2d").drawImage(
      bitmap,
      0,
      top,
      bitmap.width,
      height,
      0,
      0,
      bitmap.width,
      height,
    );
    const blob = await canvas.convertToBlob({ type: "image/png" });
    return `data:image/png;base64,${encodeBase64(new Uint8Array(await blob.arrayBuffer()))}`;
  } catch {
    return null;
  }
}

/** Bytes of a `data:` URL's base64 payload. */
function decodeDataUrl(dataUrl) {
  const binary = atob(dataUrl.slice(dataUrl.indexOf(",") + 1));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

/** Base64 for a byte array, chunked so a large image cannot blow the stack. */
function encodeBase64(bytes) {
  let binary = "";
  const CHUNK = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += CHUNK) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + CHUNK));
  }
  return btoa(binary);
}

/**
 * Locate the question between its instruction and the answer area.
 *
 * This intentionally returns no result unless both edges are defensible.
 * Full-width is retained because diagrams can extend beyond their text or
 * MathML; the vertical crop still excludes Hawkes' header, answer keypad and
 * footer.
 */
function measureQuestionBounds() {
  let frameOffsetTop = 0;
  try {
    // captureVisibleTab uses top-level viewport coordinates. Translate a
    // same-origin child frame into that coordinate space; an opaque
    // cross-origin boundary cannot be translated safely and therefore yields
    // no crop rather than a plausible-but-wrong one.
    let current = window;
    while (current !== current.top) {
      const frame = current.frameElement;
      if (!frame) {
        return null;
      }
      frameOffsetTop += frame.getBoundingClientRect().top;
      current = current.parent;
    }
  } catch {
    return null;
  }
  const controls = [
    ...document.querySelectorAll(
      'input.qbaseCSS, input[id^="txtAns"], input.boxStyle, input[id$="_optchk"]'
    ),
  ].filter((element) => element.getBoundingClientRect().height > 0);
  if (controls.length === 0) {
    return null;
  }
  const answerTop = Math.min(
    ...controls.map((element) => element.getBoundingClientRect().top),
  );
  // The same verbs the question probe reads instructions with. Two lists drift:
  // this one had no `graph`, `identify`, `select` or `round`, so an instruction
  // the probe recognised could be invisible to the crop and the question would
  // reach neither route.
  const instruction = /graph|simplify|evaluate|determine|convert|factor|express|rationaliz|find|add|subtract|multiply|expand|identify|write|state|name|list|select|choose|arrange|round|solve|calculate|perform|use the|following|assum/i;
  const candidates = [...document.querySelectorAll("p, div, span, td, math")]
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || rect.top >= answerTop) {
        return false;
      }
      if (element.localName === "math") {
        return true;
      }
      // A container's own words still count. Hawkes writes a figure question as
      // a bare text node beside a `div` holding the graph, so skipping every
      // container skipped the only element the instruction was in -- and with
      // no candidate there is no crop, which is the whole of
      // `errorQuestionRegion` on that layout.
      const value =
        element.querySelector("p, div, table") !== null
          ? [...element.childNodes]
              .filter((node) => node.nodeType === 3)
              .map((node) => node.textContent)
              .join(" ")
              .replace(/\s+/g, " ")
              .trim()
          : (element.textContent || "").trim();
      return value.length >= 4 && value.length < 500 && instruction.test(value);
    });
  if (candidates.length === 0) {
    return null;
  }
  const questionTop = Math.min(
    ...candidates.map((element) => element.getBoundingClientRect().top),
  );
  if (!Number.isFinite(questionTop) || answerTop - questionTop < 80) {
    return null;
  }
  const ratio = window.devicePixelRatio || 1;
  return {
    top: Math.max(0, frameOffsetTop + questionTop - 24) * ratio,
    bottom: Math.max(0, frameOffsetTop + answerTop - 8) * ratio,
  };
}

/** Capture the visible question only when exact page markup was insufficient. */
async function captureQuestion(tabId, frameId) {
  update({ stage: "capturing" });
  try {
    let bounds = null;
    if (settings.cropCapture) {
      const [measured] = await browser.scripting.executeScript({
        target: { tabId, frameIds: [frameId] },
        func: measureQuestionBounds,
      });
      bounds = measured?.result;
      if (!bounds) {
        fail("errorQuestionRegion");
        return null;
      }
    }
    let screenshot = await browser.tabs.captureVisibleTab({ format: "png" });
    if (settings.cropCapture) {
      screenshot = await cropToQuestion(screenshot, bounds);
      if (!screenshot) {
        fail("errorQuestionRegion");
        return null;
      }
    }
    return screenshot;
  } catch (error) {
    log.warn("capture-failed", { error: describeError(error) });
    // Reaching this line means the question DOM was already read through the
    // scoped Hawkes host grant. Firefox deliberately requires `activeTab` or
    // `<all_urls>` for a screenshot; the one-site grant is not enough. Calling
    // this a missing Hawkes grant made the sidebar request an already-present
    // permission forever. Keep the narrow permission model and tell the owner
    // to retry from the toolbar, whose click supplies `activeTab`.
    fail("errorNoCapture");
    return null;
  }
}

/** Whether a thrown page error is Firefox withholding host access. */
function permissionWithheld(error) {
  return /host permission|not allowed|Missing/i.test(String(error?.message ?? error));
}

// --- operations the popup can ask for --------------------------------------

/** Find the answer field and read the editor's rules. Cheap, and no model. */
async function prepare(windowId = state.windowId) {
  // A prepare re-reads the tab, the frame, the editor and the signature --
  // everything a solve in flight is working against -- and then blanks the
  // phase, which is the only thing stopping `autoSolve` starting another one.
  // Without this, opening the panel during a solve started a second solve
  // beside the first: three ran at once live, each publishing its own answer
  // over the last, and each reporting an elapsed time measured from whichever
  // had most recently overwritten `startedAt`.
  inFlight?.abort();
  inFlight = null;
  const restoringAnswer = await seedRememberedAnswer(windowId);
  const previous = {
    phase: state.phase,
    tabId: state.tabId,
    frameId: state.frameId,
    fieldId: state.fieldId,
    signature: state.signature,
    answer: state.answer,
    displayText: state.displayText,
    entryText: state.entryText,
    answerParts: Array.isArray(state.answerParts) ? state.answerParts : [],
    // Carried so it can be *revalidated*, never so it can be adopted: the
    // reader refuses a table for reasons about the controls rather than about
    // the question, and re-reading is not the only honest way to keep a
    // mapping this same question was already reviewed against.
    tableTargets: Array.isArray(state.tableTargets) ? state.tableTargets : [],
    editor: state.editor,
    graphPlan: state.graphPlan,
    graphCoefficients: Array.isArray(state.graphCoefficients)
      ? state.graphCoefficients
      : [],
    placedText: state.placedText,
    promptSeen: state.promptSeen,
    problemText: state.problemText,
    source: state.source,
    detail: state.detail,
  };
  update({ ...blankState(), phase: "checking", windowId });
  try {
    const tab = await activeHawkesTab(windowId);
    const results = await runOperation({ tabId: tab.id, allFrames: true }, INSPECT_SCRIPT);
    const choice = selectAnswerFrame(results);
    const chosenReport = results.find((entry) => entry?.frameId === choice.frameId)?.result;
    const evidenceReport = chosenReport ?? results.find(
      (entry) => entry?.result?.multiFieldEvidence
    )?.result;
    log.info("answer-target-inspected", {
      code: chosenReport?.code ?? choice.code ?? "",
      fields: Array.isArray(choice.fieldIds) ? choice.fieldIds.length : 0,
      // Which window, tab and frame this run is about. Everything downstream
      // is scoped by the three of them -- a solve reads that frame, an
      // insertion writes to it, and a panel in another window is shown a blank
      // -- and until now the only entry that named them was one raised after
      // an insertion had already gone wrong.
      windowId,
      tabId: tab.id,
      frameId: Number.isInteger(choice.frameId) ? choice.frameId : null,
      frames: results.length,
      // Which branch of the field probe claimed this target. A question that
      // reports one field while two solution fields exist can be solved and
      // never inserted, because insertion wants one field id per answer part.
      via: evidenceReport?.via ?? "",
      multiFieldEvidence: evidenceReport?.multiFieldEvidence ?? null,
    });
    if (!Number.isInteger(choice.frameId)) {
      fail(frameErrorKey(choice), {
        detail: describeResults(results),
        args: choice.origin ? [choice.origin] : [],
      });
      return;
    }
    const editor = await describeEditor(tab.id, choice.frameId, 5, choice.graph === true);
    if (choice.graph && (!editor?.ok || editor.kind !== "graph")) {
      fail("errorEditorUnknown", { detail: editor?.code ?? "graph-missing" });
      return;
    }
    const swept = answerFieldIds(choice, evidenceReport?.multiFieldEvidence, editor);
    if (
      swept.length > 0
      && (swept.length < 2
        || swept.length > MAX_ANSWER_PARTS
        || editor?.kind !== "multi"
        || editor.editors?.length !== swept.length)
    ) {
      // Which of the four disagreements it was. This refusal fired live on a
      // two-field question that Facet had already answered exactly, and the
      // log said only "the answer editor could not be read" -- true of a page
      // whose editor model never loaded, of one that describes a single box
      // where the DOM shows two, and of one that describes a different number
      // of them. Those are three different faults and one message.
      fail("errorEditorUnknown", {
        detail:
          `fields=${swept.length} editor=${editor?.kind ?? "none"}`
          + ` editors=${editor?.editors?.length ?? 0} ok=${Boolean(editor?.ok)}`
          + `${editor?.code ? ` code=${editor.code}` : ""}`,
      });
      return;
    }
    // Kept at `info`, and complete. `answer-needs-template` names one of
    // fraction, radical, exponent and parentheses against an unknown character
    // set, and reading that back off the page cost a screenshot of the owner's
    // coursework to reach a guess. All of this is what the page says about its
    // own control -- what it accepts, what it offers, whether it is even
    // typeable -- and none of it is what anybody typed into it.
    log.info("editor-described", {
      kind: editor?.kind,
      ok: editor?.ok,
      code: editor?.code ?? "",
      enabled: editor?.enabled === true,
      maxLength: editor?.maxLength ?? null,
      allowedCharacters: String(editor?.allowedCharacters ?? "").slice(0, 48),
      templates: editor?.templates,
      slots: editor?.slots ?? null,
      editors: editor?.editors?.length ?? 0,
      // What the page's own control collection held, beside the control chosen
      // out of it. One textbox reported against five boxes on screen is four
      // different faults and one description without this.
      collection: editor?.collection ?? null,
    });
    if (swept.length >= 2) {
      log.info("multi-editor-described", {
        fieldIds: swept,
        editorNames: editor.editors.map((item) => item.name),
        allowedCharacters: editor.editors.map((item) => item.allowedCharacters),
        templates: editor.editors.map((item) => item.templates),
      });
    }
    const question = await readQuestion(tab.id, choice.frameId);
    const signature = questionSignature(question);
    // A question we could not read is never treated as the previous one.
    // Identity is the question's own content and nothing about the editor:
    // which box has the caret and what state the answer controls are in both
    // change while the question on screen does not, and treating either as a
    // new question threw away a correct answer and solved it again.
    const sameQuestion = signature !== null
      && sameQuestionSignature(signature, previous.signature)
      && tab.id === previous.tabId
      && choice.frameId === previous.frameId;
    // The table's own mapping, re-acquired from this read. The controls under
    // it are the page's and are re-found every time, so a re-render that keeps
    // the grid and renumbers its boxes is followed rather than written into
    // blindly -- and where this read cannot state the mapping at all, the one
    // this same question was already reviewed against is revalidated against
    // the boxes the page is showing rather than discarded.
    const readTargets = tableTargetsOf(question);
    const tableTargets = readTargets.length >= 2
      ? readTargets
      : revalidatedTableTargets(
        sameQuestion ? previous.tableTargets ?? [] : [],
        evidenceReport?.multiFieldEvidence?.fieldIds ?? []
      );
    // Two readings can both claim to have found the answer's fields, and only
    // one of them knows which cell is which. The geometric sweep sorts boxes
    // top-to-bottom and left-to-right; the live completion grid's records run
    // down its columns, so that order names a different cell for every blank.
    // Where a table has been accepted, its mapping is the answer surface and
    // the sweep is dropped rather than reconciled.
    const fieldIds = tableTargets.length >= 2 ? [] : swept;
    // What the other reading saw at the same moment, so a disagreement between
    // the two is visible without another run: the boxes the geometric sweep
    // found, and whichever of them it was willing to adopt.
    noteTableTargets(tableTargets, question, {
      swept: evidenceReport?.multiFieldEvidence?.fieldIds ?? [],
      adopted: fieldIds,
      // Whether this read stated the mapping, or whether the one already
      // reviewed against this question was revalidated against the page.
      via: readTargets.length >= 2 ? "read" : "revalidated",
    });
    const alreadyInserted = sameQuestion && previous.phase === "inserted";
    const hasAnswer = sameQuestion
      && (previous.answer !== "" || previous.answerParts?.length >= 2);
    // What was answered, and what answered it, describe a question that is
    // still on screen in both cases -- so they outlive the insertion that
    // consumed the answer itself. Without this the sidebar watcher blanked the
    // card, the source and the recognized problem 1.5 seconds after a
    // successful insertion, on its very next tick.
    const context = hasAnswer || alreadyInserted;
    log.info("question-identified", { signature, sameQuestion, alreadyInserted });
    update({
      phase: alreadyInserted ? "inserted" : hasAnswer ? "solved" : "ready",
      tabId: tab.id,
      frameId: choice.frameId,
      fieldId: choice.fieldId ?? "",
      fieldIds,
      tableTargets,
      editor: hasAnswer && previous.graphPlan ? previous.editor : editor,
      signature,
      // Carried over only while the question is unchanged, so a previous
      // answer can never be offered for a new one.
      answer: hasAnswer ? previous.answer : "",
      displayText: hasAnswer ? previous.displayText : "",
      entryText: hasAnswer ? previous.entryText : "",
      answerParts: hasAnswer ? previous.answerParts : [],
      graphPlan: hasAnswer ? previous.graphPlan : null,
      graphCoefficients: hasAnswer ? previous.graphCoefficients : [],
      promptSeen: hasAnswer ? previous.promptSeen : true,
      placedText: alreadyInserted ? previous.placedText : "",
      problemText: context ? previous.problemText : "",
      source: context ? previous.source : "",
      detail: context ? previous.detail : "",
      stage: sameQuestion ? "done" : "",
    });
    if (restoringAnswer) {
      log.info(hasAnswer ? "answer-session-restored" : "answer-session-discarded", {
        why: hasAnswer ? "question-matched" : "question-changed",
        answerLength: hasAnswer
          ? String(previous.displayText || previous.answer || "").length
          : 0,
      });
    }
    // Insertion handles this question. Keep that state across a sidebar watch
    // tick and a close/reopen; solve again only when prompt/MathML changes.
    if (alreadyInserted || hasAnswer) {
      return;
    }
    await settingsReady;
    if (settings.autoSolve) {
      solve();
    }
  } catch (error) {
    fail(errorKeyOf(error));
  }
}

function frameErrorKey(choice) {
  if (choice.code === "focus-in-subframe") {
    return choice.origin ? "errorFrameUnreachableAt" : "errorFrameUnreachable";
  }
  return (
    {
      "no-focused-answer-field": "errorNoFocusedField",
      "field-not-editable": "errorFieldNotEditable",
      "wrong-site": "errorWrongSite",
      "ambiguous-frame": "errorFrameAmbiguous",
      "editor-dialog-open": "errorEditorDialogOpen",
    }[choice.code] ?? "errorNoBridge"
  );
}

function errorKeyOf(error) {
  const key = error?.message;
  return typeof key === "string" && key.startsWith("error") ? key : "errorNoBridge";
}

/** Capture the question and solve it. Survives the popup closing. */
async function solve(windowId = state.windowId) {
  if (state.phase === "solving") {
    return;
  }
  if (state.tabId === null) {
    await prepare(windowId);
    if (state.phase !== "ready") {
      return;
    }
  }

  await settingsReady;
  // The phase guard above is checked before two awaits and is therefore not
  // enough on its own: `prepare` can blank the phase, and `prepare` itself
  // starts a solve when `autoSolve` is on. Assigning `inFlight` used to
  // overwrite a live controller, leaving the earlier solve unreachable and
  // running -- so it finished, and published its answer, long after the panel
  // had moved on. Whatever was in flight is cancelled here instead.
  inFlight?.abort();
  const controller = new AbortController();
  inFlight = controller;
  log.info("solve-started", {
    solveTimeoutSeconds: settings.solveTimeoutSeconds,
    cropCapture: settings.cropCapture,
  });
  // A retry must not keep presenting the previous result while new work is in
  // flight. Apart from being confusing, a failed retry used to leave that old
  // answer beside the failure and make it look usable for the current read.
  update({
    phase: "solving",
    startedAt: Date.now(),
    answer: "",
    displayText: "",
    entryText: "",
    answerParts: [],
    graphPlan: null,
    graphCoefficients: [],
    placedText: "",
    promptSeen: true,
    problemText: "",
    source: "",
    detail: "",
    errorKey: "",
  });

  try {
    // Confirm the companion is even installed before spending a minute on a
    // capture.
    const health = await askEthnos(
      "health", {}, HEALTH_TIMEOUT_MS, undefined, controller.signal
    );
    if (health?.status !== "ok") {
      throw new Error("errorEthnosUnreachable");
    }
    if (controller.signal.aborted) {
      return;
    }

    update({ stage: "capturing" });

    // The page's own MathML first. It is exact, instant, and needs no
    // permission beyond the one already used to reach the tab. A screenshot is
    // the fallback for a question drawn as an image — and `captureVisibleTab`
    // needs `activeTab` or all-sites access, neither of which a sidebar has,
    // so it is not always available at all.
    const question = (await readQuestion(state.tabId, state.frameId)) ?? {
      promptText: "",
      expressions: [],
    };
    // Kept at `info`, not `debug`. What the add-on managed to read of the
    // question is the first fork in every failure -- an exact reading that
    // then failed and a reading that was refused are different faults -- and
    // requiring it to have been turned up in advance meant a live failure
    // never had it. None of it is the question: counts and verdicts only.
    runFacts.evidence = {
      read: "markup",
      expressions: question.expressions.length,
      graph: question.evidence?.graph ?? "unknown",
      table: question.evidence?.table ?? "unknown",
      answerTable: question.evidence?.answerTable ?? "unknown",
      answerTableDetail: question.evidence?.answerTableDetail ?? null,
      promptChars: question.evidence?.promptChars ?? 0,
    };
    log.info("question-read", {
      expressions: runFacts.evidence.expressions,
      graph: runFacts.evidence.graph,
      table: runFacts.evidence.table,
      answerTable: runFacts.evidence.answerTable,
      answerTableDetail: runFacts.evidence.answerTableDetail,
      promptChars: runFacts.evidence.promptChars,
    });
    // The answer about to be solved belongs to the question just read, not to
    // whatever was on screen when the panel opened. The same is true of the
    // table mapping: the grid crossing to the host and the controls its blanks
    // will come back to are two halves of this one read, and pairing them
    // across two reads is the mistake that puts part 1 in part 3's box.
    const tableTargets = tableTargetsOf(question);
    update({
      signature: questionSignature(question) ?? state.signature,
      tableTargets,
    });
    noteTableTargets(tableTargets, question, { adopted: state.fieldIds ?? [] });
    runFacts.evidence.signature = state.signature ?? "";
    if (controller.signal.aborted) {
      return;
    }

    let screenshot = "";
    if (!readableQuestion(question)) {
      // The page stated nothing this add-on could read exactly, and the next
      // forty-five seconds are a model looking at a picture. Which reading was
      // refused, and why, is the one fact worth having here: without it the
      // log says only that a question had no markup, which is true of a
      // genuine image question and of nine different extraction faults alike.
      runFacts.evidence = {
        ...runFacts.evidence,
        read: "refused",
        expressions: question.expressions?.length ?? 0,
        graph: question.evidence?.graph ?? "unknown",
        table: question.evidence?.table ?? "unknown",
        answerTable: question.evidence?.answerTable ?? "unknown",
        answerTableDetail: question.evidence?.answerTableDetail ?? null,
        promptChars: question.evidence?.promptChars ?? 0,
      };
      noteRunEvent("evidence-refused");
      log.info("evidence-refused", {
        expressions: runFacts.evidence.expressions,
        graph: runFacts.evidence.graph,
        table: runFacts.evidence.table,
        answerTable: runFacts.evidence.answerTable,
        answerTableDetail: runFacts.evidence.answerTableDetail,
        promptChars: runFacts.evidence.promptChars,
      });
      screenshot = await captureQuestion(state.tabId, state.frameId);
      if (screenshot === null) {
        return;
      }
      if (controller.signal.aborted) {
        return;
      }
    }

    const solveDeadline = Date.now() + settings.solveTimeoutSeconds * 1000;
    const shape = answerShapeOf(state.editor, question.answerTable, tableTargets);
    const askToSolve = (image, pipeline) => {
      log.info("host-request-shaped", {
        pipeline,
        answerTable: Boolean(question.answerTable),
        tableRows: question.answerTable?.rows?.length ?? 0,
        tableColumns: question.answerTable?.columns?.length ?? 0,
        tableBlanks: question.answerTable?.rows?.flatMap((row) => row)
          .filter((cell) => Number.isInteger(cell?.blank)).length ?? 0,
        answerShape: shape.kind,
        answerParts: shape.count ?? 0,
        // How many cells this browser can place an answer in. Asking for five
        // values while holding no mapping is a solve that could never be
        // inserted, and the two counts belong in the same line.
        tableTargets: tableTargets.length,
      });
      return askEthnos(
        "solve_hawkes_problem",
        {
          origin: "https://learn.hawkeslearning.com",
          solve_engine: pipeline,
          problem: {
            prompt_text: question.promptText || "",
            mathml: question.expressions,
            ...(question.graphPoints ? { graph_points: question.graphPoints } : {}),
            // The table's own reading of itself: headings and cells, exactly
            // as the page wrote them. No element, no selector, no geometry.
            ...(question.dataTable ? { data_table: question.dataTable } : {}),
            // The table the answer is typed into, when the question is
            // answered by completing one: the same headings and cells, with a
            // numbered blank where each answer goes. The boxes themselves,
            // their ids and their rules stay here.
            ...(question.answerTable ? { answer_table: question.answerTable } : {}),
            screenshot_png_base64: image,
            answer_shape: shape,
          },
        },
        Math.max(1, solveDeadline - Date.now()),
        (progress) => {
          log.debug("stage", { stage: progress.stage });
          update({ stage: progress.stage, stageDetail: progress.detail ?? "" });
        },
        controller.signal
      );
    };

    // Facet is asked about the mathematics, never about a picture: it has no
    // reader for one, so sending the capture here would hand image data to a
    // path that cannot use it and would be refused anyway.
    let reply = await askToSolve("", SOLVE_PIPELINE);
    // Facet answers what the page states as mathematics. A question drawn as a
    // picture states none, and markup can be perfectly readable yet outside the
    // solvers' current vocabulary -- both come back `unsupported`, and both are
    // then read from an image instead. Capture only after that cheap path
    // explicitly declines, so an ordinary question leaves no screenshot and
    // pays no vision-model cost.
    if (reply?.status === "unsupported" && !controller.signal.aborted) {
      // The host says which decline this was; without it a live fallback
      // reports only that the exact path did not work, which is the one thing
      // already obvious from the minute it then takes.
      log.info("markup-fallback", {
        expressions: question.expressions.length,
        why: String(reply.message || "").slice(0, 120),
      });
      if (screenshot.length === 0) {
        screenshot = await captureQuestion(state.tabId, state.frameId);
        if (screenshot === null || controller.signal.aborted) {
          return;
        }
      }
      reply = await askToSolve(screenshot, IMAGE_PIPELINE);
    }
    if (controller.signal.aborted) {
      return;
    }
    await acceptReply(reply);
  } catch (error) {
    // A cancellation is not a failure; `cancel` has already set the panel back.
    if (!controller.signal.aborted && error?.message !== "errorCancelled") {
      fail(errorKeyOf(error));
    }
  } finally {
    if (inFlight === controller) {
      inFlight = null;
    }
  }
}

/**
 * The most readable form of an answer, for the panel to show.
 *
 * Kept separate from the form that gets inserted. The readable one may contain
 * notation no answer box would accept -- a fraction bar, a radical sign -- and
 * gating the display on what is typeable is what left the panel showing
 * `sqrt(30)*sqrt(y)*sqrt(z)/(5*z)` when it had `√(30yz)/(5z)` to hand.
 *
 * @param {{display_text?: string, keyboard_entry?: string}} answer
 * @returns {string}
 */
function readableAnswer(answer) {
  const display = (answer.display_text ?? "").trim();
  if (display.length === 0) {
    return (answer.keyboard_entry ?? "").trim();
  }
  // The solver writes fractions as LaTeX; the panel is plain text. A compound
  // denominator keeps its parentheses, or "1/12x^7y" reads as "(1/12)x^7y".
  // Bare only for a plain number or a single variable: "√(30yz)/5z" reads as
  // "(√(30yz)/5)·z", which is a different value.
  const group = (side) =>
    /^[0-9]+$|^[A-Za-z](\^[0-9]+)?$/.test(side) ? side : `(${side})`;
  let readable = display;
  for (let depth = 0; depth < 3; depth += 1) {
    readable = readable.replace(
      /\\frac\{([^{}]*)\}\{([^{}]*)\}/g,
      (_, numerator, denominator) =>
        `${/[+\-]/.test(numerator) ? `(${numerator})` : numerator}/${group(denominator)}`
    );
  }
  return readable.replace(/\\/g, "").trim() || display;
}

/**
 * The companion's refusals, as labels this file owns.
 *
 * Every entry matches one `error_response` in `ethnos/hawkes_host.py`, and a
 * test asserts the correspondence in both directions -- so a new refusal there
 * fails the suite here rather than arriving in the log as "unclassified".
 */
const REFUSAL_REASONS = Object.freeze([
  ["no-question-content", /^No question content was supplied/i],
  ["origin-not-allowed", /^The requesting origin is not allowed/i],
  ["markup-not-solved-exactly", /^The question's markup was not solved exactly/i],
  ["missing-answer-parts", /^Facet did not return the \d+ separate answers/i],
  ["facet-did-not-answer", /^Facet did not answer/i],
  ["facet-answer-unusable", /^Facet returned no usable answer/i],
  ["no-mathematics-on-the-page", /^Facet needs mathematics read from the page/i],
  ["no-final-answer", /^Ethnos produced no final answer/i],
  ["table-question-refused", /^Table question refused/i],
  ["regression-refused", /^Regression refused/i],
  ["graph-plan-refused", /^Graph plan refused/i],
  ["invalid-request", /^Invalid request/i],
  ["malformed-message", /^Malformed message/i],
  ["not-an-object", /^Message was not an object/i],
  ["host-exception", /^[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Interrupt):/],
]);

/** Which refusal this was, named from the list above and never from the text. */
function refusalReason(message) {
  const found = REFUSAL_REASONS.find(([, pattern]) => pattern.test(message));
  return found ? found[0] : "unclassified";
}

async function acceptReply(reply) {
  if (reply.status !== "ready" || !reply.answer) {
    // What the companion said, in the two parts that are safe to keep.
    //
    // `errorSolveRefused` was the whole of what the ring recorded, and it
    // covers a question Facet's solvers declined, a transport that failed, and
    // a reply that arrived shaped wrongly -- three faults fixed in three
    // different places. The panel shows the full message; the log did not
    // carry even the status.
    //
    // The message itself is never written. Keeping its first clause would be
    // safe today only by accident: a decline reason can be `str(refusal)` from
    // `facet_runtime.exact`, and a nested reason that interpolated before its
    // own colon would put the question into a ring that promises never to hold
    // it. So the message is classified against {@link REFUSAL_REASONS} and the
    // label written is one this file authored. `status` is a closed set in
    // `hawkes_protocol.py` and is safe as it stands.
    const message = String(reply.message ?? "");
    runFacts.refusal = refusalReason(message);
    noteRunEvent("solve-refused");
    log.warn("solve-refused", {
      status: String(reply.status ?? "none"),
      hasAnswer: Boolean(reply.answer),
      why: runFacts.refusal,
    });
    fail("errorSolveRefused", {
      detail: message || String(reply.status).slice(0, 400),
    });
    return;
  }
  const certainty = reply.certainty ?? {};
  // Where Facet sent this question and what answered it, kept from here on:
  // every failure below this line is one a retained record should be able to
  // attribute to a route and a runtime, including the ones that never reach a
  // solved state.
  runFacts.certainty = certainty;
  const notes = provenanceNotes(certainty);
  if (certainty.prompt_seen === false) {
    notes.push("Instruction not read from the page");
  }
  if (certainty.issues?.length) {
    notes.push(...certainty.issues.slice(0, 4));
  }
  // Remembered so the settings page can name the configured reasoner without
  // making a network request to ask. It is the last thing actually observed,
  // and is shown as such rather than as a current fact.
  if (certainty.facet_invoked && certainty.model && certainty.runtime) {
    rememberFacetRun(certainty);
  }


  if (reply.answer.graph_plan) {
    if (state.editor?.kind !== "graph" || certainty.answered_by !== "facet" || !certainty.facet_invoked || !certainty.insertable
      || reply.answer.graph_coefficients?.length !== 3) {
      fail("errorAnswerInvalid");
      return;
    }
    update({ phase: "solved", stage: "done", solveRun: currentRun(),
      answer: reply.answer.display_text,
      displayText: reply.answer.display_text, entryText: "", answerParts: [],
      graphPlan: reply.answer.graph_plan, graphCoefficients: reply.answer.graph_coefficients,
      problemText: reply.problem_text, source: [answeredByBadge(certainty), certainty.model, certainty.device].filter(Boolean).join(" · "), detail: notes.join("\n"), errorKey: "" });
    log.info("graph-plan-validated", { facetInvoked: true, facetModel: certainty.model, backend: certainty.actual_backend, device: certainty.device, elapsedMs: certainty.elapsed_ms });
    lastSolve = { run: currentRun(), certainty, answerLength: reply.answer.display_text.length };
    return;
  }
  const displayText = readableAnswer(reply.answer);
  if (displayText.length === 0) {
    fail("errorAnswerInvalid", { detail: JSON.stringify(reply.answer).slice(0, 300) });
    return;
  }

  const answerParts = Array.isArray(reply.answer.parts)
    ? reply.answer.parts.filter((value) => typeof value === "string")
    : [];
  const hasParts = answerParts.length >= 2
    && answerParts.length <= MAX_ANSWER_PARTS
    && answerParts.every((value) => validateAnswer(value).ok);
  // What may be typed is a narrower question than what may be shown. A
  // multi-part answer keeps the readable equality only as its reviewed
  // identity; its entry values remain separate all the way to the field writer.
  const candidates = [reply.answer.display_text, reply.answer.keyboard_entry].filter(
    (value) => typeof value === "string" && validateAnswer(value).ok
  );
  const answer = hasParts
    ? displayText
    : candidates.find((value) => answerFitsEditor(value, state.editor).insertable) ??
      candidates[0] ??
      "";
  // Neither form of the answer survived `validateAnswer`. Publishing "solved"
  // anyway put a readable answer on the card with nothing behind it: Insert
  // stayed disabled, and the panel -- finding no answer to check against the
  // editor -- reported "the answer editor could not be read", blaming the one
  // part of the page that was working. Live, on `√-27`, for eight solves.
  if (answer.length === 0) {
    fail("errorAnswerInvalid", { detail: displayText.slice(0, 300) });
    return;
  }
  const entryText = hasParts
    ? ""
    :
    typeof reply.answer.keyboard_entry === "string"
    && validateAnswer(reply.answer.keyboard_entry).ok
      ? reply.answer.keyboard_entry
      : answer;

  log.info("solved", {
    source: certainty.source ?? "",
    answeredBy: certainty.answered_by ?? "",
    facetInvoked: Boolean(certainty.facet_invoked),
    insertable: Boolean(certainty.insertable),
    answerLength: answer.length,
    answerParts: answerParts.length,
    hostAnswerParts: Number.isInteger(certainty.answer_parts) ? certainty.answer_parts : 0,
    elapsedMs: state.startedAt ? Date.now() - state.startedAt : 0,
    // Which machinery answered. The panel has shown this in its provenance
    // block from the beginning; the log had it only for a graph plan, so
    // "which model and which device handled it" was unanswerable afterwards
    // for every ordinary question -- the common case.
    //
    // Prefixed names, exactly as `rememberFacetRun` prefixes them and for the
    // same reason: an unprefixed execution-config key in this file is
    // indistinguishable from the browser naming one to the host, which it must
    // never do and which a test asserts by reading the file. These are what
    // the host reported back.
    facetReading: certainty.reading ?? "",
    facetRouter: certainty.router ?? "",
    facetMethod: certainty.method ?? "",
    facetRuntime: certainty.runtime ?? "",
    facetModel: certainty.model ?? "",
    facetRequestedBackend: certainty.requested_backend ?? "",
    facetBackend: certainty.actual_backend ?? "",
    facetDevice: certainty.device ?? "",
    facetFallback: Boolean(certainty.fallback),
    stages: runStages.join(">"),
  });
  // An answer the editor will take neither as text nor as keypad steps leaves
  // Insert disabled, and nothing sends `ethnos:insert` -- so the diagnostic log
  // recorded a clean solve and then silence, with no failure to look for. Live,
  // six solves in a row ended that way on `2sqrt(2(-x^9))`. The panel already
  // shows the editor's own objection; this is so the log shows it too.
  const partsFit = hasParts
    && (tableAnswerFits(answerParts, state.tableTargets ?? [], state.editor)
      || multiAnswerFits(answerParts, state.editor)
      || commaAnswerPlan(answerParts, state.editor, reply.problem_text) !== null);
  let partsFailure = null;
  if (hasParts && !partsFit) {
    // Everything needed to see why, in one line: the answer's shape, the
    // shape the page published, and what each of the three entry routes said
    // about each part.
    partsFailure = describePartsFailure(
      answerParts, state.editor, reply.problem_text, state.tableTargets ?? []
    );
    noteRunEvent("answer-parts-unplaceable");
    log.info("answer-parts-unplaceable", partsFailure);
  }
  if (hasParts && state.editor?.kind !== "multi" && (state.tableTargets ?? []).length < 2) {
    log.info("multi-answer-editor-described", {
      allowedCharacters: state.editor?.allowedCharacters ?? "",
      slots: state.editor?.slots ?? {},
      templates: state.editor?.templates ?? {},
      commaPrompt: /separate multiple answers with a comma/i.test(
        reply.problem_text ?? ""
      ),
    });
  }
  const fits = hasParts
    ? { insertable: partsFit, code: "answer-parts" }
    : answerFitsEditor(answer, state.editor);
  const plan = hasParts
    ? { ok: false, code: "answer-parts" }
    : planEntry(entryText, state.editor);
  if (!fits.insertable && plan.ok === false) {
    // Which route said what, per answer part, so the record can be grouped by
    // the disagreement rather than by the question it happened on.
    runFacts.notInsertable = {
      editor: fits.code ?? "",
      plan: plan.code ?? "",
      directFit: partsFailure?.directFit ?? [],
      plannedFit: partsFailure?.plannedFit ?? [],
    };
    noteRunEvent("answer-not-insertable");
    log.warn("answer-not-insertable", {
      source: certainty.source ?? "",
      editor: fits.code,
      plan: plan.code,
      answerLength: answer.length,
      ...(hasParts ? {} : describeFieldFailure(answer, state.editor, fits, plan)),
    });
  }
  update({
    phase: "solved",
    stage: "done",
    solveRun: currentRun(),
    answer,
    displayText,
    entryText,
    answerParts: hasParts ? answerParts : [],
    problemText: reply.problem_text ?? "",
    source: answeredByBadge(certainty),
    // Absent means an older host that cannot report it; only an explicit false
    // is treated as "the question reached the model unlabelled".
    promptSeen: certainty.prompt_seen !== false,
    detail: notes.join("\n"),
    errorKey: certainty.insertable ? "" : "errorTranscriptionDisputed",
  });
  log.info("answer-retained", {
    answerParts: Array.isArray(state.answerParts) ? state.answerParts.length : 0,
    panels: panels.size,
  });
  // The answer this solve produced, kept past the end of this run so the
  // insertion -- a separate gesture, a separate run -- can still say what
  // answered the question it is about to fail on.
  lastSolve = { run: currentRun(), certainty, answerLength: answer.length };
  // Two endings that are not failures and are not successes either.
  //
  // A solve the editor will not take shows an answer, leaves Insert disabled,
  // and sends nothing: the ring recorded a clean solve followed by silence,
  // and there was no failure to go looking for. A disputed transcription
  // solved something, and said the page may not have been read as written.
  // Both are terminal, both are diagnostic, and neither raises `fail`.
  if (runFacts.notInsertable) {
    retain("not-insertable", { phase: "solved", stage: "done" });
  } else if (!certainty.insertable) {
    retain("disputed", { errorKey: "errorTranscriptionDisputed", phase: "solved", stage: "done" });
  }
}

/**
 * Build a structured answer with the editor's own templates.
 *
 * Only reached when the answer cannot simply be typed. The plan is worked out
 * beforehand from this question's permitted templates and character set, so
 * this either performs it or reports which step the editor refused.
 */
async function buildStructured(answer, cadence, target, editor) {
  // Planning consumes explicit machine notation (`sqrt(30)*y/30`), not the
  // compact display (`y√30/30`). Keeping those roles separate removes an
  // entire class of radical-boundary and implicit-multiplication bugs.
  const plan = planEntry(answer, editor);
  if (plan.ok === false) {
    return plan;
  }
  let results;
  try {
    results = await runScoredEntry(target, plan.steps, cadence, () => browser.scripting.executeScript({
      // The pinned frame, never the live one: this call is the write.
      target: { tabId: target.tabId, frameIds: [target.frameId] },
      world: "MAIN",
      func: enterPlan,
      args: [plan.steps, cadence],
    }));
  } catch (error) {
    return { ok: false, code: errorKeyOf(error) };
  }
  return results?.[0]?.result ?? { ok: false, code: "editor-model-missing" };
}

/**
 * Everything an insertion is allowed to know about where it is writing.
 *
 * Taken synchronously, before the first `await`, and never re-read from the
 * live state afterwards. `state` is one mutable object shared by every window,
 * and `prepare()` replaces its identity wholesale -- so an insertion that
 * re-read `state.tabId` between awaits could be pointed at a different tab
 * part-way through. It would then validate the *new* question against the
 * *new* signature, agree with itself, and write the answer reviewed for one
 * window into another window's answer box.
 *
 * Paced entry made that window seconds wide rather than milliseconds.
 *
 * @typedef {object} InsertionTarget
 * @property {number | null} windowId
 * @property {number} tabId
 * @property {number} frameId
 * @property {string} fieldId
 * @property {string[]} fieldIds
 * @property {object[]} tableTargets blank-to-control mapping, in blank order
 * @property {string | null} signature the question the answer was reviewed for
 * @property {string} reviewed the answer as shown and approved
 * @property {string} machineEntry the form the panel planned and offered
 * @property {string[]} answerParts independently planned roots, when present
 * @property {string} problemText exact instruction used to choose an answer separator
 */

/** Snapshot the insertion target. Must be called before any `await`. */
function pinInsertionTarget() {
  return Object.freeze({
    windowId: state.windowId,
    tabId: state.tabId,
    frameId: state.frameId,
    fieldId: state.fieldId,
    fieldIds: Object.freeze([...(state.fieldIds ?? [])]),
    // Frozen with everything else, and for the same reason: the mapping is
    // what says which box each value belongs in, so it must not be re-read
    // from the live state between the awaits of a paced insertion.
    tableTargets: Object.freeze((state.tableTargets ?? []).map(
      (target) => Object.freeze({ ...target })
    )),
    signature: state.signature,
    detail: state.detail,
    graphPlan: state.graphPlan,
    graphCoefficients: state.graphCoefficients,
    graphSnapshot: state.editor?.snapshot,
    solveRun: state.solveRun,
    reviewed: state.answer,
    machineEntry: state.entryText || state.answer,
    answerParts: Object.freeze([...(state.answerParts ?? [])]),
    problemText: state.problemText,
    // The readable form the card showed for review, kept so the settled
    // panel reports what was approved rather than whatever is live now.
    displayText: state.displayText,
  });
}

/**
 * Whether the live state is still the insertion this call claimed.
 *
 * Identity rather than a generation counter: anything that could redirect the
 * write -- `prepare`, `claim`, `reset`, a tab moving, a window closing --
 * changes the phase, and all but the narrowest also change the tab or the
 * signature. Comparing the fields themselves therefore needs no extra
 * bookkeeping to keep honest, and it is conservative in the safe direction: a
 * re-prepare of this very question aborts rather than writing on.
 */
function ownsTarget(target) {
  return ownershipDelta(target).length === 0;
}

/**
 * The components {@link ownsTarget} compares, one predicate each.
 *
 * Written out rather than folded into one boolean so that a lost insertion can
 * say *which* thing moved. "The target changed" was true of a tab that moved
 * windows, a question that advanced, an answer that was re-solved and a panel
 * in a second window claiming the state -- four different faults reported in
 * one sentence, and the log gave nothing to tell them apart.
 */
const OWNERSHIP_COMPONENTS = Object.freeze({
  phase: (target) => state.phase === "inserting",
  windowId: (target) => state.windowId === target.windowId,
  tabId: (target) => state.tabId === target.tabId,
  frameId: (target) => state.frameId === target.frameId,
  fieldId: (target) => state.fieldId === target.fieldId,
  fieldIds: (target) => sameStringArray(state.fieldIds ?? [], target.fieldIds),
  tableTargets: (target) => sameTableMapping(state.tableTargets ?? [], target.tableTargets),
  answerParts: (target) => sameStringArray(state.answerParts ?? [], target.answerParts),
  signature: (target) => state.signature === target.signature,
  graphPlan: (target) => state.graphPlan === target.graphPlan,
  answer: (target) => state.answer === target.reviewed,
});

/** Which pinned components no longer match the live state, in fixed order. */
function ownershipDelta(target) {
  return Object.entries(OWNERSHIP_COMPONENTS)
    .filter(([, matches]) => !matches(target))
    .map(([name]) => name);
}

/**
 * The pinned snapshot as shapes, never as content.
 *
 * Identity and counts only: the answer and the question are the coursework,
 * and `common/log.js` would redact them anyway. What is worth keeping is
 * enough to recognise the same target again in a later entry.
 */
function ownershipSnapshot(target) {
  return {
    windowId: target.windowId,
    tabId: target.tabId,
    frameId: target.frameId,
    fieldId: target.fieldId,
    fieldIds: target.fieldIds.length,
    tableTargets: target.tableTargets.length,
    answerParts: target.answerParts.length,
    signature: target.signature,
    graphPlan: target.graphPlan ?? "",
    graphSnapshot: target.graphSnapshot ? Object.keys(target.graphSnapshot).length : 0,
    // The run that produced what is about to be written. An insertion is its
    // own gesture and its own run; this is the join back to the solve.
    solvedIn: target.solveRun ?? "",
    answerLength: String(target.reviewed ?? "").length,
  };
}

/**
 * Give up an insertion whose target is no longer ours, without retargeting.
 *
 * Reported against the pinned target, and only while the live state still
 * belongs to the same window: once another window owns the state, saying
 * anything into it would put this window's failure on that window's panel.
 */
function abandonInsertion(target, why) {
  log.warn("insertion-target-changed", {
    why,
    // The step that noticed, and the components that actually moved. One of
    // these says when, the other says what.
    changed: ownershipDelta(target).join(","),
    pinned: ownershipSnapshot(target),
    nowPhase: state.phase,
    wasWindow: target.windowId,
    nowWindow: state.windowId,
    wasTab: target.tabId,
    nowTab: state.tabId,
  });
  if (state.windowId === target.windowId) {
    fail("errorInsertionAbandoned");
  }
}

/** Put the reviewed answer in the field. */
async function insert() {
  if (state.phase === "inserting" || state.tabId === null) {
    return;
  }
  // Pinned before anything can yield. Everything below reads this and never
  // the live state, so no concurrent `prepare` can move where the write lands.
  const target = pinInsertionTarget();
  log.info("insertion-pinned", ownershipSnapshot(target));
  const reviewed = target.reviewed;
  // Claim the insertion synchronously. Two panel messages can enter this
  // function in the same turn; publishing the busy phase after yielding lets
  // both pass the guard and write the same answer twice.
  update({ phase: "inserting" });
  await settingsReady;
  if (!ownsTarget(target)) {
    abandonInsertion(target, "settings");
    return;
  }

  // The tab is looked up by window when the field is found; this confirms the
  // ownership still holds at the moment of writing. An event can be missed, or
  // arrive after a click has already been dispatched -- a check here cannot
  // be, and this is the one operation that changes the page.
  try {
    const tab = await browser.tabs.get(target.tabId);
    if (Number.isInteger(target.windowId) && tab.windowId !== target.windowId) {
      log.warn("tab-left-its-window-before-insert", {
        was: target.windowId, now: tab.windowId,
      });
      fail("errorTabMoved");
      return;
    }
  } catch (error) {
    log.warn("answer-tab-unreadable", { error: describeError(error) });
    fail("errorTabMoved");
    return;
  }
  if (!ownsTarget(target)) {
    abandonInsertion(target, "tab-check");
    return;
  }

  // Re-read the editor's rules now. They are published per question, and the
  // panel's copy was taken when the field was found -- which may have been a
  // different question. Checking an answer against a stale character set is
  // how a perfectly legal `y` came to be reported as rejected.
  const editor = target.graphPlan
    ? await describeEditor(target.tabId, target.frameId, 5, true)
    : await describeEditor(target.tabId, target.frameId);
  if (!editor?.ok) {
    fail("errorEditorUnknown");
    return;
  }
  if (!ownsTarget(target)) {
    abandonInsertion(target, "editor");
    return;
  }
  update({ editor });

  // Confirm the answer still belongs to the question on screen. Hawkes swaps
  // questions in place, so an answer solved a moment ago can outlive the
  // question it answers -- and inserting it would put a confident, wrong
  // answer in the box. Only a question that reads cleanly and differs is
  // grounds for refusing. An unreadable question is also refused: inserting
  // against an unknown question is never safe.
  // Read from the pinned frame and compared against the pinned signature. Read
  // from the live state instead, a retargeted insertion compared the new
  // question against the new signature, agreed with itself, and wrote on.
  // One read, used for both halves of the same question: the signature that
  // says it is still this question, and the mapping that says where its
  // answers go. Two reads could disagree with each other while each agreed
  // with itself, which is the whole shape of a wrong-box insertion.
  const liveQuestion = await readQuestion(target.tabId, target.frameId);
  const onScreen = questionSignature(liveQuestion);
  if (onScreen === null || target.signature === null) {
    fail("errorQuestionUnverified");
    return;
  }
  if (!sameQuestionSignature(onScreen, target.signature)) {
    log.warn("question-changed-before-insert", { was: target.signature, now: onScreen });
    fail("errorQuestionChanged");
    prepare(target.windowId);
    return;
  }
  if (!ownsTarget(target)) {
    abandonInsertion(target, "question-check");
    return;
  }

  if (target.graphPlan) {
    if (editor.kind !== "graph" || JSON.stringify(editor.snapshot) !== JSON.stringify(target.graphSnapshot)) {
      // Which of the four parts of the snapshot moved, and nothing of what any
      // of them says: a graph snapshot holds the question, its XML, the plotted
      // points and the answer so far, all of it coursework. Without this the
      // refusal was silent, and a live session hitting it a dozen times could
      // not say whether the question, the plot or the answer had changed.
      const was = target.graphSnapshot ?? {};
      const now = editor.snapshot ?? {};
      log.warn("graph-target-stale-before-insert", {
        kind: editor.kind,
        moved: ["question", "xml", "points", "answer"].filter(
          (part) => JSON.stringify(was[part]) !== JSON.stringify(now[part])
        ),
      });
      fail("errorQuestionChanged", { detail: "graph-target-stale" });
      return;
    }
    const [entry] = await runInjection({ target: { tabId: target.tabId, frameIds: [target.frameId] },
      world: "MAIN", func: graphOperation, args: [{ plan: target.graphPlan, coefficients: target.graphCoefficients, snapshot: target.graphSnapshot }] });
    if (!ownsTarget(target)) { abandonInsertion(target, "graph-actuation"); return; }
    if (!entry?.result?.ok) { fail("errorSolveRefused", { detail: entry?.result?.code ?? "graph-verification-failed" }); return; }
    log.info("graph-verified", { events: entry.result.events });
    await finishInsertion(target.detail + "\nGraph controls and coefficients verified", target);
    return;
  }

  // A typeable answer goes in as text; anything with structure has to be
  // built with the keypad templates, one step at a time.
  // Both entry paths perform on the same cadence; only the machinery differs.
  const cadence = resolveEntryCadence(settings);
  // A performance now runs for seconds, so how long it actually took is the
  // one thing worth recording. The answer itself never enters the log.
  const entryStartedAt = Date.now();
  if (target.answerParts.length >= 2 && target.tableTargets.length >= 2) {
    // The mapping, read again from the page by the same reader that made it,
    // and compared cell by cell against the one the answer was reviewed
    // against. Nothing here re-derives a target: a disagreement is a refusal,
    // because the only two readings that exist have stopped agreeing about
    // which control holds which blank.
    const liveTargets = tableTargetsOf(liveQuestion);
    // Where this read states the mapping, it must agree cell for cell. Where
    // it states none -- a cell showing two controls because the owner clicked
    // into it is enough -- the mapping is revalidated against the boxes the
    // page is actually showing instead. That is the same standard the check
    // above exists for: a grid renumbered under us fails it, because the ids
    // the answer was reviewed against are no longer on the page.
    let revalidated = false;
    if (!sameTableMapping(liveTargets, target.tableTargets)) {
      const showing = liveTargets.length === 0
        ? await sweptAnswerFields(target.tabId, target.frameId)
        : [];
      revalidated =
        revalidatedTableTargets(target.tableTargets, showing).length
        === target.tableTargets.length;
      if (!revalidated) {
        log.warn("table-targets-changed-before-insert", {
          was: tableTargetShapes(target.tableTargets),
          now: tableTargetShapes(liveTargets),
          blanks: liveTargets.length,
          showing: showing.length,
        });
        fail("errorQuestionChanged", { detail: "table-targets-changed" });
        return;
      }
      log.info("table-targets-revalidated", {
        blanks: target.tableTargets.length,
        showing: showing.length,
      });
      if (!ownsTarget(target)) {
        abandonInsertion(target, "table-target-revalidation");
        return;
      }
    }
    if (!tableAnswerFits(target.answerParts, target.tableTargets, editor)) {
      // The editor was re-read a moment ago, so this is the question's own
      // current character rule against the answer that was approved.
      log.warn("table-answer-no-longer-fits", describePartsFailure(
        target.answerParts, editor, target.problemText, target.tableTargets
      ));
      fail("errorEditorUnknown", { detail: "table-answer-refused" });
      return;
    }
    if (!ownsTarget(target)) {
      abandonInsertion(target, "before-table-write");
      return;
    }
    const frame = { tabId: target.tabId, frameIds: [target.frameId] };
    let outcome;
    try {
      const cells = target.tableTargets.map((one) => one.id);
      const [entry] = await runScoredEntry(
        target,
        target.answerParts.map((text) => ({ op: "type", text })),
        cadence,
        // The page's own world. A completion cell is a controlled editor: the
        // page owns a model per cell and routes `input` through the one it has
        // selected, which no isolated script can see or move. Writing from
        // outside it put four parts in their cells and the fifth in someone
        // else's, and reported five successful writes.
        () => runInjection({
          target: frame,
          world: "MAIN",
          func: enterTableCells,
          args: [[...target.answerParts], cells, cadence],
        })
      );
      outcome = entry?.result;
      if (
        !outcome?.ok
        || outcome.code !== "entered-table-cells"
        || !sameStringArray(outcome.cells, cells)
        || outcome.settled !== cells.length
      ) {
        log.warn("table-answer-not-placed", {
          code: outcome?.code ?? "no-result",
          blank: outcome?.blank ?? 0,
          // Which other cell a write moved, when one did: the failure that
          // used to be indistinguishable from success.
          moved: outcome?.moved ?? 0,
          where: outcome?.where ?? "",
          written: outcome?.written ?? 0,
          leftBehind: outcome?.leftBehind === true,
          cells: cells.length,
        });
        fail(insertErrorKey(outcome?.code ?? "table-answer-incomplete"));
        return;
      }
    } catch (error) {
      fail(errorKeyOf(error));
      return;
    }
    log.info("inserted", {
      via: "table-cells",
      fields: target.tableTargets.length,
      parts: target.answerParts.length,
      answerLength: reviewed.length,
      // What was established, not how many writes returned. Every cell settled
      // holding its own part with no other cell moving; `models` says how many
      // of the page's own control buffers agreed as well, and the two lists
      // say how each cell was tied to a control and how each was selected.
      settled: outcome.settled,
      models: outcome.models ?? 0,
      ownership: outcome.ownership ?? [],
      selected: outcome.selected ?? [],
      elapsedMs: Date.now() - entryStartedAt,
    });
    await finishInsertion(
      `entered all ${target.answerParts.length} table cells`, target
    );
    return;
  }
  if (target.answerParts.length >= 2) {
    const commaPlan = commaAnswerPlan(
      target.answerParts, editor, target.problemText
    );
    if (commaPlan !== null) {
      if (!ownsTarget(target)) {
        abandonInsertion(target, "before-comma-parts-write");
        return;
      }
      let built;
      try {
        const results = await runScoredEntry(target, commaPlan.steps, cadence, () => browser.scripting.executeScript({
          target: { tabId: target.tabId, frameIds: [target.frameId] },
          world: "MAIN",
          func: enterPlan,
          args: [commaPlan.steps, cadence],
        }));
        built = results?.[0]?.result;
      } catch (error) {
        fail(errorKeyOf(error));
        return;
      }
      if (!built?.ok || built.code !== "entered") {
        const detail = built?.detail ?? "";
        fail(insertErrorKey(built?.code ?? "answer-parts-incomplete"), {
          detail,
          args: detail ? [detail] : [],
        });
        return;
      }
      log.info("inserted", {
        via: "structured-comma-parts",
        fields: 1,
        parts: target.answerParts.length,
        answerLength: reviewed.length,
        elapsedMs: Date.now() - entryStartedAt,
      });
      await finishInsertion("entered both comma-separated answers", target);
      return;
    }
    const multiEntry = multiEntryPlans(target.answerParts, editor);
    if (multiEntry === null || target.fieldIds.length !== target.answerParts.length) {
      fail("errorEditorUnknown");
      return;
    }
    const reports = await runOperation(
      { tabId: target.tabId, frameIds: [target.frameId] }, INSPECT_SCRIPT
    );
    const live = selectAnswerFrame(reports);
    // Adopted here the same way as at the earlier gate, against the editor
    // model read a moment ago. Comparing a raw reading here against an adopted
    // one there would refuse every question this agreement exists to place.
    const liveEvidence = reports.find(
      (entry) => entry?.result?.multiFieldEvidence
    )?.result?.multiFieldEvidence;
    const liveFieldIds = answerFieldIds(live, liveEvidence, editor);
    if (
      live.frameId !== target.frameId
      || live.fieldId !== target.fieldId
      || !sameStringArray(liveFieldIds, target.fieldIds)
      || !ownsTarget(target)
    ) {
      // Its sibling gate above says what changed; this one said nothing, so a
      // refusal here was indistinguishable from the question genuinely moving
      // on. Ids only -- never an answer, and never the question's text.
      log.warn("answer-fields-changed-before-insert", {
        wasFrame: target.frameId, nowFrame: live.frameId,
        wasField: target.fieldId, nowField: live.fieldId,
        wasFields: target.fieldIds, nowFields: liveFieldIds,
        editorKind: editor?.kind, editors: editor?.editors?.length,
        candidates: liveEvidence?.fieldIds?.length,
        owned: ownsTarget(target),
      });
      fail("errorQuestionChanged");
      return;
    }
    const plain = multiEntry.plain;
    let outcome;
    if (plain) {
      const [entry] = await runScoredEntry(target, target.answerParts.map((text) => ({ op: "type", text })), cadence, () => runInjection({
        target: { tabId: target.tabId, frameIds: [target.frameId] },
        func: enterPlainAnswerParts,
        args: [target.answerParts, target.fieldIds, cadence],
      }));
      outcome = entry?.result;
      if (
        !outcome?.ok
        || outcome.code !== "native-input-fields"
        || !sameStringArray(outcome.entered, target.answerParts)
      ) {
        fail(insertErrorKey(outcome?.code ?? "answer-parts-incomplete"));
        return;
      }
    } else {
      try {
        const results = await runScoredEntry(target, multiEntry.plans.map((plan) => plan.steps), cadence, () => browser.scripting.executeScript({
          target: { tabId: target.tabId, frameIds: [target.frameId] },
          world: "MAIN",
          func: enterPlan,
          args: [multiEntry.plans.map((plan) => plan.steps), cadence, target.fieldIds],
        }));
        outcome = results?.[0]?.result;
      } catch (error) {
        fail(errorKeyOf(error));
        return;
      }
      if (
        !outcome?.ok
        || outcome.code !== "entered-fields"
        || !sameStringArray(outcome.enteredFields, target.fieldIds)
        || outcome.completed !== target.answerParts.length
      ) {
        fail(insertErrorKey(outcome?.code ?? "answer-parts-incomplete"));
        return;
      }
    }
    log.info("inserted", {
      via: plain ? "plain-fields" : "structured-fields",
      fields: target.fieldIds.length,
      parts: target.answerParts.length,
      answerLength: reviewed.length,
      elapsedMs: Date.now() - entryStartedAt,
    });
    await finishInsertion(`entered all ${target.answerParts.length} answer fields`, target);
    return;
  }
  const typeable = reviewed && answerFitsEditor(reviewed, editor).insertable;
  if (!typeable) {
    // The last check before the page is changed.
    if (!ownsTarget(target)) {
      abandonInsertion(target, "before-structured-write");
      return;
    }
    // This is the same machine form the panel planned and offered for review.
    // Replanning the readable answer can produce different template steps.
    const built = await buildStructured(target.machineEntry, cadence, target, editor);
    if (built.ok) {
      log.info("inserted", {
        via: "structured",
        answerLength: reviewed.length,
        elapsedMs: Date.now() - entryStartedAt,
        // The writer's own view of the performance: how late the browser woke
        // each write against its score offset, and how long the editor held the
        // phrase building structure. Present even when nothing was listening.
        timing: built.timing,
      });
      await finishInsertion(`entered: ${built.entered ?? ""}`, target);
    } else {
      fail(insertErrorKey(built.code), { detail: built.detail ?? built.code });
    }
    return;
  }

  try {
    const frame = { tabId: target.tabId, frameIds: [target.frameId] };
    // Refresh the isolated-world prelude immediately before the one-shot
    // function. No answer is written to storage, even briefly.
    await runOperation(frame, INSPECT_SCRIPT);
    // The last check before the page is changed.
    if (!ownsTarget(target)) {
      abandonInsertion(target, "before-plain-write");
      return;
    }
    const [entry] = await runScoredEntry(target, [{ op: "type", text: reviewed }], cadence, () => runInjection({
      target: frame,
      func: enterPlainAnswer,
      args: [reviewed, cadence],
    }));
    const outcome = entry?.result;
    if (!outcome || typeof outcome !== "object") {
      fail("errorNoBridge");
      return;
    }
    if (!outcome.ok) {
      fail(insertErrorKey(outcome.code));
      return;
    }
    if (outcome.answer !== reviewed) {
      fail("errorAnswerChanged");
      return;
    }
    log.info("inserted", {
      via: "plain",
      code: outcome.code,
      answerLength: reviewed.length,
      elapsedMs: Date.now() - entryStartedAt,
    });
    await finishInsertion("", target);
  } catch (error) {
    fail(errorKeyOf(error));
  }
}

/**
 * Settle after a successful insertion.
 *
 * The reviewed answer is dropped: nothing may insert it twice, and it must
 * never be offered for a later question. What is kept instead is `placedText`,
 * a display-only copy for the panel's card. Clearing both left the largest
 * element in the panel showing an em dash at the exact moment the add-on had
 * succeeded, which read as the answer having been lost.
 *
 * The signature deliberately remains: it marks this exact question handled,
 * preventing the sidebar watcher (or a close/reopen) from solving it a second
 * time. A real prompt/MathML change has a different signature and starts the
 * next solve normally.
 */
async function finishInsertion(detail, target) {
  // Paced entry runs for seconds, so ownership can have moved while the
  // characters were going in. The answer is already in the pinned field and
  // cannot be unwritten -- but the state that would record it may now describe
  // a different window, and publishing "inserted" into that would put this
  // window's result on another window's panel. Say so in the log and leave
  // the live state alone.
  if (!ownsTarget(target)) {
    log.warn("insertion-finished-after-ownership-change", {
      wasWindow: target.windowId,
      nowWindow: state.windowId,
    });
    return;
  }
  // Structured entry changes Hawkes' rendered answer mathematics. Depending
  // on its geometry, that can also change what the read-only question probe
  // sees, even though the prompt itself has not advanced. The watcher is
  // paused while phase === "inserting", so rebase the handled fingerprint now
  // before publishing "inserted". Otherwise the next 1.5-second watch tick
  // mistakes our own insertion for a new question and solves it twice.
  let handledSignature = target.signature;
  try {
    const afterInsertion = await readQuestion(target.tabId, target.frameId, 2);
    handledSignature = questionSignature(afterInsertion) ?? handledSignature;
  } catch (error) {
    log.debug("post-insert-question-read-failed", { error: describeError(error) });
  }
  update({
    phase: "inserted",
    errorKey: "",
    detail,
    // Readable form, matching what the card showed a moment ago for review.
    placedText: target.displayText || target.reviewed,
    answer: "",
    displayText: "",
    entryText: "",
    answerParts: [],
    graphPlan: null,
    graphCoefficients: [],
    // `problemText` and `source` are left as they are: both describe the
    // question still on screen, which the insertion did not change.
    signature: handledSignature,
    stage: "",
    stageDetail: "",
  });
}

async function reset(windowId = state.windowId) {
  inFlight?.abort();
  inFlight = null;
  state = { ...blankState(), windowId };
  update({ phase: "idle" });
  await prepare(windowId);
}

/**
 * Make the asking window the one this state describes.
 *
 * There is one state, and it names the tab that answers are read from and
 * written to. A request from a different window must therefore rebuild it,
 * which drops the previous window's answer -- so an answer solved in one
 * window can never be inserted into another. Insertion after a switch finds no
 * answer and refuses, which is the correct outcome rather than a near miss.
 */
async function claim(windowId) {
  if (!Number.isInteger(windowId) || state.windowId === windowId) {
    return;
  }
  log.info("panel-window-changed", { was: state.windowId, now: windowId });
  inFlight?.abort();
  inFlight = null;
  state = { ...blankState(), windowId };
  await prepare(windowId);
}

function cancel() {
  cancelCadence();
  inFlight?.abort();
  inFlight = null;
  update({
    phase: state.tabId === null ? "idle" : "ready",
    startedAt: 0,
    stage: "",
    stageDetail: "",
    errorKey: "",
    detail: "",
  });
}

/** Start an operation without letting its failure escape as unhandled. */
function begin(operation) {
  startRun();
  operation().catch((error) => fail(errorKeyOf(error)));
}

/**
 * Answer the settings page's connection check.
 *
 * `health` loads no model, so this is a real answer in a moment: either the
 * native host is registered and running, or it is not. Before this, the only
 * way to find out was to start a solve and wait for it to fail.
 */
async function reportHealth(port) {
  const startedAt = Date.now();
  // Not a panel operation, so `begin` never named it. Without a run of its own
  // its host call would borrow whichever solve happened to be last.
  startRun();
  try {
    const reply = await askEthnos("health", {}, HEALTH_TIMEOUT_MS);
    const ok = reply?.status === "ok";
    log.info("health-checked", { ok, elapsedMs: Date.now() - startedAt });
    port.postMessage({
      type: "ethnos:health-result",
      ok,
      elapsedMs: Date.now() - startedAt,
      errorKey: ok ? "" : "errorSolveRefused",
    });
  } catch (error) {
    // A companion that does not answer is a diagnostic terminal state of its
    // own, and the one an unattended session is least able to explain later:
    // the settings page shows a red line and the ring holds one entry.
    noteRunEvent("health-failed");
    log.warn("health-failed", { error: describeError(error) });
    retain("failed", { errorKey: errorKeyOf(error), phase: "health", stage: "health" });
    port.postMessage({
      type: "ethnos:health-result",
      ok: false,
      elapsedMs: Date.now() - startedAt,
      errorKey: errorKeyOf(error),
    });
  }
}

/**
 * The settings page, while it is open.
 *
 * A second port name rather than `runtime.sendMessage`, so this event page has
 * exactly one inbound channel and every message on it is named.
 */
function attachSettingsPage(port) {
  port.onMessage.addListener((incoming) => {
    if (incoming?.type === "ethnos:health") {
      reportHealth(port).catch((error) =>
        log.error("health-report-failed", { error: describeError(error) })
      );
    }
  });
}

/**
 * Notice the question changing while a panel is open.
 *
 * Hawkes swaps questions in place: no navigation, no `tabs.onUpdated`, no
 * event of any kind. The question was re-checked when the panel opened, which
 * is enough for the popup -- it closes whenever focus moves -- but the sidebar
 * stays open, so a solved answer sat there across question changes. A worded
 * answer is the worst case: "Not a Real Number" is still readable, still looks
 * deliberate, and belongs to the question before.
 *
 * @type {number | undefined}
 */
let questionWatch;

/**
 * Consecutive failed reads before the watcher rebuilds what it watches.
 *
 * Three ticks is under five seconds, long enough to ride out a question being
 * swapped in and short enough that the guard is never off for long.
 */
const WATCH_FAILURES_BEFORE_REPREPARE = 3;
let watchFailures = 0;

function watchQuestion() {
  if (questionWatch !== undefined) {
    return;
  }
  questionWatch = setInterval(async () => {
    if (panels.size === 0) {
      stopWatchingQuestion();
      return;
    }
    // Never interrupt work in flight; a solve reads the question itself.
    if (["checking", "solving", "inserting"].includes(state.phase)) {
      return;
    }
    if (state.tabId === null || state.frameId === null || state.signature === null) {
      return;
    }
    try {
      // The question text can stay identical while selecting "One Solution"
      // replaces the option-only target with its aria-controlled text box.
      // Re-run the same all-frame ownership decision used by prepare so that
      // handoff is noticed without weakening insertion's target checks.
      const reports = await runOperation(
        { tabId: state.tabId, allFrames: true }, INSPECT_SCRIPT
      );
      const target = selectAnswerFrame(reports);
      // Successful structured entry replaces the editor's base input with its
      // template slots. That is our own mutation, not a question transition.
      // The prompt/MathML comparison below still notices the real Next event.
      // A different frame is a handoff. A different *box* in the same frame is
      // the owner clicking into their own answer, which used to re-prepare
      // this panel every 1.5 seconds -- discarding a correct answer and
      // solving the question again while they typed it in by hand.
      const targetChanged = state.phase !== "inserted"
        && Number.isInteger(target.frameId)
        && target.frameId !== state.frameId;
      const question = await readQuestion(state.tabId, state.frameId, 1);
      const now = questionSignature(question);
      watchFailures = 0;
      if (targetChanged || (now !== null && !sameQuestionSignature(now, state.signature))) {
        log.debug("question-changed-while-open", {
          was: state.signature,
          now,
          targetChanged,
        });
        begin(() => prepare(state.windowId));
      }
    } catch (error) {
      // A frame that has gone -- Hawkes reloading its editor, the tab moving
      // on -- makes every read from here throw. Logged and swallowed, that
      // silently retired the one guard against a previous question's answer
      // staying on screen: it kept failing every tick and never said so.
      watchFailures += 1;
      log.debug("question-watch-failed", {
        attempts: watchFailures, error: describeError(error),
      });
      if (watchFailures >= WATCH_FAILURES_BEFORE_REPREPARE) {
        log.warn("question-watch-lost-the-frame", { attempts: watchFailures });
        watchFailures = 0;
        begin(() => prepare(state.windowId));
      }
    }
  }, QUESTION_WATCH_MS);
}

function stopWatchingQuestion() {
  watchFailures = 0;
  if (questionWatch !== undefined) {
    clearInterval(questionWatch);
    questionWatch = undefined;
  }
}

browser.runtime.onSuspend?.addListener(cancelCadence);

browser.runtime.onConnect.addListener((port) => {
  if (port.name.startsWith("facet-score:")) {
    attachCadencePort(port);
    return;
  }
  if (port.name === "ethnos:options") {
    attachSettingsPage(port);
    return;
  }
  if (port.name !== "ethnos:panel") {
    return;
  }
  log.debug("panel-connected", { phase: state.phase });
  panels.set(port, { windowId: null });
  // The panel renders from whatever is already here, so reopening mid-solve
  // shows the solve in progress instead of starting another.
  port.postMessage({ type: "ethnos:state", state: stateFor(null) });
  watchQuestion();

  port.onMessage.addListener((incoming) => {
    const entry = panels.get(port);
    if (entry && Number.isInteger(incoming?.windowId) && entry.windowId === null) {
      entry.windowId = incoming.windowId;
      // Now that this panel has a window, show it what belongs to it: either
      // the live state, or a blank if the state describes a different window.
      try {
        port.postMessage({ type: "ethnos:state", state: stateFor(entry.windowId) });
      } catch {
        panels.delete(port);
      }
    }
    // Undefined until the panel has said which window it is in, which makes
    // every operation fall back to its previous single-window behaviour rather
    // than act on a window it is only guessing at.
    const asking = entry?.windowId ?? undefined;
    switch (incoming?.type) {
      case "ethnos:hello":
        break;
      case "ethnos:prepare":
        begin(() => prepare(asking));
        break;
      case "ethnos:solve":
        begin(async () => {
          await claim(asking);
          await solve(asking);
        });
        break;
      case "ethnos:insert":
        begin(async () => {
          await claim(asking);
          try { await insert(); } finally { finishIdleCadence(); }
        });
        break;
      case "ethnos:cancel":
        cancel();
        break;
      case "ethnos:reset":
        begin(() => reset(asking));
        break;
      default:
        break;
    }
  });

  port.onDisconnect.addListener(() => {
    panels.delete(port);
    if (panels.size === 0) {
      stopWatchingQuestion();
    }
  });
});

// The panel can only report what it is told. An uncaught error here would
// otherwise leave it showing a state that has stopped advancing.
initLog("background", {
  level: defaultSettings().logLevel,
  onFatal: () => fail("errorNoBridge"),
  generation: GENERATION,
});
// The version goes in the log because working out which build is running is
// otherwise guesswork: a temporary add-on reports nothing about itself, and
// `about:debugging`'s Reload re-reads whichever file was first selected, so a
// newly built one can silently not be the one under test. An hour was spent
// diagnosing a fixed bug in a build that did not contain the fix.
settingsReady.then(() =>
  log.info("event-page-loaded", {
    version: MANIFEST_VERSION,
    generation: GENERATION,
    ...settings,
  })
);

/**
 * What the marker covers: every binding the event page imports, and its own
 * decision-making.
 *
 * A function rather than a constant, so that naming something that is not
 * there is a caught rejection and one `build-marker-unavailable` line. As a
 * top-level object literal it would be evaluated during module load, and a
 * stale entry in a diagnostic would stop the event page from starting at all.
 *
 * Named imports rather than module namespaces, for two reasons. It is the
 * sharper question -- this is the code the event page actually runs, not every
 * export a module happens to publish for the panel or the settings page. And
 * the offline harnesses evaluate these modules by concatenating them with the
 * import statements stripped, where a namespace object does not exist and a
 * marker built from one would take the whole event page down with it.
 *
 * A test asserts that every name this file imports appears below, so the list
 * cannot fall behind the imports it mirrors.
 */
function markedCode() {
  return {
    "common/answer-session.js#ANSWER_SESSION_KEY": ANSWER_SESSION_KEY,
    "common/answer-session.js#restoreSolvedAnswer": restoreSolvedAnswer,
    "common/answer-session.js#snapshotSolvedAnswer": snapshotSolvedAnswer,
    "common/build-marker.js#collectSources": collectSources,
    "common/build-marker.js#foldSources": foldSources,
    "common/cadence-session.js#attachCadencePort": attachCadencePort,
    "common/cadence-session.js#beginCadenceRun": beginCadenceRun,
    "common/cadence-session.js#cadenceMeasurements": cadenceMeasurements,
    "common/cadence-session.js#cancelCadence": cancelCadence,
    "common/cadence-session.js#createCadencePresentation": createCadencePresentation,
    "common/cadence-session.js#finishIdleCadence": finishIdleCadence,
    "common/cadence-session.js#insertionInstrument": insertionInstrument,
    "common/cadence-session.js#observeCadence": observeCadence,
    "common/cadence.js": globalThis.ethnosCadence,
    "common/config.js#ALLOWED_HOST_PATTERN": ALLOWED_HOST_PATTERN,
    "common/config.js#MAX_ANSWER_PARTS": MAX_ANSWER_PARTS,
    "common/config.js#validateAnswer": validateAnswer,
    "common/editor-plan.js#planAnswerParts": planAnswerParts,
    "common/editor-plan.js#planEntry": planEntry,
    "common/editor-rules.js#answerFitsEditor": answerFitsEditor,
    "common/failure-record.js#buildFailureRecord": buildFailureRecord,
    "common/failure-record.js#recordFailure": recordFailure,
    "common/editor-rules.js#insertErrorKey": insertErrorKey,
    "common/editor-rules.js#isTableMapping": isTableMapping,
    "common/editor-rules.js#sameTableMapping": sameTableMapping,
    "common/editor-rules.js#tableAnswerFits": tableAnswerFits,
    "common/editor-rules.js#tableAnswerVerdicts": tableAnswerVerdicts,
    "common/frames.js#describeResults": describeResults,
    "common/frames.js#selectAnswerFrame": selectAnswerFrame,
    "common/graph-actions.js#graphOperation": graphOperation,
    "common/log.js#currentRun": currentRun,
    "common/log.js#describeError": describeError,
    "common/log.js#initLog": initLog,
    "common/log.js#log": log,
    "common/log.js#newRunId": newRunId,
    "common/log.js#setLogLevel": setLogLevel,
    "common/log.js#setRun": setRun,
    "common/page-actions.js#enterPlan": enterPlan,
    "common/table-actions.js#enterTableCells": enterTableCells,
    "common/settings.js#defaultSettings": defaultSettings,
    "common/settings.js#migrateSettings": migrateSettings,
    "common/settings.js#onSettingsChanged": onSettingsChanged,
    "common/settings.js#readSettings": readSettings,
    "common/settings.js#resolveEntryCadence": resolveEntryCadence,
    "background.js#acceptReply": acceptReply,
    "background.js#answerFieldIds": answerFieldIds,
    "background.js#answerShapeOf": answerShapeOf,
    "background.js#askEthnos": askEthnos,
    "background.js#buildStructured": buildStructured,
    "background.js#captureQuestion": captureQuestion,
    "background.js#commaAnswerPlan": commaAnswerPlan,
    "background.js#describeEditor": describeEditor,
    "background.js#describeFieldFailure": describeFieldFailure,
    "background.js#finishInsertion": finishInsertion,
    "background.js#insert": insert,
    "background.js#multiAnswerFits": multiAnswerFits,
    "background.js#multiEntryPlans": multiEntryPlans,
    "background.js#ownershipDelta": ownershipDelta,
    "background.js#pinInsertionTarget": pinInsertionTarget,
    "background.js#prepare": prepare,
    "background.js#questionSignature": questionSignature,
    "background.js#sameQuestionSignature": sameQuestionSignature,
    "background.js#revalidatedTableTargets": revalidatedTableTargets,
    "background.js#sweptAnswerFields": sweptAnswerFields,
    "background.js#retain": retain,
    "background.js#readQuestion": readQuestion,
    "background.js#readableAnswer": readableAnswer,
    "background.js#readableQuestion": readableQuestion,
    "background.js#refusalReason": refusalReason,
    "background.js#runScoredEntry": runScoredEntry,
      "background.js#solve": solve,
  };
}

/**
 * Say which code this is, once, after everything else has settled.
 *
 * The manifest version above is not an answer: a temporary add-on keeps it
 * across every edit. The marker is a digest of the files Firefox actually
 * loaded, so an observer hashing the source tree can say whether the running
 * add-on is that tree or something older.
 *
 * Deliberately not awaited by anything and deliberately last. It reads a few
 * hundred kilobytes of the add-on's own package, which is quick, but a solve
 * must never wait on a diagnostic -- and an event page must not be kept alive
 * by one either, which is why this is a single bounded pass rather than
 * anything periodic.
 */
settingsReady.then(() => {
  setTimeout(() => {
    Promise.resolve()
      .then(() => foldSources(collectSources(markedCode())))
      .then(
        (build) => {
          // Kept as well as logged: a retained failure record names the build
          // it happened on, which is how "still happening after the fix"
          // stays answerable once the ring holding this entry has rolled over.
          buildMarker = build.marker;
          log.info("build-marker", { ...build, generation: GENERATION });
        },
        (error) => log.debug("build-marker-unavailable", { error: describeError(error) })
      );
  }, 0);
});

// A new page means the old answer field is gone.
browser.tabs.onUpdated.addListener((tabId, info) => {
  if (tabId === state.tabId && info.status === "loading") {
    inFlight?.abort();
    inFlight = null;
    // The observer's own pagehide normally closes the port first. This is the
    // case where it cannot -- a navigation that discards the frame outright --
    // and a presentation pinned to a tab that has left must not play on.
    cancelCadence();
    state = blankState();
    syncRememberedAnswer(state);
  }
});

/**
 * Forget a tab that has moved between windows, or gone.
 *
 * `state` pairs one window with one tab, and both are captured when the field
 * is found. Dragging that tab out into a window of its own changes which
 * window it is in while its id stays the same, so the pair silently stops
 * describing anything real -- and the panel left behind would read from, and
 * insert into, a tab that is no longer in its window. Scoping the tab lookup
 * by window does not cover this: the lookup already happened.
 */
function forgetMovedTab(tabId) {
  if (tabId !== state.tabId) {
    return;
  }
  log.info("answer-tab-moved", { tabId, windowId: state.windowId });
  inFlight?.abort();
  inFlight = null;
  cancelCadence();
  // The window binding, not just the answer, is what went stale. Re-preparing
  // is the panel's own next step; this only makes sure nothing acts first.
  state = { ...blankState(), windowId: state.windowId };
  update({ phase: "idle" });
  // Leave the panel usable rather than parked at "Checking…" forever. The
  // window it belongs to is remembered, so this looks at whatever is in front
  // there now -- which after a detach is a different tab, correctly.
  if (panels.size > 0) {
    begin(() => prepare(state.windowId));
  }
}

/**
 * Hand the work on when the window it belongs to is closed.
 *
 * Panels in a closing window disconnect by themselves. The state does not: it
 * goes on naming a window that no longer exists, so `stateFor` shows every
 * surviving panel a blank of its own and nothing ever re-prepares. The panel
 * looks broken, and the only way back is pressing something.
 */
/**
 * Re-check when the window's front tab changes.
 *
 * A sidebar belongs to a window, not to a tab: it stays open as its window
 * moves between tabs, exactly as Firefox's own sidebars do. With nothing
 * watching for that, the panel went on showing a question and an answer that
 * belonged to a tab no longer in front -- reported as the add-on being
 * attached to every tab at once.
 *
 * Re-preparing drops an answer solved against the tab being left. That is the
 * safe direction and, since the exact path answers in about a second, a cheap
 * one: an answer still on screen for a tab you are no longer looking at is the
 * failure this whole class of bug keeps producing.
 */
browser.tabs.onActivated.addListener(({ windowId }) => {
  if (panels.size === 0 || windowId !== state.windowId) {
    return;
  }
  if (["checking", "solving", "inserting"].includes(state.phase)) {
    // Work in flight already holds the tab it targets, and a prepare is one.
    return;
  }
  begin(() => prepare(windowId));
});

browser.windows.onRemoved.addListener((windowId) => {
  for (const [port, entry] of panels) {
    if (entry.windowId === windowId) {
      panels.delete(port);
    }
  }
  if (state.windowId !== windowId) {
    return;
  }
  log.info("owning-window-closed", { windowId, panelsLeft: panels.size });
  inFlight?.abort();
  inFlight = null;
  cancelCadence();
  const survivor = [...panels.values()].find((entry) => Number.isInteger(entry.windowId));
  state = { ...blankState(), windowId: survivor ? survivor.windowId : null };
  update({ phase: "idle" });
  if (survivor) {
    begin(() => prepare(survivor.windowId));
  }
});

browser.tabs.onAttached.addListener(forgetMovedTab);
browser.tabs.onDetached.addListener(forgetMovedTab);
browser.tabs.onRemoved.addListener(forgetMovedTab);
