"use strict";

/**
 * The settings page.
 *
 * Controls are bound by `data-setting="<key>"`, and the key is looked up in
 * `common/settings.js` to decide how to read the control and how to validate
 * what comes out of it. The cadence card adds only presentation behaviour: a
 * live beat preview, linked duration endpoints, and preset tempo suggestions.
 *
 * The rest of the page is the two things you cannot put in a schema: the
 * keyboard shortcut, which Firefox owns and which is changed through
 * `browser.commands`, and the diagnostic log.
 */

import { localizeDocument, message } from "../common/i18n.js";
import {
  ENTRY_GENRE_PRESETS,
  SETTINGS,
  clamp,
  readSettings,
  resetSettings,
  resolveEntryCadence,
  writeSetting,
} from "../common/settings.js";
import { clearLog, describeError, formatEntry, initLog, log, readLog, setLogLevel } from "../common/log.js";

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
const cadenceCustom = document.querySelector("#cadence-custom");
const cadenceNote = document.querySelector("#cadence-note");
const cadencePreview = document.querySelector("#cadence-preview");
const cadenceSummary = document.querySelector("#cadence-summary");
const cadenceBars = [...cadencePreview.querySelectorAll(".cadence-preview__beat")];

const SETTING_OUTPUT_KEYS = Object.freeze({
  panelWidth: "optionsWidthValue",
  entryTempoBpm: "optionsCadenceTempoValue",
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

/** Draw the selected arrangement without playing sound or touching a page. */
function showCadence() {
  const values = visibleSettings();
  const genre = values.entryGenre;
  const resolved = resolveEntryCadence(values);
  const genreName = message(GENRE_LABEL_KEYS[genre]);
  cadenceCustom.hidden = genre !== "custom";
  cadenceNote.textContent = message(GENRE_HELP_KEYS[genre]);
  cadenceSummary.textContent = message(
    "optionsCadenceSummary", [genreName, String(resolved.tempoBpm)]
  );
  cadencePreview.setAttribute(
    "aria-label",
    message("optionsCadencePreviewLabel", [genreName, String(resolved.tempoBpm)])
  );
  for (let index = 0; index < cadenceBars.length; index += 1) {
    const bar = cadenceBars[index];
    const weight = resolved.rhythmWeights[index];
    bar.hidden = weight === undefined;
    if (weight !== undefined) {
      bar.style.setProperty("--beat-weight", String(weight));
    }
  }
}

/** Keep the two ends of the hard timing window in chronological order. */
function alignDurationWindow(changedKey, settledValue) {
  const minimum = document.querySelector("#entryDurationMinSeconds");
  const maximum = document.querySelector("#entryDurationMaxSeconds");
  if (changedKey === "entryDurationMinSeconds" && settledValue > Number(maximum.value)) {
    showValue(maximum, settledValue);
    return writeSetting("entryDurationMaxSeconds", settledValue);
  }
  if (changedKey === "entryDurationMaxSeconds" && settledValue < Number(minimum.value)) {
    showValue(minimum, settledValue);
    return writeSetting("entryDurationMinSeconds", settledValue);
  }
  return Promise.resolve(true);
}

async function bindSettings() {
  const stored = await readSettings();
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

    // `input` drives the readout only. A slider fires it for every pixel of a
    // drag, and none of those are a preference the user has settled on.
    control.addEventListener("input", () => {
      const settled = clamp(key, controlValue(control));
      showReadout(control, settled.value);
      if (key.startsWith("entry")) {
        showCadence();
      }
    });

    // `change` is the commit: the pointer released, the select closed, the
    // number field left. A value out of range is put back to something valid
    // rather than silently disagreeing with what is stored.
    control.addEventListener("change", () => {
      const settled = clamp(key, controlValue(control));
      showValue(control, settled.value);
      const writes = [
        writeSetting(key, settled.value),
        alignDurationWindow(key, settled.value),
      ];
      if (key === "entryGenre" && settled.value !== "custom") {
        const recommendedTempo = ENTRY_GENRE_PRESETS[settled.value].tempoBpm;
        const tempo = document.querySelector("#entryTempoBpm");
        showValue(tempo, recommendedTempo);
        writes.push(writeSetting("entryTempoBpm", recommendedTempo));
      }
      Promise.all(writes)
        .then(() => {
          if (key === "logLevel") {
            setLogLevel(settled.value);
          }
          if (key.startsWith("entry")) {
            showCadence();
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

// --- the Ethnos connection -------------------------------------------------

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
  logSummary.textContent = entries.length === 0
    ? message("optionsDiagnosticsEmpty")
    : message("optionsDiagnosticsCount", [String(shown.length), String(entries.length)]);
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
on(document.querySelector("#health"), "click", testConnection);
on(document.querySelector("#log-refresh"), "click", showLog);
on(document.querySelector("#log-copy"), "click", copyLog);
on(document.querySelector("#log-clear"), "click", async () => {
  await clearLog();
  await showLog();
  say(logStatus, message("optionsDiagnosticsCleared"), "ready");
});

on(document.querySelector("#reset-all"), "click", async () => {
  await resetSettings();
  await bindSettings();
  say(resetStatus, message("optionsResetDone"), "ready");
  log.info("settings-reset", {});
});

async function initialize() {
  localizeDocument();
  const stored = await readSettings();
  initLog("options", { level: stored.logLevel });
  await bindSettings();
  await showShortcut();
  await showLog();
}

initialize().catch((error) => {
  initLog("options");
  log.error("options-init-failed", { error: describeError(error) });
});
