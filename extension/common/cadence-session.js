"use strict";

import { CadenceInstrument } from "/common/cadence-audio.js";

// Firefox's event page owns bounded insertion audio. Real score cues are its
// only activity: nothing here sends keepalive traffic. How long Firefox then
// keeps the page is Firefox's business and this feature does not depend on it --
// `runtime.onSuspend` closes every presentation and the device the moment it
// says so, and a fresh device is opened for the next answer.
//
// `idle: "close"` matters here and nowhere else. A background page has no user
// activation of its own: Firefox admits a newly created AudioContext under its
// extension-background autoplay exemption, but a resume() on a device this page
// suspended has nothing to draw on and was observed to stay suspended -- so the
// second answer of a session played into a stopped device. Closing when idle
// means every performance opens a device on the path that is known to start.
export const insertionInstrument = new CadenceInstrument(undefined, { idle: "close" });
const presentations = new Map();
// What the most recent performance measured, kept after its run is released so
// the log can report it. Numbers only; never a character, note or answer.
let lastPerformance = null;

export function cancelCadence() {
  for (const run of presentations.values()) { run.release(); }
  insertionInstrument.close();
}

/** Register a finite, presentation-only capability before installing its observer. */
export function createCadencePresentation(target, score, options, visit, isCurrent) {
  for (const prior of presentations.values()) { prior.release(); }
  insertionInstrument.stop();
  const channel = `facet-score:${crypto.randomUUID()}`;
  const run = { target, score, options, visit, isCurrent, next: 0, port: null,
    channel, finished: false, heldMs: 0, lateness: [] };
  run.release = () => {
    if (presentations.delete(channel) && run.lateness.length > 0) {
      lastPerformance = {
        notes: run.lateness.length,
        maxLatenessMs: Math.max(...run.lateness),
        meanLatenessMs: Math.round(
          run.lateness.reduce((total, late) => total + late, 0) / run.lateness.length
        ),
        driftMs: run.lateness[run.lateness.length - 1] - run.lateness[0],
        structuralHoldMs: Math.round(run.heldMs),
        ...insertionInstrument.timing(),
      };
    }
    clearTimeout(run.drain);
    try { run.port?.postMessage({ type: "close" }); } catch { /* gone */ }
  };
  presentations.set(channel, run);
  return {
    channel,
    close(success = false) {
      if (!presentations.has(channel)) { return; }
      // Preserve the final note's short natural release on success. A refused
      // or incomplete answer must not leave a triumphant chord hanging.
      if (!success) {
        insertionInstrument.stop();
        insertionInstrument.finish();
        run.release();
      } else if (run.next === score.notes.length) {
        insertionInstrument.finish();
        run.release();
      } else {
        // executeScript's result and the final port cue use different IPC
        // channels. Allow that already-emitted cue to drain, without awaiting
        // it in insertion or scheduling a musical event on this cleanup timer.
        run.finished = true;
        run.drain = setTimeout(() => { insertionInstrument.finish(); run.release(); }, 250);
      }
    },
  };
}

/**
 * Forget the last performance, before a new entry begins.
 *
 * An insertion refused before a single character is accepted has no performance
 * of its own, and was observed logging the previous answer's numbers as though
 * they were its own. Clearing here rather than on read keeps
 * {@link cadenceMeasurements} an ordinary getter that anything may ask twice.
 */
export function beginCadenceRun() {
  lastPerformance = null;
}

/**
 * What the performance that just ran actually did, for the diagnostic log.
 *
 * Two independent numbers, deliberately: how late each accepted write was
 * against its own score offset, and how far ahead of that write its voice was
 * scheduled. The first is the browser's; the second is this instrument's.
 */
export function cadenceMeasurements() {
  return lastPerformance;
}

export function finishIdleCadence() {
  if (presentations.size === 0) { insertionInstrument.finish(); }
}

/** Only a registered run in its exact tab and frame may emit bounded note indices. */
export function attachCadencePort(port) {
  const run = presentations.get(port.name);
  if (!run || run.port || port.sender?.tab?.id !== run.target.tabId
      || port.sender?.frameId !== run.target.frameId) {
    port.disconnect();
    return;
  }
  run.port = port;
  port.onMessage.addListener((cue) => {
    if (!presentations.has(run.channel) || (!run.finished && !run.isCurrent())
        || cue?.index !== run.next
        || !Number.isFinite(cue.elapsedMs) || cue.elapsedMs < 0 || cue.elapsedMs > 60000) { return; }
    // A template landing is not a scored note: it does not advance the phrase,
    // and it is only ever the editor structure the plan already asked for.
    if (cue.structure === true) {
      if (typeof cue.label !== "string" || cue.label.length > 32) { return; }
      if (run.options.enabled) { insertionInstrument.strikeStructure(cue.label, run.options); }
      run.heldMs = Math.max(0, Math.round(cue.heldMs) || 0);
      try {
        run.visit({ index: run.next, elapsedMs: cue.elapsedMs, structure: cue.label,
          heldMs: run.heldMs, durationMs: run.score.durationMs,
          count: run.score.notes.length,
          audio: run.options.enabled ? insertionInstrument.status() : "off" });
      } catch { /* view gone */ }
      return;
    }
    if (run.next >= run.score.notes.length) { return; }
    const index = run.next++;
    const note = run.score.notes[index];
    if (run.options.enabled) { insertionInstrument.strike(note, index, run.options); }
    run.lateness.push(Math.round(cue.elapsedMs - note.offsetMs));
    try { run.visit({ index, elapsedMs: cue.elapsedMs, offsetMs: note.offsetMs,
      heldMs: run.heldMs, durationMs: run.score.durationMs,
      count: run.score.notes.length,
      audio: run.options.enabled ? insertionInstrument.status() : "off" }); } catch { /* view gone */ }
    if (run.finished && run.next === run.score.notes.length) {
      insertionInstrument.finish();
      run.release();
    }
  });
  port.onDisconnect.addListener(() => {
    if (presentations.delete(run.channel)) {
      clearTimeout(run.drain);
      insertionInstrument.stop();
      insertionInstrument.finish();
    }
  });
}

/**
 * Serialized into the ISOLATED world for one finite performance. It never
 * reads answer text, writes a page element, or accepts an instruction to insert.
 * String-only DOM details work across Firefox's Xray boundary. The page may
 * forge cues, so the receiver treats them solely as untrusted presentation.
 */
export function observeCadence(channel, count) {
  if (typeof channel !== "string" || !channel.startsWith("facet-score:")
      || !Number.isInteger(count) || count < 1 || count > 8192) { return; }
  const port = browser.runtime.connect({ name: channel });
  let next = 0;
  let closed = false;
  const close = () => {
    if (closed) { return; }
    closed = true;
    document.removeEventListener(channel, receive);
    window.removeEventListener("pagehide", close);
    clearTimeout(expiry);
    try { port.disconnect(); } catch { /* gone */ }
  };
  const receive = (event) => {
    try {
      if (typeof event.detail !== "string" || event.detail.length > 160) { return; }
      const [index, elapsedMs, label, heldMs] = JSON.parse(event.detail);
      if (index !== next || !Number.isFinite(elapsedMs)) { return; }
      if (typeof label === "string") {
        // A template landing. It names the structure and how long the editor
        // held the phrase; it never advances the note counter.
        if (label.length > 32 || index > count || !Number.isFinite(heldMs)) { return; }
        port.postMessage({ index, elapsedMs, structure: true, label, heldMs });
        return;
      }
      if (index >= count) { return; }
      next += 1;
      port.postMessage({ index, elapsedMs });
    } catch { /* page data and audio delivery are never insertion failures */ }
  };
  // A resource lease, not a beat clock. Also cleans up if an injection fails or
  // a background process disappears before its normal finally can close us.
  const expiry = setTimeout(close, 20000);
  document.addEventListener(channel, receive);
  window.addEventListener("pagehide", close, { once: true });
  port.onDisconnect.addListener(close);
  port.onMessage.addListener((cue) => { if (cue?.type === "close") { close(); } });
}
