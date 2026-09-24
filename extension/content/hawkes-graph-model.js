"use strict";

/**
 * Read one labeled Cartesian point from Hawkes' page-owned question model.
 *
 * Some Hawkes graph families keep their authoritative `<graph>` description
 * in `questionPartViewModel.questionGraphHTML` and render the visible graph
 * outside `#partInformation`.  This script runs in Firefox's MAIN world only
 * after the ordinary DOM/SVG reader found no usable graph.  It returns a
 * bounded normalized point or a named verdict; no model object or coursework
 * markup crosses back to the extension.
 */
(() => {
  const unavailable = (reason) => ({
    graphReason: reason,
    graphQuestion: "labeled-point",
    graphDecision: "unavailable",
  });
  const ambiguous = (reason) => ({
    graphReason: reason,
    graphQuestion: "labeled-point",
    graphDecision: "ambiguous",
  });
  const cleanText = (value) => String(value ?? "")
    .replace(/^\s*<!\[CDATA\[/, "")
    .replace(/\]\]>\s*$/, "")
    .trim();
  const htmlText = (value) => {
    const parsed = new DOMParser().parseFromString(String(value ?? ""), "text/html");
    return String(parsed.body?.textContent ?? "").replace(/\s+/g, " ").trim();
  };
  const exactNumber = (node) => {
    const raw = cleanText(node?.textContent);
    if (!/^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(raw)) return null;
    const number = Number(raw);
    return Number.isFinite(number) ? { raw, number } : null;
  };
  const named = (root, name) => root.querySelector(name);
  const readOwned = (value) => {
    if (typeof value !== "function") return value;
    try {
      return window.ko?.isObservable?.(value) ? value() : null;
    } catch {
      return null;
    }
  };

  const view = window.questionPartViewModel;
  if (!view || typeof view !== "object") return unavailable("question-model-missing");
  const instruction = htmlText(readOwned(view.partDescription));
  const coordinateRequest = (
    /\b(?:identify|find|determine|give|state|read|what\s+are)\b[^.?!]{0,200}\bcoordinates?\s+of\s+(?:the\s+)?(?:labeled\s+)?point\s+([^\s.,;:!?()[\]{}]{1,16})(?=\s|[.,;:!?]|$)/i.exec(instruction)
    || /\b(?:identify|find|determine|give|state|read|what\s+are)\b[^.?!]{0,200}\bpoint\s+([^\s.,;:!?()[\]{}'’]{1,16})(?:['’]s)?\s+coordinates?\b/i.exec(instruction)
  );
  if (!coordinateRequest) return unavailable("question-model-not-labeled-point");

  const source = readOwned(view.questionGraphHTML);
  if (typeof source !== "string" || source.length === 0 || source.length > 200000) {
    return unavailable("question-graph-model-missing");
  }
  const model = new DOMParser().parseFromString(source, "text/html");
  const graph = model.querySelector("graph");
  if (!graph || cleanText(named(graph, "isqagraph")?.textContent).toLowerCase() !== "true") {
    return unavailable("question-graph-model-invalid");
  }
  const cartesian = named(graph, "grid > cartesian");
  const xmin = exactNumber(named(cartesian, "xmin"));
  const xmax = exactNumber(named(cartesian, "xmax"));
  const ymin = exactNumber(named(cartesian, "ymin"));
  const ymax = exactNumber(named(cartesian, "ymax"));
  const xinterval = exactNumber(named(cartesian, "xinterval"));
  const yinterval = exactNumber(named(cartesian, "yinterval"));
  if (![xmin, xmax, ymin, ymax, xinterval, yinterval].every(Boolean)) {
    return unavailable("question-graph-scale-missing");
  }
  if (
    xmin.number >= xmax.number || ymin.number >= ymax.number
    || xinterval.number <= 0 || yinterval.number <= 0
  ) {
    return ambiguous("question-graph-scale-invalid");
  }
  if (xmin.number > 0 || xmax.number < 0 || ymin.number > 0 || ymax.number < 0) {
    return ambiguous("question-graph-origin-missing");
  }

  const target = coordinateRequest[1];
  const candidates = [...graph.querySelectorAll("graphobjects > point")].filter((point) => {
    // In HTML parsing, the custom `<label>` wrapper can acquire native form
    // semantics. The text script is the model's actual label owner and is
    // unambiguous within one `<point>`.
    const label = cleanText(named(point, "script[type='text']")?.textContent);
    return label === target;
  });
  if (candidates.length === 0) return unavailable("question-model-label-missing");
  if (candidates.length !== 1) return ambiguous(`question-model-label-count-${candidates.length}`);
  const point = candidates[0];
  const type = cleanText(named(point, "type")?.textContent).toLowerCase();
  const coordinates = cleanText(named(point, "coordinatestype")?.textContent).toLowerCase();
  const visible = cleanText(named(point, "visible")?.textContent).toLowerCase();
  const showLabel = cleanText(named(point, "showlabel")?.textContent).toLowerCase();
  if (type !== "point" || coordinates !== "cartesian") {
    return ambiguous("question-model-point-kind-invalid");
  }
  if (visible !== "true" || showLabel !== "true") {
    return ambiguous("question-model-point-not-visible");
  }
  const x = exactNumber(named(point, "x"));
  const y = exactNumber(named(point, "y"));
  if (!x || !y) return unavailable("question-model-point-geometry-missing");
  if (
    x.number < xmin.number || x.number > xmax.number
    || y.number < ymin.number || y.number > ymax.number
  ) {
    return ambiguous("question-model-point-out-of-bounds");
  }
  const onGrid = (value, interval) =>
    Math.abs(value / interval - Math.round(value / interval)) < 1e-9;
  if (!onGrid(x.number, xinterval.number) || !onGrid(y.number, yinterval.number)) {
    return ambiguous("question-model-point-off-grid");
  }
  const normalized = (value) => value.number === 0 ? "0" : value.raw;
  return {
    labeledPoint: {
      label: target, x: normalized(x), y: normalized(y), reading: "page-model",
    },
    graphReason: "",
    graphQuestion: "labeled-point",
    graphDecision: "accepted",
    graphReading: "page-model",
  };
})();
