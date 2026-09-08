"use strict";

/**
 * Shared helpers for locating and writing the Hawkes answer field.
 *
 * Injected immediately before an operation script (`inspect-field.js`) or a
 * one-shot function, which calls into it. Firefox gives an extension one
 * global scope per frame, so the two files see each other — and that scope is
 * the extension's own sandbox, never the page's: "page scripts cannot see
 * JavaScript properties added by content scripts".
 *
 * The body is an IIFE, so a single name reaches that shared scope and
 * everything else is local to one execution. That name is declared with `var`
 * rather than `const` on purpose: the popup re-injects this file on every use,
 * and a top-level lexical declaration would throw a redeclaration error the
 * second time. Declarations inside the IIFE are function-scoped and rebuilt
 * per execution, so they use `const` freely.
 *
 * Two rules keep the page unable to see any of this, and the build enforces
 * both:
 *
 * 1. Nothing is written to the page. No property is set on `window`, no node,
 *    attribute, class, or stylesheet is added to the document, and no DOM
 *    message channel is opened. There is no marker to fingerprint and, because
 *    no listener is registered, nothing survives the call.
 * 2. The isolation boundary is never crossed. Firefox's three object-sharing
 *    escapes -- the unwrapped page object and the clone and export helpers --
 *    are all absent, and no built-in prototype is touched, so the page cannot
 *    detect a patched native. Ordinary DOM access needs none of them; the
 *    enforced list lives in `scripts/build_extension.py`.
 */

var ethnosHawkes = (function () {
  const ALLOWED_ORIGIN = "https://learn.hawkeslearning.com";
  const MAX_ANSWER_LENGTH = 40;
  // Kept in step with `common/config.js` by the build's shared-constant check;
  // this file is injected as a classic script and imports nothing.
  const MAX_ANSWER_PARTS = 5;
  const ANSWER_PATTERN = /^[0-9A-Za-z+\-*/^().,√π ]+$/;

  const FIELD_SELECTOR = [
    "input:not([type])",
    'input[type="text"]',
    'input[type="search"]',
    'input[type="number"]',
    "textarea",
    '[contenteditable="true"]',
    '[role="textbox"]',
  ].join(",");

  const EDITOR_SELECTOR = `${FIELD_SELECTOR}, .mq-editable-field, .mathquill-editable`;
  const HAWKES_FIELD_SELECTOR = [
    "input.qbaseCSS",
    'input[id^="txtAns"]',
    "input.boxStyle",
  ].join(",");

  /** Refuse to operate unless this document really is the approved origin. */
  function originAllowed() {
    return window.location.origin === ALLOWED_ORIGIN;
  }

  /**
   * Whether Hawkes has one of its own modal dialogs open.
   *
   * While one is up it holds focus, the editor reports no focused control, and
   * every later `focus()` fails silently -- so anything attempted in that state
   * looks like an unrelated bug. Detecting it turns a mystery into a sentence.
   */
  function hawkesDialogOpen() {
    for (const node of document.querySelectorAll('[id*="customMessageBox"]')) {
      if (node.getBoundingClientRect().height > 0) {
        return true;
      }
    }
    return false;
  }

  /** True when focus has moved into a nested browsing context. */
  function focusIsInSubframe() {
    const focused = document.activeElement;
    return (
      focused instanceof HTMLIFrameElement || focused instanceof HTMLFrameElement
    );
  }

  /**
   * Origin of the focused child frame, when this document can read it.
   *
   * Only the origin is taken, never the full URL, which can carry a query
   * string. It names the single host that would have to be granted if the
   * editor turns out to live in a cross-origin frame.
   *
   * @returns {string | undefined}
   */
  function focusedSubframeOrigin() {
    const focused = document.activeElement;
    const source = typeof focused?.src === "string" ? focused.src : "";
    if (source.length === 0) {
      return undefined;
    }
    try {
      const origin = new URL(source, document.baseURI).origin;
      return origin && origin !== "null" ? origin : undefined;
    } catch {
      return undefined;
    }
  }

  /**
   * The focused answer field in *this* document, or null.
   *
   * `document.activeElement` is used rather than `document.hasFocus()` because
   * opening the toolbar popup moves system focus away from the page; the
   * document still remembers which element was focused.
   *
   * @returns {Element | null}
   */
  function focusedAnswerField() {
    const focused = document.activeElement;
    if (focusIsInSubframe()) {
      return null;
    }
    if (!focused || focused === document.body || focused === document.documentElement) {
      // A docked sidebar can hold Firefox focus while the page only reports
      // BODY. If Hawkes exposes exactly one visible, editable answer input,
      // there is no ambiguity to resolve and requiring another click merely
      // makes the sidebar appear broken. Never guess when several fields remain.
      const candidates = [...document.querySelectorAll(HAWKES_FIELD_SELECTOR)].filter(
        (element) =>
          element.getBoundingClientRect().width > 0
          && element.getBoundingClientRect().height > 0
          && !element.disabled
          && !element.readOnly
      );
      return candidates.length === 1 ? candidates[0] : null;
    }
    if (focused.matches?.(FIELD_SELECTOR)) {
      return focused;
    }
    return focused.closest?.(EDITOR_SELECTOR) ?? null;
  }

  /**
   * One complete Hawkes solution set: two or more editors, up to
   * `MAX_ANSWER_PARTS`, joined by the expected number of visible literal "or"
   * separators.
   *
   * Geometry and every separator are required. Merely seeing several inputs
   * is not enough: they could be unrelated fields in a word problem.
   *
   * @returns {Element[]}
   */
  let lastSolutionFieldEvidence = {
    fields: 0,
    separatorCandidates: 0,
    separators: 0,
    fieldIds: [],
  };

  function solutionFields() {
    const fields = [...document.querySelectorAll(HAWKES_FIELD_SELECTOR)]
      .filter(
        (element) =>
          element.id
          && element.getBoundingClientRect().width > 0
          && element.getBoundingClientRect().height > 0
          && !element.disabled
          && !element.readOnly
      )
      .sort((left, right) => {
        const a = left.getBoundingClientRect();
        const b = right.getBoundingClientRect();
        return a.top - b.top || a.left - b.left;
      });
    if (
      fields.length < 2
      || fields.length > MAX_ANSWER_PARTS
      || new Set(fields.map((field) => field.id)).size !== fields.length
    ) {
      lastSolutionFieldEvidence = {
        fields: fields.length,
        separatorCandidates: 0,
        separators: 0,
        // Not a shape this add-on can fill: too few boxes, too many, or ids it
        // cannot tell apart. Offering these as candidates would invite the
        // event page to adopt fields that were refused here for a reason.
        fieldIds: [],
      };
      return [];
    }
    const rectangles = fields.map((field) => field.getBoundingClientRect());
    const bounds = {
      left: Math.min(...rectangles.map((rect) => rect.left)),
      right: Math.max(...rectangles.map((rect) => rect.right)),
      top: Math.min(...rectangles.map((rect) => rect.top)),
      bottom: Math.max(...rectangles.map((rect) => rect.bottom)),
    };
    const saysOr = (element) => {
      const values = [
        element.textContent,
        element.innerText,
        element.value,
        element.getAttribute?.("aria-label"),
      ];
      if (typeof window.getComputedStyle === "function") {
        for (const pseudo of ["::before", "::after"]) {
          try {
            values.push(window.getComputedStyle(element, pseudo).content);
          } catch {
            // This element has no readable generated content.
          }
        }
      }
      return values.some(
        (value) => String(value ?? "").trim().replace(/^['"]|['"]$/g, "").toLowerCase() === "or"
      );
    };
    const separatorCandidates = [...document.querySelectorAll("*")].filter(saysOr);
    const separators = separatorCandidates
      .map((element) => element.getBoundingClientRect())
      .filter(
        (rect) =>
          rect.width > 0
          && rect.height > 0
          && rect.right >= bounds.left - 60
          && rect.left <= bounds.right + 60
          && rect.bottom >= bounds.top - 12
          && rect.top <= bounds.bottom + 12
      );
    lastSolutionFieldEvidence = {
      fields: fields.length,
      separatorCandidates: separatorCandidates.length,
      separators: separators.length,
      // Reported as candidates, not as a decision. These boxes are visible,
      // editable and uniquely identified; the only thing missing is the
      // wording that would prove they are one answer. Lesson 3.3's "find two
      // points" step labels its two boxes "A:" and "B:" and never says "or",
      // so the separator rule below discards them -- and while these ids went
      // no further, no number of correct parts could ever be placed in them.
      // The event page adopts them only when the page's own editor model
      // publishes exactly this many enabled editors.
      fieldIds: fields.map((field) => field.id),
    };
    // Hawkes may wrap one visible separator in nested elements whose boxes are
    // not identical. Those are duplicate evidence, not extra separators. The
    // field count still fixes how many separators the shape must provide.
    return separators.length >= fields.length - 1 ? fields : [];
  }

  /**
   * The answer options, if this question is answered by choosing one.
   *
   * Focus is deliberately not required. On a typed question the caret says
   * where the answer goes, but on an option question clicking a radio *is*
   * answering — so demanding focus first would mean choosing before being
   * told what to choose. The presence of Hawkes' own option group is the
   * signal instead.
   *
   * @returns {HTMLInputElement[]}
   */
  function optionGroup() {
    const options = [...document.querySelectorAll('input[type="radio"].opt')].filter(
      (radio) =>
        !radio.disabled
        && radio.getBoundingClientRect().width > 0
        && radio.getBoundingClientRect().height > 0
    );
    const names = new Set(options.map((radio) => radio.name || radio.id));
    return options.length > 0 && names.size === 1 ? options : [];
  }

  /** The one visible field explicitly owned by the selected option. */
  function revealedOptionField() {
    const controlled = optionGroup()
      .filter((radio) => radio.checked)
      .flatMap((radio) => String(radio.getAttribute("aria-controls") || "").split(/\s+/))
      .filter((id) => id.length > 0)
      .map((id) => document.getElementById(id))
      .filter(
        (field) =>
          field?.matches?.(HAWKES_FIELD_SELECTOR)
          && field.getBoundingClientRect().width > 0
          && field.getBoundingClientRect().height > 0
          && !field.disabled
          && !field.readOnly
      );
    return controlled.length === 1 ? controlled[0] : null;
  }

  /** One member of the page's single unambiguous Hawkes option group. */
  function focusedOption() {
    const options = optionGroup();
    const focused = document.activeElement;
    return options.includes(focused) ? focused : options[0] ?? null;
  }

  /** @returns {boolean} whether the target is a plain form control. */
  function isNativeField(target) {
    return (
      target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement
    );
  }

  /** @returns {boolean} whether a value is a supported plain-text answer. */
  function answerIsSupported(value) {
    return (
      typeof value === "string"
      && value.length > 0
      && value.length <= MAX_ANSWER_LENGTH
      && ANSWER_PATTERN.test(value)
    );
  }

  /**
   * Report whether an insertion could proceed in this frame.
   *
   * @returns {{ready: boolean, code: string}}
   */
  function inspectField() {
    if (!originAllowed()) {
      return { ready: false, code: "wrong-site" };
    }
    if (hawkesDialogOpen()) {
      return { ready: false, code: "editor-dialog-open" };
    }
    if (focusIsInSubframe()) {
      // A child frame holds the caret and answers for itself. Saying so lets
      // the popup tell "nothing is focused" apart from "focused somewhere I
      // cannot reach", which is what a cross-origin editor frame looks like
      // under activeTab.
      return {
        ready: false,
        code: "focus-in-subframe",
        frameOrigin: focusedSubframeOrigin(),
      };
    }
    // A question answered on the graph has no answer box, and looking for one
    // is how the panel came to tell somebody to click a box their question does
    // not have. Live, on 2026-09-07, on "plot the following points in the
    // Cartesian plane": `no-focused-answer-field`, and a recovery instruction
    // that could not be followed.
    //
    // The graph is the answer surface whenever the page draws one and offers no
    // field beside it. Which *kind* of graph question it is -- a parabola whose
    // three controls this add-on can move, or one it cannot yet place -- is the
    // editor probe's decision and is made against the page's own graph model,
    // not guessed from the markup here.
    const controls = 'svg g.parabola g.point a[draggable="true"][role="button"]';
    const graphs = [...document.querySelectorAll('#QGraph[role="application"]')].filter(
      node => node.getBoundingClientRect().width > 0
    );
    if (graphs.length === 1) {
      const ids = [...graphs[0].querySelectorAll(controls)].map(node => node.id);
      if (ids.length === 3 && ids.every(Boolean)) {
        return {
          ready: true,
          code: "graph-answer",
          via: "parabola-controls",
          fieldId: ids.join("\u001f"),
        };
      }
      // Only where nothing else on the page takes an answer. A scatter plot
      // drawn beside a text box is that question's *data*, and the box is
      // still where its answer goes.
      if (solutionFields().length === 0) {
        return {
          ready: true,
          code: "graph-answer",
          via: "graph-surface",
          fieldId: graphs[0].id || "QGraph",
        };
      }
    }
    // A selected option may reveal the only text field that completes it.
    // Hawkes links that field from the radio with aria-controls, so following
    // that relation is exact and does not weaken the one-target rule.
    const revealed = revealedOptionField();
    if (revealed) {
      // Which branch claimed a single field, when the page has several.
      // Insertion additionally requires one field id per answer part, so a
      // question reporting one field while two solution fields exist can be
      // solved and never inserted -- and until now the report said only
      // "focused-answer-field" either way.
      // No `multiFieldEvidence` here: the solution-field sweep has not run at
      // this point, and reporting its stale zero would be a measurement that
      // was never taken.
      return {
        ready: true,
        code: "focused-answer-field",
        via: "revealed-option",
        fieldId: revealed.id || "",
      };
    }
    const fields = solutionFields();
    if (fields.length >= 2) {
      return {
        ready: true,
        code: "multi-answer-fields",
        fieldId: fields.map((field) => field.id).join("\u001f"),
        fieldIds: fields.map((field) => field.id),
      };
    }
    // Some questions are answered by choosing an option. That is still an
    // answer field for the purpose of finding the question -- the answer is
    // worked out and shown; only the selecting stays the user's.
    const option = focusedOption();
    if (option) {
      return { ready: true, code: "option-answer", fieldId: option.name || option.id || "" };
    }
    const target = focusedAnswerField();
    if (!target) {
      const report = {
        ready: false,
        code: "no-focused-answer-field",
      };
      if (lastSolutionFieldEvidence.fields >= 2) {
        report.multiFieldEvidence = lastSolutionFieldEvidence;
      }
      return report;
    }
    if (isNativeField(target) && (target.disabled || target.readOnly)) {
      return { ready: false, code: "field-not-editable" };
    }
    // The id identifies the field; prompt and MathML identify the question.
    return {
      ready: true,
      code: "focused-answer-field",
      via: "focused-field",
      fieldId: target.id || "",
      multiFieldEvidence: lastSolutionFieldEvidence,
    };
  }

  /** Ask the page whether it accepts this input before changing anything. */
  function beforeInputAccepted(target, value) {
    return target.dispatchEvent(
      new InputEvent("beforeinput", {
        bubbles: true,
        cancelable: true,
        data: value,
        inputType: "insertText",
      })
    );
  }

  /**
   * Presentation cadence for plain-text answers.
   *
   * Each answer receives a small settings snapshot from the event page. Tempo
   * suggests its natural length, the chosen genre supplies a beat shape, and
   * the duration window remains a hard bound. Operators and separators get a
   * longer rest so a voice-over has room to name them. Normalising the final
   * weights keeps the complete entry inside its chosen duration.
   *
   * The score and transport come from `common/cadence.js`, injected immediately
   * before this prelude. This is presentation timing, not an attempt to imitate
   * or conceal human input. Synthetic InputEvents remain observable to the page.
   */
  /** Treat the event page's snapshot as data, even though it is trusted. */
  function normalizedCadence(offered = {}) {
    return {
      ...ethnosCadence.normalize(offered),
      ...(offered.score ? { score: offered.score } : {}),
      channel: offered.channel,
    };
  }

  /** Return the elapsed-time cue for every character in one performance. */
  function entryBeatOffsets(characters, cadence) {
    return ethnosCadence.planCharacters(characters, cadence).offsets;
  }

  /**
   * Run one write on every beat. The callback may return a failure outcome to
   * stop the performance without writing any remaining characters.
   */
  async function playEntryCadence(characters, write, cadence) {
    cadence.startedAt ??= performance.now();
    const cursor = cadence.cursor ?? 0;
    // Moving to the next field of a structured answer is editor work the score
    // never allotted time for. Hold the phrase over it, exactly as the MAIN
    // writer holds over a template, rather than letting every remaining note
    // fall due at once the moment the field is ready.
    const due = cadence.score?.offsets?.[cursor];
    if (due !== undefined) {
      const overrun = performance.now() - cadence.startedAt - due;
      if (overrun > 0) {
        cadence.startedAt += overrun;
      }
    }
    const segment = cadence.score ? { ...cadence, score: {
      ...cadence.score,
      offsets: cadence.score.offsets.slice(cursor, cursor + characters.length),
      notes: cadence.score.notes.slice(cursor, cursor + characters.length),
    } } : cadence;
    const played = await ethnosCadence.playCharacters(characters, write, segment, {
      visit: (_note, index) => {
        if (cadence.channel) {
          document.dispatchEvent(new CustomEvent(cadence.channel, {
            detail: JSON.stringify([cursor + index, performance.now() - cadence.startedAt]),
          }));
        }
      },
    });
    cadence.cursor = cursor + characters.length;
    return played.failure;
  }

  /**
   * Write one character, as the field's own machinery expects to receive it.
   *
   * Reads the prototype's setter so frameworks that patch the instance
   * property still observe the change. This only reads a descriptor; it never
   * installs one, so no built-in is modified.
   */
  function writeCharacter(target, character) {
    const start = Number.isInteger(target.selectionStart)
      ? target.selectionStart
      : target.value.length;
    const end = Number.isInteger(target.selectionEnd) ? target.selectionEnd : start;
    const next = `${target.value.slice(0, start)}${character}${target.value.slice(end)}`;
    const owner = target instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const descriptor = Object.getOwnPropertyDescriptor(owner, "value");
    if (descriptor?.set) {
      descriptor.set.call(target, next);
    } else {
      target.value = next;
    }
    const caret = start + character.length;
    target.setSelectionRange?.(caret, caret);
    target.dispatchEvent(
      new InputEvent("input", { bubbles: true, data: character, inputType: "insertText" })
    );
  }

  async function insertIntoNativeField(target, value, cadence, preflighted = false) {
    if (target.disabled || target.readOnly) {
      return { ok: false, code: "field-not-editable" };
    }
    if (!preflighted && !beforeInputAccepted(target, value)) {
      return { ok: false, code: "input-cancelled" };
    }

    target.focus();
    const failure = await playEntryCadence([...value], (character) => {
      if (!target.isConnected) {
        // Hawkes swaps a question in place, and a performance now spans
        // seconds: the field this began in can be replaced part-way through.
        // A detached input still accepts writes and still reports itself as
        // editable, so without this the rest of the answer went nowhere and
        // the insertion reported success. The structured path re-reads its box
        // by id for the same reason.
        return { ok: false, code: "editor-lost-focus" };
      }
      if (target.disabled || target.readOnly) {
        // The field closed under us part-way through. Stop rather than write
        // into something that has stopped accepting input.
        return { ok: false, code: "field-not-editable" };
      }
      writeCharacter(target, character);
      return null;
    }, cadence);
    if (failure) {
      return failure;
    }
    return { ok: true, code: "native-input" };
  }

  async function insertIntoEditable(target, value, cadence) {
    target.focus();
    const selection = window.getSelection();
    if (
      !selection
      || selection.rangeCount === 0
      || !target.contains(selection.anchorNode)
    ) {
      const range = document.createRange();
      range.selectNodeContents(target);
      range.collapse(false);
      selection?.removeAllRanges();
      selection?.addRange(range);
    }
    if (!beforeInputAccepted(target, value)) {
      return { ok: false, code: "input-cancelled" };
    }
    // execCommand remains the only insertion path a MathQuill-style editor
    // reliably observes. Each call inserts text only and never markup.
    const failure = await playEntryCadence([...value], (character) => {
      // `execCommand` writes wherever the selection happens to be, and a
      // performance now spans seconds rather than one burst. Confirm the
      // caret is still ours on every beat, or the rest of the answer lands
      // in whatever the page focused in the meantime.
      const live = window.getSelection();
      if (
        !target.isConnected
        || !live
        || live.rangeCount === 0
        || !target.contains(live.anchorNode)
      ) {
        return { ok: false, code: "editor-lost-focus" };
      }
      if (!document.execCommand("insertText", false, character)) {
        return { ok: false, code: "editor-rejected-insert" };
      }
      return null;
    }, cadence);
    if (failure) {
      return failure;
    }
    return { ok: true, code: "contenteditable" };
  }

  /**
   * Insert `value` at the caret of this frame's focused answer field.
   *
   * @returns {{ok: boolean, code: string}}
   */
  async function insertAnswer(value, cadenceOptions = {}) {
    if (!originAllowed()) {
      return { ok: false, code: "wrong-site" };
    }
    const revealed = revealedOptionField();
    if (!revealed && focusedOption()) {
      return { ok: false, code: "editor-option-answer" };
    }
    if (solutionFields().length > 0) {
      return { ok: false, code: "editor-multiple-answer" };
    }
    if (hawkesDialogOpen()) {
      return { ok: false, code: "editor-dialog-open" };
    }
    if (!answerIsSupported(value)) {
      return { ok: false, code: "answer-invalid" };
    }
    const target = revealed ?? focusedAnswerField();
    if (!target) {
      return { ok: false, code: "no-focused-answer-field" };
    }
    const cadence = normalizedCadence(cadenceOptions);
    if (isNativeField(target)) {
      // Returns a promise: entry is paced, and `executeScript` awaits it.
      return insertIntoNativeField(target, value, cadence);
    }
    if (target.isContentEditable || target.getAttribute("role") === "textbox") {
      return insertIntoEditable(target, value, cadence);
    }
    return { ok: false, code: "unsupported-field" };
  }

  /** Insert one structured solution set into its exact pinned fields. */
  async function insertAnswerParts(parts, expectedFieldIds, cadenceOptions = {}) {
    if (!originAllowed()) {
      return { ok: false, code: "wrong-site" };
    }
    if (
      !Array.isArray(parts)
      || parts.length < 2
      || parts.length > MAX_ANSWER_PARTS
      || !parts.every(answerIsSupported)
      || !Array.isArray(expectedFieldIds)
      || expectedFieldIds.length !== parts.length
    ) {
      return { ok: false, code: "answer-invalid" };
    }
    const fields = solutionFields();
    if (
      fields.length !== parts.length
      || fields.some((field, index) => field.id !== expectedFieldIds[index])
    ) {
      return { ok: false, code: "answer-fields-changed" };
    }
    if (fields.some((field) => !isNativeField(field) || field.value !== "")) {
      return { ok: false, code: "answer-fields-not-empty" };
    }
    // Validate every editor before the first mutation. Hawkes uses this event
    // to reject characters that its published model does not accept.
    if (!fields.every((field, index) => beforeInputAccepted(field, parts[index]))) {
      return { ok: false, code: "input-cancelled" };
    }

    const cadence = normalizedCadence(cadenceOptions);
    for (let index = 0; index < fields.length; index += 1) {
      const current = solutionFields();
      if (
        current.length !== parts.length
        || current.some((field, offset) => field.id !== expectedFieldIds[offset])
      ) {
        return { ok: false, code: "answer-fields-changed", written: index };
      }
      const outcome = await insertIntoNativeField(
        current[index], parts[index], cadence, true
      );
      if (!outcome.ok) {
        return { ...outcome, written: index };
      }
    }
    const settled = solutionFields();
    if (
      settled.length !== parts.length
      || settled.some((field, index) => field.id !== expectedFieldIds[index])
      || settled.some((field, index) => field.value !== parts[index])
    ) {
      return { ok: false, code: "answer-parts-incomplete", written: parts.length };
    }
    return { ok: true, code: "native-input-fields", entered: [...parts] };
  }

  /**
   * A completion table is written from the page's own world, not from here.
   *
   * `insertTableParts` used to live at this point in the file and did what an
   * isolated writer can do: focus the cell, set its value, dispatch `input`.
   * A Hawkes completion cell is a controlled editor, and its `input` handling
   * is routed through a page-owned selection this scope cannot see or move --
   * so all five parts were applied to whichever control the page had selected
   * before the panel opened, and the run reported five successful writes over
   * a table holding one wrong answer. `common/table-actions.js` is where that
   * work is done now; nothing in this file may reach the page's model.
   */

  return {
    answerIsSupported,
    inspectField,
    insertAnswer,
    insertAnswerParts,
    originAllowed,
  };
})();
