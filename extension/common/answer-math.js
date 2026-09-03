"use strict";

/**
 * The answer, laid out as mathematics rather than as the string that carried it.
 *
 * An answer travels between the host, the event page and the panel as one line
 * of text: `\frac{z^4|y^5|}{3}`, `-x^13 + 2x^12`, `y^(3/2)`. That is a
 * transport encoding. Shown to a person it reads as neither what Hawkes
 * renders nor what they must type, and the owner of this add-on said so
 * plainly -- that the card was "useless" and "sometimes confusing on what the
 * answer really needs to be".
 *
 * This turns that line into a tree the panel can draw with real superscripts,
 * fraction bars, radical signs and bars. It is DOM-free on purpose, exactly as
 * `panel-view.js` is: the layout decisions are made here where the test suite
 * can run them, and `popup.js` is left with element creation.
 *
 * Nothing here changes the answer. What is copied, inserted, and checked is
 * still the same string; only its presentation is built.
 */

/** Radical signs, and the index each one carries. */
const ROOTS = { "√": "", "∛": "3", "∜": "4" };

/** Characters that end a bare run of text. */
const BREAKS = new Set(["^", "|", "√", "∛", "∜", "\\"]);

/**
 * Lay one answer out.
 *
 * @param {string} text the readable answer, as the panel would otherwise show
 * @returns {{kind: "row", items: object[]}} always a row, possibly empty
 */
export function layoutAnswer(text) {
  if (typeof text !== "string" || text.length === 0) {
    return { kind: "row", items: [] };
  }
  const reader = { text, at: 0 };
  const row = readRow(reader, null);
  return row;
}

/**
 * Read items until `closer`, or to the end when there is none.
 *
 * Unbalanced input stops rather than throwing. A malformed answer must still
 * be shown -- falling back to plain text is the panel's job, and it cannot do
 * that if this raises.
 */
function readRow(reader, closer) {
  const items = [];
  while (reader.at < reader.text.length) {
    const char = reader.text[reader.at];
    if (closer !== null && char === closer) {
      break;
    }
    if (char === "^") {
      reader.at += 1;
      items.push({ kind: "sup", exponent: readArgument(reader) });
      continue;
    }
    if (char === "|") {
      reader.at += 1;
      const body = readRow(reader, "|");
      if (reader.text[reader.at] === "|") {
        reader.at += 1;
      }
      items.push({ kind: "abs", body });
      continue;
    }
    if (char in ROOTS) {
      reader.at += 1;
      items.push({ kind: "radical", index: ROOTS[char], radicand: readArgument(reader) });
      continue;
    }
    if (reader.text.startsWith("\\frac{", reader.at)) {
      reader.at += "\\frac".length;
      const numerator = readBraced(reader);
      const denominator = readBraced(reader);
      items.push({ kind: "frac", numerator, denominator });
      continue;
    }
    const run = readPlain(reader, closer);
    if (run === "") {
      // Nothing consumed: an unhandled character. Take it literally rather
      // than spin, so an answer this does not understand still appears.
      items.push({ kind: "text", text: char });
      reader.at += 1;
      continue;
    }
    items.push({ kind: "text", text: run });
  }
  return { kind: "row", items };
}

/**
 * What an exponent or a radical applies to.
 *
 * A parenthesised group takes the whole group; otherwise it is the shortest
 * conventional thing -- one run of letters and digits. `x^13` raises thirteen,
 * `y^(3/2)` raises the fraction, and `√30y` is the root of thirty times y,
 * which is why the bare form stops at the end of the run and not at the end of
 * the line.
 */
function readArgument(reader) {
  if (reader.text[reader.at] === "(") {
    reader.at += 1;
    const inner = readRow(reader, ")");
    if (reader.text[reader.at] === ")") {
      reader.at += 1;
    }
    return inner;
  }
  const start = reader.at;
  if (reader.text[reader.at] === "-") {
    reader.at += 1;
  }
  while (reader.at < reader.text.length && /[A-Za-z0-9.]/.test(reader.text[reader.at])) {
    reader.at += 1;
  }
  const literal = reader.text.slice(start, reader.at);
  return { kind: "row", items: literal ? [{ kind: "text", text: literal }] : [] };
}

/** Read one `{...}` group, allowing nesting. */
function readBraced(reader) {
  if (reader.text[reader.at] !== "{") {
    return { kind: "row", items: [] };
  }
  reader.at += 1;
  const inner = readRow(reader, "}");
  if (reader.text[reader.at] === "}") {
    reader.at += 1;
  }
  return inner;
}

/** A run of ordinary characters, up to the next thing with structure. */
function readPlain(reader, closer) {
  const start = reader.at;
  while (reader.at < reader.text.length) {
    const char = reader.text[reader.at];
    if (char === closer || BREAKS.has(char)) {
      break;
    }
    reader.at += 1;
  }
  return reader.text.slice(start, reader.at);
}

/**
 * Whether laying this out would show anything a plain string does not.
 *
 * An answer with no structure -- `13`, `Not a Real Number` -- gains nothing
 * from being built out of elements, and the panel keeps its simpler path.
 */
export function hasStructure(text) {
  const row = layoutAnswer(text);
  return row.items.some((item) => item.kind !== "text");
}
