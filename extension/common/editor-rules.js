"use strict";

import { MAX_ANSWER_PARTS, displayableAnswer, validateAnswer } from "./config.js";

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
 * @typedef {object} TableTarget
 * @property {number} blank 1-based semantic blank number
 * @property {string} id the control occupying that cell, in this page
 * @property {number} row logical row of the grid the reader accepted
 * @property {number} column logical column of that grid
 * @property {number | null} maxLength the box's own published bound
 * @property {string} label the cell, said in the table's own words
 */

/**
 * Whether one mapping entry is the shape a validated reading produces.
 *
 * Nothing here trusts the value: the mapping arrives from a page reader, is
 * held across a solve, and is compared against a second reading before a
 * character is written. A malformed entry must fail the comparison rather
 * than throw inside it.
 *
 * @param {TableTarget} target
 */
export function isTableTarget(target) {
  return Boolean(
    target
    && Number.isInteger(target.blank)
    && target.blank > 0
    && typeof target.id === "string"
    && target.id.length > 0
    && target.id.length <= 120
    && Number.isInteger(target.row)
    && target.row > 0
    && Number.isInteger(target.column)
    && target.column > 0
    && (target.maxLength === null || Number.isInteger(target.maxLength))
  );
}

/**
 * A whole mapping: closed, sequential blank numbering over distinct controls.
 *
 * The blank numbers are the contract with the host, which answers in that
 * order and knows nothing else about the page. Requiring them to be exactly
 * `1..n` here is what makes "part N" and "the control mapped to blank N" the
 * same statement.
 *
 * @param {TableTarget[]} targets
 */
export function isTableMapping(targets) {
  return (
    Array.isArray(targets)
    && targets.length >= 2
    && targets.length <= MAX_ANSWER_PARTS
    && targets.every(isTableTarget)
    && targets.every((target, index) => target.blank === index + 1)
    && new Set(targets.map((target) => target.id)).size === targets.length
  );
}

/** Whether two readings of the same table name the same cells and controls. */
export function sameTableMapping(left, right) {
  return (
    Array.isArray(left)
    && Array.isArray(right)
    && left.length === right.length
    && left.every((target, index) =>
      target?.id === right[index]?.id
      && target?.blank === right[index]?.blank
      && target?.row === right[index]?.row
      && target?.column === right[index]?.column)
  );
}

/**
 * The one character rule a completion table's cells are all typed under.
 *
 * Hawkes publishes its answer rules per question, not per cell, and the page's
 * control collection is no help in saying which control is which: a five-blank
 * grid publishes ten of them, one per value cell. So the rule is taken from
 * the description the probe returned, in the two forms it can arrive in --
 * one plain box, or several that agree with each other. Several that disagree
 * is a page this cannot read, and returns null rather than picking one.
 */
function tableCellRule(editor) {
  if (editor?.ok === false || editor?.enabled === false) {
    return null;
  }
  if (editor?.kind === "textbox") {
    return editor;
  }
  const editors = editor?.kind === "multi" && Array.isArray(editor.editors)
    ? editor.editors
    : [];
  if (
    editors.length === 0
    || editors.some((one) => one?.kind !== "textbox" || one?.enabled === false)
    || new Set(editors.map((one) => String(one.allowedCharacters ?? ""))).size !== 1
  ) {
    return null;
  }
  return { ...editors[0], kind: "textbox" };
}

/**
 * That rule as it applies to one cell.
 *
 * The question states the character set; each box states its own length bound
 * in the markup. Preferring the box's is the only per-cell refinement
 * available, and it is the page's own number either way.
 */
function cellEditor(editor, target) {
  return Number.isInteger(target?.maxLength) && target.maxLength > 0
    ? { ...editor, maxLength: target.maxLength }
    : editor;
}

/**
 * One answer part, as the two halves the cell would hold it in, or null.
 *
 * The same split the table writer makes, and deliberately the same shape of
 * answer: one top-level `/` with something on each side. Null means "not a
 * fraction this cell could hold" -- either there is no `/` at all, or the part
 * is a shape no pair of boxes can take -- and both are then judged as one
 * whole value, which is what refuses the second.
 */
function fractionHalves(part) {
  const at = typeof part === "string" ? part.indexOf("/") : -1;
  if (at < 0) {
    return null;
  }
  const numerator = part.slice(0, at);
  const denominator = part.slice(at + 1);
  return numerator.length > 0 && denominator.length > 0 && !denominator.includes("/")
    ? { numerator, denominator }
    : null;
}

/**
 * Whether this cell can open a second box, by the name Hawkes gives it.
 *
 * The mapping names a cell by its numerator control, and the denominator does
 * not exist until a `/` has been typed -- so at review time the name is all
 * there is to go on, and it is the same rule the writer routes by. A cell
 * already showing a fraction also states its other half, and states this box.
 */
function cellExpands(target) {
  return typeof target?.id === "string" && target.id.endsWith("_num");
}

/**
 * Whether one part can be placed in the one cell that holds it.
 *
 * A plain Hawkes answer box has no keypad template to press, so a fraction is
 * not built with one: typing `/` into the cell's own box turns it into a
 * numerator and a denominator, and the value is entered across the pair. That
 * makes `16/9` one answer in one cell, bounded by two boxes rather than by
 * one -- `100/9` fits two four-character boxes and would never fit one.
 *
 * Judging the whole part against a single box instead is what refused every
 * value of a four-blank table Facet had answered exactly. Live, on
 * 2026-09-07, four correct fractions in four mapped cells produced
 * `answer-needs-template` four times, against a question whose editor
 * publishes no templates and needs none for the way that answer is entered.
 */
function cellVerdict(part, rule, target) {
  const box = cellEditor(rule, target);
  const halves = fractionHalves(part);
  if (halves === null) {
    return answerFitsEditor(part, box);
  }
  if (!cellExpands(target)) {
    return { insertable: false, code: "table-cell-not-expandable" };
  }
  const numerator = answerFitsEditor(halves.numerator, box);
  return numerator.insertable ? answerFitsEditor(halves.denominator, box) : numerator;
}

/**
 * Can each part of a table answer be typed into the cell it belongs to?
 *
 * Deliberately not the multi-editor rule. Hawkes' live completion grid
 * publishes ten control models for five answer boxes -- one per value cell,
 * given and blank alike -- so that collection can say neither how many answers
 * there are nor which control is which, and asking it produced a single
 * textbox for a page showing five boxes. The count and the targets come from
 * the accepted table instead; what the collection is still good for is the
 * question's own published character rule, which is per question and not per
 * cell.
 *
 * Returns one verdict per part, or null when the shapes do not line up at all.
 *
 * @param {string[]} parts
 * @param {TableTarget[]} targets
 * @param {EditorDescription} editor
 */
export function tableAnswerVerdicts(parts, targets, editor) {
  const rule = tableCellRule(editor);
  if (
    rule === null
    || !Array.isArray(parts)
    || !isTableMapping(targets)
    || parts.length !== targets.length
  ) {
    return null;
  }
  return parts.map((part, index) => cellVerdict(part, rule, targets[index]));
}

/** Whether every part of a table answer can be placed. */
export function tableAnswerFits(parts, targets, editor) {
  const verdicts = tableAnswerVerdicts(parts, targets, editor);
  return verdicts !== null && verdicts.every((verdict) => verdict.insertable);
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
  // Injection failures have already been translated into catalogue keys by
  // `errorKeyOf`. Preserve them: looking them up as low-level editor reason
  // codes would turn a precise timeout or permission failure into the generic
  // `errorNoBridge` fallback.
  if (typeof code === "string" && code.startsWith("error")) {
    return code;
  }
  return {
    "no-focused-answer-field": "errorNoFocusedField",
    // The caret left the field part-way through a paced entry.
    "editor-lost-focus": "errorNoFocusedField",
    "field-not-editable": "errorFieldNotEditable",
    "unsupported-field": "errorUnsupportedField",
    "input-cancelled": "errorInsertRejected",
    "editor-rejected-insert": "errorInsertRejected",
    "answer-fields-changed": "errorQuestionChanged",
    // The table mapping stopped describing the page between the review and
    // the write: a cell's control is gone, replaced, or no longer editable.
    "table-target-missing": "errorQuestionChanged",
    "table-target-not-editable": "errorFieldNotEditable",
    "table-target-repeated": "errorQuestionChanged",
    "table-targets-changed": "errorQuestionChanged",
    "table-answer-incomplete": "errorInsertRejected",
    // A cell the page owns no single control for, or two cells owning one
    // control: the write has nowhere unambiguous to be routed.
    "table-cell-model-missing": "errorEditorUnknown",
    "table-cell-model-ambiguous": "errorEditorUnknown",
    "table-cell-model-shared": "errorEditorUnknown",
    "table-cell-model-disagrees": "errorEditorUnknown",
    "table-cell-not-selected": "errorEditorUnknown",
    // A fraction part with nowhere to put its other half: the cell's second
    // box did not open, or the mapping names a control that has none.
    "table-cell-not-expandable": "errorEditorUnknown",
    // The single-answer counterpart: a `/` that did not split the box, or a
    // box that split into something this writer cannot prove is its own other
    // half; and a fraction whose two boxes did not settle holding it.
    "fraction-not-expandable": "errorEditorUnknown",
    "fraction-not-settled": "errorEditorUnknown",
    // The cell did not settle holding its own part, or a write moved another
    // cell of the same table. Its own sentence: this is the editor placing an
    // answer somewhere nobody asked for, not the editor refusing one.
    "table-cell-not-settled": "errorTableCellsCrossed",
    "table-cell-crossed": "errorTableCellsCrossed",
    "answer-fields-not-empty": "errorFieldNotEditable",
    "answer-parts-incomplete": "errorInsertRejected",
    "editor-multiple-answer": "errorEditorUnknown",
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


/**
 * The one gate every answer a person is shown has to pass.
 *
 * Everything above decides whether an answer can be *typed*. This decides
 * whether it may be *published* at all -- shown on the card, remembered across
 * an event-page unload, restored onto the next question, named in a failure
 * record -- and it is asked of the state that is about to become current,
 * against the shape the question on screen has right now.
 *
 * It exists because the answer and its readable form were being checked in
 * different places and, on one route, in neither. A multi-part reply published
 * its FINAL ANSWER line as the reviewed identity without validating it, and
 * the display guard beside it fell back to that same unvalidated string -- so
 * a card showed "all answers as they would ordinarily be written", which is
 * Facet's own description of the line, echoed by the model instead of answered.
 * Two guards, one hole between them. This is the one guard.
 *
 * The rule it enforces is a single sentence: nothing may be published as an
 * answer unless it validates as an answer for the current question shape.
 *
 * @param {{answer?: string, displayText?: string, entryText?: string,
 *          answerParts?: string[], graphPlan?: object|null}} published
 * @param {{kind?: string, count?: number}} shape from `answerShapeOf`
 * @returns {{ok: true} | {ok: false, code: string}}
 */
export function publishableAnswer(published, shape) {
  const text = (value) => (typeof value === "string" ? value.trim() : "");
  const answer = text(published?.answer);
  const displayText = text(published?.displayText);
  const entryText = text(published?.entryText);
  const parts = Array.isArray(published?.answerParts)
    ? published.answerParts.filter((part) => typeof part === "string")
    : [];
  const plan = published?.graphPlan ?? null;
  const kind = shape?.kind ?? "field";

  // Nothing is being offered as an answer. Every state before a solve lands
  // looks like this, and holding those to an answer's contract would refuse
  // the panel's own "Solving…".
  if (!answer && !displayText && !entryText && parts.length === 0 && plan === null) {
    return { ok: true };
  }

  // Whichever field carries it, what reaches a reader has to read as an
  // answer. Checked before anything else, because it is the only rule that
  // applies to every shape and it is the one that was missing.
  for (const readable of [answer, displayText]) {
    if (readable && !displayableAnswer(readable)) {
      return { ok: false, code: "answer-not-an-answer" };
    }
  }

  // A plan is proved geometry and carries no writable value. It belongs to a
  // graph question and to no other, and a graph question is answered by no
  // other means -- a value published for one would be a value nothing proved.
  if (plan !== null) {
    return kind === "graph" && parts.length === 0 && !entryText
      ? { ok: true }
      : { ok: false, code: "answer-shape-graph" };
  }
  if (kind === "graph") {
    return { ok: false, code: "answer-shape-graph" };
  }

  if (parts.length > 0) {
    if (parts.length < 2 || parts.length > MAX_ANSWER_PARTS) {
      return { ok: false, code: "answer-parts-count" };
    }
    // Each part is typed into a real answer box of its own, so each is held to
    // what may be typed and not merely to what may be read.
    if (!parts.every((part) => validateAnswer(part).ok)) {
      return { ok: false, code: "answer-part-invalid" };
    }
    // A question that published its own control count is the authority on it.
    // A single box asking for two answers separated by a comma publishes one
    // control and is a `field`, so the count is only binding where the page
    // stated one.
    if (kind === "multi" && parts.length !== shape.count) {
      return { ok: false, code: "answer-parts-count" };
    }
    // An option question is answered by choosing one of the page's own
    // choices. Several typed values is not an answer to it in any form.
    if (kind === "option") {
      return { ok: false, code: "answer-shape-option" };
    }
    // Separate values and a single one are two different answers to the same
    // question, and nothing downstream picks between them.
    return entryText ? { ok: false, code: "answer-parts-and-entry" } : { ok: true };
  }

  // One value, where the page published several controls, is not this
  // question's answer -- it is an answer to a differently shaped one.
  if (kind === "multi") {
    return { ok: false, code: "answer-parts-count" };
  }
  // A readable form may carry notation no box would take, so it is never the
  // thing that makes an answer publishable. Some validated machine form has to
  // stand behind it, or the card is showing something with nothing under it.
  if (!validateAnswer(entryText).ok && !validateAnswer(answer).ok) {
    return { ok: false, code: "answer-invalid" };
  }
  return { ok: true };
}
