"use strict";

import { mathNotation } from "./config.js";
import { accepts } from "./editor-rules.js";

/**
 * Turning an answer into a sequence of editor steps.
 *
 * The Hawkes dynamic box cannot be handed a whole expression. Structure is
 * built one template at a time, and a template only loads when the box it
 * attaches to already holds something — pressing Exponent on an empty box
 * makes the editor raise a modal refusal instead. So an answer becomes an
 * ordered plan: type, press, type, continue.
 *
 * Exponents (including a fractional one), one top-level fraction,
 * parenthesized groups, absolute value, and square or indexed radicals are
 * supported. An answer needing anything else is refused by name so the panel
 * can say so.
 *
 * DOM-free, so it can be exercised directly — see `tests/test_hawkes_plan.py`.
 */

/**
 * @typedef {{op: "type", text: string}
 *   | {op: "template", name: string}
 *   | {op: "slot", name: "denominator"}
 *   | {op: "base"}} Step
 */

/**
 * Plan the keystrokes and template presses for one answer.
 *
 * @param {string} answer displayed form, e.g. "x^6yz^5"
 * @param {{allowedCharacters?: string, templates?: {exponent?: boolean}}} editor
 * @returns {{ok: true, steps: Step[]} | {ok: false, code: string, detail?: string}}
 */
export function planEntry(answer, editor) {
  if (typeof answer !== "string" || answer.length === 0) {
    return { ok: false, code: "answer-empty" };
  }
  // The host's machine form is deliberately explicit; unlike compact display
  // text, `sqrt(30)*y` cannot mean sqrt(30y). Converted to notation by the
  // same rule the panel reads with, so what is shown and what is built can
  // never disagree about what the answer is.
  answer = mathNotation(answer);
  // Display answers may contain spacing for readability; Hawkes treats it as
  // formatting, and its per-question character set often excludes spaces.
  answer = answer.replace(/\s+/g, "");
  // Explicit multiplication is Ethnos's ASCII convention; the editor wants
  // juxtaposition, and "*" is in no question's character set.
  answer = answer.replace(/\*/g, "");

  // Choosing an option is answering, not filling a field in.
  if (editor?.kind === "option") {
    return { ok: false, code: "editor-option-answer" };
  }
  // Without a published character set there is nothing to check an answer
  // against, and typing blind is how the editor's refusal dialog appears.
  if (!editor?.allowedCharacters) {
    return { ok: false, code: "editor-rules-unknown" };
  }

  // A pair the page has already bracketed.
  //
  // Lesson 3.3 step 1 asks for a vertex and draws `( [box] )` around a single
  // dynamic box whose published character set is `1234567890-+,` and whose
  // templates are `fraction+radical+exponent`. `(1,-4)` therefore cannot be
  // entered by any route -- parentheses are structural, so they can only come
  // from a template, and this question offers none -- while `1,-4` fits the
  // set exactly. The comma in that set is the page saying the box holds a
  // pair; the parentheses around it are the page's own furniture.
  //
  // The discriminator is the template, and it is the page's own: a question
  // that *means* its parentheses offers the template to build them, which is
  // how interval notation is asked and is the path `planRun` already takes.
  // A question that offers no template did not mean them as notation. So this
  // fires only where the bracketed form is unenterable and the interior is
  // exactly enterable, which is the one reading under which the question is
  // answerable at all.
  const shelled = pageBracketedPair(answer, editor);
  if (shelled !== null) {
    return planAnswerParts(shelled, editor);
  }

  const fraction = splitFraction(answer);
  if (fraction !== null) {
    if (editor?.templates?.fraction === true) {
      // Loading a fraction focuses the numerator, so the numerator is planned
      // first and the denominator is reached with an explicit slot move.
      const numerator = planRun(fraction.numerator, editor, "numerator");
      if (numerator.ok === false) {
        return numerator;
      }
      const denominator = planRun(fraction.denominator, editor, "denominator");
      if (denominator.ok === false) {
        return denominator;
      }
      return {
        ok: true,
        steps: [
          { op: "template", name: "Fraction" },
          ...numerator.steps,
          { op: "slot", name: "denominator" },
          ...denominator.steps,
        ],
      };
    }
    return planFractionBySlash(fraction, editor);
  }

  return planRun(answer, editor);
}

/**
 * A rational typed into an ordinary box that publishes no Fraction template.
 *
 * Hawkes offers a keypad template for structure, and where it offers one that
 * is the route. Where it offers none, this was read as "the answer cannot be
 * entered here" -- and that is not what the page does. An ordinary Hawkes
 * answer box turns into a numerator and a denominator when a `/` is typed into
 * it, which is how a student enters a fraction into it, and the box publishes
 * the second control from the start.
 *
 * Live, on 2026-09-07: an exact rational from Facet, a plain box publishing
 * `[0-9-]` and not one template, and `template-refused-by-question` against a
 * question whose own editor would have taken it.
 *
 * The same fact the table writer already works from, asked of a single answer
 * rather than of a cell: `editor.pairedControl` is the probe saying this one
 * drawn box has a second control behind it. Without that the refusal stands --
 * a box with nowhere to put a denominator genuinely cannot take a fraction,
 * and guessing that a `/` will open one is how a half-built answer is left in
 * somebody's coursework.
 *
 * Each half is typed into a box of its own, so each half is what the box's own
 * bound has to hold; `100/9` fits two six-character boxes and would never fit
 * one.
 */
function planFractionBySlash(fraction, editor) {
  if (editor?.pairedControl !== true) {
    return { ok: false, code: "template-refused-by-question", detail: "fraction" };
  }
  const bound = editor?.maxLength;
  if (
    Number.isInteger(bound)
    && bound > 0
    && Math.max(fraction.numerator.length, fraction.denominator.length) > bound
  ) {
    return { ok: false, code: "answer-too-long" };
  }
  const numerator = planRun(fraction.numerator, editor);
  if (numerator.ok === false) {
    return numerator;
  }
  const denominator = planRun(fraction.denominator, editor);
  if (denominator.ok === false) {
    return denominator;
  }
  // Every step is plain typing but the `/` itself, which is not a character
  // the box accepts -- it is the gesture that splits the box in two, and the
  // writer proves the second one appeared and belongs to this same answer
  // before a digit of the denominator is typed into it.
  return {
    ok: true,
    steps: [...numerator.steps, { op: "slash" }, ...denominator.steps],
  };
}

/**
 * Plan two already-separated answers for Hawkes' single comma-answer editor.
 *
 * The roots stay separate until this layer. A structured first root leaves
 * the cursor inside its last template, so move to that template's continuation
 * before typing the comma and building the second root.
 */
export function planAnswerParts(parts, editor, separator = ",") {
  if (!Array.isArray(parts) || parts.length !== 2 || separator !== ",") {
    return { ok: false, code: "answer-invalid" };
  }
  const planned = parts.map((part) => planEntry(part, editor));
  const divided = planEntry(separator, editor);
  const failure = [...planned, divided].find((plan) => plan.ok === false);
  if (failure) {
    return failure;
  }
  const first = planned[0].steps;
  const leavesTemplate = first.some((step) => step.op === "template");
  return {
    ok: true,
    steps: [
      ...first,
      ...(leavesTemplate ? [{ op: "base" }] : []),
      ...divided.steps,
      ...planned[1].steps,
    ],
  };
}

/**
 * The two halves of a pair whose brackets the page supplies, or null.
 *
 * Deliberately narrow. Dynamic boxes only, because "parentheses can only come
 * from a template" is that editor's rule; a plain textbox states its own
 * pattern and may simply accept the characters. Exactly two parts, because a
 * drawn `( , )` shell is a coordinate pair. And only where the question
 * publishes no parentheses template, so an answer that genuinely means its
 * brackets still goes the template route.
 */
function pageBracketedPair(answer, editor) {
  if (editor?.kind !== "dynamic" || editor?.templates?.parentheses === true) {
    return null;
  }
  const interior = unwrap(answer);
  if (interior === answer || interior.length === 0) {
    return null;
  }
  if (!accepts(editor?.allowedCharacters ?? "", ",", "dynamic")) {
    return null;
  }
  const parts = splitTopLevel(interior, ",");
  if (parts.length !== 2 || parts.some((part) => part.length === 0)) {
    return null;
  }
  return parts;
}

/** Split on a delimiter that is not inside brackets. */
function splitTopLevel(value, delimiter) {
  const parts = [];
  let depth = 0;
  let start = 0;
  for (let index = 0; index < value.length; index += 1) {
    const character = value[index];
    if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      depth -= 1;
    } else if (character === delimiter && depth === 0) {
      parts.push(value.slice(start, index));
      start = index + 1;
    }
  }
  parts.push(value.slice(start));
  return parts;
}

/**
 * Split `A/B` at its only top-level slash, unwrapping a parenthesised side.
 *
 * Returns null when there is no top-level slash, and refuses more than one:
 * nested fractions need a traversal this planner does not yet do.
 */
function splitFraction(answer) {
  let depth = 0;
  let position = -1;
  for (let index = 0; index < answer.length; index += 1) {
    const character = answer[index];
    if (character === "(") {
      depth += 1;
    } else if (character === ")") {
      depth -= 1;
    } else if (character === "/" && depth === 0) {
      if (position !== -1) {
        return null;
      }
      position = index;
    }
  }
  if (position === -1) {
    return null;
  }
  return {
    numerator: unwrap(answer.slice(0, position)),
    denominator: unwrap(answer.slice(position + 1)),
  };
}

/** Strip one fully-enclosing pair of parentheses. */
function unwrap(value) {
  if (!value.startsWith("(") || !value.endsWith(")")) {
    return value;
  }
  let depth = 0;
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] === "(") {
      depth += 1;
    } else if (value[index] === ")") {
      depth -= 1;
      if (depth === 0 && index !== value.length - 1) {
        return value;
      }
    }
  }
  return value.slice(1, -1);
}

/**
 * The characters one slot of the editor will take.
 *
 * Slots differ: on lesson 1.2 question 14 the base took `0123456789y` while
 * both halves of a fraction took digits only. A question that publishes no set
 * for a slot falls back to the base's, which is how this behaved throughout.
 */
function slotCharacters(editor, slot) {
  const published = editor?.slots?.[slot];
  if (typeof published === "string" && published.length > 0) {
    return published;
  }
  return editor?.allowedCharacters ?? "";
}

/**
 * Plan one run of characters and exponents, with no fraction in it.
 *
 * @param {string} answer
 * @param {{allowedCharacters?: string, templates?: {exponent?: boolean}}} editor
 * @param {string} [slot] which slot the run is typed into
 * @returns {{ok: true, steps: Step[]} | {ok: false, code: string, detail?: string}}
 */
function planRun(answer, editor, slot = "base") {
  if (answer.length === 0) {
    return { ok: false, code: "answer-empty" };
  }
  const allowed = slotCharacters(editor, slot);
  const exponentAllowed = editor?.templates?.exponent === true;
  const steps = [];
  let base = "";
  let index = 0;

  /** Flush pending base characters as one typing step. */
  const flush = () => {
    if (base.length > 0) {
      steps.push({ op: "type", text: base });
      base = "";
    }
  };

  while (index < answer.length) {
    const character = answer[index];

    if (character === "^") {
      if (!exponentAllowed) {
        return { ok: false, code: "template-refused-by-question", detail: "exponent" };
      }
      // The template attaches to whatever precedes it, so that has to be typed
      // first and must exist.
      if (base.length === 0) {
        return { ok: false, code: "exponent-without-base" };
      }
      flush();
      const exponent = readExponent(answer, index + 1);
      if (exponent === null) {
        return { ok: false, code: "exponent-not-understood" };
      }
      steps.push({ op: "template", name: "Exponent" });
      if (exponent.denominator !== undefined) {
        // A rational exponent is a fraction built inside the exponent box.
        // Fraction loads on an empty box and focuses the numerator, so no
        // base is typed first here.
        if (editor?.templates?.fraction !== true) {
          return { ok: false, code: "template-refused-by-question", detail: "fraction" };
        }
        steps.push({ op: "template", name: "Fraction" });
        steps.push({ op: "type", text: exponent.text });
        steps.push({ op: "slot", name: "denominator" });
        steps.push({ op: "type", text: exponent.denominator });
      } else {
        steps.push({ op: "type", text: exponent.text });
      }
      // Pressing a template also creates a continuation base; later characters
      // belong there, not inside the exponent.
      index = exponent.next;
      if (index < answer.length) {
        steps.push({ op: "base" });
      }
      continue;
    }

    if (character === "(") {
      if (editor?.templates?.parentheses !== true) {
        return { ok: false, code: "template-refused-by-question", detail: "parentheses" };
      }
      const group = readGroup(answer, index);
      if (group === null) {
        return { ok: false, code: "parentheses-not-understood" };
      }
      const inner = planRun(group.text, editor, slot);
      if (inner.ok === false) {
        return inner;
      }
      // The group attaches after the pending outer factor, so finish that
      // factor before loading Hawkes's parenthesis template.
      flush();
      steps.push({ op: "template", name: "PBrace" }, ...inner.steps);
      index = group.next;
      if (index < answer.length) {
        steps.push({ op: "base" });
      }
      continue;
    }

    if (character === ")") {
      return { ok: false, code: "parentheses-not-understood" };
    }

    if (character === "|") {
      if (editor?.templates?.absoluteValue !== true) {
        return { ok: false, code: "answer-needs-absolute-value", detail: "|" };
      }
      // `Mod` is one of the editor's parentheses: it loads on an empty box and
      // focuses inside the bars, so anything typed so far is flushed first and
      // stands to the left of them.
      flush();
      const inside = readBars(answer, index + 1);
      if (inside === null) {
        return { ok: false, code: "absolute-value-not-understood" };
      }
      const inner = planRun(inside.text, editor);
      if (inner.ok === false) {
        return inner;
      }
      steps.push({ op: "template", name: "Mod" });
      steps.push(...inner.steps);
      index = inside.next;
      if (index < answer.length) {
        steps.push({ op: "base" });
      }
      continue;
    }

    const root = readRadicalSign(answer, index);
    if (root !== null) {
      if (editor?.templates?.radical !== true) {
        return { ok: false, code: "template-refused-by-question", detail: "radical" };
      }
      // Radical loads on an empty box and focuses inside, so anything typed so
      // far is flushed first and becomes what precedes the sign.
      flush();
      const radicand = readGroup(answer, root.next);
      if (radicand === null) {
        return { ok: false, code: "radical-not-understood" };
      }
      const inner = planRun(radicand.text, editor, "radicand");
      if (inner.ok === false) {
        return inner;
      }
      if (root.index === "2") {
        steps.push({ op: "template", name: "Radical" });
      } else {
        // An indexed radical is the same loader with its index box asked for.
        // It focuses the index first and offers the radicand as its next slot,
        // which is the order the executor walks its slots in.
        steps.push({ op: "template", name: "IndexedRadical" });
        steps.push({ op: "type", text: root.index });
        steps.push({ op: "base" });
      }
      steps.push(...inner.steps);
      index = radicand.next;
      if (index < answer.length) {
        steps.push({ op: "base" });
      }
      continue;
    }

    if (allowed.length > 0 && !accepts(allowed, character, editor?.kind)) {
      return {
        ok: false,
        code: "answer-has-rejected-characters",
        detail: character,
      };
    }
    base += character;
    index += 1;
  }

  flush();
  return { ok: true, steps };
}

/**
 * Read the exponent that follows a `^`.
 *
 * Understands a digit run, optionally negative and optionally parenthesised,
 * and a rational exponent such as `(3/2)` — the form a "convert to rational
 * exponent notation" question asks for. Anything richer is declined rather
 * than mis-entered.
 *
 * @returns {{text: string, denominator?: string, next: number} | null}
 */
function readExponent(answer, start) {
  let cursor = start;
  let wrapped = false;
  if (answer[cursor] === "(") {
    wrapped = true;
    cursor += 1;
  }

  const numerator = readSignedDigits(answer, cursor);
  if (numerator === null) {
    return null;
  }
  cursor = numerator.next;

  let denominator;
  if (answer[cursor] === "/") {
    const lower = readSignedDigits(answer, cursor + 1);
    if (lower === null) {
      return null;
    }
    denominator = lower.text;
    cursor = lower.next;
  }

  if (wrapped) {
    if (answer[cursor] !== ")") {
      return null;
    }
    cursor += 1;
  }
  return denominator === undefined
    ? { text: numerator.text, next: cursor }
    : { text: numerator.text, denominator, next: cursor };
}

/**
 * Read what a radical sign applies to: a parenthesised group, or the single
 * token that follows it.
 */
/**
 * Read what sits between a pair of absolute-value bars.
 *
 * The bars are the same character at both ends, so there is no nesting to
 * count: the group ends at the next bar. `|y|^5` gives `y`, and `next` points
 * just past the closing bar, at the `^`.
 */
function readBars(answer, start) {
  const close = answer.indexOf("|", start);
  if (close === -1 || close === start) {
    return null;
  }
  return { text: answer.slice(start, close), next: close + 1 };
}

/**
 * Read a radical sign and the index it carries.
 *
 * The solver writes the index into the sign itself: `√` is two, `∛` three,
 * `∜` four, and anything higher is a superscript digit before the sign, as in
 * `⁵√`. Returns null when there is no radical here.
 */
function readRadicalSign(answer, start) {
  const fixed = { "√": "2", "∛": "3", "∜": "4" };
  const here = answer[start];
  if (fixed[here] !== undefined) {
    return { index: fixed[here], next: start + 1 };
  }
  const superscripts = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  let cursor = start;
  let digits = "";
  while (cursor < answer.length && superscripts.includes(answer[cursor])) {
    digits += String(superscripts.indexOf(answer[cursor]));
    cursor += 1;
  }
  if (digits.length > 0 && answer[cursor] === "√") {
    return { index: digits, next: cursor + 1 };
  }
  return null;
}

function readGroup(answer, start) {
  if (answer[start] !== "(") {
    let cursor = start;
    let text = "";
    while (cursor < answer.length && /[0-9A-Za-z]/.test(answer[cursor])) {
      text += answer[cursor];
      cursor += 1;
    }
    return text.length === 0 ? null : { text, next: cursor };
  }
  let depth = 0;
  for (let cursor = start; cursor < answer.length; cursor += 1) {
    if (answer[cursor] === "(") {
      depth += 1;
    } else if (answer[cursor] === ")") {
      depth -= 1;
      if (depth === 0) {
        return { text: answer.slice(start + 1, cursor), next: cursor + 1 };
      }
    }
  }
  return null;
}

/** Read an optionally negative run of digits. */
function readSignedDigits(answer, start) {
  let cursor = start;
  let text = "";
  if (answer[cursor] === "-") {
    text += "-";
    cursor += 1;
  }
  while (cursor < answer.length && answer[cursor] >= "0" && answer[cursor] <= "9") {
    text += answer[cursor];
    cursor += 1;
  }
  if (text.length === 0 || text === "-") {
    return null;
  }
  return { text, next: cursor };
}
