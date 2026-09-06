"use strict";

import { CadenceInstrument } from "/common/cadence-audio.js";

// Firefox's event page owns bounded insertion audio. Real score cues are
// activity; an open port alone is NOT a keepalive. The measured default idle
// timeout is 30s, beyond the supported 2–12s score and its short release.
export const insertionInstrument = new CadenceInstrument();
const presentations = new Map();

export function cancelCadence() {
  for (const run of presentations.values()) { run.release(); }
  insertionInstrument.close();
}

/** Register a finite, presentation-only capability before installing its observer. */
export function createCadencePresentation(target, score, options, visit, isCurrent) {
  for (const prior of presentations.values()) { prior.release(); }
  insertionInstrument.stop();
  const channel = `facet-score:${crypto.randomUUID()}`;
  const run = { target, score, options, visit, isCurrent, next: 0, port: null, channel, finished: false };
  run.release = () => {
    presentations.delete(channel);
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
        || cue?.index !== run.next || run.next >= run.score.notes.length
        || !Number.isFinite(cue.elapsedMs) || cue.elapsedMs < 0 || cue.elapsedMs > 60000) { return; }
    const index = run.next++;
    const note = run.score.notes[index];
    if (run.options.enabled) { insertionInstrument.strike(note, index, run.options); }
    try { run.visit({ index, elapsedMs: cue.elapsedMs, offsetMs: note.offsetMs,
      durationMs: run.score.durationMs, count: run.score.notes.length,
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
      if (typeof event.detail !== "string" || event.detail.length > 100) { return; }
      const [index, elapsedMs] = JSON.parse(event.detail);
      if (index !== next || index >= count || !Number.isFinite(elapsedMs)) { return; }
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
