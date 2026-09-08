"use strict";

/** One bounded MAIN-world operation. Reads Hawkes' model; writes only arrow/space
 * keyboard events to the three identified SVG point anchors. No page state is
 * installed. The plan is data, never code or prose. */
export function graphOperation(offered = null) {
  /**
   * Why this graph was refused, and what it actually is.
   *
   * `graph-family-unsupported` was the whole report, and it is true of a
   * scatter of points to plot, of a circle, of a line, and of a page whose
   * model this reader simply cannot walk. Live, on 2026-09-07, a question that
   * asks for four given points to be plotted reached here for the first time
   * and said only that -- which named no gap anybody could close.
   *
   * Titles, counts and flags the page publishes about its own graph. No point
   * coordinates, no question text: what a graph *is*, never what it holds or
   * what the student has put on it.
   */
  let seen = {};
  const note = (facts) => {
    seen = { ...seen, ...facts };
  };
  const refuse = (code) => ({ ok: false, code, found: seen });
  try {
    if (window.location.origin !== "https://learn.hawkeslearning.com") return refuse("wrong-site");
    const roots = [...document.querySelectorAll('#QGraph[role="application"]')];
    if (roots.length !== 1 || roots[0].getBoundingClientRect().width <= 0) return refuse("graph-missing");
    const root = roots[0];
    const plotRect = root.querySelector("svg defs clipPath rect");
    const renderedCurve = root.querySelector("svg g.parabola > path");
    note({
      plotRect: Boolean(plotRect),
      parabolaPath: Boolean(renderedCurve),
      // Every drawn group the graph has, by class, so a family with no
      // `g.parabola` at all says what it does have instead.
      groups: [...new Set([...root.querySelectorAll("svg g[class]")]
        .map((node) => String(node.getAttribute("class") ?? "").slice(0, 24)))]
        .slice(0, 12),
      anchorsAnywhere: root.querySelectorAll('a[draggable="true"][role="button"]').length,
    });
    if (!plotRect || !renderedCurve) return refuse("graph-renderer-unsupported");
    const plotWidth = Number(plotRect.getAttribute("width"));
    const plotHeight = Number(plotRect.getAttribute("height"));
    if (!(plotWidth > 0 && plotHeight > 0)) return refuse("graph-renderer-unsupported");
    const models = Object.values(window.quant_wp_UI?.controlsCollection ?? {});
    note({ models: models.length, isGraph: models[0]?.isGraph === true });
    if (models.length !== 1 || models[0].isGraph !== true) return refuse("graph-model-missing");
    const model = models[0];
    const objects = Object.values(model.allGraphObjects());
    note({
      objects: objects.length,
      // The page's own name for what it is drawing. This is the one fact that
      // says which graph question this is.
      titles: objects.map((one) => String(one?.title ?? "").slice(0, 32)).slice(0, 8),
      children: objects.map((one) =>
        Array.isArray(one?.children) ? one.children.length : -1).slice(0, 8),
      enabled: model.getEnableState() === true,
    });
    if (objects.length !== 1 || objects[0].title !== "Parabola") return refuse("graph-family-unsupported");
    const curve = objects[0];
    const points = curve.children;
    const names = ["Vertex", "Control Point 1", "Control Point 2"];
    const anchors = [...root.querySelectorAll('svg g.parabola g.point a[draggable="true"][role="button"]')];
    note({ points: points.length, anchors: anchors.length });
    if (points.length !== 3 || anchors.length !== 3) return refuse("graph-controls-unsupported");
    const titles = anchors.map(anchor => document.getElementById(anchor.getAttribute("aria-labelledby")));
    const circles = anchors.map(anchor => anchor.querySelector("circle"));
    const descriptions = anchors.map(anchor => document.getElementById(anchor.getAttribute("aria-describedby")));
    if (!points.every((p, i) => p.title === names[i] && titles[i]?.textContent === names[i]
      && circles[i] && descriptions[i] && p.plotted && p.visible && anchors[i].id)) return refuse("graph-controls-unsupported");
    const xml = new DOMParser().parseFromString(model.graphXML(), "application/xml");
    const value = selector => xml.querySelector(selector)?.textContent;
    if (value("grid > type") !== "cartesian" || value("parabola > orientation") !== "vertical"
      || value("parabola > definedby") !== "points") return refuse("graph-orientation-unsupported");
    const bounds = ["xmin", "xmax", "ymin", "ymax"].map(axisName => Number(value(`cartesian > ${axisName}`)));
    const snap = [points[0].snapX, points[0].snapY];
    if (![...bounds, ...snap].every(Number.isFinite) || !snap.every(n => n > 0)
      || !points.every(p => p.snapX === snap[0] && p.snapY === snap[1])) return refuse("graph-grid-unsupported");
    const questionNodes = ["questionDescription", "questionString", "partInformation"].map(id => document.getElementById(id));
    if (questionNodes.some(n => !n)) return refuse("graph-question-missing");
    const question = () => questionNodes.map(n => new XMLSerializer().serializeToString(n)).join("\u001f");
    const pointState = () => points.map((p, i) => ({ id: p.ID, anchor: anchors[i].id, x: p.x, y: p.y,
      cx: circles[i].getAttribute("cx"), cy: circles[i].getAttribute("cy"),
      transform: circles[i].getAttribute("transform"), description: descriptions[i].textContent }));
    const snapshot = () => {
      // Hawkes normalizes missing parabola coefficients as a side effect of
      // userAnswer().  Normalize before graphXML() so one observation cannot
      // make the next otherwise-identical ownership snapshot look stale.
      const answer = model.userAnswer();
      return { question: question(), xml: model.graphXML(), points: pointState(), answer };
    };
    const context = { family: "parabola", orientation: "vertical", bounds, snap, controls: "vertex-and-symmetric-points" };
    const initial = snapshot();
    const structure = () => model.graphXML().replace(/<(x|y)>[^<]*<\/\1>/g, "<$1/>");
    const initialStructure = structure();
    const initialTransform = renderedCurve.getAttribute("transform");
    if (!offered) return { ok: true, kind: "graph", code: "graph-described", enabled: model.getEnableState(), context, snapshot: initial };
    if (JSON.stringify(initial) !== JSON.stringify(offered.snapshot)) return refuse("graph-target-stale");
    const plan = offered.plan;
    const rational = s => {
      if (typeof s !== "string" || !/^-?(?:0|[1-9][0-9]*)(?:\/[1-9][0-9]*)?$/.test(s) || s.length > 30) throw Error("graph-plan-invalid");
      const [a, b = "1"] = s.split("/");
      const n = Number(a) / Number(b);
      if (!Number.isFinite(n)) throw Error("graph-plan-invalid");
      return n;
    };
    const keys = (o, keyList) => o && Object.keys(o).sort().join() === keyList.split(" ").sort().join();
    if (!keys(plan, "kind orientation opening vertex points") || plan.kind !== "parabola" || plan.orientation !== "vertical"
      || !["up", "down"].includes(plan.opening) || !Array.isArray(plan.points) || plan.points.length !== 2) return refuse("graph-plan-invalid");
    const desired = [plan.vertex, ...plan.points].map(p => {
      if (!keys(p, "x y")) throw Error("graph-plan-invalid");
      return [rational(p.x), rational(p.y)];
    });
    const [a, b, c] = offered.coefficients.map(rational);
    const [h, k] = desired[0];
    const close = (x, y) => Math.abs(x - y) < 1e-9;
    if (offered.coefficients.length !== 3 || !a || (a > 0 ? "up" : "down") !== plan.opening
      || !close(h, -b / (2 * a)) || !close(k, a*h*h+b*h+c)
      || desired[1][0] <= h || !close(desired[2][0], 2*h-desired[1][0])
      || !desired.every(([x, y]) => close(y, a*x*x+b*x+c))) return refuse("graph-plan-invalid");
    if (!desired.every(([x,y], i) => x >= bounds[0] && x <= bounds[1] && y >= bounds[2] && y <= bounds[3]
      && close((x-points[i].x)/snap[0], Math.round((x-points[i].x)/snap[0]))
      && close((y-points[i].y)/snap[1], Math.round((y-points[i].y)/snap[1])))) return refuse("graph-plan-off-grid");
    const maxSteps = desired.reduce((n, [x,y],i) => n+Math.abs((x-points[i].x)/snap[0])+Math.abs((y-points[i].y)/snap[1]),0);
    if (maxSteps > 160) return refuse("graph-plan-too-long");
    let expected = initial;
    const assertPinned = () => {
      if (structure() !== initialStructure || root.querySelector("svg defs clipPath rect") !== plotRect
        || root.querySelector("svg g.parabola > path") !== renderedCurve
        || renderedCurve.getAttribute("transform") !== initialTransform
        || Number(plotRect.getAttribute("width")) !== plotWidth || Number(plotRect.getAttribute("height")) !== plotHeight
        || !root.isConnected || document.querySelectorAll('#QGraph[role="application"]').length !== 1
        || document.getElementById("QGraph") !== root || !model.getEnableState()
        || Object.values(window.quant_wp_UI.controlsCollection)[0] !== model
        || Object.values(model.allGraphObjects())[0] !== curve
        || questionNodes.some(n => !n.isConnected || document.getElementById(n.id) !== n)
        || points.some((p,i) => curve.children[i] !== p || !anchors[i].isConnected || document.getElementById(anchors[i].id) !== anchors[i]
          || anchors[i].querySelector("circle") !== circles[i] || titles[i].textContent !== names[i]
          || anchors[i].getAttribute("draggable") !== "true" || anchors[i].getAttribute("role") !== "button")
        || [...document.querySelectorAll('[id*="customMessageBox"]')].some(n => n.getBoundingClientRect().height > 0)
        || JSON.stringify(snapshot()) !== JSON.stringify(expected)) throw Error("graph-target-stale");
    };
    let events = 0;
    for (let i = 0; i < 3; i += 1) {
      for (let axis = 0; axis < 2; axis += 1) {
        let attempts = 0;
        while (!close(axis ? points[i].y : points[i].x, desired[i][axis])) {
          assertPinned();
          if (++attempts > 80 || ++events > 160) throw Error("graph-movement-limit");
          const before = axis ? points[i].y : points[i].x;
          const sign = Math.sign(desired[i][axis] - before);
          const code = axis ? (sign > 0 ? "ArrowUp" : "ArrowDown") : (sign > 0 ? "ArrowRight" : "ArrowLeft");
          anchors[i].focus();
          assertPinned();
          anchors[i].dispatchEvent(new KeyboardEvent("keydown", {key: code, code, bubbles: true, cancelable: true}));
          const after = axis ? points[i].y : points[i].x;
          if (!close(after, before + sign*snap[axis])) throw Error("graph-movement-unexpected");
          // Only coordinates, generated curve markup and descriptions may change.
          const next = snapshot();
          if (next.question !== initial.question || next.points.some((p,j) => p.id !== initial.points[j].id || p.anchor !== initial.points[j].anchor)) throw Error("graph-target-stale");
          expected = next;
          assertPinned();
        }
      }
      if (anchors[i].getAttribute("aria-grabbed") === "true") {
        assertPinned();
        anchors[i].dispatchEvent(new KeyboardEvent("keydown", {key: " ", code: "Space", bubbles: true, cancelable: true}));
        assertPinned();
      }
    }
    assertPinned();
    const answer = new DOMParser().parseFromString(model.userAnswer(), "application/xml");
    const coeff = ["aval", "bval", "cval"].map(n => Number(answer.querySelector(n)?.textContent));
    if (!desired.every(([x,y],i) => close(points[i].x,x) && close(points[i].y,y))
      || !coeff.every((v,i) => close(v,[a,b,c][i])) || answer.querySelector("orientation")?.textContent !== "1"
      || anchors.some(n => n.getAttribute("aria-grabbed") !== "false")) return refuse("graph-verification-failed");
    const toGraph = (px, py) => [bounds[0]+px*(bounds[1]-bounds[0])/plotWidth, bounds[3]-py*(bounds[3]-bounds[2])/plotHeight];
    if (!circles.every((circle,i) => {
      const [x,y] = toGraph(Number(circle.getAttribute("cx")), Number(circle.getAttribute("cy")));
      return close(x,desired[i][0]) && close(y,desired[i][1]) && circle.getAttribute("transform") === initial.points[i].transform;
    })) return refuse("graph-rendered-points-mismatch");
    const path = renderedCurve.getAttribute("d") ?? "";
    const number = "-?(?:[0-9]+(?:\\.[0-9]*)?|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?";
    const segments = [...path.matchAll(new RegExp(`[ML](${number}),(${number})`, "g"))];
    if (segments.length < 3 || segments.map(m => m[0]).join("") !== path
      || new Set(segments.map(m => m[1])).size < 3
      || !segments.every(m => { const [x,y] = toGraph(Number(m[1]),Number(m[2])); return Math.abs(y-(a*x*x+b*x+c)) < 1e-7; })) return refuse("graph-rendered-curve-mismatch");
    return { ok: true, code: "graph-verified", events, coefficients: coeff, points: desired };
  } catch (error) {
    return refuse(String(error.message || "graph-operation-failed"));
  }
}
