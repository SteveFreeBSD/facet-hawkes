"use strict";

/**
 * The one function that writes to the Hawkes editor.
 *
 * It is passed to `scripting.executeScript` as `func` and runs in the page's
 * own world, because building structure means calling the editor's own
 * `keyPadButtonClick` — a page-owned method no isolated script can reach.
 * Passing it as a function rather than a file is what allows the plan to be an
 * argument; `executeScript` accepts files or a function with arguments, never
 * both.
 *
 * It must stay self-contained: `executeScript` serialises it, so it may not
 * reference anything outside its own body.
 *
 * The plan comes from `editor-plan.js`, which has already checked the answer
 * against this question's own character set and permitted templates. This
 * function performs the plan and reports what happened; it makes no decisions
 * about what the answer should be, and it never touches Submit or Check.
 */

/**
 * @param {Array<{op: string, text?: string, name?: string}>|Array<Array<{
 *   op: string, text?: string, name?: string
 * }>>} steps one plan, or independently preflighted plans for multiple fields
 * @param {object} cadence
 * @param {string[]} targetFieldIds exact multi-field target, empty for one editor
 * @returns {Promise<{ok: boolean, code: string, entered?: string, detail?: string}>}
 */
export async function enterPlan(steps, cadence = {}, targetFieldIds = []) {
  const SETTLE_MS = 4000;
  const multi = Array.isArray(targetFieldIds) && targetFieldIds.length >= 2 && targetFieldIds.length <= 4;
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

  const boxes = () =>
    [...document.querySelectorAll("input.qbaseCSS")].filter(
      (box) => box.getBoundingClientRect().width > 0
    );
  const ids = () => boxes().map((box) => box.id);
  const dialogUp = () =>
    [...document.querySelectorAll('[id*="customMessageBox"]')].some(
      (node) => node.getBoundingClientRect().height > 0
    );

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

  const typeInto = async (id, text) => {
    const box = document.getElementById(id);
    if (!box) {
      return { ok: false, code: "answer-field-disappeared" };
    }
    box.focus();
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value"
    ).set;
    for (const character of text) {
      await waitForNote();
      // The box is re-read every note: this now spans seconds rather than one
      // tick, and a box that went away mid-performance must not be written to.
      const live = document.getElementById(id);
      if (!live) {
        return { ok: false, code: "answer-field-disappeared" };
      }
      setter.call(live, live.value + character);
      live.dispatchEvent(
        new InputEvent("input", {
          bubbles: true,
          data: character,
          inputType: "insertText",
        })
      );
      if (!live.value.endsWith(character)) {
        // Name the one character Hawkes rejected, not the whole typing run.
        // This distinguishes a character refusal from a template failure and
        // makes the panel's diagnostic specific without retaining the answer.
        return {
          ok: false,
          code: "answer-has-rejected-characters",
          detail: character,
        };
      }
      // Emitted in the accepted write's callback. An optional, one-way
      // presentation observer hears only the index and elapsed time. A page
      // can observe/spoof this DOM cue; it confers no insertion capability.
      emit([notesStruck - 1, performance.now() - origin]);
    }
    return { ok: true };
  };

  /** How this performance actually ran, as numbers only. */
  const measured = () => ({
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

    for (const step of plans[planIndex]) {
      if (step.op === "type") {
        const typed = await typeInto(cursor, step.text);
        if (!typed.ok) {
          return await abandon(typed.code, typed.detail);
        }
        continue;
      }

      if (step.op === "template") {
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
  return { ok: true, code: "entered", entered, timing: measured() };
}
