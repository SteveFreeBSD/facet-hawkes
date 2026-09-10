"use strict";

/**
 * The one function that writes to the Hawkes editor.
 *
 * It is passed to `scripting.executeScript` as `func` and runs in the page's
 * own world, because both of the transports it performs need the page's own
 * model: a dynamic editor takes every character through `keyPadButtonClick`,
 * and a plain answer box splits into two only when the control behind it says
 * it did. Passing it as a function rather than a file is what allows the plan
 * to be an argument; `executeScript` accepts files or a function with
 * arguments, never both.
 *
 * It must stay self-contained: `executeScript` serialises it, so it may not
 * reference anything outside its own body.
 *
 * The plan comes from `editor-plan.js`, which has already checked the answer
 * against this question's own character set and permitted templates. This
 * function performs the plan and reports what happened; it makes no decisions
 * about what the answer should be, and it never touches Submit or Check.
 *
 * ## It is told its transport; it does not choose one
 *
 * `common/transport.js` decides which writer runs, from the page's own answer
 * model and nothing else, and the name of that decision arrives here as an
 * argument. This function refuses a transport it does not implement rather
 * than picking whichever mechanism the plan's steps happen to suggest — the
 * defect being closed is exactly a writer that chose its own mechanism from
 * the answer in front of it.
 *
 * | Transport | Characters | Structure |
 * |---|---|---|
 * | `hawkes-dynamic-keypad` | `keyPadButtonClick(character)` | `keyPadButtonClick(template)` |
 * | `hawkes-plain-box` | the box's own `input` handling | a typed `/`, which the box splits on |
 *
 * A dynamic character is not merely acceptable to the editor: it is one of the
 * editor's own operations. `keyPadButtonClick(name)` delegates to
 * `addElement(name, true, callback)`, whose ordinary-character branch
 * validates the character against the slot the editor is in, updates the
 * page-owned `Base`, focuses it and runs Hawkes' own change handler. The DOM
 * setter reaches the same box and bypasses all of that, which is why it is no
 * longer how a dynamic editor is typed into.
 *
 * A plain answer box publishes no such API. Hawkes' own `AnswerBoxKeyPadClick`
 * builds structure there by assigning `.value` and letting the box's `input`
 * handling sanitise it, so the box's own input handling *is* its native path
 * and pressing a keypad at it would be this add-on inventing a capability the
 * page does not have.
 */

/**
 * @param {Array<{op: string, text?: string, name?: string}>|Array<Array<{
 *   op: string, text?: string, name?: string
 * }>>} steps one plan, or independently preflighted plans for multiple fields
 * @param {object} cadence
 * @param {string[]} targetFieldIds exact multi-field target, empty for one editor
 * @param {string} transport the route chosen in `common/transport.js`
 * @returns {Promise<{ok: boolean, code: string, entered?: string, detail?: string}>}
 */
export async function enterPlan(steps, cadence = {}, targetFieldIds = [], transport = "") {
  const SETTLE_MS = 4000;
  // The two routes this writer implements. Anything else -- including the
  // empty string a caller that forgot to say would pass -- is refused before
  // the page is touched, so a new branch upstream cannot silently inherit
  // whichever mechanism happens to be written first below.
  const KEYPAD = "hawkes-dynamic-keypad";
  const PLAIN_BOX = "hawkes-plain-box";
  if (transport !== KEYPAD && transport !== PLAIN_BOX) {
    return { ok: false, code: "transport-unavailable", detail: String(transport ?? "") };
  }
  const viaKeypad = transport === KEYPAD;
  // Kept in step with `common/config.js` by the build's shared-constant
  // check; this function is serialized into the page's own world by
  // `scripting.executeScript`, so no import survives here.
  const MAX_ANSWER_PARTS = 5;
  const multi = Array.isArray(targetFieldIds) && targetFieldIds.length >= 2
    && targetFieldIds.length <= MAX_ANSWER_PARTS;
  // Several plain answer boxes are not this writer's. They are the
  // `hawkes-plain-fields` transport, written by `enterOwnedFields` through the
  // control Hawkes has selected for each -- which is what keeps one box's part
  // out of another's. This writer pins several targets by the dynamic editor's
  // own `Base` objects, which a plain box does not have, so a plain-box plan
  // handed several targets was routed against some other page.
  if (multi && !viaKeypad) {
    return { ok: false, code: "transport-unavailable", detail: transport };
  }
  const plans = multi ? steps : [steps];
  if (
    !Array.isArray(plans)
    || plans.length !== (multi ? targetFieldIds.length : 1)
    || !plans.every((plan) => Array.isArray(plan))
  ) {
    return { ok: false, code: "answer-invalid" };
  }

  // The extension passes the shared, already-built score as data. MAIN owns
  // editor mechanics only; it no longer carries a second rhythm algorithm.
  const characters = [...plans.flat().filter((step) => step.op === "type")
    .map((step) => step.text ?? "").join("")];
  const noteOffsets = cadence.score?.offsets;
  if (!Array.isArray(noteOffsets) || noteOffsets.length !== characters.length
      || noteOffsets.some((at, index) => !Number.isFinite(at) || at < 0 || at > 12000
        || (index > 0 && at < noteOffsets[index - 1]))) {
    return { ok: false, code: "answer-invalid" };
  }

  const performanceStartedAt = performance.now();
  // One origin for the whole performance, which structural editor work may move
  // forward. Every note is due at an absolute offset from it, so a callback the
  // browser wakes late costs one late note rather than shifting the rest.
  let origin = performanceStartedAt;
  let notesStruck = 0;
  let heldMs = 0;
  const lateness = [];
  // How each accepted character actually reached the page, counted as it
  // happens. The log used to say `via: "plain"` or `via: "structured"`, which
  // named the shape of the answer rather than the route it took; these are the
  // route, measured rather than assumed.
  const written = { keypad: 0, native: 0, fields: new Set() };

  /**
   * Tell an optional listener that something happened, in the write's own turn.
   *
   * One-way, string-only, and never awaited. A page can observe or forge this;
   * it confers no capability, and a failure here cannot change what was typed.
   */
  const emit = (payload) => {
    try {
      if (cadence.channel) {
        document.dispatchEvent(new CustomEvent(cadence.channel, {
          detail: JSON.stringify(payload),
        }));
      }
    } catch { /* audio failure cannot change entry */ }
  };

  /**
   * Hold until this note is due. A late clock simply plays it now.
   *
   * The deadline is approached in two steps. One long `setTimeout` is coalesced
   * with everything else the page's process has pending -- a four-second gap
   * between notes was measured waking a third of a second late -- while a timer
   * that is already nearly due is fired promptly. Every wait is still computed
   * from the same absolute origin, so this cannot overshoot and no lateness is
   * ever carried into the next note.
   */
  const waitForNote = async () => {
    const due = noteOffsets[notesStruck];
    notesStruck += 1;
    if (due === undefined) {
      return;
    }
    for (let approach = 0; approach < 8; approach += 1) {
      const wait = due - (performance.now() - origin);
      if (wait <= 0) {
        break;
      }
      const step = wait > 250 ? wait - 200 : wait;
      await new Promise((resolve) => setTimeout(resolve, step));
    }
    lateness.push(Math.round(performance.now() - origin - due));
  };

  /**
   * Absorb the wall time a template actually took.
   *
   * Loading a fraction means pressing the editor's own key and waiting for its
   * boxes to settle -- real work, of a length only the editor knows, that the
   * score never allotted time for. Leaving the origin where it was made every
   * remaining note overdue the moment the structure appeared, so the rest of
   * the answer arrived in one burst and the music with it. Moving the origin
   * instead makes the structure a fermata: the phrase is held while the editor
   * builds, and the notes after it keep the spacing the score gave them.
   */
  const holdForStructure = (name) => {
    const due = noteOffsets[notesStruck] ?? noteOffsets[noteOffsets.length - 1] ?? 0;
    const overrun = performance.now() - origin - due;
    if (overrun > 0) {
      origin += overrun;
      heldMs += overrun;
    }
    emit([notesStruck, Math.round(performance.now() - origin), name, Math.round(heldMs)]);
  };

  // Every shape of answer box Hawkes draws, which is the same set the reader,
  // the probe and the table writer all use. This said `input.qbaseCSS` alone,
  // which is the dynamic editor's box and not the only one: a plain answer box
  // is `txtAns1_num`, and against one of those `ids()` came back empty, the
  // first step had no cursor, and a perfectly good plan abandoned itself as
  // `answer-fields-changed` -- reported as the question having moved on. Live,
  // on 2026-09-07, that was the last gate between an exact rational and the
  // box it belonged in.
  const boxes = () =>
    [...document.querySelectorAll(
      'input.qbaseCSS, input[id^="txtAns"], input.boxStyle'
    )].filter((box) => box.getBoundingClientRect().width > 0);
  const ids = () => boxes().map((box) => box.id);
  const dialogUp = () =>
    [...document.querySelectorAll('[id*="customMessageBox"]')].some(
      (node) => node.getBoundingClientRect().height > 0
    );

  /**
   * How long the page is given to accept or undo what was just written, as a
   * count of polls rather than a wall-clock deadline.
   *
   * Counted, because the two clocks a caller may virtualise are not the same
   * one: a harness that drives `setTimeout` from a queue without also moving
   * `Date.now` leaves a deadline loop spinning forever against a clock nothing
   * advances. Polls advance whatever the timers advance, so this terminates
   * under a real clock and a virtual one alike.
   */
  const PERSIST_POLLS = 15;
  const PERSIST_INTERVAL_MS = 80;

  /**
   * Whether the page kept the entry once its own handling had run.
   *
   * Reading a box back in the same turn as the write proves the assignment
   * happened and nothing more. Hawkes decides afterwards, from its own copy of
   * the answer: on 2026-09-10 the character went in, read back correctly, this
   * writer reported success -- and Hawkes then raised "Your answer seems
   * incomplete" and emptied the box, with the panel still saying the answer
   * had been placed. An entry the page discards is a failed insertion, and
   * saying so is the difference between a bug that is reported and one that is
   * watched happening.
   *
   * Held to the boxes' own text rather than to any model of what should be in
   * them, so this stays a persistence check and decides nothing about the
   * answer. Hawkes' own dialog counts as a refusal however the text ended up.
   */
  const heldByThePage = async (expected) => {
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    for (let poll = 0; poll < PERSIST_POLLS; poll += 1) {
      await pause(PERSIST_INTERVAL_MS);
      if (dialogUp()) {
        return "editor-dialog-open";
      }
      if (boxes().map((box) => box.value).join("") !== expected) {
        return "answer-did-not-persist";
      }
    }
    return true;
  };

  /**
   * Wait for the editor to finish adding boxes after a template loads.
   *
   * It must settle, not merely change. `Fraction` adds three boxes — numerator,
   * denominator, and the continuation after it — and they do not all appear in
   * the same tick. Returning at the first change captured only part of them,
   * so the slots recorded for that template were wrong and every later move
   * went to the wrong box: the answer came out half-entered.
   */
  const settle = async (before) => {
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const deadline = Date.now() + SETTLE_MS;
    const start = before.join("|");
    let last = start;
    let stable = 0;
    while (Date.now() < deadline) {
      await pause(60);
      const now = ids().join("|");
      if (now !== last) {
        last = now;
        stable = 0;
        continue;
      }
      stable += 1;
      // Changed, and then held still for three polls.
      if (now !== start && stable >= 3) {
        return ids();
      }
    }
    return ids();
  };

  /** `txtAns1_num` and `txtAns1_den` are the two halves of `txtAns1`. */
  const baseOf = (id) => String(id ?? "").replace(/_(?:num|den)$/, "");

  /**
   * The box a `/` just opened, when it provably belongs to this same answer.
   *
   * A denominator has no identity of its own in the plan -- it did not exist
   * when the plan was made. What can be required of it is that exactly one box
   * appeared, that it is named as this box's other half, and that Hawkes names
   * it a denominator. Anything else is a page doing something this writer did
   * not ask for, and is refused rather than typed into.
   */
  const openedDenominator = (from, fresh) => {
    const base = baseOf(from);
    if (base.length === 0 || fresh.length !== 1) {
      return null;
    }
    const [opened] = fresh;
    return opened.endsWith("_den") && baseOf(opened) === base ? opened : null;
  };

  /**
   * Make Hawkes select this box through its own focus handling.
   *
   * `focus()` moves `document.activeElement` and nothing else; the page selects
   * from the focus events it binds at document level, which never fire while
   * the panel holds system focus. Both are run, in that order, exactly as the
   * table writer reaches a cell's second box.
   */
  const focusThroughPage = (id) => {
    const box = document.getElementById(id);
    if (!box) {
      return false;
    }
    try {
      box.focus();
    } catch { /* the page's own path, tried first */ }
    try {
      box.dispatchEvent(new FocusEvent("focus", { relatedTarget: null }));
      box.dispatchEvent(new FocusEvent("focusin", { bubbles: true, relatedTarget: null }));
    } catch { /* an event the page will not take is not a selection */ }
    return true;
  };

  /**
   * Press one ordinary character on the editor's own keypad.
   *
   * `keyPadButtonClick` is the same entry point a template press takes. Its
   * `addElement(name, true, callback)` handles the templates and special keys
   * first and then falls through to an ordinary-character branch, so a digit,
   * a letter and a supported operator are editor operations in exactly the
   * sense `Fraction` is. Nothing here decides whether the character is
   * allowed: the editor validates it against the slot it is in and refuses it
   * itself, which is the whole reason for coming this way.
   */
  const pressCharacter = (character) => {
    const control = currentControl();
    if (!control || typeof control.keyPadButtonClick !== "function") {
      return false;
    }
    try {
      control.keyPadButtonClick(character, () => {});
    } catch {
      // The editor declining is not this writer throwing. The read-back below
      // is what decides, and it will see that nothing landed.
      return false;
    }
    return true;
  };

  /**
   * Write one character the way a plain answer box receives one.
   *
   * The prototype's setter, then the `input` the box's own sanitiser runs
   * inside. This is what Hawkes' own `AnswerBoxKeyPadClick` does to a plain
   * box, and there is no page-owned character API to prefer over it.
   */
  /**
   * One key event, carrying the fields an older editor reads.
   *
   * `KeyboardEvent` cannot be constructed with `keyCode`, `charCode` or
   * `which`: they are legacy accessors and the init dictionary ignores them,
   * so a constructed event reports 0 for all three. Hawkes' answer boxes are
   * ASP.NET-era code and read exactly those, and a handler that switches on
   * `keyCode` treats 0 as "not a character" and does nothing. Defined back on
   * the event so the page sees what a real key press carries.
   */
  const keyEvent = (box, type, character) => {
    const event = new KeyboardEvent(type, {
      bubbles: true,
      cancelable: true,
      key: character,
    });
    const code = character.charCodeAt(0);
    for (const name of ["keyCode", "charCode", "which"]) {
      try {
        Object.defineProperty(event, name, { get: () => code });
      } catch {
        // An engine that will not redefine it still gets the event.
      }
    }
    return box.dispatchEvent(event);
  };

  /**
   * Write one character the way a plain answer box receives one.
   *
   * The prototype's setter, then the `input` the box's own sanitiser runs
   * inside -- surrounded by the key events a real press makes. Those are not
   * decoration: a box that syncs the page's answer model on `keyup` never sees
   * a value written without one, and the DOM then holds a value the page does
   * not own. That is what live insertion looked like on 2026-09-10 -- the
   * character went in, read back correctly, and Hawkes raised its own "Your
   * answer seems incomplete" dialog and cleared the box.
   */
  const writeCharacter = (box, character) => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value"
    ).set;
    keyEvent(box, "keydown", character);
    setter.call(box, box.value + character);
    box.dispatchEvent(
      new InputEvent("input", {
        bubbles: true,
        data: character,
        inputType: "insertText",
      })
    );
    keyEvent(box, "keyup", character);
  };

  const typeInto = async (id, text) => {
    const box = document.getElementById(id);
    if (!box) {
      return { ok: false, code: "answer-field-disappeared" };
    }
    box.focus();
    if (viaKeypad) {
      // DOM focus moves `document.activeElement` and nothing else, and it is
      // the *editor's* own cursor that decides where a keypad character lands.
      // Without this a slot move typed its characters wherever the editor
      // still thought it was -- the same fault `press` aims out before loading
      // a template, and the read-back below is what catches it if aiming
      // fails.
      aimEditorAt(id);
    } else if (box.disabled || box.readOnly) {
      return { ok: false, code: "field-not-editable" };
    } else if (!box.dispatchEvent(new InputEvent("beforeinput", {
      bubbles: true,
      cancelable: true,
      data: text,
      inputType: "insertText",
    }))) {
      // The box's own preflight, kept from the writer this transport replaced:
      // Hawkes cancels this event for input its published model will not take.
      return { ok: false, code: "input-cancelled" };
    }
    for (const character of text) {
      await waitForNote();
      // The box is re-read every note: this now spans seconds rather than one
      // tick, and a box that went away mid-performance must not be written to.
      const live = document.getElementById(id);
      if (!live) {
        return { ok: false, code: "answer-field-disappeared" };
      }
      if (viaKeypad) {
        pressCharacter(character);
      } else {
        if (live.disabled || live.readOnly) {
          // The field closed under us part-way through. Stop rather than write
          // into something that has stopped accepting input.
          return { ok: false, code: "field-not-editable" };
        }
        writeCharacter(live, character);
      }
      // Read back from the box by id rather than from the reference written
      // through: a keypad press is the editor's own code, and the editor may
      // replace the node it renders into.
      const settled = document.getElementById(id);
      if (!settled || !settled.value.endsWith(character)) {
        // Name the one character Hawkes rejected, not the whole typing run.
        // This distinguishes a character refusal from a template failure and
        // makes the panel's diagnostic specific without retaining the answer.
        // Under the keypad transport it also catches a character the editor
        // accepted into some *other* box, because this asks the box the plan
        // meant rather than asking whether anything happened.
        return {
          ok: false,
          code: "answer-has-rejected-characters",
          detail: character,
        };
      }
      written[viaKeypad ? "keypad" : "native"] += 1;
      // Emitted in the accepted write's callback. An optional, one-way
      // presentation observer hears only the index and elapsed time. A page
      // can observe/spoof this DOM cue; it confers no insertion capability.
      emit([notesStruck - 1, performance.now() - origin]);
    }
    written.fields.add(id);
    return { ok: true };
  };

  /**
   * Commit the boxes that were written, the way finishing with them does.
   *
   * A native input fires `change` when the caret leaves it having been
   * modified, and a page that keeps its own copy of the answer takes it there.
   * Done once the whole answer is in rather than per box, because that is when
   * a person is finished with it -- and because the expected text has to be
   * read *before* any of this, or a page that discards the entry here would be
   * checked against the wreckage it left.
   *
   * Dispatched rather than waited on, and the caret is left where it is: this
   * add-on never moves focus away from an answer it has just entered.
   */
  const commitWrittenBoxes = () => {
    for (const id of written.fields) {
      document
        .getElementById(id)
        ?.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  /** How this performance actually ran, as numbers only. */
  const measured = () => ({
    // Not a number, and the only one: which route the characters actually
    // took. A diagnostic that cannot say this cannot tell a transport that
    // drifted from one that was chosen.
    transport,
    keypadWrites: written.keypad,
    nativeWrites: written.native,
    notes: lateness.length,
    heldMs: Math.round(heldMs),
    elapsedMs: Math.round(performance.now() - performanceStartedAt),
    maxLatenessMs: lateness.length ? Math.max(...lateness) : 0,
    meanLatenessMs: lateness.length
      ? Math.round(lateness.reduce((total, late) => total + late, 0) / lateness.length) : 0,
    driftMs: lateness.length ? lateness[lateness.length - 1] - lateness[0] : 0,
  });

  const ui = window.quant_wp_UI;
  if (!ui || ui.controlsCollection === undefined) {
    return { ok: false, code: "editor-model-missing" };
  }
  if (dialogUp()) {
    return { ok: false, code: "editor-dialog-open" };
  }


  let activeControl = null;
  const currentControl = () => {
    if (activeControl) {
      return activeControl;
    }
    const index = ui.focusedElementIndex;
    return ui.controlsCollection[index >= 0 ? index : 0];
  };

  /**
   * The editor's own base object that owns a given answer box.
   *
   * Setting DOM focus on an input does not move the editor's cursor: it keeps
   * its own `CurrentBase`, and a template loads onto that. So typing `12x`
   * into the denominator worked while the exponent that followed it landed in
   * the numerator, because that is where the editor still thought it was.
   *
   * The tree is walked to find the `Base` owning the target box, so a template
   * is loaded where the plan meant it to go. Only nodes that can actually load
   * one are considered; a `Fraction` and its `Numerator` report the same box.
   */
  const findBase = (inputId, control = currentControl()) => {
    let found = null;
    const walk = (node, depth) => {
      if (!node || found || depth > 8) {
        return;
      }
      if (node.Type === "Base" && typeof node.loadExponent === "function") {
        try {
          const div = node.objMyDiv;
          const element = div && (div.jquery ? div[0] : div);
          const input = element?.querySelector?.("input.qbaseCSS");
          if (input && input.id === inputId) {
            found = node;
            return;
          }
        } catch {
          // Not this one.
        }
      }
      const children = node.arrChildObjects;
      if (children) {
        for (let index = 0; index < children.length; index += 1) {
          walk(children[index], depth + 1);
        }
      }
    };
    walk(control, 0);
    return found;
  };

  // A structured multi-part answer must name distinct page-owned editors.
  // Resolve all of them before the first write; DOM order alone is not enough because
  // loading a fraction replaces the first editor's base input.
  const pinnedControls = [];
  if (multi) {
    for (const fieldId of targetFieldIds) {
      const matches = [];
      for (let index = 0; index < ui.controlsCollection.length; index += 1) {
        const control = ui.controlsCollection[index];
        if (control && findBase(fieldId, control)) {
          matches.push(control);
        }
      }
      const field = document.getElementById(fieldId);
      if (matches.length !== 1 || !field || field.value !== "") {
        return { ok: false, code: "answer-fields-changed" };
      }
      pinnedControls.push(matches[0]);
    }
    if (new Set(pinnedControls).size !== pinnedControls.length) {
      return { ok: false, code: "answer-fields-changed" };
    }
  }

  /** Move the editor's own cursor to the base owning a box, if it will. */
  const aimEditorAt = (inputId) => {
    const base = findBase(inputId);
    if (!base) {
      return null;
    }
    try {
      if (typeof base.setFocus === "function") {
        base.setFocus();
      }
    } catch {
      // The direct loader below does not need it.
    }
    return base;
  };

  /**
   * Whether the editor will actually load this template right now.
   *
   * These are the editor's own guards — `addElement` calls exactly these and
   * raises its refusal dialog when one says no. Asking first turns a silent
   * half-built answer into a wait.
   */
  const readyFor = (name, base = currentControl()?.CurrentBase) => {
    if (!base) {
      return false;
    }
    // Absolute value is one of the editor's parentheses: `addElement` groups
    // `Mod` with `PBrace`, `SBrace` and the rest, and guards them all with
    // `qualifyLoadParenthesis(ObjType)` -- which, unlike the other guards,
    // takes the type as an argument.
    const guards = {
      Exponent: [base.qualifyLoadExponent, []],
      Fraction: [base.qualifyLoadFraction, []],
      Radical: [base.qualifyLoadRadical, []],
      IndexedRadical: [base.qualifyLoadRadical, []],
      PBrace: [base.qualifyLoadParenthesis, ["PBrace"]],
      Mod: [base.qualifyLoadParenthesis, ["Mod"]],
    };
    const [guard, guardArgs] = guards[name] ?? [undefined, []];
    try {
      return typeof guard === "function" ? guard.apply(base, guardArgs) === true : true;
    } catch {
      return false;
    }
  };

  /**
   * Wait until the editor is ready for a template, then press it.
   *
   * Typing and pressing in the same turn was the bug: the editor updates its
   * notion of the current box from its own focus handling, and had not caught
   * up. The answer came out half-built — `x^6y` where `x^6y^7z^4` was meant,
   * because the second exponent was refused and the rest of the plan had
   * nowhere to go.
   */
  const press = async (name, inputId) => {
    if (currentControl()?.enabled === false) {
      return false;   // sending an answer mid-plan disables the control
    }
    // Aim the editor at the box the plan is working in, before asking it for
    // anything. Otherwise the template lands wherever the editor last was.
    const base = aimEditorAt(inputId);

    const deadline = Date.now() + SETTLE_MS;
    while (Date.now() < deadline) {
      if (readyFor(name, base ?? undefined)) {
        break;
      }
      await new Promise((resolve) => setTimeout(resolve, 60));
    }
    if (!readyFor(name, base ?? undefined)) {
      return false;
    }

    // Prefer the keypad path, which is what a real click takes, once the
    // editor's cursor agrees with ours. Fall back to the owning base's own
    // loader when it does not.
    const control = currentControl();
    if (base && control?.CurrentBase !== base) {
      const loaders = {
        Exponent: [base.loadExponent, [true]],
        Fraction: [base.loadFraction, [true]],
        Radical: [base.loadRadical, [true]],
        // `loadRadical(fromKeypad, IsIndexed)` -- the same loader, with the
        // index box asked for by a second argument.
        IndexedRadical: [base.loadRadical, [true, true]],
        PBrace: [base.loadParenthesis, ["PBrace", true]],
        Mod: [base.loadParenthesis, ["Mod", true]],
      };
      const [loader, loaderArgs] = loaders[name] ?? [undefined, []];
      if (typeof loader !== "function") {
        return false;
      }
      loader.apply(base, loaderArgs);
      return true;
    }
    if (!control || typeof control.keyPadButtonClick !== "function") {
      return false;
    }
    control.keyPadButtonClick(name, () => {});
    return true;
  };

  /** Whether anything at all is left in the answer boxes. */
  const answerIsEmpty = () =>
    ids().every((id) => (document.getElementById(id)?.value ?? "") === "");

  /** Whether one pinned page-owned editor still exists and contains an answer. */
  const controlHasAnswer = (control) => {
    const div = control?.objMyDiv;
    const root = div && (div.jquery ? div[0] : div);
    if (!root || root.isConnected === false) {
      return false;
    }
    const inputs = [...(root.querySelectorAll?.("input.qbaseCSS") ?? [])];
    return inputs.some((input) => typeof input.value === "string" && input.value !== "");
  };

  /**
   * Undo a half-built answer, so nothing wrong is left in the box.
   *
   * `addElement` reads the caret before it dispatches, but only when the call
   * says it came from the keypad:
   *
   *     if (EventFromKeyPad) {
   *         ObjType = mapName(ObjType);
   *         this.CaretIndex = objMe.CurrentBase.getCaretIndex();
   *     }
   *     if (ObjType == 'Clear') { clearAll(); }
   *
   * With no `CurrentBase` -- which is where a rejected character leaves it --
   * that caret read throws and `Clear` never runs. A half-built `1/7` was left
   * in the box that way. Calling it as not-from-the-keypad skips both the
   * mapping and the caret read, so `clearAll` is reached either way, and the
   * result is checked rather than assumed.
   */
  const clearAnswer = async () => {
    const control = currentControl();
    if (!control) {
      return false;
    }
    const attempts = [
      () => control.addElement("Clear", false, () => {}),
      () => control.keyPadButtonClick("Clear", () => {}),
      () => {
        // Last resort: the editor's own backspace, one element at a time.
        for (let step = 0; step < 40 && !answerIsEmpty(); step += 1) {
          control.CurrentBase?.backSpaceClick();
        }
      },
    ];
    for (const attempt of attempts) {
      try {
        attempt();
      } catch {
        continue; // try the next way in
      }
      await new Promise((resolve) => setTimeout(resolve, 120));
      if (answerIsEmpty()) {
        return true;
      }
    }
    return answerIsEmpty();
  };

  /** Report a failure, leaving no partial answer behind. */
  const abandon = async (code, detail) => {
    const controls = multi ? pinnedControls : [currentControl()];
    for (const control of controls) {
      activeControl = control;
      await clearAnswer();
    }
    const cleared = answerIsEmpty();
    const report = detail === undefined ? { ok: false, code } : { ok: false, code, detail };
    if (!cleared) {
      // Say so rather than let a half-built answer look like a clean refusal.
      report.leftBehind = true;
    }
    return report;
  };

  // A disabled control accepts typing through the DOM but silently ignores
  // every template: `addElement` skips its whole body when the control is
  // disabled and the call came from the keypad. That combination is what
  // produced half-built answers -- the characters landed, the structure did
  // not, and nothing said so.
  if (
    (multi ? pinnedControls : [currentControl()])
      .some((control) => control?.enabled === false)
  ) {
    return { ok: false, code: "editor-disabled" };
  }

  // One answer, and one place for it. A single plan takes the first visible
  // answer box and types the whole answer into the structure it opens, which
  // is only true while the page is showing one answer's boxes. The isolated
  // writer this transport replaced refused a page showing several solution
  // fields; this is the same refusal, asked of the boxes rather than of the
  // markup around them, and asked before anything is written. A cell's two
  // halves -- `txtAns1_num` and `txtAns1_den` -- are one group, because they
  // are one answer.
  if (!multi && new Set(ids().map(baseOf)).size > 1) {
    return { ok: false, code: "editor-multiple-answer" };
  }

  const enteredParts = [];
  for (let planIndex = 0; planIndex < plans.length; planIndex += 1) {
    activeControl = multi ? pinnedControls[planIndex] : null;
    let cursor = multi ? targetFieldIds[planIndex] : ids()[0];
    const target = cursor ? document.getElementById(cursor) : null;
    if (!target || (multi && target.value !== "")) {
      return await abandon("answer-fields-changed");
    }
    // One frame per template loaded, so a slot move returns to the structure it
    // belongs to rather than to whatever was opened most recently inside it.
    const frames = [];
    // What a `/` split, once one has. Kept so the whole logical value can be
    // read back from the two boxes it ended up in.
    let expansion = null;
    let typedSoFar = "";

    for (const step of plans[planIndex]) {
      if (step.op === "type") {
        const typed = await typeInto(cursor, step.text);
        if (!typed.ok) {
          return await abandon(typed.code, typed.detail);
        }
        typedSoFar = `${typedSoFar}${step.text ?? ""}`;
        if (expansion) {
          expansion.denominatorText = `${expansion.denominatorText}${step.text ?? ""}`;
        }
        continue;
      }

      if (step.op === "template") {
        if (!viaKeypad) {
          // A plain answer box has no templates to press. A plan carrying one
          // was made against a different editor than the one being written to.
          return await abandon("transport-step-mismatch", step.name);
        }
        const before = ids();
        document.getElementById(cursor)?.focus();
        if (!(await press(step.name, cursor))) {
          return await abandon("template-unavailable", step.name);
        }
        const after = await settle(before);
        if (dialogUp()) {
          return await abandon("editor-dialog-open", step.name);
        }
        const fresh = after.filter((id) => !before.includes(id));
        const focused = document.activeElement?.id;
        cursor = fresh.includes(focused) ? focused : fresh[0];
        if (cursor === undefined) {
          return await abandon("template-refused-by-question", step.name);
        }
        frames.push({
          template: step.name,
          slots: fresh.filter((id) => id !== cursor),
        });
        holdForStructure(step.name);
        continue;
      }

      if (step.op === "slash") {
        if (viaKeypad) {
          // A dynamic editor builds a fraction with its own Fraction template,
          // and `/` is in no dynamic question's character set: typing one there
          // raises the editor's refusal dialog. The planner only emits this
          // step for a paired plain box, so reaching it here means the plan and
          // the transport disagree about which editor this is.
          return await abandon("transport-step-mismatch", "slash");
        }
        // Native expansion. There is no template to press: typing `/` into an
        // ordinary Hawkes answer box is what turns it into a numerator and a
        // denominator, and it is how a student enters a fraction into a
        // question that publishes no Fraction template at all.
        //
        // The `/` is not a character the box keeps, so nothing here checks
        // that it landed. What is checked is that the box split.
        const before = ids();
        const box = document.getElementById(cursor);
        if (!box) {
          return await abandon("answer-field-disappeared");
        }
        focusThroughPage(cursor);
        try {
          const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, "value"
          ).set;
          setter.call(box, `${box.value}/`);
          box.dispatchEvent(new InputEvent("input", {
            bubbles: true, data: "/", inputType: "insertText",
          }));
        } catch {
          return await abandon("fraction-not-expandable", "slash");
        }
        const after = await settle(before);
        if (dialogUp()) {
          return await abandon("editor-dialog-open", "slash");
        }
        const opened = openedDenominator(
          cursor, after.filter((id) => !before.includes(id))
        );
        if (opened === null) {
          return await abandon("fraction-not-expandable", "slash");
        }
        // Hawkes moves the editor into the new box itself, as it does for a
        // template's first slot. Its own focus handling is run for the case
        // where it has not.
        if (!focusThroughPage(opened)) {
          return await abandon("fraction-not-expandable", "slash");
        }
        expansion = {
          numerator: cursor,
          denominator: opened,
          numeratorText: typedSoFar,
          denominatorText: "",
        };
        cursor = opened;
        holdForStructure("Fraction");
        continue;
      }

      if (step.op === "slot" || step.op === "base") {
        // A named slot belongs to its own template: discard anything opened
        // inside it since, so "denominator" is the fraction's, not a radical's.
        let index = frames.length - 1;
        if (step.op === "slot" && step.name === "denominator") {
          while (index >= 0 && frames[index].template !== "Fraction") {
            index -= 1;
          }
        }
        while (index >= 0 && frames[index].slots.length === 0) {
          index -= 1;
        }
        if (index < 0) {
          return await abandon("plan-lost-its-place", step.op);
        }
        frames.length = index + 1;
        cursor = frames[index].slots.shift();
        continue;
      }

      return await abandon("unknown-step", step.op);
    }
    // The whole rational, read back from the two boxes it was entered across.
    // A cell showing `-3/2` holds it as `-3` and `2`; checking the boxes
    // separately is the only way to say the logical value settled, and the
    // only way to catch a denominator that went somewhere else.
    if (expansion !== null) {
      const numerator = document.getElementById(expansion.numerator);
      const denominator = document.getElementById(expansion.denominator);
      if (
        !numerator
        || !denominator
        || numerator.value !== expansion.numeratorText
        || denominator.value !== expansion.denominatorText
      ) {
        return await abandon("fraction-not-settled", "slash");
      }
    }
    enteredParts.push(
      plans[planIndex]
        .filter((step) => step.op === "type")
        .map((step) => step.text ?? "")
        .join("")
    );
  }

  if (multi) {
    if (
      pinnedControls.some(
        (control) =>
          !Array.from(ui.controlsCollection).includes(control) || !controlHasAnswer(control)
      )
    ) {
      return await abandon("answer-parts-incomplete");
    }
    return {
      ok: true,
      code: "entered-fields",
      transport,
      entered: enteredParts,
      enteredFields: [...targetFieldIds],
      completed: enteredParts.length,
      timing: measured(),
    };
  }
  activeControl = null;
  const entered = boxes()
    .map((box) => box.value)
    .join("");
  // The keypad transport writes through the editor's own API, so what it
  // entered is the editor's by construction. A plain box is written to
  // directly, and only the page can say whether it kept it.
  if (!viaKeypad) {
    commitWrittenBoxes();
    const kept = await heldByThePage(entered);
    if (kept !== true) {
      return { ok: false, code: kept, transport, timing: measured() };
    }
  }
  return { ok: true, code: "entered", transport, entered, timing: measured() };
}
