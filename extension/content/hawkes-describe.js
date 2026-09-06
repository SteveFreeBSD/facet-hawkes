"use strict";

/**
 * MAIN-world probe: what will this question's editor actually accept?
 *
 * Hawkes drives its answer editor through page-owned JavaScript — a global
 * `quant_wp_UI` holding the controls and their rules — which an isolated
 * content script cannot see. This is the one file injected into the page's own
 * world, and it only reads.
 *
 * It matters because the rules are per question. The same lesson offers a box
 * accepting `0123456789y` for one question and `[0-9.-]` for the next, and
 * typing a character outside that set raises a blocking Hawkes dialog rather
 * than being ignored. Reading `qdyBase_AllowedChar` lets the add-on refuse
 * before it touches the page instead of guessing from the answer's shape.
 *
 * Deliberately narrow: fixed operation, no arguments, read-only, and nothing
 * declared on the page. Everything is inside one IIFE whose value returns to
 * the popup as the script's completion value. The page can observe code
 * running in its world while it runs; that is the documented cost of MAIN, and
 * it buys the only access that works.
 */

(() => {
  const ui = window.quant_wp_UI;
  if (!ui || ui.controlsCollection === undefined) {
    return { ok: false, code: "editor-model-missing" };
  }

  /** Call one of the editor's zero-argument accessors, tolerating absence. */
  const read = (accessor) => {
    try {
      return typeof accessor === "function" ? accessor() : accessor;
    } catch {
      return undefined;
    }
  };

  /** Describe one page-owned editor control without changing it. */
  const describe = (index) => {
    const control = ui.controlsCollection[index];
    const data = ui.controlsCollectionData ? ui.controlsCollectionData[index] : null;
    if (!control || !data) {
      return null;
    }

    // A dynamic box builds structure from keypad templates. A plain answer box
    // takes characters only, and states its rule as a regular expression. A
    // question can also be answered by choosing an option -- "Not a Real
    // Number" and the like -- which is a selection, not text.
    const dynamic = data.isQDy === true || control.Type !== undefined;
    const option = !dynamic && data.boxValue === undefined;
    if (option) {
      return {
        ok: true,
        code: "described",
        kind: "option",
        name: String(read(data.Name) ?? ""),
        enabled: control.enabled !== false && read(data.enableState) !== false,
        text: "",
        allowedCharacters: "",
        maxLength: null,
        templates: { fraction: false, radical: false, exponent: false },
      };
    }

    return {
      ok: true,
      code: "described",
      kind: dynamic ? "dynamic" : "textbox",
      name: String(read(data.Name) ?? ""),
      enabled: control.enabled !== false && read(data.enableState) !== false,
      text: dynamic
        ? control.CurrentTextboxText ?? ""
        : String(read(control.boxValue) ?? ""),
      // For a dynamic box this is a literal set of characters; for a plain box it
      // is a character-class pattern such as "[0-9.-]".
      allowedCharacters: dynamic
        ? String(control.qdyBase_AllowedChar ?? "")
        : String(read(data.validString) ?? ""),
      maxLength: dynamic
        ? control.qdyBaseMaxChars ?? null
        : Number(read(data.maxLength)) || null,
      slots: dynamic
        ? {
            base: String(control.qdyBase_AllowedChar ?? ""),
            numerator: String(control.qdyFrac_AllowedNumeChar ?? ""),
            denominator: String(control.qdyFrac_AllowedDenoChar ?? ""),
            exponent: String(control.qdyExpo_AllowedChar ?? ""),
            exponentBase: String(control.qdyExpo_AllowedBaseChar ?? ""),
            radicand: String(control.qdyRoot_AllowedRadicandChar ?? ""),
            index: String(control.qdyRoot_AllowedIndexChar ?? ""),
          }
        : null,
      templates: {
        fraction: control.qdyFractionAllowed === true,
        radical: control.qdyRadicalAllowed === true,
        exponent: control.qdyExponentAllowed === true,
        parentheses: [control.qdyBase_AllowedTemplates].some((allowed) =>
          String(allowed ?? "").includes("PBrace")
        ),
        absoluteValue: [
          control.qdyBase_AllowedTemplates,
          control.qdyFrac_AllowedNumeTemplates,
          control.qdyFrac_AllowedDenoTemplates,
        ].some((allowed) => String(allowed ?? "").includes("Mod")),
      },
    };
  };

  const candidates = [];
  for (let offset = 0; offset < ui.controlsCollection.length; offset += 1) {
    if (ui.controlsCollection[offset] && ui.controlsCollectionData?.[offset]) {
      candidates.push(offset);
    }
  }
  // A control nobody can type into is not one of the question's answers.
  //
  // Live, lesson 3.3's "find two points on the parabola" step publishes three
  // controls: the two coordinate boxes it shows, and a *disabled* option
  // control it does not. Counting that third one made the answer three values
  // long -- so the reasoning route was asked for three and produced a third
  // coordinate the page had nowhere to put -- and then refused the insertion,
  // because a disabled control accepts nothing. Both boxes had planned
  // perfectly well. Dropping it is what makes the count the page's own.
  //
  // Enabled state is read from the same control the answer would be typed
  // into, so this decides nothing that `answerFitsEditor` would not decide
  // again later; it decides it before the count is taken.
  const described = candidates.map(describe);
  const usable = described.filter(
    (editor) => editor !== null && editor.enabled !== false
  );
  if (usable.length >= 2 && usable.length <= 4) {
    return described.every(Boolean)
      ? { ok: true, code: "described-multi", kind: "multi", editors: usable }
      : { ok: false, code: "no-focused-control" };
  }
  if (usable.length === 1) {
    // One control left once the unusable ones are out: unambiguous, and the
    // same answer the single-control path below would give.
    return usable[0];
  }

  let index = ui.focusedElementIndex;
  if (!Number.isInteger(index) || index < 0 || index >= ui.controlsCollection.length) {
    // Opening the sidebar clears Hawkes' cursor. Exactly one live model remains
    // unambiguous; a multi-control model is returned above and must additionally
    // match the isolated DOM solution set before insertion is offered.
    if (candidates.length !== 1) {
      return { ok: false, code: "no-focused-control" };
    }
    [index] = candidates;
  }
  return describe(index) ?? { ok: false, code: "no-focused-control" };
})();
