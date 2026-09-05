"use strict";

/**
 * Read the question from the page instead of photographing it.
 *
 * Hawkes renders with MathJax, which leaves the expression in the document as
 * presentation MathML. Taking that is exact and free, and skips the two
 * independent image transcriptions that are otherwise almost the whole of a
 * solve. It also removes an error class outright: nothing can misread an
 * exponent that was never rendered to pixels.
 *
 * Only mathematics *above* the answer controls is taken. The answer area has
 * MathML of its own — whatever has been entered so far — and including that
 * would feed the add-on's own output back in as part of the question.
 *
 * Returns whatever it can. An empty result is not a failure; the caller falls
 * back to a screenshot.
 */

(() => {
  const ANSWER_CONTROLS =
    'input.qbaseCSS, input[id^="txtAns"], input.boxStyle, input[id$="_optchk"], '
    + 'input[type="radio"].opt, #QGraph[role="application"]';

  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  /** Where the answer area begins; mathematics below it is not the question. */
  const answerTop = () => {
    const tops = [...document.querySelectorAll(ANSWER_CONTROLS)]
      .filter(visible)
      .filter((element) => !element.closest?.("#partInformation"))
      .map((element) => element.getBoundingClientRect().top);
    return tops.length > 0 ? Math.min(...tops) : Number.POSITIVE_INFINITY;
  };

  // A graph in the instruction is evidence, not an answer surface. Read only
  // the disabled scatter points; never infer values from screenshot pixels.
  const graphPoints = (() => {
    const parts = [...document.querySelectorAll("#partInformation")];
    if (parts.length !== 1 || !/quadratic regression/i.test(parts[0].textContent)) return null;
    const svgs = [...parts[0].querySelectorAll("svg")];
    if (svgs.length !== 1) return null;
    const svg = svgs[0];
    const points = [...svg.querySelectorAll("g.graph-objects > g.point.disable")];
    const axes = ["horizontal", "vertical"].map(axis => {
      const text = svg.querySelector(`g.${axis}-axis desc`)?.textContent ?? "";
      const match = text.match(/starts at (-?\d+), and ends at (-?\d+);/);
      return match ? [Number(match[1]), Number(match[2])] : null;
    });
    const grid = svg.querySelector("g.cartesian-grid");
    const rect = grid?.getBBox();
    if (points.length < 3 || points.length > 32 || axes.some(a => !a) || !rect) return null;
    const width = rect.width;
    const height = rect.height;
    if (!(width > 0 && height > 0)) return null;
    const result = [];
    for (const point of points) {
      const desc = point.querySelector("desc")?.textContent ?? "";
      const circle = point.querySelector("circle");
      const match = desc.match(/^A dot drawn (\d+) units? (left|right) of and (\d+) units? (above|below) the origin\.$/);
      if (!circle || !match || point.querySelector("a")) return null;
      const x = Number(match[1]) * (match[2] === "left" ? -1 : 1);
      const y = Number(match[3]) * (match[4] === "below" ? -1 : 1);
      const drawnX = axes[0][0] + Number(circle.getAttribute("cx")) * (axes[0][1]-axes[0][0]) / width;
      const drawnY = axes[1][1] - Number(circle.getAttribute("cy")) * (axes[1][1]-axes[1][0]) / height;
      if (Math.abs(drawnX-x) > 1e-9 || Math.abs(drawnY-y) > 1e-9) return null;
      result.push({ x: String(x), y: String(y) });
    }
    return result;
  })();

  const limit = answerTop();

  /**
   * The question's data table, read as a table.
   *
   * A word problem that carries its numbers in a table is stating them
   * exactly, in markup, with a heading over each column saying what the
   * quantity is. Reading that is the same kind of win as reading MathJax's
   * MathML instead of photographing it: nothing is transcribed, nothing is
   * measured off a picture, and the column headings survive -- which is what
   * lets the host say which column the question is a function of rather than
   * guessing from position.
   *
   * Read only when the shape is unambiguous. Hawkes lays parts of its page out
   * with tables too, so a table without a header row of its own is not treated
   * as data, and more than one candidate is refused rather than picked between.
   * Values are taken verbatim, currency and all: what "$56" means as a number
   * is the host's reading, not the page's.
   */
  const dataTable = (() => {
    const clean = (node) => (node.textContent || "").replace(/\s+/g, " ").trim();
    // The row that names the columns, or null. Two unambiguous declarations of
    // one are accepted -- a `thead`, or a first row made entirely of `th` --
    // and nothing else, because "the first row" of a table used for layout is
    // not a heading and reading it as one would rename the question's data.
    const headerRow = (table) => {
      const head = table.tHead;
      if (head !== null && head.rows.length > 0) {
        return head.rows[head.rows.length - 1];
      }
      const first = table.rows[0] ?? null;
      return first !== null
        && [...first.cells].every((cell) => cell.tagName === "TH")
        ? first
        : null;
    };
    const candidates = [...document.querySelectorAll("table")].filter(
      (table) =>
        visible(table)
        && table.getBoundingClientRect().top < limit
        && table.querySelector("table") === null
        && table.querySelector(ANSWER_CONTROLS) === null
        && table.rows.length <= 33
        && headerRow(table) !== null
    );
    if (candidates.length !== 1) return null;
    const table = candidates[0];
    const header = headerRow(table);
    const columns = [...header.cells].map(clean);
    const body = [...table.rows]
      .filter((row) => row !== header && !(table.tHead?.contains(row) ?? false))
      .map((row) => [...row.cells].map(clean));
    if (columns.length < 2 || columns.length > 8) return null;
    if (body.length < 2 || body.length > 32) return null;
    if (columns.some((name) => name.length === 0 || name.length > 80)) return null;
    if (body.some((row) => row.length !== columns.length)) return null;
    if (body.some((row) => row.some((cell) => cell.length === 0 || cell.length > 40))) {
      return null;
    }
    return { node: table, columns, rows: body };
  })();

  const expressions = [];
  for (const math of document.querySelectorAll("math")) {
    if (!visible(math) || math.getBoundingClientRect().top >= limit) {
      continue;
    }
    // Serialised, not cloned: reading the node is enough, and building a
    // stripped copy would mean creating and appending elements -- which the
    // build forbids in anything injected into the page, rightly. MathJax's
    // semantic attributes come along and are ignored by the converter.
    expressions.push(new XMLSerializer().serializeToString(math).slice(0, 40000));
    if (expressions.length >= 4) {
      break;
    }
  }

  /** Verbs that mark a line as the question's own instruction. */
  const INSTRUCTION =
    /graph|simplify|evaluate|determine|convert|factor|express|rationaliz|find|add|subtract|multiply|expand|identify|write|state|name|list|select|choose|arrange|round|solve/i;

  /** Prose above the answer area, in document order. */
  const lines = [...document.querySelectorAll("p, div, span, td")]
    .filter((element) => {
      if (!visible(element) || element.getBoundingClientRect().top >= limit) {
        return false;
      }
      // A cell of the data table is a quantity, not a sentence. It is read
      // exactly, as a table, and letting it back in here would put it up for
      // selection as the question's instruction as well.
      if (dataTable !== null && dataTable.node.contains(element)) {
        return false;
      }
      if (element.querySelector("p, div, table")) {
        return false;   // a container, not the sentence itself
      }
      const length = (element.textContent || "").trim().length;
      return length > 3 && length < 400;
    })
    .map((element) => element.textContent.trim());

  /**
   * Which step of a multi-step question this is.
   *
   * Hawkes keeps one prompt and one expression across every step of a question
   * and changes only this line. Read without it, steps 2 and 3 of lesson 1.3
   * question 7 were the same question: the same digest, so the watcher saw no
   * change and step 2's answer stayed on the card while step 3 sat empty.
   */
  const stepLines = lines.filter((text) => /step\s+\d+\s+of\s+\d+/i.test(text));
  // Hawkes prints "Step N of M" twice: once in the page header beside the
  // question number, and once at the head of the instruction itself. The
  // header comes first in the document and says nothing about what to do, so
  // taking it left the instruction to be found separately -- and when it was
  // missed, the page's radio-button boilerplate was picked up instead.
  const step = stepLines.find((text) => INSTRUCTION.test(text)) ?? stepLines[0] ?? "";

  /**
   * The instruction itself.
   *
   * The verb list is what decides whether the host is told the question at all;
   * anything it misses is sent as "Solve the question in the image", where no
   * exact operation can match and a model has to infer the task from a
   * picture. "Identify the leading coefficient" missed, which is how a
   * one-millisecond question became a minute of vision plus model.
   */
  // Long enough to be a sentence, and no longer. "Identify the degree." is
  // exactly twenty characters, so a `> 20` cutoff dropped it -- and the next
  // line carrying an accepted verb was Hawkes' own note about radio buttons,
  // which named no operation at all. The question then cost a screenshot the
  // sidebar had no permission to take, and reported that it could not be
  // captured, which was true and useless.
  const instruction = lines.find(
    (text) => text.length > 8 && INSTRUCTION.test(text)
  ) ?? "";

  // Formula questions put the target variable after the displayed equation,
  // on a separate line: "C = 2πr; solve for r."  The generic instruction
  // above only says "the indicated variable", which is not enough for an
  // exact solver to know which symbol to isolate.
  const target = lines
    .map((text) => text.match(/\bsolve\s+for\s+([A-Za-z])\b/i))
    .find((match) => match !== null);
  const qualifier = target ? `Solve for ${target[1]}.` : "";

  // One line when the step already carries the instruction, which is the usual
  // Hawkes markup; both when the step marker sits in its own element.
  let promptText = (
    step && instruction && step.includes(instruction)
      ? step
      : [step, instruction].filter((text) => text.length > 0).join(" ")
  );
  if (qualifier && !new RegExp(`\\bsolve\\s+for\\s+${target[1]}\\b`, "i").test(promptText)) {
    promptText = `${promptText} ${qualifier}`.trim();
  }
  if (graphPoints) {
    const part = document.querySelectorAll("#partInformation")[0];
    const description = part.querySelector("#partDescription");
    let graphContainer = description?.querySelector("svg");
    while (graphContainer && graphContainer.parentElement !== description) graphContainer = graphContainer.parentElement;
    if (!description || !graphContainer) return { promptText: "", expressions: [] };
    // The prose, without the table. Flattened into a sentence, a data table
    // becomes a run of bare numbers in the middle of the question: useless to
    // a solver, and long enough to push the sentence that says what to do past
    // the length limit below. The table is carried exactly and separately
    // instead, so the words and the numbers each stay what they are.
    const walker = document.createTreeWalker(description, NodeFilter.SHOW_TEXT);
    const spoken = [];
    for (let node = walker.nextNode(); node !== null; node = walker.nextNode()) {
      if (graphContainer.contains(node)) break;
      if (dataTable !== null && dataTable.node.contains(node)) continue;
      spoken.push(node.textContent);
    }
    promptText = [part.querySelector(".part_status")?.textContent, spoken.join(" ")]
      .join(" ").replace(/\s+/g, " ").trim();
  }
  // Long enough for a word problem. A truncated instruction is not a shorter
  // question, it is a different one: lesson 3.3's revenue question states the
  // situation, then the table, then -- last -- says to fit a quadratic
  // regression and maximize. Cut at 400 characters it asked nothing at all.
  promptText = promptText.slice(0, 1200);

  return {
    promptText,
    expressions,
    ...(graphPoints ? { graphPoints } : {}),
    // The node stays here. What crosses is the reading of the table.
    ...(dataTable
      ? { dataTable: { columns: dataTable.columns, rows: dataTable.rows } }
      : {}),
  };
})();
