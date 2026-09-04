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
  const ANSWER_PATTERN = /^[0-9A-Za-z+\-*/^().,√ ]+$/;

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
      // makes the sidebar appear broken. Never guess when two fields remain.
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
   * The answer options, if this question is answered by choosing one.
   *
   * Focus is deliberately not required. On a typed question the caret says
   * where the answer goes, but on an option question clicking a radio *is*
   * answering — so demanding focus first would mean choosing before being
   * told what to choose. The presence of Hawkes' own option group is the
   * signal instead.
   *
   * @returns {HTMLInputElement | null}
   */
  function focusedOption() {
    const focused = document.activeElement;
    if (
      focused instanceof HTMLInputElement
      && focused.type === "radio"
      && !focused.disabled
    ) {
      return focused;
    }
    // Nothing is focused, or focus sits on the page body: fall back to the
    // question's own option group, which Hawkes marks with the "opt" class.
    if (focused && focused !== document.body && focused !== document.documentElement) {
      return null;
    }
    for (const radio of document.querySelectorAll('input[type="radio"].opt')) {
      if (!radio.disabled && radio.getBoundingClientRect().width > 0) {
        return radio;
      }
    }
    return null;
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
    // Some questions are answered by choosing an option. That is still an
    // answer field for the purpose of finding the question -- the answer is
    // worked out and shown; only the selecting stays the user's.
    const option = focusedOption();
    if (option) {
      return { ready: true, code: "option-answer", fieldId: option.name || option.id || "" };
    }
    const target = focusedAnswerField();
    if (!target) {
      return { ready: false, code: "no-focused-answer-field" };
    }
    if (isNativeField(target) && (target.disabled || target.readOnly)) {
      return { ready: false, code: "field-not-editable" };
    }
    // The id identifies the field; prompt and MathML identify the question.
    return { ready: true, code: "focused-answer-field", fieldId: target.id || "" };
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
    return ethnosCadence.normalize(offered);
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
    const played = await ethnosCadence.playCharacters(characters, write, cadence);
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

  async function insertIntoNativeField(target, value, cadence) {
    if (target.disabled || target.readOnly) {
      return { ok: false, code: "field-not-editable" };
    }
    if (!beforeInputAccepted(target, value)) {
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
    if (focusedOption()) {
      return { ok: false, code: "editor-option-answer" };
    }
    if (hawkesDialogOpen()) {
      return { ok: false, code: "editor-dialog-open" };
    }
    if (!answerIsSupported(value)) {
      return { ok: false, code: "answer-invalid" };
    }
    const target = focusedAnswerField();
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

  return {
    answerIsSupported,
    inspectField,
    insertAnswer,
    originAllowed,
  };
})();
