"use strict";

/**
 * The panel is a view, not a worker.
 *
 * Every operation runs in the background event page, because a popup closes
 * whenever anything else takes focus and a solve takes the better part of a
 * minute. So this file renders whatever state the background reports, and
 * reopening the panel mid-solve shows the solve still running rather than
 * starting over.
 *
 * What to show is decided in `common/panel-view.js`, which has no DOM and can
 * therefore be run in the test suite. What is left here is the application of
 * that decision to elements, the wiring of the controls, and the panel's own
 * lifecycle — none of which the suite can reach, so all of it is kept thin and
 * every entry point is guarded.
 */

import { message, localizeDocument } from "../common/i18n.js";
import { ALLOWED_HOST_PATTERN } from "../common/config.js";
import { describeView } from "../common/panel-view.js";
import { initLog, log, flushLog, readLog, formatEntry, describeError } from "../common/log.js";
import { readSettings } from "../common/settings.js";

const elements = {
  badge: document.querySelector("#badge"),
  problemBlock: document.querySelector("#problem-block"),
  problem: document.querySelector("#problem"),
  answer: document.querySelector("#answer"),
  placed: document.querySelector("#placed"),
  copy: document.querySelector("#copy"),
  status: document.querySelector("#status"),
  progress: document.querySelector("#progress-fill"),
  detailToggle: document.querySelector("#detail-toggle"),
  detail: document.querySelector("#detail"),
  solve: document.querySelector("#solve"),
  insert: document.querySelector("#insert"),
  options: document.querySelector("#options"),
  reset: document.querySelector("#reset"),
  close: document.querySelector("#close"),
  dock: document.querySelector("#dock"),
  hint: document.querySelector("#hint"),
  fault: document.querySelector("#fault"),
  faultCopy: document.querySelector("#fault-copy"),
  faultReload: document.querySelector("#fault-reload"),
};

/** The last state the event page reported. */
let current = null;
/** Whether a state has ever arrived, which is also "has the panel settled". */
let settled = false;
/** Whether focus has already been moved to Insert for this answer. */
let handedOver = false;
/** Pending animation frame for a coalesced repaint. */
let frame = null;
/** Interval that advances the elapsed-seconds readout during a solve. */
let ticking = null;
/** What Enter does right now, as named by the view. */
let primary = "none";

/**
 * Whether this is the docked sidebar rather than the toolbar popup.
 *
 * A popup is torn down whenever anything else takes focus, which loses the
 * answer on screen mid-read. The sidebar stays put — and only the sidebar
 * keeps the event page's question watcher alive, so what the panel promises
 * after an insertion differs between the two. Same page either way; the
 * controls that make no sense in each are hidden.
 *
 * Read during the first paint, so it is declared before anything can render.
 */
const inSidebar = new URLSearchParams(window.location.search).get("sidebar") === "1";

/**
 * The link to the background page.
 *
 * A port rather than one-off messages: a panel closes whenever anything else
 * takes focus, and a request awaiting a reply then rejects into a destroyed
 * context. A port carries state in one direction, needs no reply, and
 * disconnects cleanly when the panel goes away.
 */
const port = browser.runtime.connect({ name: "ethnos:panel" });
let portOpen = true;
let recoveringPort = false;

/**
 * The window this panel is in, which the event page needs and cannot infer.
 *
 * Firefox gives every window its own sidebar, and a sidebar's port carries no
 * sender tab -- so without this the event page read "the current window",
 * meaning whichever was focused last. With two windows open, a solve started
 * here could read, and an insertion could write to, the other one's tab.
 *
 * Announced as soon as it is known rather than awaited: the port is already
 * registered and receiving state, and every request carries the id too, so a
 * click landing before this resolves is merely unscoped, never misdirected.
 */
let panelWindowId = null;
const announced = browser.windows
  .getCurrent()
  .then((info) => {
    panelWindowId = info.id;
    port.postMessage({ type: "ethnos:hello", windowId: info.id });
  })
  .catch((error) => log.warn("panel-window-unknown", { error: describeError(error) }));

/** Send one request. Only ever called once the window is known. */
function post(type) {
  try {
    port.postMessage({ type, windowId: panelWindowId });
    log.debug("panel-request", { type, windowId: panelWindowId });
    return true;
  } catch (error) {
    log.error("panel-request-failed", { type, error: describeError(error) });
    recoverPort();
    return false;
  }
}

/**
 * Ask the background to do something. Progress arrives back as state.
 *
 * Held until this panel knows which window it is in. Sent before that, the
 * event page has no window to scope the tab lookup to and falls back to "the
 * current window" -- whichever was focused last. The panel's own automatic
 * prepare fires on the first state and routinely beat `windows.getCurrent()`,
 * so a panel could point itself at a tab that had just been dragged out into
 * a new window, which is exactly the window that focus had moved to.
 */
function request(type) {
  if (!portOpen) {
    render(null);
    return false;
  }
  if (panelWindowId === null) {
    announced.finally(() => {
      if (portOpen) {
        post(type);
      }
    });
    return true;
  }
  return post(type);
}

/**
 * Stop presenting stale state after the event-page connection is lost.
 *
 * Reloading a temporary add-on leaves an already-open Firefox sidebar alive
 * but invalidates its runtime port. Previously, Solve still painted an
 * optimistic running state and its elapsed timer counted forever even though
 * no message had left the panel. Reloading this extension page gives it the
 * current runtime context and a fresh port; rendering the offline view first
 * makes the short recovery window fail closed.
 */
function recoverPort() {
  if (recoveringPort) {
    return;
  }
  recoveringPort = true;
  portOpen = false;
  stopTicking();
  render(null);
  setTimeout(() => window.location.reload(), 250);
}

function showStatus(text, kind = "") {
  elements.status.textContent = text;
  elements.status.className = `status ${kind}`.trim();
}

/**
 * Show that the panel itself has failed.
 *
 * Distinct from every error in the status line, all of which are things the
 * add-on understood and decided. This one means the panel's own code threw, so
 * what is on screen may be stale and the only honest thing to offer is the log
 * and a reload.
 */
function showFault(info) {
  elements.fault.hidden = false;
  elements.solve.disabled = true;
  elements.insert.disabled = true;
  log.error("panel-fault", info);
}

// --- rendering -------------------------------------------------------------

/**
 * Queue a repaint.
 *
 * A solve reports a stage every few seconds and the clock ticks every second;
 * coalescing into one animation frame means a burst of state can never make
 * the panel do more layout work than the display can show.
 */
function render(state) {
  current = state;
  if (frame !== null) {
    return;
  }
  frame = requestAnimationFrame(() => {
    frame = null;
    paint();
  });
}

/** Repaint now, from `current`. Never throws. */
function paint() {
  try {
    apply(describeView(current, Date.now(), { docked: inSidebar }));
  } catch (error) {
    // A rendering bug must degrade to a visible fault, not to a panel that
    // has quietly stopped updating. That is exactly how the 0.22.0 panel
    // failed: `render` threw on its first line and nothing said so.
    showFault({ where: "paint", error: describeError(error) });
  }
}

/** Write one view onto the elements. The only place that touches the DOM. */
function apply(view) {
  elements.answer.textContent = view.answer.text || "—";
  elements.answer.dataset.empty = String(view.answer.empty);
  elements.answer.dataset.placed = String(view.answer.placed);
  elements.placed.hidden = !view.answer.placed;
  if (!view.answer.empty) {
    // Spelled out for a screen reader: "3y" read as a word is not an answer.
    elements.answer.setAttribute("aria-label", view.answer.text.split("").join(" "));
  } else {
    elements.answer.removeAttribute("aria-label");
  }

  elements.copy.disabled = !view.copy.enabled;
  if (!view.copy.enabled) {
    delete elements.copy.dataset.copied;
  }

  elements.problem.textContent = view.problem.text;
  elements.problemBlock.dataset.idle = String(view.problem.idle);
  if (view.problem.idle) {
    elements.problemBlock.open = false;
  }

  elements.badge.textContent = view.badge ? message(view.badge.key, view.badge.args) : "";

  elements.detail.textContent = view.detail.text;
  elements.detailToggle.disabled = !view.detail.available;
  if (!view.detail.available) {
    elements.detail.hidden = true;
    elements.detailToggle.setAttribute("aria-expanded", "false");
  }

  elements.solve.textContent = message(view.solve.key);
  elements.solve.disabled = view.solve.disabled;
  elements.solve.classList.toggle("button--secondary", !view.solve.primary);
  elements.insert.disabled = !view.insert.enabled;
  elements.insert.classList.toggle("button--secondary", !view.insert.primary);
  elements.reset.disabled = view.resetDisabled;

  let text = message(view.status.key, view.status.args);
  if (typeof view.status.elapsed === "number") {
    text = `${text} ${message("statusElapsed", [String(view.status.elapsed)])}`;
  }
  showStatus(text, view.status.kind);

  elements.progress.style.width = `${Math.round(view.progress.fraction * 100)}%`;
  if (view.progress.state) {
    elements.progress.dataset.state = view.progress.state;
  } else {
    delete elements.progress.dataset.state;
  }

  // Named by the view, which is also what decides whether Enter is bound at
  // all. A hint the panel would not act on is worse than no hint.
  primary = view.primary;
  elements.hint.textContent = view.hint ? message(view.hint) : "";

  if (view.running) {
    startTicking();
  } else {
    stopTicking();
  }
  focusPrimary(view);
}

/**
 * Keep the caret on whichever action is primary.
 *
 * Twice at most, and never against the user. On open, focus goes to the
 * primary button so the panel is usable without reaching for Tab. Then, when a
 * solve finishes and Insert becomes primary, focus moves across -- but only if
 * it is still sitting where the panel put it. Anywhere the user moved it is
 * left alone, and once focus has been handed over it is not taken again.
 *
 * Without the hand-over, a finished solve left the caret on a Solve button
 * that had just stopped being the thing to press, while the panel's own hint
 * said "Enter to insert".
 *
 * Where the view names no primary action -- after an insertion, and during one
 * -- the caret is not placed at all. Parking it on Solve there is precisely
 * what turned an Enter press into a needless re-solve of a question that had
 * just been answered.
 */
function focusPrimary(view) {
  const wantsInsert = view.primary === "insert";
  const target = wantsInsert
    ? elements.insert
    : view.primary === "solve" || view.primary === "cancel"
      ? elements.solve
      : null;

  if (target === null) {
    // Deliberately not settled: when the next question makes the panel
    // actionable again, focus may still be offered -- and only if the user has
    // not moved it in the meantime.
    handedOver = false;
    return;
  }
  if (!settled && document.activeElement === document.body) {
    settled = true;
    if (!target.disabled) {
      target.focus();
      handedOver = wantsInsert;
    }
    return;
  }
  if (!wantsInsert) {
    handedOver = false;
    return;
  }
  if (!handedOver && document.activeElement === elements.solve) {
    handedOver = true;
    elements.insert.focus();
  }
}

/** Elapsed seconds, so a long solve visibly progresses rather than hanging. */
function startTicking() {
  if (ticking !== null) {
    return;
  }
  ticking = setInterval(() => {
    if (current?.phase !== "solving") {
      stopTicking();
      return;
    }
    paint();
  }, 1000);
}

function stopTicking() {
  if (ticking !== null) {
    clearInterval(ticking);
    ticking = null;
  }
}

// --- actions ---------------------------------------------------------------

async function toggleSolve() {
  if (current?.errorKey === "errorTabAccessLost") {
    try {
      const granted = await browser.permissions.request({ origins: [ALLOWED_HOST_PATTERN] });
      if (granted) {
        request("ethnos:prepare");
      } else {
        showStatus(message("errorTabAccessLost"), "error");
      }
    } catch (error) {
      log.warn("site-access-request-failed", { error: describeError(error) });
      showStatus(message("errorTabAccessLost"), "error");
    }
    return;
  }
  if (current?.phase === "solving") {
    if (!request("ethnos:cancel")) {
      return;
    }
    // Optimistic: the panel looks stopped immediately rather than when the
    // background gets round to replying.
    render({ ...current, phase: "ready", stage: "", stageDetail: "", startedAt: 0,
             errorKey: "", detail: "" });
    return;
  }
  if (!request("ethnos:solve")) {
    return;
  }
  // Match the background immediately: a retry is new work, so an old answer
  // must not remain visible while the panel waits for the first state update.
  render({ ...current, phase: "solving", startedAt: Date.now(), errorKey: "", detail: "",
           answer: "", displayText: "", entryText: "", placedText: "", problemText: "",
           source: "", stage: "checking-host" });
}

function requestInsert() {
  if (elements.insert.disabled) {
    return;
  }
  if (!request("ethnos:insert")) {
    return;
  }
  render({ ...current, phase: "inserting" });
}

function requestReset() {
  if (!request("ethnos:reset")) {
    return;
  }
  render({ ...current, phase: "checking", answer: "", displayText: "", placedText: "",
           problemText: "", detail: "", errorKey: "", source: "" });
}

/**
 * Copy the answer as shown.
 *
 * This is the way out of every case where the add-on will not type for you —
 * an option question, notation the editor forbids — and those are the cases
 * where the answer is otherwise re-keyed by eye from a 26px serif.
 */
async function copyAnswer() {
  const text = elements.answer.textContent;
  if (!text || elements.copy.disabled) {
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    elements.copy.dataset.copied = "true";
    showStatus(message("popupCopied"), "ready");
    setTimeout(() => delete elements.copy.dataset.copied, 1200);
  } catch (error) {
    log.warn("clipboard-refused", { error: describeError(error) });
    showStatus(message("popupCopyFailed"), "error");
  }
}

/**
 * The action Enter performs, as named by the view.
 *
 * Asked of the view rather than inferred from which buttons happen to be
 * enabled. Solve stays enabled after an insertion -- a doubted answer is
 * re-solved from there -- so "not disabled" quietly meant Enter re-solved the
 * question that had just been answered.
 */
function primaryAction() {
  if (primary === "insert") {
    requestInsert();
  } else if (primary === "solve" || primary === "cancel") {
    toggleSolve();
  }
}

// --- wiring ----------------------------------------------------------------

/** Attach a handler that can never leave an unhandled rejection or throw. */
function on(element, type, handler) {
  element.addEventListener(type, (event) => {
    try {
      const result = handler(event);
      if (result && typeof result.catch === "function") {
        result.catch((error) => showFault({ where: type, error: describeError(error) }));
      }
    } catch (error) {
      showFault({ where: type, error: describeError(error) });
    }
  });
}

on(elements.solve, "click", toggleSolve);
on(elements.insert, "click", requestInsert);
on(elements.reset, "click", requestReset);
on(elements.copy, "click", copyAnswer);

on(elements.detailToggle, "click", () => {
  const shown = elements.detail.hidden;
  elements.detail.hidden = !shown;
  elements.detailToggle.setAttribute("aria-expanded", String(shown));
});

on(elements.options, "click", () => {
  browser.runtime.openOptionsPage().catch((error) =>
    log.warn("options-open-failed", { error: describeError(error) })
  );
  window.close();
});

if (inSidebar) {
  document.body.dataset.sidebar = "true";
  elements.close.hidden = true;   // the sidebar has Firefox's own close
  elements.dock.hidden = true;
}

on(elements.close, "click", () => window.close());

on(elements.dock, "click", () => {
  // The work lives in the background page, so moving the view does not
  // disturb a solve that is already running.
  browser.sidebarAction.open().catch((error) => log.warn("sidebar-open-failed", {
    error: describeError(error),
  }));
  window.close();
});

on(elements.faultReload, "click", () => window.location.reload());

on(elements.faultCopy, "click", async () => {
  await flushLog();
  const lines = (await readLog()).map(formatEntry).join("\n");
  try {
    await navigator.clipboard.writeText(lines);
    showStatus(message("popupCopied"), "ready");
  } catch {
    // Nothing further to offer here; the settings page can show the log.
    showStatus(message("popupCopyFailed"), "error");
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    window.close();
    return;
  }
  // Ctrl+Enter reaches Solve even while Insert is the primary action, so a
  // questionable answer can be re-solved without leaving the keyboard.
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    if (!elements.solve.disabled) {
      toggleSolve();
    }
    return;
  }
  if (event.key === "Enter" && event.target === document.body) {
    event.preventDefault();
    primaryAction();
  }
});

port.onMessage.addListener((incoming) => {
  if (incoming?.type !== "ethnos:state") {
    return;
  }
  const first = current === null;
  render(incoming.state);
  // Re-check on every open, not only the first: Hawkes swaps in the next
  // question without navigating, so a panel that only checked once would keep
  // showing the previous answer. An in-flight solve is left alone.
  const busy = incoming.state?.phase === "solving" || incoming.state?.phase === "inserting";
  if (first && !busy) {
    request("ethnos:prepare");
  }
});

// The event page is non-persistent. If Firefox unloads it under us, the panel
// would otherwise sit on a state that can no longer change.
port.onDisconnect.addListener(() => {
  log.warn("panel-port-closed", {});
  recoverPort();
});

// A popup is torn down the moment anything else takes focus, so anything still
// queued has to be written now or not at all.
window.addEventListener("pagehide", () => {
  stopTicking();
  flushLog();
});

/** Apply the preferences that shape the panel, before the first state lands. */
async function applySettings() {
  const settings = await readSettings();
  initLog("panel", {
    level: settings.logLevel,
    onFatal: (info) => showFault(info),
  });
  document.documentElement.style.setProperty("--panel-width", `${settings.panelWidth}px`);
  if (settings.problemOpen) {
    elements.problemBlock.open = true;
  }
  log.debug("panel-open", { panelWidth: settings.panelWidth });
}

localizeDocument();
showStatus(message("statusChecking"));
applySettings().catch((error) => {
  // Defaults are already in the stylesheet, so a failure here costs the
  // preferences and nothing else.
  initLog("panel", { onFatal: (info) => showFault(info) });
  log.warn("settings-unavailable", { error: describeError(error) });
});
