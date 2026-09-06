"use strict";

/**
 * The settings page.
 *
 * Controls are bound by `data-setting="<key>"`, and the key is looked up in
 * `common/settings.js` to decide how to read the control and how to validate
 * what comes out of it. Answer Cadence keeps a separate draft until Apply and
 * performs a structured demo through the same score and transport as plain
 * insertion. The demo never leaves this extension document.
 *
 * The rest of the page is the two things you cannot put in a schema: the
 * keyboard shortcut, which Firefox owns and which is changed through
 * `browser.commands`, and the diagnostic log.
 */

import { localizeDocument, message } from "../common/i18n.js";
import { CadenceInstrument } from "../common/cadence-audio.js";
import { planEntry } from "../common/editor-plan.js";
import {
  SETTINGS,
  clamp,
  readSettings,
  resetSettings,
  resolveEntryCadence,
  writeSetting,
  writeSettings,
} from "../common/settings.js";
import { clearLog, describeError, formatEntry, initLog, log, readLog, setLogLevel } from "../common/log.js";
import { clearFailures, readFailures } from "../common/failure-record.js";

/** The toolbar-button command, which is the one shortcut this add-on has. */
const ACTION_COMMAND = "_execute_action";

/** Entries shown at once. The ring holds more; the page shows the recent end. */
const LOG_ROWS = 60;

const shortcutInput = document.querySelector("#shortcut");
const shortcutStatus = document.querySelector("#shortcut-status");
const healthStatus = document.querySelector("#health-status");
const logView = document.querySelector("#log");
const logSummary = document.querySelector("#log-summary");
const logStatus = document.querySelector("#log-status");
const resetStatus = document.querySelector("#reset-status");
const cadenceCard = document.querySelector("#cadence-card");
const cadenceCustom = document.querySelector("#cadence-custom");
const cadenceNote = document.querySelector("#cadence-note");
const cadenceSummary = document.querySelector("#cadence-summary");
const cadenceApply = document.querySelector("#cadence-apply");
const cadenceApplyStatus = document.querySelector("#cadence-apply-status");
const cadenceDraftStatus = document.querySelector("#cadence-draft-status");
const cadencePlay = document.querySelector("#cadence-play");
const cadenceStop = document.querySelector("#cadence-stop");
const cadenceEquation = document.querySelector("#cadence-equation");
const cadenceScoreFill = document.querySelector("#cadence-score-fill");
const cadenceScoreBeats = document.querySelector("#cadence-score-beats");
const cadenceScoreHead = document.querySelector("#cadence-score-head");
const cadencePreviewStatus = document.querySelector("#cadence-preview-status");
const cadenceElapsed = document.querySelector("#cadence-elapsed");
const cadenceTarget = document.querySelector("#cadence-target");
const cadenceStep = document.querySelector("#cadence-step");
const cadenceAction = document.querySelector("#cadence-action");
const cadenceEffectiveTempo = document.querySelector("#cadence-effective-tempo");
const cadencePlannedSteps = document.querySelector("#cadence-planned-steps");
const cadenceWindowState = document.querySelector("#cadence-window-state");
const cadenceArrangement = document.querySelector("#cadence-arrangement");

// One device for the whole Settings session. Preview restarts stop its voices
// and suspend it; they do not open another. Settings can resume it because
// Preview is a real click in this document, which is exactly what the event
// page cannot do -- see `cadence-session.js`.
const previewInstrument = new CadenceInstrument();
const cadenceAudioStatus = document.querySelector("#cadence-audio-status");

function showAudioStatus() {
  const status = previewInstrument.status();
  cadenceAudioStatus.dataset.audio = status;
  cadenceAudioStatus.textContent = message({
    ready: "optionsCadenceAudioReady", muted: "optionsCadenceAudioMuted",
    idle: "optionsCadenceAudioIdle",
    blocked: "optionsCadenceAudioBlocked", unavailable: "optionsCadenceAudioUnavailable",
  }[status]);
}

const CADENCE_KEYS = Object.freeze([
  "entryGenre",
  "entryMusicEnabled",
  "entryMusicMuted",
  "entryMusicVolume",
  "entryVoice",
  "entryTempoBpm",
  "entryDurationMinSeconds",
  "entryDurationMaxSeconds",
  "entryPattern",
  "entrySwingPercent",
  "entryVariationPercent",
  "entrySymbolRestPercent",
]);

const DEMO_EXPRESSION = "(2ix^4√(2x)+3)/(5y^2)";
const DEMO_EDITOR = Object.freeze({
  allowedCharacters: "0123456789ixy+",
  templates: Object.freeze({
    exponent: true, fraction: true, radical: true, parentheses: true,
  }),
  slots: Object.freeze({
    numerator: "0123456789ixy+",
    denominator: "0123456789ixy",
  }),
});

const ACTION_LABEL_KEYS = Object.freeze({
  character: "optionsCadenceActionCharacter",
  operator: "optionsCadenceActionOperator",
  "structure-enter": "optionsCadenceActionStructureEnter",
  "structure-exit": "optionsCadenceActionStructureExit",
  rest: "optionsCadenceActionRest",
  resolution: "optionsCadenceActionResolution",
});

let appliedCadence = null;
let demoSteps = null;
let previewBroken = false;
let previewRun = null;

/**
 * Live, rather than sampled once per Play: someone who turns reduced motion on
 * while Settings is open should not have to reload the page to be believed.
 */
const motionQuery = matchMedia("(prefers-reduced-motion: reduce)");

const SETTING_OUTPUT_KEYS = Object.freeze({
  panelWidth: "optionsWidthValue",
  entryTempoBpm: "optionsCadenceTempoValue",
  entryMusicVolume: "optionsCadencePercentValue",
  entrySwingPercent: "optionsCadencePercentValue",
  entryVariationPercent: "optionsCadencePercentValue",
  entrySymbolRestPercent: "optionsCadencePercentValue",
});

const GENRE_LABEL_KEYS = Object.freeze({
  classical: "optionsCadenceGenreClassical",
  jazz: "optionsCadenceGenreJazz",
  lofi: "optionsCadenceGenreLofi",
  electronic: "optionsCadenceGenreElectronic",
  custom: "optionsCadenceGenreCustom",
});

const GENRE_HELP_KEYS = Object.freeze({
  classical: "optionsCadenceGenreClassicalHelp",
  jazz: "optionsCadenceGenreJazzHelp",
  lofi: "optionsCadenceGenreLofiHelp",
  electronic: "optionsCadenceGenreElectronicHelp",
  custom: "optionsCadenceGenreCustomHelp",
});

/**
 * @param {Element} element
 * @param {string} text
 * @param {"" | "ready" | "error" | "note"} [kind]
 */
function say(element, text, kind = "") {
  element.textContent = text;
  element.className = `status ${kind}`.trim();
}

// --- preferences -----------------------------------------------------------

/** Every control bound to a schema key. */
function boundControls() {
  return [...document.querySelectorAll("[data-setting]")];
}

/** Update the small unit readout paired with a range control. */
function showReadout(control, value) {
  const outputKey = SETTING_OUTPUT_KEYS[control.id];
  const output = outputKey && document.querySelector(`#${control.id}-value`);
  if (output) {
    output.textContent = message(outputKey, [String(value)]);
  }
}

/** Put a stored value into whichever kind of control holds it. */
function showValue(control, value) {
  if (control.type === "checkbox") {
    control.checked = Boolean(value);
  } else {
    control.value = String(value);
  }
  showReadout(control, value);
}

/** Read whichever kind of control this is, in the type the schema expects. */
function controlValue(control) {
  if (control.type === "checkbox") {
    return control.checked;
  }
  return SETTINGS[control.dataset.setting].kind === "integer"
    ? Number(control.value)
    : control.value;
}

/** Current control values, in the same shape as readSettings(). */
function visibleSettings() {
  const values = {};
  for (const control of boundControls()) {
    const key = control.dataset.setting;
    values[key] = clamp(key, controlValue(control)).value;
  }
  return values;
}

function cadenceSubset(values) {
  return Object.fromEntries(CADENCE_KEYS.map((key) => [key, values[key]]));
}

function cadenceDraft() {
  return cadenceSubset(visibleSettings());
}

function cadenceIsDirty(draft = cadenceDraft()) {
  return CADENCE_KEYS.some((key) => draft[key] !== appliedCadence?.[key]);
}

function showDraftState() {
  const dirty = cadenceIsDirty();
  cadenceApply.disabled = !dirty;
  cadenceDraftStatus.textContent = message(
    dirty ? "optionsCadenceDraftChanged" : "optionsCadenceDraftApplied"
  );
  cadenceDraftStatus.classList.toggle("is-applied", !dirty);
  // Apply sits below the preview, which is far enough from the controls to be
  // off-screen while a slider moves. The card heading carries the same fact
  // back to where the hand already is.
  cadenceCard.classList.toggle("is-draft", dirty);
  if (dirty) {
    // "Answer Cadence applied." must never stand beside "Unapplied changes".
    // Reading both at once is the fastest way to stop trusting a save button.
    cadenceApplyStatus.textContent = "";
  }
}

/** Draw the selected arrangement without playing sound or touching a page. */
function showCadence() {
  const values = visibleSettings();
  const genre = values.entryGenre;
  const resolved = resolveEntryCadence(values);
  const genreName = message(GENRE_LABEL_KEYS[genre]);
  cadenceCustom.hidden = genre !== "custom";
  previewInstrument.setLevel(values.entryMusicVolume / 100, values.entryMusicMuted);
  if (previewInstrument.context) { showAudioStatus(); }
  cadenceNote.textContent = message(GENRE_HELP_KEYS[genre]);
  cadenceSummary.textContent = message(
    "optionsCadenceSummary", [genreName, String(resolved.tempoBpm)]
  );
  cadenceEquation.dataset.genre = genre;
  showDraftState();
  if (previewRun) {
    // A performance owns the transport until it ends. Retiming it mid-phrase
    // would show numbers no performance ever had; note instead that the idle
    // display is now describing an arrangement that has moved on.
    previewRun.stale = true;
    return;
  }
  stagePreview(resolved);
}

/** Keep the two ends of the hard timing window in chronological order. */
function alignDurationWindow(changedKey, settledValue) {
  const minimum = document.querySelector("#entryDurationMinSeconds");
  const maximum = document.querySelector("#entryDurationMaxSeconds");
  if (changedKey === "entryDurationMinSeconds" && settledValue > Number(maximum.value)) {
    showValue(maximum, settledValue);
  } else if (
    changedKey === "entryDurationMaxSeconds" && settledValue < Number(minimum.value)
  ) {
    showValue(minimum, settledValue);
  }
}

async function bindSettings() {
  const stored = await readSettings();
  appliedCadence = cadenceSubset(stored);
  for (const control of boundControls()) {
    const key = control.dataset.setting;
    const setting = SETTINGS[key];
    // The schema owns the bounds, so the control cannot offer a value the
    // schema would then reject.
    if (setting.kind === "integer") {
      control.min = String(setting.min);
      control.max = String(setting.max);
    }
    showValue(control, stored[key]);

    // Reset reuses this function to repaint defaults. Listeners belong to the
    // controls, not to a particular paint, so attach each one only once.
    if (control.dataset.bound === "true") {
      continue;
    }
    control.dataset.bound = "true";

    // Cadence controls are always a draft. Other settings preserve their
    // established change-to-save behaviour.
    control.addEventListener("input", () => {
      const settled = clamp(key, controlValue(control));
      showReadout(control, settled.value);
      if (key.startsWith("entry")) {
        showCadence();
      }
    });

    control.addEventListener("change", () => {
      const settled = clamp(key, controlValue(control));
      showValue(control, settled.value);
      if (key === "entryGenre" && settled.value === "custom") {
        // Choosing Custom and being shown a closed disclosure reads as though
        // the choice did nothing. Open it once, on the choice itself, so a
        // panel the user then collapses stays collapsed.
        cadenceCustom.open = true;
      }
      if (key.startsWith("entry")) {
        // No write here: cadence is a draft, and `showCadence` is what reports
        // that -- including retiring a stale "applied" confirmation.
        alignDurationWindow(key, settled.value);
        showCadence();
        return;
      }
      writeSetting(key, settled.value)
        .then(() => {
          if (key === "logLevel") {
            setLogLevel(settled.value);
          }
          say(resetStatus, message("optionsSaved"), "ready");
        })
        .catch((error) => {
          log.error("setting-write-failed", { key, error: describeError(error) });
          say(resetStatus, message("optionsSaveFailed"), "error");
        });
      });
  }
  showCadence();
}

async function applyCadence() {
  const patch = cadenceDraft();
  cadenceApply.disabled = true;
  try {
    const accepted = await writeSettings(patch);
    if (!accepted) {
      throw new Error("cadence-draft-invalid");
    }
    appliedCadence = patch;
    showDraftState();
    say(cadenceApplyStatus, message("optionsCadenceApplied"), "ready");
    log.info("cadence-settings-applied", { genre: patch.entryGenre });
  } catch (error) {
    cadenceApply.disabled = !cadenceIsDirty();
    say(cadenceApplyStatus, message("optionsSaveFailed"), "error");
    log.error("cadence-settings-write-failed", { error: describeError(error) });
  }
}

// --- cadence preview ------------------------------------------------------

/**
 * The demo expression as a real editor plan.
 *
 * Both the expression and the editor description are constants, so the plan is
 * one too. It used to be rebuilt on every `input` event, which meant dragging
 * the tempo slider re-parsed the same expression through the whole structured
 * planner for every pixel of travel.
 */
function demoPlan() {
  if (!demoSteps) {
    const planned = planEntry(DEMO_EXPRESSION, DEMO_EDITOR);
    if (!planned.ok) {
      throw new Error(`cadence-demo-plan-${planned.code}`);
    }
    demoSteps = planned.steps;
  }
  return demoSteps;
}

function formatSeconds(milliseconds) {
  return `${(milliseconds / 1000).toFixed(1)}s`;
}

/**
 * Say what the hard window did to the tempo-led length.
 *
 * Planned phrases are clamped into the window by construction, so reporting
 * "within window" before one has played says nothing at all -- and it hid the
 * one thing worth knowing, which is that 300 BPM produced a 5-second phrase
 * because the window's floor, not the tempo, decided. The measured verdict
 * after a performance is a different claim and is still made below.
 */
function showWindowState(phrase) {
  const held = {
    minimum: () => message(
      "optionsCadenceWindowRaised", [formatSeconds(phrase.cadence.durationMinMs)]
    ),
    maximum: () => message(
      "optionsCadenceWindowHeld", [formatSeconds(phrase.cadence.durationMaxMs)]
    ),
    none: () => message("optionsCadenceWindowTempoLed"),
  };
  cadenceWindowState.textContent = held[phrase.clampedBy]();
  cadenceWindowState.classList.remove("cadence-window-ok", "cadence-window-warn");
}

/** Report whether the performance that just ran really met its window. */
function showMeasuredWindow(phrase, elapsedMs) {
  const actualWithin = elapsedMs >= phrase.cadence.durationMinMs
    && elapsedMs <= phrase.cadence.durationMaxMs;
  cadenceWindowState.textContent = message(
    actualWithin ? "optionsCadenceWindowWithin" : "optionsCadenceWindowOutside"
  );
  cadenceWindowState.classList.toggle("cadence-window-ok", actualWithin);
  cadenceWindowState.classList.toggle("cadence-window-warn", !actualWithin);
}

/**
 * Draw the phrase as a rhythm strip.
 *
 * One tick per note, placed at the time it is due, so tempo, swing and timing
 * variation are spacing and an accent is height. A structural rest is the band
 * between the operator that earned it and the note that follows -- the shape
 * the design note describes, made visible without having to play it first.
 */
function drawScore(phrase) {
  const marks = [];
  if (phrase.durationMs > 0) {
    for (const [index, note] of phrase.notes.entries()) {
      const at = (note.offsetMs / phrase.durationMs) * 100;
      if (note.rest) {
        const until = (phrase.notes[index + 1].offsetMs / phrase.durationMs) * 100;
        const rest = document.createElement("span");
        rest.className = "cadence-rest";
        rest.dataset.rest = String(index);
        rest.style.left = `${at}%`;
        rest.style.width = `${Math.max(0, until - at)}%`;
        marks.push(rest);
      }
      const beat = document.createElement("span");
      beat.className = "cadence-beat";
      beat.classList.toggle("is-accent", Boolean(note.accent));
      beat.classList.toggle("is-resolution", index === phrase.notes.length - 1);
      beat.dataset.beat = String(index);
      beat.style.left = `${at}%`;
      marks.push(beat);
    }
  }
  cadenceScoreBeats.replaceChildren(...marks);
}

/** Put the playhead, the fill and the elapsed readout at one point in time. */
function showClock(phrase, elapsedMs) {
  const played = Math.max(0, Math.min(elapsedMs, phrase.durationMs));
  const progress = phrase.durationMs === 0 ? 100 : (played / phrase.durationMs) * 100;
  cadenceElapsed.textContent = formatSeconds(played);
  cadenceScoreFill.style.width = `${progress}%`;
  cadenceScoreHead.style.left = `${progress}%`;
}

/** Paint one phrase at rest: nothing played yet, everything legible. */
function showPhrase(phrase) {
  cadenceTarget.textContent = `${formatSeconds(phrase.durationMs)} / ${
    phrase.cadence.durationMinMs / 1000
  }–${phrase.cadence.durationMaxMs / 1000}s`;
  cadenceStep.textContent = `0/${phrase.notes.length} · 0/${phrase.timeline.length}`;
  cadenceAction.textContent = message("optionsCadenceActionReady");
  cadenceEffectiveTempo.textContent = message(
    "optionsCadenceTempoValue", [String(phrase.effectiveTempoBpm)]
  );
  cadencePlannedSteps.textContent = `${phrase.notes.length} / ${phrase.timeline.length}`;
  cadenceArrangement.textContent = message(
    GENRE_LABEL_KEYS[cadenceDraft().entryGenre] ?? GENRE_LABEL_KEYS.classical
  );
  showWindowState(phrase);
  drawScore(phrase);
  showClock(phrase, 0);
  clearStructureMarks();
  for (const note of cadenceEquation.querySelectorAll("[data-note]")) {
    note.classList.add("is-entered");
    note.classList.remove("is-current", "is-accented");
  }
  return phrase;
}

/**
 * Show the draft's arrangement without playing it.
 *
 * The deterministic score staged here is exactly the score Play will perform.
 * Genre changes orchestration; it cannot reroll variation or move the strip.
 */
function stagePreview(cadence = resolveEntryCadence(cadenceDraft())) {
  if (previewBroken) {
    return null;
  }
  try {
    return showPhrase(
      ethnosCadence.planSemanticPhrase(demoPlan(), cadence)
    );
  } catch (error) {
    previewUnavailable(error);
    return null;
  }
}

/**
 * Retire the preview without taking the rest of Settings down with it.
 *
 * The demo plan runs the real structured planner, and a planner that stopped
 * accepting this expression would otherwise throw during initialisation --
 * costing the log level, the shortcut and the diagnostic view as well.
 */
function previewUnavailable(error) {
  // Latched, and reported once. Every control change restages the preview, so
  // a planner that has stopped accepting the demo expression would otherwise
  // re-plan and re-log on every pixel of slider travel.
  previewBroken = true;
  cadencePlay.disabled = true;
  cadenceStop.hidden = true;
  cadenceAction.textContent = message("optionsCadencePreviewUnavailable");
  log.error("cadence-preview-unavailable", { error: describeError(error) });
}

function clearCurrentPreviewMarks() {
  for (const current of cadenceEquation.querySelectorAll(
    ".is-current, .is-accented"
  )) {
    current.classList.remove("is-current", "is-accented");
  }
  for (const current of cadenceScoreBeats.querySelectorAll(".is-current")) {
    current.classList.remove("is-current");
  }
}

function clearStructureMarks() {
  for (const current of cadenceEquation.querySelectorAll(".is-current-structure")) {
    current.classList.remove("is-current-structure");
  }
}

/**
 * Sweep the playhead on the browser's own frame clock.
 *
 * The transport used to move only when a note fell due, so a structural rest
 * looked like a stall: the elapsed count ran on while the bar sat still for a
 * second. A continuous head is what makes a rest read as a rest. Reduced
 * motion gets the same numbers on a slow interval instead.
 */
function runClock(run, phrase) {
  if (run.reducedMotion) {
    run.interval = setInterval(
      () => showClock(phrase, performance.now() - run.startedAt), 250
    );
    return;
  }
  const tick = () => {
    if (previewRun !== run) {
      return;
    }
    showClock(phrase, performance.now() - run.startedAt);
    run.frame = requestAnimationFrame(tick);
  };
  run.frame = requestAnimationFrame(tick);
}

function stopClock(run) {
  clearInterval(run.interval);
  cancelAnimationFrame(run.frame);
}

/**
 * @param {{announce?: boolean, restage?: boolean}} [options] `restage` puts the
 *   idle phrase back when the draft moved on while this run was playing.
 */
function stopPreview({ announce = false, restage = false } = {}) {
  if (!previewRun) {
    return;
  }
  const run = previewRun;
  previewRun = null;
  run.controller.abort();
  // Release the voices, keep the device. Closing and reopening an AudioContext
  // for every Preview churned a real output device for no gain; this leaves one
  // suspended instrument that the next Preview resumes in its own click.
  previewInstrument.stop();
  previewInstrument.finish();
  stopClock(run);
  clearCurrentPreviewMarks();
  clearStructureMarks();
  cadenceStop.hidden = true;
  if (announce) {
    cadencePreviewStatus.textContent = message("optionsCadencePreviewStopped");
    cadenceAction.textContent = message("optionsCadenceActionStopped");
  }
  if (restage && run.stale) {
    stagePreview();
  }
}

function showSemanticStep(step, timelineIndex, phrase, elapsedMs) {
  const noteNumber = Number.isInteger(step.noteIndex) ? step.noteIndex + 1 : 0;
  if (step.kind === "rest") {
    // The rest belongs to the note that earned it. Holding that note's mark
    // through the rest is the point; blinking it off and on again would read
    // as a dropped beat rather than a held one.
    cadenceScoreBeats
      .querySelector(`[data-rest="${step.noteIndex}"]`)
      ?.classList.add("is-current");
  } else {
    clearCurrentPreviewMarks();
    if (noteNumber > 0) {
      const note = cadenceEquation.querySelector(`[data-note="${step.noteIndex}"]`);
      note?.classList.add("is-entered", "is-current");
      if (step.accent) {
        note?.classList.add("is-accented");
      }
      cadenceScoreBeats
        .querySelector(`[data-beat="${step.noteIndex}"]`)
        ?.classList.add("is-struck", "is-current");
    }
  }
  if (step.kind === "structure-enter") {
    cadenceEquation.querySelector(
      `[data-structure-index="${step.structureIndex}"]`
    )?.classList.add("is-current-structure");
  }
  if (step.kind === "structure-exit") {
    cadenceEquation.querySelector(
      `[data-structure-index="${step.structureIndex}"]`
    )?.classList.remove("is-current-structure");
  }
  if (step.kind === "resolution") {
    clearStructureMarks();
    for (const note of cadenceEquation.querySelectorAll("[data-note]")) {
      note.classList.add("is-entered");
    }
    for (const beat of cadenceScoreBeats.querySelectorAll("[data-beat]")) {
      beat.classList.add("is-struck");
    }
    showMeasuredWindow(phrase, elapsedMs);
  }
  cadenceStep.textContent = `${noteNumber}/${phrase.notes.length} · ${
    timelineIndex + 1
  }/${phrase.timeline.length}`;
  cadenceAction.textContent = [
    message(ACTION_LABEL_KEYS[step.kind]),
    step.label,
    step.accent ? message("optionsCadenceAccent") : "",
  ].filter(Boolean).join(" · ");
}

async function startPreview() {
  stopPreview();
  const draft = cadenceDraft();
  previewInstrument.setLevel(draft.entryMusicVolume / 100, draft.entryMusicMuted);
  previewInstrument.unlock();
  showAudioStatus();
  const orchestration = { genre: draft.entryGenre, voice: draft.entryVoice };
  const cadence = resolveEntryCadence(draft);
  let phrase;
  try {
    phrase = ethnosCadence.planSemanticPhrase(demoPlan(), cadence);
  } catch (error) {
    previewUnavailable(error);
    return;
  }
  const reducedMotion = motionQuery.matches;
  showPhrase(phrase);
  if (!reducedMotion) {
    // Notes arrive with the beat. Reduced motion keeps them all legible from
    // the start and lets the transport carry the timing instead.
    for (const note of cadenceEquation.querySelectorAll("[data-note]")) {
      note.classList.remove("is-entered");
    }
  }
  // Identity, not a sequence number: `previewRun` is replaced before an
  // outgoing run's `finally` can run, so "am I still the current run?" is
  // exactly the question `previewRun === run` answers.
  const run = {
    controller: new AbortController(),
    startedAt: performance.now(),
    reducedMotion,
    stale: false,
  };
  previewRun = run;
  // Give a newly opened output device a bounded warm-up before the score's
  // origin. Autoplay denial may leave resume pending forever; it costs at most
  // this setup grace, and never changes a note offset or insertion behavior.
  let warmup;
  try {
    await Promise.race([
      previewInstrument.context?.resume().catch(() => {}),
      new Promise((resolve) => { warmup = setTimeout(resolve, 200); }),
    ]);
  } finally { clearTimeout(warmup); }
  if (previewRun !== run) { return; }
  run.startedAt = performance.now();
  runClock(run, phrase);
  cadenceStop.hidden = false;
  cadencePreviewStatus.textContent = message("optionsCadencePreviewPlaying");
  try {
    await ethnosCadence.playSemanticPhrase(
      phrase,
      (step, index, playedPhrase, elapsed) => {
        if (previewRun === run) {
          showSemanticStep(step, index, playedPhrase, elapsed);
          if (step.kind === "character" || step.kind === "operator") {
            previewInstrument.strike(playedPhrase.notes[step.noteIndex], step.noteIndex, orchestration);
            showAudioStatus();
          } else if (step.kind === "structure-enter") {
            // The same template chord insertion plays when the editor's own
            // structure lands, so the preview demonstrates the real thing.
            previewInstrument.strikeStructure(step.label, orchestration);
            showAudioStatus();
          }
        }
      },
      { signal: run.controller.signal, startedAt: run.startedAt }
    );
    if (previewRun === run) {
      cadencePreviewStatus.textContent = message("optionsCadencePreviewComplete");
      cadenceAction.textContent = message("optionsCadenceActionResolved");
    }
  } catch (error) {
    if (error?.name !== "AbortError") {
      throw error;
    }
  } finally {
    if (previewRun === run) {
      previewRun = null;
      previewInstrument.finish();
      stopClock(run);
      showClock(phrase, phrase.durationMs);
      clearCurrentPreviewMarks();
      clearStructureMarks();
      cadenceStop.hidden = true;
      if (run.stale) {
        stagePreview();
      }
    }
  }
}

// --- keyboard shortcut -----------------------------------------------------

/**
 * Firefox owns the shortcut, not storage.
 *
 * `commands.update` needs no permission and is the supported way to rebind a
 * command; it throws on a combination Firefox will not accept, which is the
 * only validation worth having here.
 */
async function showShortcut() {
  try {
    const commands = await browser.commands.getAll();
    const action = commands.find((command) => command.name === ACTION_COMMAND);
    shortcutInput.value = action?.shortcut ?? "";
  } catch (error) {
    log.warn("commands-unavailable", { error: describeError(error) });
    shortcutInput.disabled = true;
  }
}

async function applyShortcut() {
  const shortcut = shortcutInput.value.trim();
  try {
    await browser.commands.update({ name: ACTION_COMMAND, shortcut });
    say(shortcutStatus, message("optionsShortcutApplied"), "ready");
    log.info("shortcut-changed", {});
  } catch (error) {
    say(shortcutStatus, message("optionsShortcutInvalid"), "error");
    log.warn("shortcut-rejected", { error: describeError(error) });
    await showShortcut();
  }
}

async function resetShortcut() {
  try {
    await browser.commands.reset(ACTION_COMMAND);
    await showShortcut();
    say(shortcutStatus, message("optionsShortcutApplied"), "ready");
  } catch (error) {
    say(shortcutStatus, message("optionsShortcutInvalid"), "error");
    log.warn("shortcut-reset-failed", { error: describeError(error) });
  }
}

// --- the companion connection ----------------------------------------------

/**
 * The link to the event page.
 *
 * Only the event page may speak to the native host — that separation is the
 * add-on's whole trust boundary — so the connection test is asked for here and
 * performed there.
 */
const port = browser.runtime.connect({ name: "ethnos:options" });

port.onMessage.addListener((incoming) => {
  if (incoming?.type !== "ethnos:health-result") {
    return;
  }
  if (incoming.ok) {
    say(healthStatus, message("optionsConnectionOk", [String(incoming.elapsedMs)]), "ready");
  } else {
    say(healthStatus, message(incoming.errorKey || "errorEthnosUnreachable"), "error");
  }
});

function testConnection() {
  say(healthStatus, message("optionsConnectionChecking"));
  try {
    port.postMessage({ type: "ethnos:health" });
  } catch (error) {
    log.error("health-request-failed", { error: describeError(error) });
    say(healthStatus, message("errorNoBridge"), "error");
  }
}

// --- diagnostics -----------------------------------------------------------

/** Draw the recent end of the log. Built as elements; nothing is ever HTML. */
async function showLog() {
  const entries = await readLog();
  logView.replaceChildren();
  const shown = entries.slice(-LOG_ROWS);
  for (const entry of shown) {
    const row = document.createElement("div");
    row.className = `log__row log__row--${entry.level}`;

    const time = document.createElement("span");
    time.className = "log__time";
    time.textContent = new Date(entry.t).toISOString().slice(11, 19);

    const scope = document.createElement("span");
    scope.className = "log__scope";
    scope.textContent = entry.scope;

    const event = document.createElement("span");
    event.className = "log__event";
    event.textContent = entry.event;

    const data = document.createElement("span");
    data.className = "log__data";
    data.textContent = entry.data === undefined ? "" : JSON.stringify(entry.data);

    row.append(time, scope, event, data);
    logView.append(row);
  }
  logView.scrollTop = logView.scrollHeight;
  // The ledger is storage the user did not ask for and cannot see in this
  // view, so it is counted here. Hidden retained state would be a worse
  // bargain than no retained state at all, and Clear below erases both.
  const failures = await readFailures();
  const kept = failures.groups.reduce((total, group) => total + (group.count ?? 0), 0);
  const counted = entries.length === 0
    ? message("optionsDiagnosticsEmpty")
    : message("optionsDiagnosticsCount", [String(shown.length), String(entries.length)]);
  logSummary.textContent = kept === 0
    ? counted
    : `${counted} ${message("optionsDiagnosticsFailures", [
      String(kept),
      String(failures.groups.length),
    ])}`;
}

async function copyLog() {
  const lines = (await readLog()).map(formatEntry).join("\n");
  if (lines.length === 0) {
    say(logStatus, message("optionsDiagnosticsEmpty"));
    return;
  }
  try {
    await navigator.clipboard.writeText(lines);
    say(logStatus, message("optionsCopied"), "ready");
  } catch (error) {
    log.warn("clipboard-refused", { error: describeError(error) });
    say(logStatus, message("optionsCopyFailed"), "error");
  }
}

// --- wiring ----------------------------------------------------------------

/** Attach a handler that reports its own failure rather than vanishing. */
function on(element, type, handler) {
  element.addEventListener(type, (event) => {
    let result;
    try {
      result = handler(event);
    } catch (error) {
      log.error("handler-threw", { type, error: describeError(error) });
      return;
    }
    if (result && typeof result.catch === "function") {
      result.catch((error) => log.error("handler-rejected", { type, error: describeError(error) }));
    }
  });
}

on(document.querySelector("#shortcut-save"), "click", applyShortcut);
on(document.querySelector("#shortcut-reset"), "click", resetShortcut);
on(cadenceApply, "click", applyCadence);
on(cadencePlay, "click", startPreview);
on(cadenceStop, "click", () => stopPreview({ announce: true, restage: true }));
on(document.querySelector("#health"), "click", testConnection);
on(document.querySelector("#log-refresh"), "click", showLog);
on(document.querySelector("#log-copy"), "click", copyLog);
on(document.querySelector("#log-clear"), "click", async () => {
  await clearLog();
  // Clearing diagnostics clears every one of them. A ledger that survived the
  // button labelled Clear would be exactly the kind of quiet retention this
  // add-on promises not to have.
  await clearFailures();
  await showLog();
  say(logStatus, message("optionsDiagnosticsCleared"), "ready");
});

on(document.querySelector("#reset-all"), "click", async () => {
  stopPreview();
  await resetSettings();
  await bindSettings();
  say(resetStatus, message("optionsResetDone"), "ready");
  log.info("settings-reset", {});
});

self.addEventListener("pagehide", () => { stopPreview(); previewInstrument.close(); });

/** Reflect the motion preference in one place the stylesheet can read. */
function showMotionPreference() {
  cadenceEquation.dataset.reducedMotion = String(motionQuery.matches);
}

motionQuery.addEventListener("change", showMotionPreference);

/**
 * Describe the pipeline, which is no longer a choice.
 *
 * Facet routes every question the page states as mathematics, so these lines
 * are a statement of the architecture rather than a readout of a setting. The
 * one thing that genuinely varies is the last run the event page happened to
 * see, and nothing is fetched to find it: a settings page that woke a model
 * host to render a label would be paying a real cost for a cosmetic one, and a
 * page that guessed instead would be worse than one that says it does not know.
 */
async function showPipeline() {
  const exact = document.querySelector("#pipeline-exact");
  const reasoner = document.querySelector("#pipeline-reasoner");
  const graph = document.querySelector("#pipeline-graph");
  const observed = document.querySelector("#pipeline-observed");
  if (!exact || !reasoner || !graph || !observed) {
    return;
  }
  exact.textContent = message("optionsPipelineExactValue");
  reasoner.textContent = message("optionsPipelineReasonerFacet");
  graph.textContent = message("optionsPipelineGraphValue");
  let seen = null;
  try {
    ({ facetLastSeen: seen } = await browser.storage.local.get("facetLastSeen"));
  } catch {
    seen = null;
  }
  observed.textContent = seen?.facetModel
    ? [seen.facetModel, seen.facetRuntime, seen.facetDevice]
        .filter(Boolean)
        .join(" · ")
    : message("optionsPipelineObservedNone");
}

async function initialize() {
  localizeDocument();
  showMotionPreference();
  const stored = await readSettings();
  initLog("options", { level: stored.logLevel });
  await bindSettings();
  await showPipeline();
  await showShortcut();
  await showLog();
}

initialize().catch((error) => {
  initLog("options");
  log.error("options-init-failed", { error: describeError(error) });
});
