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

import { MAX_ANSWER_PARTS } from "/common/config.js";
import { answerFitsEditor, tableAnswerFits } from "/common/editor-rules.js";
import { planAnswerParts, planEntry } from "/common/editor-plan.js";

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
  if (state.graphPlan && state.editor?.kind === "graph" && !state.errorKey) {
    return { insertable: true, status: { key: "statusSolved", args: [], kind: "ready" } };
  }
  if (
    Array.isArray(state.answerParts)
    && state.answerParts.length >= 2
    && state.answerParts.length <= MAX_ANSWER_PARTS
  ) {
    // A completion table publishes one control per blank, found by the reader
    // that accepted the table. That mapping is what places these values, so it
    // is what decides whether they can be placed -- the page's editor
    // collection holds a control for every cell of the grid, given and blank
    // alike, and cannot say which is which.
    const tableInsertable = tableAnswerFits(
      state.answerParts, state.tableTargets ?? [], state.editor
    );
    const editors = state.editor?.kind === "multi" ? state.editor.editors : [];
    const multiInsertable = Array.isArray(editors)
      && editors.length === state.answerParts.length
      && state.answerParts.every(
        (part, index) =>
          answerFitsEditor(part, editors[index]).insertable
          || planEntry(part, editors[index]).ok
      );
    const commaInsertable = state.answerParts.length === 2
      && state.editor?.kind !== "multi"
      && /separate multiple answers with a comma/i.test(state.problemText ?? "")
      && planAnswerParts(state.answerParts, state.editor).ok;
    const insertable = tableInsertable || multiInsertable || commaInsertable;
    return insertable
      ? {
          insertable: true,
          status: { key: "statusSolved", args: [], kind: "ready" },
        }
      : {
          insertable: false,
          status: { key: "errorEditorUnknown", args: [], kind: "error" },
        };
  }
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
 * The refusal this state may still show, which is not always the one it holds.
 *
 * An insertion refusal is about one answer. "This question's answer box does
 * not accept: s" is a true and useful sentence about `sqrt101`, and says
 * nothing whatever about the answer that replaced it -- but the event page's
 * state is merged rather than rebuilt, so a key and its arguments outlive the
 * answer they were raised for and land on the next one's card. Live, on
 * 2026-09-07, that put a rejected-character message beside an answer with no
 * such character in it, and the character it named read as a digit.
 *
 * So a refusal is stamped with the answer that produced it, and shown only
 * while that is still the answer. A refusal about nothing in particular -- a
 * lost tab, a site that is not Hawkes, a state written before this stamp
 * existed -- carries no answer and is always shown; those are about the
 * session, not about a value, and clearing them early would hide a live fault.
 */
function heldRefusal(state) {
  if (!state?.errorKey) {
    return "";
  }
  const about = state.errorAnswer ?? "";
  if (about.length === 0) {
    return state.errorKey;
  }
  return about === (state.entryText || state.answer || "") ? state.errorKey : "";
}

/**
 * A multi-part answer, part by part, each named by where it goes.
 *
 * One line reading `0, 8, 8, 5, 3` is the reviewed answer and is also five
 * numbers in a row, which anybody would read as "the first box, then the
 * next". For a completion table that reading is wrong: the page's blanks are
 * numbered by the mathematics -- down the ordered pairs of a row-headed grid
 * -- and the boxes are laid out across two rows, so the two orders name
 * different cells. The panel must not imply an order it does not mean.
 *
 * So a table answer is shown against the table's own words: which column, and
 * which record. Anything else multi-part is genuinely one box per part in
 * visual order, and is numbered as such.
 *
 * @returns {{kind: string, items: {label: string, text: string}[]}}
 */
function answerBreakdown(state) {
  const parts = Array.isArray(state.answerParts) ? state.answerParts : [];
  const none = { kind: "none", items: [] };
  if (parts.length < 2 || parts.length > MAX_ANSWER_PARTS) {
    return none;
  }
  const targets = Array.isArray(state.tableTargets) ? state.tableTargets : [];
  if (targets.length === parts.length) {
    return {
      kind: "cells",
      items: parts.map((text, index) => ({
        label: String(targets[index]?.label ?? `#${index + 1}`).slice(0, 48),
        text,
      })),
    };
  }
  return {
    kind: "fields",
    items: parts.map((text, index) => ({ label: `#${index + 1}`, text })),
  };
}

/**
 * @typedef {object} PanelView
 * @property {{text: string, empty: boolean, placed: boolean}} answer
 * @property {{kind: string, items: {label: string, text: string}[]}} parts
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

  // The refusal this state is still entitled to show, which is not always the
  // one it is still carrying. Worked out before anything reads it.
  const errorKey = heldRefusal(state);

  // Worked out before the stance, because whether the editor will take this
  // answer is exactly what separates "press Insert" from "your turn".
  const offer = !errorKey && state.phase === "solved" ? reviewOffer(state) : null;

  /** @type {Stance} */
  const stance = running
    ? "working"
    : state.phase === "inserting"
      ? "inserting"
      : errorKey
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
    // Only beside a settled answer. While a solve is running the card is
    // deliberately blank, and a breakdown of the previous answer beneath it
    // would be the one thing on screen still describing the question before.
    parts: running || shown.length === 0 ? { kind: "none", items: [] } : answerBreakdown(state),
    problem: { text: state.problemText || "", idle: !state.problemText },
    badge: state.source ? { key: "popupSourceBadge", args: [state.source] } : null,
    detail: { text: state.detail || "", available: Boolean(state.detail) },
    status: { key: "statusChecking", args: [], kind: "" },
    progress: { fraction: 0, state: "" },
    solve: {
      key: running
        ? "popupCancelButton"
        : errorKey === "errorTabAccessLost"
          ? "popupGrantAccessButton"
          : errorKey
            ? "popupRetryButton"
            // The same button, renamed for what pressing it would now mean.
            // "Solve with Facet" beside an answer already in the box reads as
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

  if (errorKey) {
    view.status = { key: errorKey, args: state.errorArgs ?? [], kind: "error" };
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
  } else if (errorKey) {
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
    parts: { kind: "none", items: [] },
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
