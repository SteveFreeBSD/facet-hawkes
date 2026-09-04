"use strict";

/**
 * Deciding whether an answer can be typed, from the editor's own rules.
 *
 * The rules are per question, so they cannot be hardcoded. One question in a
 * lesson accepts `0123456789y`; the next accepts `[0-9.-]`. Typing a character
 * outside the set raises a blocking Hawkes dialog that holds focus until it is
 * dismissed, so refusing beforehand is the difference between a clean refusal
 * and leaving the page stuck.
 *
 * DOM-free, so it can be exercised directly — see `tests/test_hawkes_rules.py`.
 */

/**
 * @typedef {object} EditorDescription
 * @property {"dynamic" | "textbox"} kind
 * @property {boolean} enabled
 * @property {string} allowedCharacters literal set (dynamic) or pattern (textbox)
 * @property {number | null} maxLength
 * @property {{fraction: boolean, radical: boolean, exponent: boolean}} templates
 */

/** Characters that can only come from a keypad template, never typed. */
const STRUCTURAL = {
  "/": "fraction",
  "√": "radical",
  "∛": "radical",
  "∜": "radical",
  "^": "exponent",
  "(": "parentheses",
  ")": "parentheses",
};

/**
 * Can this exact answer be typed into the described control?
 *
 * @param {string} answer
 * @param {EditorDescription} editor
 * @returns {{insertable: true} | {insertable: false, code: string, detail?: string}}
 */
export function answerFitsEditor(answer, editor) {
  if (typeof answer !== "string" || answer.length === 0) {
    return { insertable: false, code: "answer-empty" };
  }
  if (!editor || editor.ok === false) {
    return { insertable: false, code: editor?.code ?? "editor-unknown" };
  }
  if (editor.enabled === false) {
    return { insertable: false, code: "editor-disabled" };
  }
  // Some questions are answered by choosing an option rather than typing.
  // Selecting one is answering, not filling in a field, so it stays the
  // user's action.
  if (editor.kind === "option") {
    return { insertable: false, code: "editor-option-answer" };
  }
  // Hawkes can keep its ordinary numeric/fraction editor visible even though
  // the prompt names a prose escape such as "Not a Real Number". That answer
  // belongs to Hawkes' separate choice/control, not in the digits-only box.
  if (/^(?:Not a Real Number|Real Number|Not Factorable)$/i.test(answer.trim())) {
    return { insertable: false, code: "editor-option-answer" };
  }
  if (Number.isInteger(editor.maxLength) && answer.length > editor.maxLength) {
    return { insertable: false, code: "answer-too-long" };
  }

  // Structure is built with keypad templates, so its notation can never be
  // typed even when the question permits the template.
  const structural = [...answer].filter((character) => character in STRUCTURAL);
  if (structural.length > 0) {
    return {
      insertable: false,
      code: "answer-needs-template",
      detail: [...new Set(structural.map((c) => STRUCTURAL[c]))].join(", "),
    };
  }

  const allowed = editor.allowedCharacters ?? "";
  if (allowed.length === 0) {
    return { insertable: false, code: "editor-rules-unknown" };
  }

  const rejected = [...answer].filter((character) => !accepts(allowed, character, editor.kind));
  if (rejected.length > 0) {
    return {
      insertable: false,
      code: "answer-has-rejected-characters",
      detail: [...new Set(rejected)].join(" "),
    };
  }
  return { insertable: true };
}

/**
 * A dynamic box publishes a literal character set; a plain answer box
 * publishes a character-class pattern such as `[0-9.-]`.
 *
 * @param {string} allowed
 * @param {string} character
 * @param {"dynamic" | "textbox"} kind
 */
export function accepts(allowed, character, kind) {
  if (kind === "textbox" && allowed.startsWith("[")) {
    try {
      // Anchored so the class matches the single character and nothing else.
      return new RegExp(`^(?:${allowed})$`).test(character);
    } catch {
      return false;
    }
  }
  return allowed.includes(character);
}

/**
 * Catalogue key for a reason code the insertion script returned.
 *
 * @param {string} code
 * @returns {string}
 */
export function insertErrorKey(code) {
  return {
    "no-focused-answer-field": "errorNoFocusedField",
    // The caret left the field part-way through a paced entry.
    "editor-lost-focus": "errorNoFocusedField",
    "field-not-editable": "errorFieldNotEditable",
    "unsupported-field": "errorUnsupportedField",
    "input-cancelled": "errorInsertRejected",
    "editor-rejected-insert": "errorInsertRejected",
    "answer-invalid": "errorAnswerInvalid",
    "answer-unavailable": "errorAnswerInvalid",
    "prelude-missing": "errorNoBridge",
    "wrong-site": "errorWrongSite",
    "editor-dialog-open": "errorEditorDialogOpen",
    "editor-model-missing": "errorEditorUnknown",
    "template-unavailable": "errorEditorUnknown",
    "template-refused-by-question": "errorAnswerNeedsTemplate",
    "answer-has-rejected-characters": "errorAnswerRejected",
    "answer-needs-absolute-value": "errorAnswerNeedsAbsoluteValue",
    "absolute-value-not-understood": "errorAnswerNeedsTemplate",
    "plan-lost-its-place": "errorEditorUnknown",
    "radical-not-understood": "errorAnswerNeedsTemplate",
    "exponent-not-understood": "errorAnswerNeedsTemplate",
    "exponent-without-base": "errorAnswerNeedsTemplate",
    "answer-empty": "errorAnswerInvalid",
    "unknown-step": "errorEditorUnknown",
  }[code] ?? "errorNoBridge";
}
