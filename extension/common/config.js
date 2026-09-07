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
 * How many separate values one question may ask for.
 *
 * This was four, sized for the shape it was written against: `x = ___ or ___`,
 * and a quartic's four roots behind it. Lesson 2.1 completes a table for
 * `x = y²` with five blank cells, and five is what every gate between the page
 * and Facet then refused -- silently, each one falling back to "one box".
 * Live, the DOM sweep counted the five boxes and reported no ids for them, the
 * page's own editor model declined to call five controls a multi-control
 * answer, and the question was sent as a single field. Facet answered the
 * single field it was asked about, exactly, and one number came back for a
 * five-part question.
 *
 * Raised to the shape the page actually publishes and no further. A question
 * with more parts than this is still refused rather than half-answered, which
 * is the behaviour that made this diagnosable at all.
 */
export const MAX_ANSWER_PARTS = 5;

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
