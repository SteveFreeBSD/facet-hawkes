"use strict";

/**
 * Every preference the add-on has, declared once.
 *
 * The settings page used to offer one control that did something — automatic
 * solving — beside a text box for a fixed answer, left over from before there
 * was a solver. Everything that actually governed a solve was a constant in
 * `background.js`.
 *
 * So the schema below is the definition, and both the settings page and the
 * event page read it: the page builds its controls from it and validates
 * against it, and the event page reads values through {@link readSettings}.
 * Adding a preference means adding one entry here, not four edits that can
 * disagree.
 *
 * A stored value that is missing, of the wrong type, or out of range falls
 * back to the declared default rather than propagating — a corrupt preference
 * should cost you the preference, not the add-on.
 */

import { LEVELS } from "/common/log.js";

/** Beat shapes offered by the custom cadence panel. */
export const ENTRY_PATTERNS = Object.freeze({
  steady: Object.freeze([1, 1, 1, 1]),
  waltz: Object.freeze([1.35, 0.82, 0.92]),
  backbeat: Object.freeze([1, 0.68, 1.18, 0.78]),
  syncopated: Object.freeze([1, 0.56, 0.9, 1.24]),
});

/**
 * Musical starting points. Tempo is copied into its independent control when
 * a genre is chosen; every other value remains owned by the preset until the
 * user selects Custom.
 */
export const ENTRY_GENRE_PRESETS = Object.freeze({
  classical: Object.freeze({
    pattern: "waltz", tempoBpm: 72, swingPercent: 0,
    variationPercent: 7, symbolRestPercent: 32,
  }),
  jazz: Object.freeze({
    pattern: "syncopated", tempoBpm: 112, swingPercent: 30,
    variationPercent: 22, symbolRestPercent: 58,
  }),
  lofi: Object.freeze({
    pattern: "backbeat", tempoBpm: 82, swingPercent: 12,
    variationPercent: 18, symbolRestPercent: 42,
  }),
  electronic: Object.freeze({
    pattern: "steady", tempoBpm: 128, swingPercent: 0,
    variationPercent: 6, symbolRestPercent: 24,
  }),
});

export const ENTRY_GENRES = Object.freeze([
  ...Object.keys(ENTRY_GENRE_PRESETS),
  "custom",
]);

/**
 * @typedef {object} Setting
 * @property {"boolean" | "integer" | "enum"} kind
 * @property {boolean | number | string} fallback value used when unset or invalid
 * @property {number} [min] integer only, inclusive
 * @property {number} [max] integer only, inclusive
 * @property {readonly string[]} [values] enum only
 */

/** @type {Record<string, Setting>} */
export const SETTINGS = {
  /* Start solving as soon as an answer field is found, rather than waiting for
     a click. Insertion is never automatic; that is the add-on's whole safety
     contract and is deliberately not a preference. */
  autoSolve: { kind: "boolean", fallback: true },

  /* How long a solve may run before it is abandoned. Was a hardcoded four
     minutes. A larger vision model on a slower machine needs more; someone
     who would rather retry than wait needs less. */
  solveTimeoutSeconds: { kind: "integer", fallback: 240, min: 30, max: 900 },

  /* Send only the vertical region from the question instruction to the answer
     area. If those boundaries cannot be established, fail closed rather than
     silently transmitting the full viewport. The user may explicitly disable
     this protection for an unusual question layout. */
  cropCapture: { kind: "boolean", fallback: true },

  /* How wide the panel opens. Firefox sizes a popup to its content, so this is
     the only control there is over it. Long problem text is much easier to
     check at 420 than at 320. */
  panelWidth: { kind: "integer", fallback: 360, min: 300, max: 560 },

  /* Show the recognized problem expanded rather than folded away. Checking the
     transcription is the point of showing it, so wanting it open by default is
     reasonable; it costs panel height, so wanting it folded is too. */
  problemOpen: { kind: "boolean", fallback: false },

  /* Theatrical, audible-in-spirit pacing for demonstrations. Presets own the
     beat shape and feel; tempo and the hard duration window stay independent
     so any preset can be sped up without losing its character. */
  entryGenre: { kind: "enum", fallback: "lofi", values: ENTRY_GENRES },
  entryTempoBpm: { kind: "integer", fallback: 82, min: 45, max: 180 },
  entryDurationMinSeconds: { kind: "integer", fallback: 5, min: 2, max: 12 },
  entryDurationMaxSeconds: { kind: "integer", fallback: 10, min: 2, max: 12 },

  /* These values are retained while a preset is active and become live when
     Custom is selected, so experimentation never destroys a saved custom
     arrangement. */
  entryPattern: {
    kind: "enum", fallback: "backbeat", values: Object.freeze(Object.keys(ENTRY_PATTERNS)),
  },
  entrySwingPercent: { kind: "integer", fallback: 12, min: 0, max: 60 },
  entryVariationPercent: { kind: "integer", fallback: 18, min: 0, max: 35 },
  entrySymbolRestPercent: { kind: "integer", fallback: 42, min: 0, max: 100 },

  /* What reaches the diagnostic log. Never the coursework itself -- see
     `common/log.js`. */
  logLevel: { kind: "enum", fallback: "info", values: LEVELS },
};

/** Names of every preference, for iteration and for clearing them all. */
export const SETTING_KEYS = Object.freeze(Object.keys(SETTINGS));

/** Every default, as a plain object. */
export function defaultSettings() {
  const out = {};
  for (const [key, setting] of Object.entries(SETTINGS)) {
    out[key] = setting.fallback;
  }
  return out;
}

/**
 * Turn stored preferences into the small, serializable object passed to the
 * isolated insertion script. Relational duration validation lives here: each
 * field is valid on its own, but the order can still be reversed by hand in
 * storage, and the insertion path must remain safe in that case.
 */
export function resolveEntryCadence(settings = {}) {
  const genre = ENTRY_GENRES.includes(settings.entryGenre)
    ? settings.entryGenre
    : SETTINGS.entryGenre.fallback;
  const custom = genre === "custom";
  const feel = custom
    ? {
        pattern: settings.entryPattern,
        swingPercent: settings.entrySwingPercent,
        variationPercent: settings.entryVariationPercent,
        symbolRestPercent: settings.entrySymbolRestPercent,
      }
    : ENTRY_GENRE_PRESETS[genre];
  const pattern = ENTRY_PATTERNS[feel.pattern] ?? ENTRY_PATTERNS.backbeat;
  const firstSeconds = coerce(
    "entryDurationMinSeconds", settings.entryDurationMinSeconds
  ).value;
  const secondSeconds = coerce(
    "entryDurationMaxSeconds", settings.entryDurationMaxSeconds
  ).value;

  return {
    tempoBpm: coerce("entryTempoBpm", settings.entryTempoBpm).value,
    durationMinMs: Math.min(firstSeconds, secondSeconds) * 1000,
    durationMaxMs: Math.max(firstSeconds, secondSeconds) * 1000,
    rhythmWeights: [...pattern],
    swingRatio: coerce("entrySwingPercent", feel.swingPercent).value / 100,
    variationRatio: coerce("entryVariationPercent", feel.variationPercent).value / 100,
    symbolRestRatio: coerce("entrySymbolRestPercent", feel.symbolRestPercent).value / 100,
  };
}

/**
 * Coerce one stored value to something the schema permits.
 *
 * @param {string} key
 * @param {unknown} value
 * @returns {{ok: true, value: boolean|number|string} | {ok: false, value: boolean|number|string}}
 *   `ok` is false when the input had to be replaced by the default.
 */
export function coerce(key, value) {
  const setting = SETTINGS[key];
  if (!setting) {
    return { ok: false, value: undefined };
  }
  if (setting.kind === "boolean") {
    return typeof value === "boolean"
      ? { ok: true, value }
      : { ok: false, value: setting.fallback };
  }
  if (setting.kind === "integer") {
    const number = typeof value === "number" ? Math.round(value) : Number.NaN;
    if (!Number.isFinite(number) || number < setting.min || number > setting.max) {
      return { ok: false, value: setting.fallback };
    }
    return { ok: true, value: number };
  }
  return setting.values.includes(value)
    ? { ok: true, value }
    : { ok: false, value: setting.fallback };
}

/**
 * Interpret a value a person just typed.
 *
 * Distinct from {@link coerce}, which reads storage and answers "is this
 * usable?" — the safe reply there is the default. Someone typing 9999 into a
 * field labelled "30 to 900" means "as long as you will allow", so a number
 * outside the range is pulled to the nearest end of it rather than thrown away.
 * Anything that is not a number at all still falls back.
 *
 * @returns {{ok: boolean, value: boolean|number|string}} `ok` is false when the
 *   input had to be adjusted, whether by clamping or by falling back.
 */
export function clamp(key, value) {
  const setting = SETTINGS[key];
  if (!setting || setting.kind !== "integer") {
    return coerce(key, value);
  }
  const number = typeof value === "number" ? Math.round(value) : Number.NaN;
  if (!Number.isFinite(number)) {
    return { ok: false, value: setting.fallback };
  }
  if (number < setting.min) {
    return { ok: false, value: setting.min };
  }
  if (number > setting.max) {
    return { ok: false, value: setting.max };
  }
  return { ok: true, value: number };
}

/**
 * Every preference, with defaults filled in for anything unset or invalid.
 *
 * @returns {Promise<Record<string, boolean|number|string>>}
 */
export async function readSettings() {
  let stored = {};
  try {
    stored = (await browser.storage.local.get(SETTING_KEYS)) ?? {};
  } catch {
    return defaultSettings();
  }
  const out = {};
  for (const key of SETTING_KEYS) {
    out[key] = coerce(key, stored[key]).value;
  }
  return out;
}

/**
 * Store one preference, after checking it against the schema.
 *
 * @returns {Promise<boolean>} whether the value was accepted
 */
export async function writeSetting(key, value) {
  const checked = coerce(key, value);
  if (!checked.ok) {
    return false;
  }
  await browser.storage.local.set({ [key]: checked.value });
  return true;
}

/** Put every preference back to its default. */
export async function resetSettings() {
  await browser.storage.local.remove([...SETTING_KEYS]);
}

/**
 * Call back whenever a preference changes, wherever it changed.
 *
 * The event page holds settings in memory to keep a solve from waiting on
 * storage, so it has to hear about a change made in the settings page while it
 * is loaded rather than only at startup.
 *
 * @param {(changed: Record<string, boolean|number|string>) => void} listener
 */
export function onSettingsChanged(listener) {
  browser.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") {
      return;
    }
    const changed = {};
    for (const key of SETTING_KEYS) {
      if (key in changes) {
        changed[key] = coerce(key, changes[key].newValue).value;
      }
    }
    if (Object.keys(changed).length > 0) {
      listener(changed);
    }
  });
}
