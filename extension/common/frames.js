"use strict";

/**
 * Choosing which frame holds the Hawkes answer field.
 *
 * Kept free of DOM and `browser` API access so the decision can be exercised
 * directly against recorded `scripting.executeScript` results — see
 * `tests/test_hawkes_frames.py`. The popup owns the injection; this module
 * owns only the judgement about what came back.
 */

/**
 * @typedef {object} FrameReport
 * @property {number} [frameId] frame the result came from
 * @property {{ready?: boolean, code?: string, frameOrigin?: string}} [result]
 * @property {unknown} [error] thrown value, when a frame failed outright
 */

/**
 * Summarize per-frame results as a short technical line for the panel.
 *
 * Reported by the user when something goes wrong, so it names frames, reason
 * codes, and thrown messages — never page content.
 *
 * @param {FrameReport[]} results
 * @returns {string}
 */
export function describeResults(results) {
  if (!Array.isArray(results) || results.length === 0) {
    return "no frames responded";
  }
  return results
    .map((entry) => {
      const frame = Number.isInteger(entry?.frameId) ? entry.frameId : "?";
      if (entry?.error !== undefined) {
        const detail = entry.error?.message ?? String(entry.error);
        return `frame ${frame}: threw ${String(detail).slice(0, 120)}`;
      }
      const code = entry?.result?.code;
      const ready = entry?.result?.ready === true ? " ready" : "";
      return `frame ${frame}: ${code ?? "no result"}${ready}`;
    })
    .join("; ");
}

/**
 * Decide where — or whether — an answer can be inserted.
 *
 * Exactly one frame may claim the caret. A frame whose focus sits in a child
 * reports `focus-in-subframe` instead of claiming it, so two frames claiming
 * at once means something is wrong (a stale `activeElement` in a sibling, say)
 * and the answer is refused rather than guessed. That is the fail-closed rule
 * the architecture requires.
 *
 * @param {FrameReport[]} results
 * @returns {{frameId: number} | {code: string, origin?: string}}
 */
export function selectAnswerFrame(results) {
  if (!Array.isArray(results)) {
    return { code: "no-results" };
  }

  const reports = results.filter(
    (entry) => entry && typeof entry.result === "object" && entry.result !== null
  );
  if (reports.length === 0) {
    return { code: "no-results" };
  }

  const claimed = reports.filter(
    (entry) => entry.result.ready === true && Number.isInteger(entry.frameId)
  );
  if (claimed.length === 1) {
    const selected = {
      frameId: claimed[0].frameId,
      fieldId: claimed[0].result.fieldId ?? "",
    };
    return Array.isArray(claimed[0].result.fieldIds)
      ? { ...selected, fieldIds: [...claimed[0].result.fieldIds] }
      : selected;
  }
  if (claimed.length > 1) {
    return { code: "ambiguous-frame" };
  }

  const codes = reports.map((entry) => entry.result.code);
  if (codes.includes("prelude-missing")) {
    return { code: "prelude-missing" };
  }
  // A modal holds focus, so every other frame's report is a consequence of it
  // rather than an independent finding. Say the cause, not the symptoms.
  if (codes.includes("editor-dialog-open")) {
    return { code: "editor-dialog-open" };
  }

  // Only the top frame can say the tab is the wrong site. A subframe reporting
  // `wrong-site` is ordinary — any third-party frame on the page does — and
  // must not drown out what the top frame had to say.
  const top = reports.find((entry) => entry.frameId === 0);
  if (top?.result.code === "wrong-site") {
    return { code: "wrong-site" };
  }
  if (codes.includes("field-not-editable")) {
    return { code: "field-not-editable" };
  }

  // Focus is in a child frame that never reported back, so it was not
  // injected: a cross-origin editor, which activeTab does not cover. The
  // origin, when the parent could read it, names exactly which host would
  // have to be granted.
  const trapped = reports.find((entry) => entry.result.code === "focus-in-subframe");
  if (trapped) {
    const origin = trapped.result.frameOrigin;
    return typeof origin === "string" && origin.length > 0
      ? { code: "focus-in-subframe", origin }
      : { code: "focus-in-subframe" };
  }

  return { code: "no-focused-answer-field" };
}
