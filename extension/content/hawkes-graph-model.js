"use strict";

/**
 * Read exact Cartesian facts from Hawkes' page-owned question model.
 *
 * Hawkes can render the visible graph outside `#partInformation`, while its
 * authoritative `<graph>` remains in an observable on
 * `questionPartViewModel`. This MAIN-world reader normalizes that one model
 * for every supported labeled-point family. Only bounded coordinates and a
 * named verdict cross back to the extension; raw coursework markup does not.
 */
(() => {
  const result = (graphQuestion, graphDecision, graphReason, extra = {}) => ({
    ...extra, graphReason, graphQuestion, graphDecision,
  });
  const unavailable = (question, reason) => result(question, "unavailable", reason);
  const ambiguous = (question, reason) => result(question, "ambiguous", reason);
  const cleanText = (value) => String(value ?? "")
    .replace(/^\s*<!\[CDATA\[/, "")
    .replace(/\]\]>\s*$/, "")
    .trim();
  const htmlText = (value) => {
    const parsed = new DOMParser().parseFromString(String(value ?? ""), "text/html");
    return String(parsed.body?.textContent ?? "").replace(/\s+/g, " ").trim();
  };
  const gcd = (left, right) => {
    let a = left < 0n ? -left : left;
    let b = right < 0n ? -right : right;
    while (b !== 0n) [a, b] = [b, a % b];
    return a;
  };
  const exactNumber = (node) => {
    const raw = cleanText(node?.textContent);
    if (raw.length > 30 || !/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(raw)) return null;
    const number = Number(raw);
    if (!Number.isFinite(number)) return null;
    const negative = raw.startsWith("-");
    const unsigned = negative ? raw.slice(1) : raw;
    const [whole, decimals = ""] = unsigned.split(".");
    let numerator = BigInt(`${whole}${decimals}`);
    if (negative) numerator = -numerator;
    let denominator = 10n ** BigInt(decimals.length);
    const divisor = gcd(numerator, denominator);
    numerator /= divisor;
    denominator /= divisor;
    const exact = denominator === 1n ? String(numerator) : `${numerator}/${denominator}`;
    return {
      exact: numerator === 0n ? "0" : exact,
      numerator,
      denominator,
      number,
    };
  };
  const direct = (root, name) => [...(root?.children ?? [])]
    .find((child) => child.tagName.toLowerCase() === name) ?? null;
  const directText = (root, name) => cleanText(direct(root, name)?.textContent);
  const readOwned = (value) => {
    if (typeof value !== "function") return value;
    try {
      return window.ko?.isObservable?.(value) ? value() : null;
    } catch {
      return null;
    }
  };

  const view = window.questionPartViewModel;
  if (!view || typeof view !== "object") return unavailable("", "question-model-missing");
  const partSource = readOwned(view.partDescription);
  const instruction = htmlText(partSource);
  const coordinateRequest = (
    /\b(?:identify|find|determine|give|state|read|what\s+are)\b[^.?!]{0,200}\bcoordinates?\s+of\s+(?:the\s+)?(?:labeled\s+)?point\s+([^\s.,;:!?()[\]{}]{1,16})(?=\s|[.,;:!?]|$)/i.exec(instruction)
    || /\b(?:identify|find|determine|give|state|read|what\s+are)\b[^.?!]{0,200}\bpoint\s+([^\s.,;:!?()[\]{}'’]{1,16})(?:['’]s)?\s+coordinates?\b/i.exec(instruction)
  );
  const slopeRequest = /\b(?:find|determine|calculate|compute)\b[^.?!]{0,160}\bslope\b(?![-\s]?intercept)/i.test(instruction);
  const graphQuestion = coordinateRequest ? "labeled-point" : slopeRequest ? "line-slope" : "";
  if (!graphQuestion) return unavailable("", "question-model-not-supported");

  const graphHTML = readOwned(view.questionGraphHTML);
  const source = typeof graphHTML === "string" && /<graph\b/i.test(graphHTML)
    ? graphHTML
    : typeof partSource === "string" && /<graph\b/i.test(partSource)
      ? partSource
      : null;
  if (source === null || source.length === 0 || source.length > 200000) {
    return unavailable(graphQuestion, "question-graph-model-missing");
  }
  const model = new DOMParser().parseFromString(source, "text/html");
  const graphs = [...model.querySelectorAll("graph")];
  if (graphs.length !== 1) {
    return graphs.length > 1
      ? ambiguous(graphQuestion, `question-graph-count-${graphs.length}`)
      : unavailable(graphQuestion, "question-graph-model-invalid");
  }
  const graph = graphs[0];
  if (directText(graph, "isqagraph").toLowerCase() !== "true") {
    return unavailable(graphQuestion, "question-graph-model-invalid");
  }
  const grid = direct(graph, "grid");
  const cartesian = direct(grid, "cartesian");
  const xmin = exactNumber(direct(cartesian, "xmin"));
  const xmax = exactNumber(direct(cartesian, "xmax"));
  const ymin = exactNumber(direct(cartesian, "ymin"));
  const ymax = exactNumber(direct(cartesian, "ymax"));
  const xinterval = exactNumber(direct(cartesian, "xinterval"));
  const yinterval = exactNumber(direct(cartesian, "yinterval"));
  if (![xmin, xmax, ymin, ymax, xinterval, yinterval].every(Boolean)) {
    return unavailable(graphQuestion, "question-graph-scale-missing");
  }
  if (
    xmin.number >= xmax.number || ymin.number >= ymax.number
    || xinterval.number <= 0 || yinterval.number <= 0
  ) {
    return ambiguous(graphQuestion, "question-graph-scale-invalid");
  }
  if (xmin.number > 0 || xmax.number < 0 || ymin.number > 0 || ymax.number < 0) {
    return ambiguous(graphQuestion, "question-graph-origin-missing");
  }
  const objects = direct(graph, "graphobjects");
  if (!objects) return unavailable(graphQuestion, "question-graph-objects-missing");
  const onGrid = (value, interval) => (
    (value.numerator * interval.denominator)
    % (value.denominator * interval.numerator) === 0n
  );
  const labelOf = (point) => {
    const owner = direct(point, "label");
    const script = owner?.querySelector("script[type='text']");
    const label = cleanText(script?.textContent ?? owner?.textContent);
    return /^\S{1,16}$/.test(label) ? label : null;
  };
  const readPoint = (point) => {
    if (
      directText(point, "type").toLowerCase() !== "point"
      || directText(point, "coordinatestype").toLowerCase() !== "cartesian"
    ) return { reason: "question-model-point-kind-invalid" };
    if (
      directText(point, "visible").toLowerCase() !== "true"
      || directText(point, "showlabel").toLowerCase() !== "true"
    ) return { reason: "question-model-point-not-visible" };
    const label = labelOf(point);
    if (label === null) return { reason: "question-model-point-label-invalid" };
    const x = exactNumber(direct(point, "x"));
    const y = exactNumber(direct(point, "y"));
    if (!x || !y) return { reason: "question-model-point-geometry-missing" };
    if (
      x.number < xmin.number || x.number > xmax.number
      || y.number < ymin.number || y.number > ymax.number
    ) return { reason: "question-model-point-out-of-bounds" };
    if (!onGrid(x, xinterval) || !onGrid(y, yinterval)) {
      return { reason: "question-model-point-off-grid" };
    }
    return {
      point: { label, x: x.exact, y: y.exact, reading: "page-model" },
    };
  };

  if (graphQuestion === "labeled-point") {
    const target = coordinateRequest[1];
    const candidates = [...objects.children].filter((point) =>
      point.tagName.toLowerCase() === "point" && labelOf(point) === target
    );
    if (candidates.length === 0) return unavailable(graphQuestion, "question-model-label-missing");
    if (candidates.length !== 1) {
      return ambiguous(graphQuestion, `question-model-label-count-${candidates.length}`);
    }
    const read = readPoint(candidates[0]);
    if (!read.point) return ambiguous(graphQuestion, read.reason);
    return result(graphQuestion, "accepted", "", {
      labeledPoint: read.point, graphReading: "page-model",
    });
  }

  const lines = [...objects.children].filter((node) => node.tagName.toLowerCase() === "line");
  if (lines.length !== 1) return ambiguous(graphQuestion, `question-model-line-count-${lines.length}`);
  const line = lines[0];
  if (
    directText(line, "type").toLowerCase() !== "line"
    || directText(line, "visible").toLowerCase() !== "true"
    || directText(line, "definedby").toLowerCase() !== "twopoint"
  ) return ambiguous(graphQuestion, "question-model-line-kind-invalid");
  const owned = [...line.children].filter((node) => node.tagName.toLowerCase() === "point");
  if (owned.length !== 2) {
    return ambiguous(graphQuestion, `question-model-line-point-count-${owned.length}`);
  }
  const reads = owned.map(readPoint);
  const invalid = reads.find((read) => !read.point);
  if (invalid) return ambiguous(graphQuestion, invalid.reason);
  const linePoints = reads.map((read) => read.point);
  if (new Set(linePoints.map((point) => point.label)).size !== 2) {
    return ambiguous(graphQuestion, "question-model-line-labels-not-unique");
  }
  return result(graphQuestion, "accepted", "", {
    linePoints, graphReading: "page-model",
  });
})();
