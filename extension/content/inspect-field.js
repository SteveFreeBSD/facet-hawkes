"use strict";

/**
 * Operation script: report this frame's answer-field state.
 *
 * The popup injects it into every frame of the active tab with
 * `allFrames: true`, so each frame reports for itself and the popup can find
 * the one holding the caret. The value of the last statement becomes this
 * frame's `InjectionResult.result`; nothing is registered and nothing is left
 * behind.
 */

(() =>
  typeof ethnosHawkes === "undefined"
    ? { ready: false, code: "prelude-missing" }
    : ethnosHawkes.inspectField())();
