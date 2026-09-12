"use strict";

/**
 * Values shared by the popup and the preferences page.
 *
 * The content script deliberately does not import this module: it is injected
 * as a classic script and repeats its own, stricter guards so that a bug in an
 * extension page can never widen what reaches the Hawkes editor.
 */

/** The only host this add-on ever acts on, compared against the active tab. */
export const ALLOWED_HOSTNAME = "learn.hawkeslearning.com";
export const ALLOWED_HOST_PATTERN = "*://learn.hawkeslearning.com/*";

/** Upper bound on an answer, matching the content script's own limit. */
export const MAX_ANSWER_LENGTH = 40;

/**
 * How many separate values one question may ask for.
 *
 * This was four, sized for the shape it was written against: `x = ___ or ___`,
 * and a quartic's four roots behind it. Lesson 2.1 completes a table for
 * `x = y²` with five blank cells, and five is what every gate between the page
 * and Facet then refused -- silently, each one falling back to "one box".
 * Live, the DOM sweep counted the five boxes and reported no ids for them, the
 * page's own editor model declined to call five controls a multi-control
 * answer, and the question was sent as a single field. Facet answered the
 * single field it was asked about, exactly, and one number came back for a
 * five-part question.
 *
 * Raised to the shape the page actually publishes and no further. A question
 * with more parts than this is still refused rather than half-answered, which
 * is the behaviour that made this diagnosable at all.
 */
export const MAX_ANSWER_PARTS = 5;

/**
 * Characters an answer may contain. Plain mathematical notation only: no
 * angle brackets, quotes, backslashes, braces, or semicolons, so a stored
 * value cannot be mistaken for markup or code anywhere downstream.
 *
 * The equals sign is here because some answers are equations. "Find the
 * equation of the line in slope-intercept form" is answered with `y = -2x + 5`
 * and a bare Hawkes box takes exactly that -- its own keypad publishes `=` as
 * one of the characters it accepts. Refusing it here withheld the answer
 * before the page's own rules were ever consulted, which is the wrong place to
 * decide it: what may reach a particular answer box is `allowedCharacters`,
 * per question, and this is only the shape every answer has to have.
 *
 */
const ANSWER_PATTERN = /^[0-9A-Za-z+\-*/^().,=√π ]+$/;

/**
 * The same shape, widened by interval notation and nothing else.
 *
 * Here for the reason the equals sign is. "Express your answer in interval
 * notation" is answered `(-8,7]` or `[2.5,∞)`, and lesson 1.7's box publishes
 * `∞` and `∅` as characters and its brackets as keypad templates. Refusing
 * `]`, `∞` or `∅` here withheld a correct interval before the page was ever
 * asked. `∪` joins two intervals and is one of Hawkes' own special characters
 * (`symUnion`); whether a particular box takes it is, again, that box's
 * published set.
 *
 * Kept apart from `ANSWER_PATTERN` rather than folded into it, because that
 * pattern is also the stricter guard the self-contained table and
 * contenteditable writers carry, and neither of them enters an interval.
 * Square brackets are admitted only as interval ends -- see
 * `bracketsAreIntervals` -- so no answer gains a delimiter it could use as
 * anything but mathematics.
 */
const INTERVAL_PATTERN = /^[0-9A-Za-z+\-*/^().,=√π \[\]∞∅∪]+$/;

/**
 * Whether every bracket in an answer closes, and every square one is an
 * interval's end.
 *
 * Round and square brackets are counted as one family, because an interval's
 * two ends may be one of each: `(a,b]`. A square bracket is otherwise no part
 * of the notation any answer is written in, so a group it opens or closes must
 * hold exactly two endpoints -- one top-level comma -- or it is not an interval
 * and is refused.
 */
function bracketsAreIntervals(text) {
  const open = [];
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    if (character === "(" || character === "[") {
      open.push({ at: index, commas: 0 });
    } else if (character === "," && open.length > 0) {
      open[open.length - 1].commas += 1;
    } else if (character === ")" || character === "]") {
      const group = open.pop();
      if (group === undefined) {
        return false;
      }
      const square = text[group.at] === "[" || character === "]";
      if (square && group.commas !== 1) {
        return false;
      }
    }
  }
  return open.length === 0;
}

/**
 * One answer written as mathematics, rather than as the spelling it arrived in.
 *
 * The host's machine form is deliberately explicit: on a wire `sqrt101` cannot
 * be misread, and `sqrt(30)*y` cannot be mistaken for `sqrt(30y)`. It is not a
 * form to show a person, and it is not one any Hawkes answer box will take.
 * The distance question publishes `0123456789-` and a Radical template, so the
 * letters of `sqrt` are refused one at a time.
 *
 * Live, on 2026-09-07, `√101` -- solved exactly -- reached the panel as
 * `sqrt101`, and the panel said "this question's answer box does not accept:
 * s". Both the reading a person sees and the plan the keypad is driven from
 * need the same conversion, so it is made once, here, and neither of them
 * carries a copy of it.
 *
 * Nothing about the answer changes. The radicand is the same number, and what
 * is inserted is still built from the editor's own templates.
 */
export function mathNotation(value) {
  if (typeof value !== "string") {
    return "";
  }
  let text = value;
  for (let pass = 0; pass < 3; pass += 1) {
    text = text
      // A bracketed radicand, which is how a compound one always arrives.
      .replace(/\bsqrt\(([^()]*)\)/g, "√($1)")
      .replace(/\bcbrt\(([^()]*)\)/g, "∛($1)")
      // And a bare numeric one, which needs no bracket and is written without
      // it: `sqrt101` is `√101` and is one radical over one number.
      .replace(/\bsqrt(\d+(?:\.\d+)?)/g, "√$1")
      .replace(/\bcbrt(\d+(?:\.\d+)?)/g, "∛$1")
      // A radicand that is one plain number or one symbol is written without
      // a bracket, because that is how it is written: `√101`, not `√(101)`.
      // The exact solvers return SymPy's own `sqrt(101)`, and the bracket is
      // that notation's, not the mathematics'. Anything compound keeps it --
      // `√(2x)` means something `√2x` does not.
      .replace(/([√∛∜])\((\d+(?:\.\d+)?|[A-Za-z])\)/g, "$1$2");
  }
  return text;
}

/** How much readable notation the answer card will carry. */
export const MAX_DISPLAY_LENGTH = 120;
/**
 * How many words of English an answer may be before it is prose.
 *
 * Three, which is the longest named answer there is: "Not a Real Number" --
 * "a" is one letter and is not one of them. Set against what has to be refused
 * rather than against a round number: Facet's own "answer number 1 by itself"
 * is four words, and the sentence that reached a live card is eight. Facet
 * holds the same bound on its own side, in `facet_runtime.solve.answer_shaped`.
 */
export const MAX_ANSWER_WORDS = 3;


/**
 * Whether a readable form may be put on the answer card.
 *
 * The card shows the readable form rather than the machine one, and that is
 * deliberate: it may legitimately carry notation no answer box would take, a
 * radical sign or a fraction bar. What it must never carry is text that is
 * not an answer at all.
 *
 * Facet builds its model contract out of English sentences, and a model that
 * echoes one back instead of answering hands that sentence over as the answer.
 * That is how "all answers as they would ordinarily be written" reached a live
 * card on a quadrant question.
 *
 * The rule is about shape, not about any particular sentence, because no list
 * of phrases to refuse survives the next rewording of the prompt. What makes
 * prompt text recognisable is that it is made of words at all: an answer is
 * written in mathematics, and where it names itself instead -- "Not a Real
 * Number", "All Real Numbers" -- it does so in a few words, because those are
 * names. Three of them is the longest Hawkes asks for.
 *
 * The first version of this rule accepted anything containing a digit or an
 * operator, which is most of a contract: "Reply with exactly 3 lines and
 * nothing else" carries a digit and would have passed. Words are counted now,
 * and nothing else about the text can buy its way past them.
 */
export function displayableAnswer(text) {
  if (typeof text !== "string") {
    return false;
  }
  const trimmed = text.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_DISPLAY_LENGTH) {
    return false;
  }
  const words = trimmed.split(/\s+/).filter((word) => /^[A-Za-z]{2,}$/.test(word));
  return words.length <= MAX_ANSWER_WORDS;
}


/**
 * Validate a candidate answer.
 *
 * @param {unknown} value
 * @returns {{ok: true, value: string} | {ok: false, code: string}}
 */
export function validateAnswer(value) {
  if (typeof value !== "string") {
    return { ok: false, code: "answer-invalid" };
  }
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > MAX_ANSWER_LENGTH) {
    return { ok: false, code: "answer-invalid" };
  }
  if (ANSWER_PATTERN.test(trimmed)) {
    return { ok: true, value: trimmed };
  }
  // Interval notation, and only as intervals. Unbalanced round brackets were
  // admitted by the pattern above and are still left for the planner to refuse
  // by name; a square bracket is new here, so it has to close an interval.
  if (!INTERVAL_PATTERN.test(trimmed) || !bracketsAreIntervals(trimmed)) {
    return { ok: false, code: "answer-invalid" };
  }
  return { ok: true, value: trimmed };
}
