"use strict";

/**
 * Values shared by the popup and the preferences page.
 *
 * The content script deliberately does not import this module: it is injected
 * as a classic script and repeats its own, stricter guards so that a bug in an
 * extension page can never widen what reaches the Hawkes editor.
 */

/** The only host this add-on ever acts on, compared against the active tab. */
export const ALLOWED_HOSTNAME = "learn.hawkeslearning.com";
export const ALLOWED_HOST_PATTERN = "*://learn.hawkeslearning.com/*";

/** Upper bound on an answer, matching the content script's own limit. */
export const MAX_ANSWER_LENGTH = 40;

/**
 * Characters an answer may contain. Plain mathematical notation only: no
 * angle brackets, quotes, backslashes, braces, or semicolons, so a stored
 * value cannot be mistaken for markup or code anywhere downstream.
 */
const ANSWER_PATTERN = /^[0-9A-Za-z+\-*/^().,√π ]+$/;

/**
 * Validate a candidate answer.
 *
 * @param {unknown} value
 * @returns {{ok: true, value: string} | {ok: false, code: string}}
 */
export function validateAnswer(value) {
  if (typeof value !== "string") {
    return { ok: false, code: "answer-invalid" };
  }
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_ANSWER_LENGTH) {
    return { ok: false, code: "answer-invalid" };
  }
  if (!ANSWER_PATTERN.test(trimmed)) {
    return { ok: false, code: "answer-invalid" };
  }
  return { ok: true, value: trimmed };
}
