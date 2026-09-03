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

import { ALLOWED_HOST_PATTERN, validateAnswer } from "/common/config.js";
import { answerFitsEditor, insertErrorKey } from "/common/editor-rules.js";
import { planEntry } from "/common/editor-plan.js";
import { describeResults, selectAnswerFrame } from "/common/frames.js";
import { enterPlan } from "/common/page-actions.js";
import { describeError, initLog, log, setLogLevel } from "/common/log.js";
import { defaultSettings, onSettingsChanged, readSettings } from "/common/settings.js";

const NATIVE_HOST = "ethnos_hawkes";
const PROTOCOL_VERSION = 1;

/** How long `health` may take. It loads no model, so this is a connectivity
 *  check rather than a solve, and is not worth a preference. */
const HEALTH_TIMEOUT_MS = 8000;

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
  return settings;
}

onSettingsChanged((changed) => {
  settings = { ...settings, ...changed };
  if ("logLevel" in changed) {
    setLogLevel(changed.logLevel);
  }
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
    editor: null,
    problemText: "",
    answer: "",
    displayText: "",
    entryText: "",
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

function update(changes) {
  state = { ...state, ...changes };
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
  log.warn("failed", { errorKey, phase: state.phase, stage: state.stage });
  update({ phase: "failed", errorKey, errorArgs: args, detail });
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
    files: alone ? [operation] : [EDITOR_SCRIPT, operation],
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
    if (/host permission|not allowed|Missing/i.test(message)) {
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
function enterPlainAnswer(answer) {
  if (typeof ethnosHawkes === "undefined") {
    return { ok: false, code: "prelude-missing" };
  }
  if (!ethnosHawkes.originAllowed()) {
    return { ok: false, code: "wrong-site" };
  }
  if (!ethnosHawkes.answerIsSupported(answer)) {
    return { ok: false, code: "answer-invalid" };
  }
  const outcome = ethnosHawkes.insertAnswer(answer);
  return { ok: outcome.ok, code: outcome.code, answer };
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
        if (question.expressions.length > 0) {
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
function questionSignature(fieldId, question) {
  if (!question || question.expressions.length === 0) {
    return null;
  }
  const content = `${question.promptText}\u0000${question.expressions.join("\u0000")}`;
  return `${fieldId ?? ""}|${digest(content)}|${content.length}`;
}

/**
 * Read the editor's rules, retrying while it is still being built.
 *
 * Hawkes replaces its editor model when it swaps in the next question, and a
 * probe that lands in that gap sees nothing. Failing on the first read
 * reported "the answer editor could not be read" for an editor that was
 * simply a moment from existing.
 */
async function describeEditor(tabId, frameId, attempts = 5) {
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
  return { ok: false, code: "editor-model-missing" };
}

// --- Ethnos ----------------------------------------------------------------

/**
 * Ask the native host one named operation.
 *
 * `health` is answered without loading a model, which is what makes it worth
 * calling before a capture: an unregistered host is reported in a moment
 * rather than after a minute of waiting.
 */
async function askEthnos(operation, extra = {}, timeoutMs, onProgress, signal) {
  const request = {
    protocol_version: PROTOCOL_VERSION,
    operation,
    request_id: crypto.randomUUID(),
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
  const instruction = /simplify|evaluate|determine|convert|factor|express|rationaliz|find|solve|write|calculate|perform|use the|following|assum/i;
  const candidates = [...document.querySelectorAll("p, div, span, td, math")]
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || rect.top >= answerTop) {
        return false;
      }
      if (element.localName === "math") {
        return true;
      }
      if (element.querySelector("p, div, table")) {
        return false;
      }
      const value = (element.textContent || "").trim();
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
    fail("errorNoCapture");
    return null;
  }
}

// --- operations the popup can ask for --------------------------------------

/** Find the answer field and read the editor's rules. Cheap, and no model. */
async function prepare(windowId = state.windowId) {
  const previous = {
    phase: state.phase,
    signature: state.signature,
    answer: state.answer,
    displayText: state.displayText,
    entryText: state.entryText,
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
    if (!Number.isInteger(choice.frameId)) {
      fail(frameErrorKey(choice), {
        detail: describeResults(results),
        args: choice.origin ? [choice.origin] : [],
      });
      return;
    }
    const editor = await describeEditor(tab.id, choice.frameId);
    log.debug("editor-described", {
      kind: editor?.kind,
      ok: editor?.ok,
      templates: editor?.templates,
    });
    const question = await readQuestion(tab.id, choice.frameId);
    const signature = questionSignature(choice.fieldId, question);
    // A question we could not read is never treated as the previous one.
    const sameQuestion = signature !== null && signature === previous.signature;
    const alreadyInserted = sameQuestion && previous.phase === "inserted";
    const hasAnswer = sameQuestion && previous.answer !== "";
    // What was answered, and what answered it, describe a question that is
    // still on screen in both cases -- so they outlive the insertion that
    // consumed the answer itself. Without this the sidebar watcher blanked the
    // card, the source and the recognized problem 1.5 seconds after a
    // successful insertion, on its very next tick.
    const context = hasAnswer || alreadyInserted;
    log.debug("question-identified", { signature, sameQuestion, alreadyInserted });
    update({
      phase: alreadyInserted ? "inserted" : hasAnswer ? "solved" : "ready",
      tabId: tab.id,
      frameId: choice.frameId,
      fieldId: choice.fieldId ?? "",
      editor,
      signature,
      // Carried over only while the question is unchanged, so a previous
      // answer can never be offered for a new one.
      answer: hasAnswer ? previous.answer : "",
      displayText: hasAnswer ? previous.displayText : "",
      entryText: hasAnswer ? previous.entryText : "",
      promptSeen: hasAnswer ? previous.promptSeen : true,
      placedText: alreadyInserted ? previous.placedText : "",
      problemText: context ? previous.problemText : "",
      source: context ? previous.source : "",
      detail: context ? previous.detail : "",
      stage: sameQuestion ? "done" : "",
    });
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
    placedText: "",
    promptSeen: true,
    problemText: "",
    source: "",
    detail: "",
    errorKey: "",
  });

  try {
    // Confirm Ethnos is even installed before spending a minute on a capture.
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
    log.debug("question-read", { expressions: question.expressions.length });
    // The answer about to be solved belongs to the question just read, not to
    // whatever was on screen when the panel opened.
    update({ signature: questionSignature(state.fieldId, question) ?? state.signature });
    if (controller.signal.aborted) {
      return;
    }

    let screenshot = "";
    if (question.expressions.length === 0) {
      screenshot = await captureQuestion(state.tabId, state.frameId);
      if (screenshot === null) {
        return;
      }
      if (controller.signal.aborted) {
        return;
      }
    }

    const solveDeadline = Date.now() + settings.solveTimeoutSeconds * 1000;
    const askToSolve = (image) =>
      askEthnos(
        "solve_hawkes_problem",
        {
          origin: "https://learn.hawkeslearning.com",
          problem: {
            prompt_text: question.promptText || "",
            mathml: question.expressions,
            screenshot_png_base64: image,
          },
        },
        Math.max(1, solveDeadline - Date.now()),
        (progress) => {
          log.debug("stage", { stage: progress.stage });
          update({ stage: progress.stage, stageDetail: progress.detail ?? "" });
        },
        controller.signal
      );

    let reply = await askToSolve(screenshot);
    // Markup can be perfectly readable yet outside the exact solver's current
    // vocabulary. Capture only after that cheap path explicitly declines, so
    // ordinary questions leave no screenshot and pay no vision-model cost.
    if (
      reply?.status === "unsupported"
      && question.expressions.length > 0
      && screenshot.length === 0
      && !controller.signal.aborted
    ) {
      log.info("markup-fallback", { expressions: question.expressions.length });
      screenshot = await captureQuestion(state.tabId, state.frameId);
      if (screenshot === null || controller.signal.aborted) {
        return;
      }
      reply = await askToSolve(screenshot);
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

async function acceptReply(reply) {
  if (reply.status !== "ready" || !reply.answer) {
    fail("errorSolveRefused", {
      detail: String(reply.message || reply.status).slice(0, 400),
    });
    return;
  }
  const certainty = reply.certainty ?? {};
  const notes = [`source: ${certainty.source ?? "unknown"}`];
  if (certainty.prompt_seen === false) {
    notes.push("instruction not read from the page");
  }
  if (certainty.issues?.length) {
    notes.push(...certainty.issues.slice(0, 4));
  }


  const displayText = readableAnswer(reply.answer);
  if (displayText.length === 0) {
    fail("errorAnswerInvalid", { detail: JSON.stringify(reply.answer).slice(0, 300) });
    return;
  }

  // What may be typed is a narrower question than what may be shown.
  const candidates = [reply.answer.display_text, reply.answer.keyboard_entry].filter(
    (value) => typeof value === "string" && validateAnswer(value).ok
  );
  const answer =
    candidates.find((value) => answerFitsEditor(value, state.editor).insertable) ??
    candidates[0] ??
    "";
  const entryText =
    typeof reply.answer.keyboard_entry === "string"
    && validateAnswer(reply.answer.keyboard_entry).ok
      ? reply.answer.keyboard_entry
      : answer;

  log.info("solved", {
    source: certainty.source ?? "",
    insertable: Boolean(certainty.insertable),
    answerLength: answer.length,
    elapsedMs: state.startedAt ? Date.now() - state.startedAt : 0,
  });
  update({
    phase: "solved",
    stage: "done",
    answer,
    displayText,
    entryText,
    problemText: reply.problem_text ?? "",
    source: certainty.source ?? "",
    // Absent means an older host that cannot report it; only an explicit false
    // is treated as "the question reached the model unlabelled".
    promptSeen: certainty.prompt_seen !== false,
    detail: notes.join("; "),
    errorKey: certainty.insertable ? "" : "errorTranscriptionDisputed",
  });
}

/**
 * Build a structured answer with the editor's own templates.
 *
 * Only reached when the answer cannot simply be typed. The plan is worked out
 * beforehand from this question's permitted templates and character set, so
 * this either performs it or reports which step the editor refused.
 */
async function buildStructured(answer) {
  // Planning consumes explicit machine notation (`sqrt(30)*y/30`), not the
  // compact display (`y√30/30`). Keeping those roles separate removes an
  // entire class of radical-boundary and implicit-multiplication bugs.
  const plan = planEntry(answer, state.editor);
  if (plan.ok === false) {
    return plan;
  }
  let results;
  try {
    results = await browser.scripting.executeScript({
      target: { tabId: state.tabId, frameIds: [state.frameId] },
      world: "MAIN",
      func: enterPlan,
      args: [plan.steps],
    });
  } catch (error) {
    return { ok: false, code: errorKeyOf(error) };
  }
  return results?.[0]?.result ?? { ok: false, code: "editor-model-missing" };
}

/** Put the reviewed answer in the field. */
async function insert() {
  if (state.phase === "inserting" || state.tabId === null) {
    return;
  }
  const reviewed = state.answer;

  // The tab is looked up by window when the field is found; this confirms the
  // pairing still holds at the moment of writing. An event can be missed, or
  // arrive after a click has already been dispatched -- a check here cannot
  // be, and this is the one operation that changes the page.
  try {
    const tab = await browser.tabs.get(state.tabId);
    if (Number.isInteger(state.windowId) && tab.windowId !== state.windowId) {
      log.warn("tab-left-its-window-before-insert", {
        was: state.windowId, now: tab.windowId,
      });
      fail("errorTabMoved");
      return;
    }
  } catch (error) {
    log.warn("answer-tab-unreadable", { error: describeError(error) });
    fail("errorTabMoved");
    return;
  }

  update({ phase: "inserting" });

  // Re-read the editor's rules now. They are published per question, and the
  // panel's copy was taken when the field was found -- which may have been a
  // different question. Checking an answer against a stale character set is
  // how a perfectly legal `y` came to be reported as rejected.
  const editor = await describeEditor(state.tabId, state.frameId);
  if (!editor?.ok) {
    fail("errorEditorUnknown");
    return;
  }
  update({ editor });

  // Confirm the answer still belongs to the question on screen. Hawkes swaps
  // questions in place, so an answer solved a moment ago can outlive the
  // question it answers -- and inserting it would put a confident, wrong
  // answer in the box. Only a question that reads cleanly and differs is
  // grounds for refusing. An unreadable question is also refused: inserting
  // against an unknown question is never safe.
  const onScreen = questionSignature(state.fieldId, await readQuestion(state.tabId, state.frameId));
  if (onScreen === null || state.signature === null) {
    fail("errorQuestionUnverified");
    return;
  }
  if (onScreen !== state.signature) {
    log.warn("question-changed-before-insert", { was: state.signature, now: onScreen });
    fail("errorQuestionChanged");
    prepare();
    return;
  }

  // A typeable answer goes in as text; anything with structure has to be
  // built with the keypad templates, one step at a time.
  const typeable = reviewed && answerFitsEditor(reviewed, state.editor).insertable;
  if (!typeable) {
    const built = await buildStructured(reviewed);
    if (built.ok) {
      await finishInsertion(`entered: ${built.entered ?? ""}`);
    } else {
      fail(insertErrorKey(built.code), { detail: built.detail ?? built.code });
    }
    return;
  }

  try {
    const target = { tabId: state.tabId, frameIds: [state.frameId] };
    // Refresh the isolated-world prelude immediately before the one-shot
    // function. No answer is written to storage, even briefly.
    await runOperation(target, INSPECT_SCRIPT);
    const [entry] = await runInjection({
      target,
      func: enterPlainAnswer,
      args: [reviewed],
    });
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
    await finishInsertion("");
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
async function finishInsertion(detail) {
  // Structured entry changes Hawkes' rendered answer mathematics. Depending
  // on its geometry, that can also change what the read-only question probe
  // sees, even though the prompt itself has not advanced. The watcher is
  // paused while phase === "inserting", so rebase the handled fingerprint now
  // before publishing "inserted". Otherwise the next 1.5-second watch tick
  // mistakes our own insertion for a new question and solves it twice.
  let handledSignature = state.signature;
  try {
    const afterInsertion = await readQuestion(state.tabId, state.frameId, 2);
    handledSignature = questionSignature(state.fieldId, afterInsertion) ?? handledSignature;
  } catch (error) {
    log.debug("post-insert-question-read-failed", { error: describeError(error) });
  }
  update({
    phase: "inserted",
    errorKey: "",
    detail,
    // Readable form, matching what the card showed a moment ago for review.
    placedText: state.displayText || state.answer,
    answer: "",
    displayText: "",
    entryText: "",
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
    log.warn("health-failed", { error: describeError(error) });
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
      const question = await readQuestion(state.tabId, state.frameId, 1);
      const now = questionSignature(state.fieldId, question);
      watchFailures = 0;
      if (now !== null && now !== state.signature) {
        log.debug("question-changed-while-open", { was: state.signature, now });
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

browser.runtime.onConnect.addListener((port) => {
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
          await insert();
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
});
settingsReady.then(() => log.info("event-page-loaded", settings));

// A new page means the old answer field is gone.
browser.tabs.onUpdated.addListener((tabId, info) => {
  if (tabId === state.tabId && info.status === "loading") {
    inFlight?.abort();
    inFlight = null;
    state = blankState();
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
