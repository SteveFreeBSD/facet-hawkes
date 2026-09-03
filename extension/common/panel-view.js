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
 * What the panel is for, right now.
 *
 * One name per situation the user can be in, so the primary button, the Enter
 * key and the footer hint are decided once rather than re-derived from
 * `insert.enabled` and `running` at every site that needs them.
 *
 * 0.38 had no name for a finished insertion, and each of those sites fell
 * through to its "nothing has happened yet" default: the answer card emptied
 * to an em dash, Solve kept the accent and the caret, and the footer offered
 * "Enter to solve" for the question that had just been answered. Pressing it
 * was the retry that started this redesign.
 *
 * @typedef {"offline"|"solve"|"working"|"review"|"inserting"|"placed"} Stance
 */

/** The action Enter performs in each stance. */
const PRIMARY = {
  offline: "none",
  solve: "solve",
  working: "cancel",
  review: "insert",
  inserting: "none",
  placed: "none",
};

/**
 * Footer hint per primary action.
 *
 * `null` where nothing is bound to Enter. An unbound key must be offered no
 * hint at all rather than the nearest available one: naming an action the
 * panel will not perform is how "Enter to solve" survived an insertion.
 */
const HINTS = {
  solve: "popupHintSolve",
  cancel: "popupHintCancel",
  insert: "popupHintInsert",
  none: null,
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
 * Whether a solved answer can be entered for you, and what to say either way.
 *
 * Two ways in: typed straight into the box, or built with the editor's own
 * keypad templates. Only when neither works is this the user's job.
 */
function reviewOffer(state) {
  const typeable = state.answer
    ? answerFitsEditor(state.answer, state.editor)
    : { insertable: false, code: "answer-empty" };
  const plan = planEntry(state.entryText || state.answer, state.editor);

  if (typeable.insertable || plan.ok) {
    // An answer reached without the question's own instruction came from a
    // model reading the picture with nothing saying what to do about it --
    // the least reliable way this add-on can arrive at anything. It is still
    // offered, because it is often right and nothing is inserted unreviewed;
    // but it must not read identically to an answer derived exactly. Without
    // this the two were indistinguishable in the panel.
    if (state.promptSeen === false) {
      return {
        insertable: true,
        status: { key: "statusSolvedUnread", args: [], kind: "note" },
      };
    }
    return {
      insertable: true,
      status: {
        key: plan.ok && !typeable.insertable ? "statusWillBuild" : "statusSolved",
        args: [],
        kind: "ready",
      },
    };
  }

  // The answer is still on screen and still usable by hand. Only the last step
  // is yours, so this is a note about what to do -- not a failure.
  // A named non-real result can accompany Hawkes' ordinary numeric editor.
  // `answerFitsEditor` recognizes that manual-choice handoff; prefer it over
  // the planner's less useful first-rejected-letter error.
  const reason = typeable.code === "editor-option-answer"
    ? typeable
    : plan.ok === false ? plan : typeable;
  const said = refusal(reason);
  return {
    insertable: false,
    status: { ...said, kind: usableByHand(reason) ? "note" : "error" },
  };
}

/**
 * @typedef {object} PanelView
 * @property {{text: string, empty: boolean, placed: boolean}} answer
 * @property {{text: string, idle: boolean}} problem
 * @property {{key: string, args: string[]} | null} badge
 * @property {{text: string, available: boolean}} detail
 * @property {{key: string, args: string[], kind: string}} status
 * @property {{fraction: number, state: string}} progress
 * @property {{key: string, disabled: boolean, primary: boolean}} solve
 * @property {{enabled: boolean, primary: boolean}} insert
 * @property {{enabled: boolean, text: string}} copy
 * @property {string | null} hint catalogue key, or null when Enter does nothing
 * @property {Stance} stance
 * @property {"none"|"solve"|"cancel"|"insert"} primary what Enter performs
 * @property {boolean} resetDisabled
 * @property {boolean} busy
 * @property {boolean} running
 */

/**
 * Derive the whole panel from one state.
 *
 * @param {object | null} state as reported by the event page
 * @param {number} [now] epoch milliseconds, for the elapsed-time readout
 * @param {{docked?: boolean}} [surface] where the panel is being shown
 * @returns {PanelView}
 */
export function describeView(state, now = 0, { docked = false } = {}) {
  if (!state) {
    return offline();
  }

  const running = state.phase === "solving";
  const busy = running || state.phase === "inserting";

  // What was put in the field, kept for display only. Read exclusively in the
  // inserted phase: the event page clears it the moment a new solve begins or
  // a different question is recognized, and gating on the phase as well means
  // no ordering of state updates can show it beside live work.
  const placed = state.phase === "inserted" ? state.placedText || "" : "";

  // Always the readable form. What can be typed is decided separately, and an
  // answer you must enter by hand still has to be legible.
  // Defense in depth: even a delayed or older event page must never make a
  // prior result look current while a fresh solve is running.
  const shown = running ? "" : state.displayText || state.answer || placed;

  // Worked out before the stance, because whether the editor will take this
  // answer is exactly what separates "press Insert" from "your turn".
  const offer = !state.errorKey && state.phase === "solved" ? reviewOffer(state) : null;

  /** @type {Stance} */
  const stance = running
    ? "working"
    : state.phase === "inserting"
      ? "inserting"
      : state.errorKey
        ? "solve"
        : state.phase === "inserted"
          ? "placed"
          : offer?.insertable
            ? "review"
            : "solve";
  const primary = PRIMARY[stance];

  /** @type {PanelView} */
  const view = {
    answer: { text: shown, empty: shown.length === 0, placed: placed.length > 0 },
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
            // The same button, renamed for what pressing it would now mean.
            // "Solve with Ethnos" beside an answer already in the box reads as
            // the next step rather than as starting the question over.
            : stance === "placed"
              ? "popupSolveAgainButton"
              : "popupSolveButton",
      disabled: state.phase === "inserting",
      primary: primary === "solve" || primary === "cancel",
    },
    insert: { enabled: stance === "review", primary: stance === "review" },
    copy: { enabled: shown.length > 0, text: shown },
    hint: HINTS[primary],
    stance,
    primary,
    resetDisabled: busy,
    busy,
    running,
  };

  if (state.errorKey) {
    view.status = { key: state.errorKey, args: state.errorArgs ?? [], kind: "error" };
  } else if (offer) {
    view.status = offer.status;
  } else if (running) {
    // The stage, plus how long it has been going, so a minute-long solve reads
    // as progress rather than as a hang.
    const label = STAGE_LABELS[state.stage] ?? "statusSolving";
    const seconds = state.startedAt ? Math.max(0, Math.round((now - state.startedAt) / 1000)) : 0;
    view.status = { key: label, args: [], kind: "", elapsed: seconds };
  } else if (stance === "placed") {
    // The sidebar stays open and the event page goes on watching for the next
    // question; a toolbar popup is gone the moment focus moves. One state, two
    // different truths about what happens next, so the panel says which.
    view.status = {
      key: docked ? "statusInsertedWatching" : "statusInserted",
      args: [],
      kind: "ready",
    };
  } else {
    view.status = { key: PHASE_STATUS[state.phase] ?? "statusChecking", args: [], kind: "" };
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
    answer: { text: "", empty: true, placed: false },
    problem: { text: "", idle: true },
    badge: null,
    detail: { text: "", available: false },
    status: { key: "errorNoBridge", args: [], kind: "error" },
    progress: { fraction: 0, state: "" },
    // Nothing here can be pressed, so nothing here carries the accent.
    solve: { key: "popupSolveButton", disabled: true, primary: false },
    insert: { enabled: false, primary: false },
    copy: { enabled: false, text: "" },
    hint: null,
    stance: "offline",
    primary: "none",
    resetDisabled: false,
    busy: false,
    running: false,
  };
}
