"use strict";

/**
 * Which writer places an answer, decided from the page and nothing else.
 *
 * This file exists because the decision used to be made from the *answer*:
 *
 *     const typeable = answerFitsEditor(reviewed, editor).insertable;
 *     if (!typeable) { buildStructured(...); } else { enterPlainAnswer(...); }
 *
 * Read as a policy that is "if the characters happen to be directly typeable,
 * write them through the DOM; otherwise ask the Hawkes editor to build them".
 * So one question's editor had two writers, and which one ran depended on what
 * the answer turned out to contain. `5` and `1/5` went into the same box by
 * different machinery, with different failure modes, and the log said only
 * `via: "plain"` or `via: "structured"` -- the shape of the answer, not the
 * route it took.
 *
 * It is also wrong on its own terms. A digit is not merely *acceptable* to a
 * Hawkes dynamic editor; it is one of that editor's own operations.
 * `keyPadButtonClick(name)` delegates to `addElement(name, true, callback)`,
 * whose ordinary-character branch validates the character against the slot the
 * editor is in, updates the page-owned `Base`, focuses it and runs Hawkes' own
 * change handler. Writing the same digit through the DOM setter reaches the
 * box and bypasses all of that.
 *
 * The rule here is one sentence: **the page's own answer model chooses the
 * transport, and the answer is then checked against the transport it chose.**
 * An answer that does not fit is a refusal, never a different writer.
 *
 * `chooseTransport` therefore takes no answer, no plan and no character set.
 * It cannot express the old policy, which is the point of it being its own
 * file -- see `tests/test_hawkes_transport.py`.
 *
 * DOM-free, so it can be exercised directly.
 */

/**
 * Every route an answer can reach the page by, and what each one is.
 *
 * `world` is where the writer runs: `"MAIN"` is the page's own world, which is
 * the only place the Hawkes editor model exists; `"isolated"` is the add-on's
 * own world, which can see the DOM and nothing of the page's model. This file
 * names those worlds and reaches neither.
 */
export const TRANSPORTS = Object.freeze({
  "hawkes-dynamic-keypad": Object.freeze({
    world: "MAIN",
    writer: "enterPlan",
    // Characters and templates alike are the editor's own operations.
    keypad: true,
    what: "the dynamic math editor's own keypad API",
  }),
  "hawkes-plain-box": Object.freeze({
    world: "MAIN",
    writer: "enterPlan",
    // A plain answer box publishes no character API: Hawkes' own
    // `AnswerBoxKeyPadClick` builds structure by assigning `.value` and
    // letting the box's `input` handling sanitise it. So the box's own input
    // handling *is* the native path, and pressing a keypad at it would be the
    // add-on inventing a capability the page does not have.
    keypad: false,
    what: "the plain answer box's own input handling",
  }),
  "hawkes-plain-fields": Object.freeze({
    world: "MAIN",
    writer: "enterOwnedFields",
    // Several plain answer boxes are several page-owned controls, routed by
    // the one Hawkes has selected -- exactly as a completion cell is, and for
    // exactly the same reason this one moved out of the isolated world. An
    // isolated writer can focus the box and cannot select the control, so its
    // parts arrived cumulative and crossed between the boxes.
    keypad: false,
    what: "the page-selected control owning each pinned answer box",
  }),
  "hawkes-table-cells": Object.freeze({
    world: "MAIN",
    writer: "enterOwnedFields",
    // A completion cell is routed through the control the page has selected,
    // which is why this one runs in MAIN; it still types, and never presses a
    // template.
    keypad: false,
    what: "the page-selected control owning each completion cell",
  }),
  "native-contenteditable": Object.freeze({
    world: "isolated",
    writer: "enterPlainAnswer",
    keypad: false,
    what: "the caret of a contenteditable answer field",
  }),
  "hawkes-graph": Object.freeze({
    world: "MAIN",
    writer: "graphOperation",
    keypad: false,
    what: "the page's own graph controls",
  }),
});

/**
 * The transport for the question on screen.
 *
 * Every argument is something the *page* said about itself: the editor model
 * it published, the completion-table mapping its own reader accepted, and what
 * kind of DOM node the pinned answer field is. Nothing about the answer is
 * accepted here, and nothing about the answer may be added.
 *
 * @param {{ok?: boolean, code?: string, kind?: string,
 *          editors?: Array<{kind?: string}>}} editor as `hawkes-describe.js`
 *   published it
 * @param {{tableTargets?: object[], fieldKind?: string}} page
 * @returns {{ok: true, transport: string, world: string, writer: string}
 *   | {ok: false, code: string}}
 */
export function chooseTransport(editor, page = {}) {
  if (!editor || editor.ok === false) {
    return { ok: false, code: editor?.code ?? "editor-unknown" };
  }
  // A graph is answered by moving the page's own controls. Unchanged, and
  // named here only so that every question has exactly one answer to this.
  if (editor.kind === "graph") {
    return settled("hawkes-graph");
  }
  // Choosing an option is answering, not filling a field in. There is no
  // transport for it, and inventing one is how an add-on comes to answer.
  if (editor.kind === "option") {
    return { ok: false, code: "editor-option-answer" };
  }
  if (editor.kind === "multi") {
    const editors = Array.isArray(editor.editors) ? editor.editors : [];
    if (editors.length < 2) {
      return { ok: false, code: "editor-unknown" };
    }
    if (editors.some((one) => one?.kind === "option")) {
      return { ok: false, code: "editor-option-answer" };
    }
    if (editors.every((one) => one?.kind === "dynamic")) {
      return settled("hawkes-dynamic-keypad");
    }
    if (editors.every((one) => one?.kind === "textbox")) {
      return settled("hawkes-plain-fields");
    }
    // Two editors of different kinds need two different writers for one
    // answer, and there is no route that is both. Refused by name rather than
    // resolved by whichever half the answer happened to suit.
    return { ok: false, code: "editor-mixed-transports" };
  }
  // A completion table is several blanks behind one editor model, found by the
  // question reader rather than by that model. It is decided before the plain
  // box below because its cells *are* plain boxes -- the difference is that
  // each one is routed through a control the page has selected.
  if (Array.isArray(page.tableTargets) && page.tableTargets.length >= 2) {
    return settled("hawkes-table-cells");
  }
  if (editor.kind === "dynamic") {
    return settled("hawkes-dynamic-keypad");
  }
  if (editor.kind === "textbox") {
    // The one case where the DOM node decides: a MathQuill-style editor is a
    // contenteditable element, not an input, and the box writer has no box to
    // write into. It is still the field's own caret either way.
    return settled(
      page.fieldKind === "contenteditable"
        ? "native-contenteditable"
        : "hawkes-plain-box"
    );
  }
  return { ok: false, code: "editor-unknown" };
}

/** One resolved transport, with the two facts a caller needs to act on it. */
function settled(transport) {
  const chosen = TRANSPORTS[transport];
  return {
    ok: true,
    transport,
    world: chosen.world,
    writer: chosen.writer,
  };
}

/**
 * Whether a writer that was reached is the one that was chosen.
 *
 * The branch an insertion takes and the transport it was routed to are decided
 * in different places, so they are compared rather than assumed to agree. A
 * disagreement is a refusal: it means the page changed shape between the two
 * decisions, or that a branch was added without a transport to match.
 *
 * @param {{ok: boolean, transport?: string}} routed
 * @param {string} reached
 */
export function transportMatches(routed, reached) {
  return routed?.ok === true && routed.transport === reached;
}
