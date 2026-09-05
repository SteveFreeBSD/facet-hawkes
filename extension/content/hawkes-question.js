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
    + 'input[type="radio"].opt';

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

  /** Verbs that mark a line as the question's own instruction. */
  const INSTRUCTION =
    /simplify|evaluate|determine|convert|factor|express|rationaliz|find|add|subtract|multiply|expand|identify|write|state|name|list|select|choose|arrange|round|solve/i;

  /** Prose above the answer area, in document order. */
  const lines = [...document.querySelectorAll("p, div, span, td")]
    .filter((element) => {
      if (!visible(element) || element.getBoundingClientRect().top >= limit) {
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
  promptText = promptText.slice(0, 400);

  return { promptText, expressions };
})();
