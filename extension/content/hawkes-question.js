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
    'input.qbaseCSS, input[id^="txtAns"], input.boxStyle, input[id$="_optchk"]';

  const visible = (element) => {
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  };

  /** Where the answer area begins; mathematics below it is not the question. */
  const answerTop = () => {
    const tops = [...document.querySelectorAll(ANSWER_CONTROLS)]
      .filter(visible)
      .map((element) => element.getBoundingClientRect().top);
    return tops.length > 0 ? Math.min(...tops) : Number.POSITIVE_INFINITY;
  };

  const limit = answerTop();

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

  /** The instruction, which is prose above the answer area. */
  const promptText = [...document.querySelectorAll("p, div, span, td")]
    .filter((element) => {
      if (!visible(element) || element.getBoundingClientRect().top >= limit) {
        return false;
      }
      if (element.querySelector("p, div, table")) {
        return false;   // a container, not the sentence itself
      }
      const text = (element.textContent || "").trim();
      return (
        text.length > 20
        && text.length < 400
        && /simplify|evaluate|determine|convert|factor|express|rationaliz|find|add|subtract|multiply|expand/i.test(text)
      );
    })
    .map((element) => element.textContent.trim())
    .slice(0, 1)
    .join(" ");

  return { promptText, expressions };
})();
