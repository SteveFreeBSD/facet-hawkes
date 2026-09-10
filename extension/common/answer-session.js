"use strict";

/**
 * The one finished answer a non-persistent event page may recover.
 *
 * Firefox tears down the toolbar popup as soon as focus returns to Hawkes and
 * may then unload the idle event page. `storage.session` outlives that event
 * page but remains memory-only and is cleared with the browser session. This
 * module defines the deliberately narrow value allowed into it.
 *
 * The snapshot is not authority to show or insert an answer. The event page
 * feeds it back through `prepare()`, which re-reads the active tab, answer
 * target, editor and question signature before carrying any answer forward.
 */

export const ANSWER_SESSION_KEY = "answerSession";
export const ANSWER_SESSION_SCHEMA = 1;

const STATE_FIELDS = [
  "windowId",
  "tabId",
  "frameId",
  "fieldId",
  "fieldIds",
  // A completion table's blank-to-control mapping. `prepare` re-reads it, and
  // where that read cannot state one -- a cell the owner has clicked into
  // shows two controls -- revalidates the mapping this same question was
  // reviewed against, from the previous state. Lost with an event-page unload,
  // that fallback had nothing to revalidate and the held answer could not be
  // placed.
  "tableTargets",
  "answer",
  "displayText",
  "entryText",
  "answerParts",
  "editor",
  "graphPlan",
  "graphCoefficients",
  "placedText",
  "promptSeen",
  "problemText",
  "signature",
  "source",
  "detail",
  "errorKey",
  "errorArgs",
];

/** Return a storage-safe copy of one completed answer. */
export function snapshotSolvedAnswer(state, savedAt = Date.now()) {
  if (
    state?.phase !== "solved"
    || !Number.isInteger(state.windowId)
    || !Number.isInteger(state.tabId)
    || !Number.isInteger(state.frameId)
    || typeof state.fieldId !== "string"
    || state.fieldId.length === 0
    || typeof state.signature !== "string"
    || state.signature.length === 0
  ) {
    return null;
  }
  const hasAnswer = [state.answer, state.displayText].some(
    (value) => typeof value === "string" && value.length > 0
  ) || (Array.isArray(state.answerParts) && state.answerParts.length >= 2);
  if (!hasAnswer) {
    return null;
  }

  const answerState = { phase: "solved" };
  for (const name of STATE_FIELDS) {
    answerState[name] = state[name];
  }
  return {
    schema: ANSWER_SESSION_SCHEMA,
    savedAt: Number.isFinite(savedAt) ? savedAt : Date.now(),
    state: answerState,
  };
}

/** Validate and sanitize a value read from extension session storage. */
export function restoreSolvedAnswer(value) {
  if (value?.schema !== ANSWER_SESSION_SCHEMA || !value.state) {
    return null;
  }
  const snapshot = snapshotSolvedAnswer(value.state, value.savedAt);
  return snapshot?.state ?? null;
}
