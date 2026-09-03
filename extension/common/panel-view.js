"use strict";

/**
 * What the panel should show, worked out from the state the event page reports.
 *
 * DOM-free and `browser`-free on purpose. Every decision the panel makes —
 * which button is primary, what the status line says, how far the bar has
 * filled, whether Insert is available — is made here and returned as plain
 * data, so `popup.js` is left with nothing but assignments to elements.
 *
 * That split exists because of a real failure: `render()` read a `const` it
 * declared thirty lines further down, so every render threw `ReferenceError`
 * and the panel silently stopped updating. Nothing caught it, because nothing
 * in the suite could run the panel — it was all DOM. This module can be run,
 * and `tests/test_hawkes_panel.py` runs it against every phase.
 *
 * Text is returned as catalogue keys rather than strings; localization belongs
 * to whoever has a `browser.i18n` to hand.
 */

import { answerFitsEditor } from "/common/editor-rules.js";
import { planEntry } from "/common/editor-plan.js";

/** The stages a solve goes through, in order. */
export const STAGES = ["capturing", "reading", "checking", "solving"];

/** Catalogue key per stage, written out so the build can check they exist. */
const STAGE_LABELS = {
  capturing: "stageCapturing",
  reading: "stageReading",
  checking: "stageChecking",
  solving: "stageSolving",
};

/** Status line per phase, when no error and no refusal is being shown. */
const PHASE_STATUS = {
  idle: "statusChecking",
  checking: "statusChecking",
  ready: "statusReady",
  solving: "statusSolving",
  solved: "statusSolved",
  inserting: "statusInserting",
  inserted: "statusInserted",
  failed: "statusChecking",
};

/**
 * How far through a solve the reported stage is, as a fraction.
 *
 * The health check is given a sliver rather than nothing, so pressing Solve
 * visibly does something before the first stage is announced.
 */
export function stageProgress(stage) {
  if (stage === "done") {
    return 1;
  }
  if (stage === "checking-host") {
    return 0.04;
  }
  const position = STAGES.indexOf(stage);
  return position < 0 ? 0 : (position + 1) / (STAGES.length + 1);
}

/**
 * Whether the answer shown is still good, and only the entry is manual.
 *
 * Choosing an option, or building a fraction with the keypad, leaves the
 * answer perfectly usable — the panel should read as an instruction rather
 * than as something having gone wrong.
 */
export function usableByHand(verdict) {
  return (
    verdict.code === "editor-option-answer" ||
    verdict.code === "answer-needs-template" ||
    verdict.code === "template-refused-by-question"
  );
}

/** Say what the editor itself objected to, in its own terms. */
function refusal(verdict) {
  if (verdict.code === "answer-needs-template") {
    return { key: "errorAnswerNeedsTemplate", args: [verdict.detail ?? ""] };
  }
  if (verdict.code === "answer-has-rejected-characters") {
    return { key: "errorAnswerRejected", args: [verdict.detail ?? ""] };
  }
  if (verdict.code === "editor-option-answer") {
    return { key: "errorOptionAnswer", args: [] };
  }
  if (verdict.code === "template-refused-by-question") {
    return { key: "errorTemplateRefused", args: [verdict.detail ?? ""] };
  }
  return { key: "errorEditorUnknown", args: [] };
}

/**
 * @typedef {object} PanelView
 * @property {{text: string, empty: boolean}} answer
 * @property {{text: string, idle: boolean}} problem
 * @property {{key: string, args: string[]} | null} badge
 * @property {{text: string, available: boolean}} detail
 * @property {{key: string, args: string[], kind: string}} status
 * @property {{fraction: number, state: string}} progress
 * @property {{key: string, disabled: boolean, primary: boolean}} solve
 * @property {{enabled: boolean, primary: boolean}} insert
 * @property {{enabled: boolean, text: string}} copy
 * @property {boolean} resetDisabled
 * @property {boolean} busy
 * @property {boolean} running
 */

/**
 * Derive the whole panel from one state.
 *
 * @param {object | null} state as reported by the event page
 * @param {number} [now] epoch milliseconds, for the elapsed-time readout
 * @returns {PanelView}
 */
export function describeView(state, now = 0) {
  if (!state) {
    return offline();
  }

  const running = state.phase === "solving";
  const busy = running || state.phase === "inserting";

  // Always the readable form. What can be typed is decided separately, and an
  // answer you must enter by hand still has to be legible.
  const shown = state.displayText || state.answer || "";

  /** @type {PanelView} */
  const view = {
    answer: { text: shown, empty: shown.length === 0 },
    problem: { text: state.problemText || "", idle: !state.problemText },
    badge: state.source ? { key: "popupSourceBadge", args: [state.source] } : null,
    detail: { text: state.detail || "", available: Boolean(state.detail) },
    status: { key: "statusChecking", args: [], kind: "" },
    progress: { fraction: 0, state: "" },
    solve: {
      key: running
        ? "popupCancelButton"
        : state.errorKey === "errorTabAccessLost"
          ? "popupGrantAccessButton"
          : state.errorKey
            ? "popupRetryButton"
            : "popupSolveButton",
      disabled: state.phase === "inserting",
      primary: true,
    },
    insert: { enabled: false, primary: false },
    copy: { enabled: shown.length > 0, text: shown },
    resetDisabled: busy,
    busy,
    running,
  };

  if (state.errorKey) {
    view.status = { key: state.errorKey, args: state.errorArgs ?? [], kind: "error" };
  } else if (state.phase === "solved") {
    // Two ways in: typed straight into the box, or built with the editor's
    // own keypad templates. Only when neither works is this the user's job.
    const typeable = state.answer
      ? answerFitsEditor(state.answer, state.editor)
      : { insertable: false, code: "answer-empty" };
    const plan = planEntry(state.entryText || state.answer, state.editor);

    if (typeable.insertable || plan.ok) {
      // The primary action moves from Solve to Insert once there is something
      // to insert, so the next step is obvious rather than described.
      view.insert = { enabled: true, primary: true };
      view.solve.primary = false;
      view.status = {
        key: plan.ok && !typeable.insertable ? "statusWillBuild" : "statusSolved",
        args: [],
        kind: "ready",
      };
    } else {
      // The answer is still on screen and still usable by hand. Only the last
      // step is yours, so this is a note about what to do -- not a failure.
      // A named non-real result can accompany Hawkes' ordinary numeric
      // editor. `answerFitsEditor` recognizes that manual-choice handoff;
      // prefer it over the planner's less useful first-rejected-letter error.
      const reason = typeable.code === "editor-option-answer"
        ? typeable
        : plan.ok === false ? plan : typeable;
      const said = refusal(reason);
      view.status = { ...said, kind: usableByHand(reason) ? "note" : "error" };
    }
  } else if (running) {
    // The stage, plus how long it has been going, so a minute-long solve reads
    // as progress rather than as a hang.
    const label = STAGE_LABELS[state.stage] ?? "statusSolving";
    const seconds = state.startedAt ? Math.max(0, Math.round((now - state.startedAt) / 1000)) : 0;
    view.status = { key: label, args: [], kind: "", elapsed: seconds };
  } else {
    view.status = {
      key: PHASE_STATUS[state.phase] ?? "statusChecking",
      args: [],
      kind: state.phase === "inserted" ? "ready" : "",
    };
  }

  if (running) {
    view.progress = { fraction: stageProgress(state.stage), state: "" };
  } else if (state.errorKey) {
    view.progress = { fraction: 1, state: "error" };
  } else if (state.phase === "solved" || state.phase === "inserted") {
    view.progress = { fraction: 1, state: "done" };
  }

  return view;
}

/** The view when the event page has said nothing at all. */
function offline() {
  return {
    answer: { text: "", empty: true },
    problem: { text: "", idle: true },
    badge: null,
    detail: { text: "", available: false },
    status: { key: "errorNoBridge", args: [], kind: "error" },
    progress: { fraction: 0, state: "" },
    solve: { key: "popupSolveButton", disabled: true, primary: true },
    insert: { enabled: false, primary: false },
    copy: { enabled: false, text: "" },
    resetDisabled: false,
    busy: false,
    running: false,
  };
}
