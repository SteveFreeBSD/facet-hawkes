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
 * @param {Array<{op: string, text?: string, name?: string}>} steps
 * @returns {Promise<{ok: boolean, code: string, entered?: string, detail?: string}>}
 */
export async function enterPlan(steps, cadence = {}) {
  const SETTLE_MS = 4000;

  /**
   * Presentation cadence for structured entry.
   *
   * The plain-text path in `content/hawkes-editor.js` has the same rules, but
   * this function is serialized into the page's own world by `executeScript`,
   * so it can close over nothing and must carry its own copy. Keep the two in
   * step; the shapes are deliberately identical.
   *
   * One performance covers every character of every `type` step. Templates sit
   * on the same clock rather than adding to it: a slow `settle` simply eats
   * into the notes that follow, so the editor's own pace can stretch the
   * performance but never doubles its length.
   */
  const NOTE_FALLBACK = {
    tempoBpm: 82,
    durationMinMs: 5000,
    durationMaxMs: 10000,
    rhythmWeights: [1, 0.68, 1.18, 0.78],
    swingRatio: 0.12,
    variationRatio: 0.18,
    symbolRestRatio: 0.42,
  };

  const randomUnit = () => {
    const sample = new Uint32Array(1);
    crypto.getRandomValues(sample);
    return sample[0] / 0x100000000;
  };

  const bounded = (value, minimum, maximum, fallback) =>
    typeof value === "number" && Number.isFinite(value)
      ? Math.min(maximum, Math.max(minimum, value))
      : fallback;

  const beat = (() => {
    const weights = Array.isArray(cadence.rhythmWeights)
      ? cadence.rhythmWeights.slice(0, 8).map((w) => bounded(w, 0.25, 2.5, 1))
      : [];
    const first = bounded(cadence.durationMinMs, 2000, 12000, NOTE_FALLBACK.durationMinMs);
    const second = bounded(cadence.durationMaxMs, 2000, 12000, NOTE_FALLBACK.durationMaxMs);
    return {
      tempoBpm: bounded(cadence.tempoBpm, 30, 300, NOTE_FALLBACK.tempoBpm),
      durationMinMs: Math.min(first, second),
      durationMaxMs: Math.max(first, second),
      rhythmWeights: weights.length > 1 ? weights : [...NOTE_FALLBACK.rhythmWeights],
      swingRatio: bounded(cadence.swingRatio, 0, 0.6, NOTE_FALLBACK.swingRatio),
      variationRatio: bounded(cadence.variationRatio, 0, 0.35, NOTE_FALLBACK.variationRatio),
      symbolRestRatio: bounded(cadence.symbolRestRatio, 0, 1, NOTE_FALLBACK.symbolRestRatio),
    };
  })();

  const noteWeight = (character, index) => {
    let weight = beat.rhythmWeights[index % beat.rhythmWeights.length];
    weight *= index % 2 === 0 ? 1 + beat.swingRatio : 1 - beat.swingRatio * 0.5;
    if (/\s/u.test(character)) {
      weight *= 1 + beat.symbolRestRatio * 1.35;
    } else if (/[-=+*/^,;:]/u.test(character)) {
      weight *= 1 + beat.symbolRestRatio;
    } else if (/[)\]}]/u.test(character)) {
      weight *= 1 + beat.symbolRestRatio * 0.5;
    }
    return weight * (1 + ((randomUnit() * 2) - 1) * beat.variationRatio);
  };

  // Every character the plan will type, scheduled up front as one performance.
  const score = [...steps]
    .filter((step) => step.op === "type")
    .map((step) => step.text ?? "")
    .join("");
  const noteOffsets = (() => {
    if (score.length < 2) {
      // A single note is struck at once. Holding the field empty for the whole
      // window, then filling it in the last instant, reads as a hang.
      return score.length === 1 ? [0] : [];
    }
    const weights = [...score].slice(0, -1).map((c, i) => noteWeight(c, i));
    const total = weights.reduce((sum, w) => sum + w, 0);
    const beatMs = 60000 / beat.tempoBpm;
    const musical = Math.max(1, total) * beatMs;
    const window =
      beat.durationMinMs
      + Math.floor(randomUnit() * (beat.durationMaxMs - beat.durationMinMs + 1));
    const duration = Math.min(
      beat.durationMaxMs,
      Math.max(beat.durationMinMs, Math.round((musical * 0.72) + (window * 0.28)))
    );
    const offsets = [0];
    let elapsed = 0;
    for (const weight of weights) {
      elapsed += weight;
      offsets.push(Math.round(duration * elapsed / total));
    }
    offsets[offsets.length - 1] = duration;
    return offsets;
  })();

  const performanceStartedAt = performance.now();
  let notesStruck = 0;

  /** Hold until this note is due. A late clock simply plays it now. */
  const waitForNote = async () => {
    const due = noteOffsets[notesStruck];
    notesStruck += 1;
    if (due === undefined) {
      return;
    }
    const wait = due - (performance.now() - performanceStartedAt);
    if (wait > 0) {
      await new Promise((resolve) => setTimeout(resolve, wait));
    }
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
      return false;
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
        return false;
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
        return false; // the editor rejected it
      }
    }
    return true;
  };

  const ui = window.quant_wp_UI;
  if (!ui || ui.controlsCollection === undefined) {
    return { ok: false, code: "editor-model-missing" };
  }
  if (dialogUp()) {
    return { ok: false, code: "editor-dialog-open" };
  }


  const currentControl = () => {
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
  const findBase = (inputId) => {
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
    walk(currentControl(), 0);
    return found;
  };

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
    const cleared = await clearAnswer();
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
  if (currentControl()?.enabled === false) {
    return { ok: false, code: "editor-disabled" };
  }

  let cursor = ids()[0];
  if (cursor === undefined) {
    return { ok: false, code: "no-focused-answer-field" };
  }
  // One frame per template loaded, so a slot move returns to the structure it
  // belongs to rather than to whatever was opened most recently inside it.
  const frames = [];

  for (const step of steps) {
    if (step.op === "type") {
      if (!(await typeInto(cursor, step.text))) {
        return await abandon("answer-has-rejected-characters", step.text);
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

  const entered = boxes()
    .map((box) => box.value)
    .join("");
  return { ok: true, code: "entered", entered };
}
