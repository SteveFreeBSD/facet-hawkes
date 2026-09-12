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

  // --- a number line: Hawkes' QNumberLine engine ------------------------------
  //
  // A different engine from the Cartesian graph below, with a different model.
  // Hawkes' NumberLine template keeps the line on the active mode, not in the
  // control collection -- `objActiveMode.objNumberLine` -- and publishes its
  // answer through that mode's own `getUserAnswer`, `setUserAnswer` and
  // `isEmpty`, which read and write the line's `data`. An interval crosses in
  // Hawkes' own markup -- `<qmath><qpsbrac>a,b</qpsbrac></qmath>`, the bracket
  // family the answer editor uses, `symInfinite` for an end at an arrow.
  //
  // So the write is one call to the page's own template, and the proof is the
  // page's own reading of it: the answer it reports afterwards, parsed and
  // compared end for end, still reported once the page has settled, and no
  // longer empty by the page's own emptiness check.
  function numberLine(surfaces) {
    note({ engine: "numberline", surfaces: surfaces.length });
    if (surfaces.length !== 1) return refuse("graph-numberline-ambiguous");
    const surface = surfaces[0];
    // Hawkes appends the tick labels and the buttons to the line's container,
    // which may be the surface itself or the element holding it.
    const labelled = "span.clsMath[label]";
    const scope = surface.querySelector(labelled) ? surface : (surface.parentElement ?? surface);
    const SHAPES = { OO: "open", CC: "closed", OC: "open-closed", CO: "closed-open" };
    const TAGS = { open: "qpbrac", closed: "qsbrac", "open-closed": "qpsbrac", "closed-open": "qspbrac" };
    // The shapes this page offers are the interval buttons it drew, braces
    // (`B..`) or circles (`C..`) alike: which one is a drawing choice, not a
    // different interval.
    const offeredShapes = Object.entries(SHAPES).filter(([ends]) =>
      ["B", "C"].some((style) => {
        const button = document.getElementById(style + ends);
        return Boolean(button) && (scope.contains(button) || surface.parentElement?.contains(button));
      })).map(([, name]) => name);
    const ticks = [...scope.querySelectorAll(labelled)]
      .map((span) => String(span.getAttribute("label") ?? "").trim());
    const values = ticks.map(Number);
    // The mode is a page global, and may be a lexical one rather than a
    // property of `window`; both are read, never assigned.
    const activeMode = () => window.objActiveMode
      ?? (typeof objActiveMode !== "undefined" ? objActiveMode : undefined);
    const mode = activeMode();
    const line = mode?.objNumberLine;
    const accessorOf = (one) => {
      for (let proto = one, depth = 0; proto && depth < 4; proto = Object.getPrototypeOf(proto), depth += 1) {
        const described = Object.getOwnPropertyDescriptor(proto, "data");
        if (described) return described;
      }
      return null;
    };
    const isLine = (one) => one !== null && typeof one === "object"
      && typeof one.loadNumberLine === "function"
      && typeof accessorOf(one)?.get === "function"
      && typeof accessorOf(one)?.set === "function";
    const templated = ["getUserAnswer", "setUserAnswer", "isEmpty"]
      .every((name) => typeof mode?.[name] === "function");
    // The line this mode owns has to be the line on screen: the template
    // renames its container to the mode's own template id.
    const container = document.getElementById(`${String(mode?.strUITemplateContainer ?? "")}NumberLineContainer`);
    note({
      shapes: offeredShapes,
      ticks: ticks.length,
      activeMode: typeof mode,
      numberLine: isLine(line),
      templated,
      owned: Boolean(container?.contains(surface)),
    });
    if (!isLine(line) || !templated) return refuse("graph-numberline-model-missing");
    if (!container || !container.contains(surface)) return refuse("graph-numberline-model-elsewhere");
    if (ticks.length < 2 || !values.every(Number.isFinite)) return refuse("graph-numberline-ticks-unreadable");
    const sorted = [...values].sort((a, b) => a - b);
    const gaps = sorted.slice(1).map((v, i) => v - sorted[i]);
    const step = Math.min(...gaps);
    const near = (a, b) => Math.abs(a - b) < 1e-9;
    if (!(step > 0) || !sorted.every((v) => near((v - sorted[0]) / step, Math.round((v - sorted[0]) / step)))) {
      return refuse("graph-numberline-grid-unsupported");
    }
    if (offeredShapes.length === 0) return refuse("graph-numberline-intervals-missing");
    if (line.disableNL === true) return refuse("graph-numberline-disabled");
    const nodes = ["questionDescription", "questionString", "partInformation"]
      .map((id) => document.getElementById(id));
    note({ questionNodes: nodes.filter(Boolean).length });
    if (nodes.some((n) => !n)) return refuse("graph-question-missing");
    const asked = () => nodes.map((n) => new XMLSerializer().serializeToString(n)).join("");
    const answer = () => String(line.data ?? "");
    // How many intervals the line will plot. A question states it as the
    // number line's `plotdata.maxplots`; where it does not, QNumberLine's own
    // `QNLGlobal` plots up to three, and stops plotting silently past it --
    // which is why a union longer than this is refused before it is written.
    const plotdata = mode?.controlsJSON?.numline?.plotdata;
    const stated = Number.parseInt(
      typeof plotdata?.maxplots === "function" ? plotdata.maxplots() : plotdata?.maxplots, 10);
    const maxIntervals = Math.min(Number.isInteger(stated) && stated >= 1 ? stated : 3, 12);
    const shot = () => ({ question: asked(), ticks: [...ticks], shapes: [...offeredShapes],
      maxIntervals, answer: answer() });
    const first = shot();
    const context = { family: "numberline", bounds: [sorted[0], sorted[sorted.length - 1]],
      snap: [step], controls: "interval-buttons", intervals: offeredShapes, count: maxIntervals };
    if (!offered) {
      return { ok: true, kind: "graph", code: "graph-described", enabled: true, context,
        snapshot: first, probe: { engine: "numberline", ticks: ticks.length,
          shapes: offeredShapes, maxIntervals,
          maxIntervalsStated: Number.isInteger(stated) && stated >= 1,
          answered: first.answer.length > 0 } };
    }
    if (JSON.stringify(first) !== JSON.stringify(offered.snapshot)) return refuse("graph-target-stale");
    // Somebody's own work on the line is not this writer's to replace.
    if (first.answer !== "") return refuse("graph-numberline-not-empty");

    const plan = offered.plan;
    const has = (o, k) => o && typeof o === "object"
      && Object.keys(o).sort().join() === k.split(" ").sort().join();
    if (!has(plan, "kind intervals") || plan.kind !== "numberline"
      || !Array.isArray(plan.intervals) || plan.intervals.length < 1) return refuse("graph-plan-invalid");
    if (plan.intervals.length > maxIntervals) return refuse("graph-numberline-too-many-intervals");
    const wanted = plan.intervals.map((interval) => {
      if (!has(interval, "left right")) throw Error("graph-plan-invalid");
      return ["left", "right"].map((side) => {
        const end = interval[side];
        if (!has(end, "value closed") || typeof end.closed !== "boolean"
          || typeof end.value !== "string") throw Error("graph-plan-invalid");
        const infinite = end.value === (side === "left" ? "-inf" : "inf");
        if (infinite) {
          if (end.closed) throw Error("graph-plan-invalid");
          return { infinite: true, closed: false };
        }
        // A finite end has to be one of the ticks the page labelled, spelled
        // as the page spells it -- which is also what it is written back as.
        const at = ticks.indexOf(end.value);
        if (at < 0) throw Error("graph-plan-off-grid");
        return { infinite: false, closed: end.closed, label: ticks[at], value: values[at] };
      });
    });
    // Each interval in order, and apart from the next: the pieces of a union
    // left to right, sharing at most an end neither of them includes.
    const SHAPE_OF = { "false,false": "open", "true,true": "closed",
      "false,true": "open-closed", "true,false": "closed-open" };
    const pieces = wanted.map(([left, right]) => ({ left, right,
      shape: SHAPE_OF[`${left.closed},${right.closed}`] }));
    if (pieces.some(({ left, right }) => !left.infinite && !right.infinite && !(left.value < right.value))) {
      return refuse("graph-plan-invalid");
    }
    for (let i = 1; i < pieces.length; i += 1) {
      const before = pieces[i - 1].right;
      const after = pieces[i].left;
      if (before.infinite || after.infinite || before.value > after.value
        || (near(before.value, after.value) && before.closed && after.closed)) {
        return refuse("graph-plan-invalid");
      }
    }
    if (pieces.some((piece) => !offeredShapes.includes(piece.shape))) {
      return refuse("graph-numberline-shape-unoffered");
    }
    const spell = (end, sign) => (end.infinite ? `${sign}<qspchar>symInfinite</qspchar>` : end.label);
    // Hawkes' own union: the intervals joined by `symUnion` inside one `qmath`,
    // exactly as its number line reports a plotted union.
    const written = `<qmath>${pieces.map(({ left, right, shape }) =>
      `<${TAGS[shape]}>${spell(left, "-")},${spell(right, "")}</${TAGS[shape]}>`)
      .join("<qspchar>symUnion</qspchar>")}</qmath>`;

    // What the page says is on the line, as intervals. Tolerant of how Hawkes
    // wraps and spells a value, strict about which interval it is.
    const readBack = (text) => {
      const bare = text.replace(/<\/?qmath>/gi, "");
      const pieces = bare.split(/<qspchar>symUnion<\/qspchar>/i).filter((piece) => piece.trim());
      return pieces.map((piece) => {
        const match = piece.trim().match(/^<(qpbrac|qsbrac|qpsbrac|qspbrac)>([\s\S]*)<\/\1>$/i);
        if (!match) return null;
        const [lo, hi] = match[2].split(",");
        const endOf = (raw, sign) => {
          const plain = String(raw ?? "").trim();
          if (plain.toLowerCase() === `${sign}<qspchar>syminfinite</qspchar>`) return { infinite: true };
          const fraction = plain.match(/^(-?)<qfrac><qnum>(-?[0-9.]+)<\/qnum><qden>([0-9.]+)<\/qden><\/qfrac>$/i);
          const number = fraction
            ? (fraction[1] ? -1 : 1) * Number(fraction[2]) / Number(fraction[3])
            : Number(plain.replace(/<[^>]*>/g, ""));
          return Number.isFinite(number) && plain !== "" ? { infinite: false, value: number } : null;
        };
        const shapeName = Object.entries(TAGS).find(([, tag]) => tag === match[1].toLowerCase())?.[0];
        return { shape: shapeName, left: endOf(lo, "-"), right: endOf(hi, "") };
      });
    };
    const agrees = (text) => {
      const got = readBack(text);
      const same = (end, want) => end !== null && end.infinite === want.infinite
        && (want.infinite || near(end.value, want.value));
      return got.length === pieces.length && got.every((one, i) => one !== null
        && one.shape === pieces[i].shape
        && same(one.left, pieces[i].left) && same(one.right, pieces[i].right));
    };
    const dialogUp = () => [...document.querySelectorAll('[id*="customMessageBox"]')]
      .some((n) => n.getBoundingClientRect().height > 0);
    const pinned = () => surface.isConnected && activeMode() === mode && mode.objNumberLine === line
      && container.isConnected && container.contains(surface)
      && asked() === first.question && line.disableNL !== true && !dialogUp();
    if (!pinned()) return refuse("graph-target-stale");

    mode.setUserAnswer(written);
    const settled = answer();
    if (!agrees(settled) || mode.isEmpty() !== false) {
      return { ...refuse("graph-numberline-not-settled"), leftBehind: settled !== "" };
    }
    // Held still while the page finishes: redrawn by its own handlers, and
    // still reporting the same interval at the end of it.
    return new Promise((resolve) => {
      let polls = 0;
      const poll = () => {
        polls += 1;
        let now = "";
        let holding = false;
        try {
          now = answer();
          holding = pinned() && now === settled && agrees(now) && mode.isEmpty() === false;
        } catch {
          holding = false;
        }
        if (!holding) {
          resolve({ ...refuse(dialogUp() ? "editor-dialog-open" : "graph-numberline-not-settled"),
            leftBehind: now !== "" });
          return;
        }
        if (polls >= 8) {
          resolve({ ok: true, code: "numberline-verified", events: 1,
            intervals: pieces.length });
          return;
        }
        setTimeout(poll, 100);
      };
      setTimeout(poll, 100);
    });
  }

  try {
    if (window.location.origin !== "https://learn.hawkeslearning.com") return refuse("wrong-site");
    // One surface per line, not per container: Hawkes' template and its engine
    // both mark a container `role="application"`, one inside the other.
    const lineSurfaces = [...new Set([...document.querySelectorAll("svg#svg_numberline")]
      .map((svg) => svg.closest?.('[role="application"]'))
      .filter((node) => node && node.getBoundingClientRect().width > 0))];
    if (document.querySelectorAll('#QGraph[role="application"]').length === 0
      && lineSurfaces.length > 0) {
      return numberLine(lineSurfaces);
    }
    const roots = [...document.querySelectorAll('#QGraph[role="application"]')];
    if (roots.length !== 1 || roots[0].getBoundingClientRect().width <= 0) return refuse("graph-missing");
    const root = roots[0];
    const plotRect = root.querySelector("svg defs clipPath rect");
    if (!plotRect) return refuse("graph-renderer-unsupported");
    const plotWidth = Number(plotRect.getAttribute("width"));
    const plotHeight = Number(plotRect.getAttribute("height"));
    if (!(plotWidth > 0 && plotHeight > 0)) return refuse("graph-renderer-unsupported");
    const models = Object.values(window.quant_wp_UI?.controlsCollection ?? {});
    note({ models: models.length, isGraph: models[0]?.isGraph === true });
    if (models.length !== 1 || models[0].isGraph !== true) return refuse("graph-model-missing");
    const model = models[0];
    const objects = Object.values(model.allGraphObjects());
    const renderedCurve = root.querySelector("svg g.parabola > path");
    note({
      objects: objects.length,
      titles: objects.map((one) => String(one?.title ?? "").slice(0, 32)).slice(0, 12),
      children: objects.map((one) =>
        Array.isArray(one?.children) ? one.children.length : -1).slice(0, 12),
      parabolaPath: Boolean(renderedCurve),
      anchorsAnywhere: root.querySelectorAll('a[draggable="true"][role="button"]').length,
      enabled: model.getEnableState?.() === true,
    });

    // --- a graph answered by placing stated points ---------------------------
    //
    // Hawkes draws one draggable control per point the question names, and the
    // question writes the points down. Nothing here is a curve: there is no
    // path to pin and no coefficients to prove against, so what is proved is
    // the coordinates themselves, which is what the question asks for.
    //
    // Deliberately its own branch. The parabola path above and below is
    // untouched: a different family, different controls, and a plan of a
    // different kind, sharing only the primitives -- pin, step by one snap on
    // one axis, re-pin, and read the model back.
    const movable = (one) =>
      one && Number.isFinite(one.x) && Number.isFinite(one.y)
      && Number.isFinite(one.snapX) && Number.isFinite(one.snapY);
    const stated = objects.every(movable) && objects.length >= 1
      ? objects
      : (objects.length === 1 && Array.isArray(objects[0]?.children)
        && objects[0].children.length >= 1 && objects[0].children.every(movable)
        ? objects[0].children
        : null);
    const plotAnchors = [...root.querySelectorAll('a[draggable="true"][role="button"]')];
    if (!renderedCurve && stated !== null) {
      const spots = stated;
      if (spots.length < 1 || spots.length > 12) return refuse("graph-controls-unsupported");
      if (plotAnchors.length !== spots.length || !plotAnchors.every((a) => a.id)) {
        return refuse("graph-controls-unsupported");
      }
      // One anchor per point, matched by what the page itself says they are --
      // never by position. A control whose anchor cannot be named, or that
      // could be either of two, is refused rather than guessed at.
      const labelOf = (anchor) =>
        String(document.getElementById(anchor.getAttribute("aria-labelledby"))
          ?.textContent ?? "").trim();
      const anchorFor = (spot) => {
        const byId = plotAnchors.filter((a) =>
          spot.ID !== undefined && String(a.id).includes(String(spot.ID)));
        if (byId.length === 1) return byId[0];
        const title = String(spot.title ?? "").trim();
        const byName = title.length > 0
          ? plotAnchors.filter((a) => labelOf(a) === title) : [];
        return byName.length === 1 ? byName[0] : null;
      };
      const paired = spots.map(anchorFor);
      if (paired.some((a) => a === null)
        || new Set(paired).size !== spots.length) return refuse("graph-points-ambiguous");
      const circleOf = paired.map((a) => a.querySelector("circle"));
      if (circleOf.some((c) => !c)) return refuse("graph-controls-unsupported");
      const xml = new DOMParser().parseFromString(model.graphXML(), "application/xml");
      const readAxis = (sel) => Number(xml.querySelector(sel)?.textContent);
      if (xml.querySelector("grid > type")?.textContent !== "cartesian") {
        return refuse("graph-orientation-unsupported");
      }
      const bounds = ["xmin", "xmax", "ymin", "ymax"].map((n) => readAxis(`cartesian > ${n}`));
      const snap = [spots[0].snapX, spots[0].snapY];
      if (![...bounds, ...snap].every(Number.isFinite) || !snap.every((n) => n > 0)
        || !spots.every((q) => q.snapX === snap[0] && q.snapY === snap[1])) {
        return refuse("graph-grid-unsupported");
      }
      const nodes = ["questionDescription", "questionString", "partInformation"]
        .map((id) => document.getElementById(id));
      if (nodes.some((n) => !n)) return refuse("graph-question-missing");
      const asked = () => nodes.map((n) => new XMLSerializer().serializeToString(n)).join("\u001f");
      const state = () => spots.map((q, i) => ({ id: q.ID, anchor: paired[i].id,
        x: q.x, y: q.y, cx: circleOf[i].getAttribute("cx"), cy: circleOf[i].getAttribute("cy") }));
      const shot = () => ({ question: asked(), xml: model.graphXML(), points: state(),
        answer: model.userAnswer() });
      const first = shot();
      const context = { family: "points", count: spots.length, bounds, snap,
        controls: "draggable-points" };
      if (!offered) {
        // What Hawkes needs beyond coordinates, as counts.
        //
        // A graph object carries a `plotted` flag, and Hawkes asks
        // `isAllGraphObjectsPlotted()` before it will accept an answer. Arrow
        // keys move a point without ever setting that flag, which is how four
        // points sat on screen at exactly the right coordinates under the
        // message "your answer seems incomplete". Reported so a described
        // graph says how many of its controls the page already counts as
        // plotted, and whether it publishes the check at all.
        const plottedControls = spots.filter((q) => q.plotted === true).length;
        return { ok: true, kind: "graph", code: "graph-described",
          enabled: model.getEnableState(), context, snapshot: first,
          probe: {
            controls: spots.length,
            plotted: plottedControls,
            publishesPlottedQuery:
              typeof model.isAllGraphObjectsPlotted === "function",
          } };
      }
      if (JSON.stringify(first) !== JSON.stringify(offered.snapshot)) return refuse("graph-target-stale");
      const plan = offered.plan;
      const num = (t) => {
        if (typeof t !== "string" || !/^-?(?:0|[1-9][0-9]*)(?:\/[1-9][0-9]*)?$/.test(t)
          || t.length > 30) throw Error("graph-plan-invalid");
        const [a, b = "1"] = t.split("/");
        const v = Number(a) / Number(b);
        if (!Number.isFinite(v)) throw Error("graph-plan-invalid");
        return v;
      };
      const has = (o, k) => o && Object.keys(o).sort().join() === k.split(" ").sort().join();
      if (!has(plan, "kind points") || plan.kind !== "points"
        || !Array.isArray(plan.points) || plan.points.length !== spots.length) {
        return refuse("graph-plan-invalid");
      }
      const wanted = plan.points.map((q) => {
        if (!has(q, "x y")) throw Error("graph-plan-invalid");
        return [num(q.x), num(q.y)];
      });
      const near = (a, b) => Math.abs(a - b) < 1e-9;
      if (!wanted.every(([x, y]) => x >= bounds[0] && x <= bounds[1]
        && y >= bounds[2] && y <= bounds[3])) return refuse("graph-plan-off-grid");
      // The answer is the set of places the controls end up, so which control
      // goes to which stated point is this writer's to choose. Chosen the one
      // way that is not a guess: both lists in the same total order.
      const order = (a, b) => (a[0] - b[0]) || (a[1] - b[1]);
      const targets = [...wanted].sort(order);
      const seats = spots.map((q, i) => [q.x, q.y, i]).sort(order).map((t) => t[2]);
      const goal = [];
      seats.forEach((at, k) => { goal[at] = targets[k]; });
      if (!goal.every(([x, y], i) =>
        near((x - spots[i].x) / snap[0], Math.round((x - spots[i].x) / snap[0]))
        && near((y - spots[i].y) / snap[1], Math.round((y - spots[i].y) / snap[1])))) {
        return refuse("graph-plan-off-grid");
      }
      const total = goal.reduce((n, [x, y], i) =>
        n + Math.abs((x - spots[i].x) / snap[0]) + Math.abs((y - spots[i].y) / snap[1]), 0);
      if (total > 400) return refuse("graph-plan-too-long");
      let expect = first;
      const pinned = () => {
        if (root.querySelector("svg defs clipPath rect") !== plotRect
          || Number(plotRect.getAttribute("width")) !== plotWidth
          || Number(plotRect.getAttribute("height")) !== plotHeight
          || !root.isConnected
          || document.querySelectorAll('#QGraph[role="application"]').length !== 1
          || document.getElementById("QGraph") !== root || !model.getEnableState()
          || Object.values(window.quant_wp_UI.controlsCollection)[0] !== model
          || nodes.some((n) => !n.isConnected || document.getElementById(n.id) !== n)
          || spots.some((q, i) => !paired[i].isConnected
            || document.getElementById(paired[i].id) !== paired[i]
            || paired[i].querySelector("circle") !== circleOf[i]
            || paired[i].getAttribute("draggable") !== "true"
            || paired[i].getAttribute("role") !== "button")
          || [...document.querySelectorAll('[id*="customMessageBox"]')]
            .some((n) => n.getBoundingClientRect().height > 0)
          || JSON.stringify(shot()) !== JSON.stringify(expect)) throw Error("graph-target-stale");
      };
      let struck = 0;
      let plotKeys = 0;
      for (let i = 0; i < spots.length; i += 1) {
        for (let axis = 0; axis < 2; axis += 1) {
          let tries = 0;
          while (!near(axis ? spots[i].y : spots[i].x, goal[i][axis])) {
            pinned();
            if (++tries > 120 || ++struck > 400) throw Error("graph-movement-limit");
            const was = axis ? spots[i].y : spots[i].x;
            const sign = Math.sign(goal[i][axis] - was);
            const code = axis ? (sign > 0 ? "ArrowUp" : "ArrowDown")
              : (sign > 0 ? "ArrowRight" : "ArrowLeft");
            paired[i].focus();
            pinned();
            paired[i].dispatchEvent(new KeyboardEvent("keydown",
              { key: code, code, bubbles: true, cancelable: true }));
            const now = axis ? spots[i].y : spots[i].x;
            if (!near(now, was + sign * snap[axis])) throw Error("graph-movement-unexpected");
            const next = shot();
            if (next.question !== first.question
              || next.points.some((q, j) => q.id !== first.points[j].id
                || q.anchor !== first.points[j].anchor)) throw Error("graph-target-stale");
            expect = next;
          }
        }
        // Arrow keys move a point. They do not plot one.
        //
        // Hawkes keeps a `plotted` flag on every graph object and sets it from
        // one key: space. Arrows change the coordinate and redraw the circle
        // and leave the flag alone, which is exactly what a live run looked
        // like -- four points on screen at the four stated coordinates, every
        // coordinate read back correct, and the page still answering "your
        // answer seems incomplete", because the flag behind that message had
        // never been set on any of them.
        //
        // So each control is plotted where it was stepped to, and only if the
        // page does not already count it as plotted: on one that does, the
        // same key toggles the grab instead, which would undo this.
        if (spots[i].plotted !== true) {
          pinned();
          paired[i].focus();
          pinned();
          if (++struck > 400) throw Error("graph-movement-limit");
          paired[i].dispatchEvent(new KeyboardEvent("keydown",
            { key: " ", code: "Space", bubbles: true, cancelable: true }));
          plotKeys += 1;
          expect = shot();
        }
      }
      // Every control on a stated point, and every stated point covered. The
      // question asks for a set, so the set is what is checked.
      const landed = spots.map((q) => [q.x, q.y]).sort(order);
      if (landed.length !== targets.length
        || !landed.every(([x, y], i) => near(x, targets[i][0]) && near(y, targets[i][1]))) {
        return refuse("graph-points-not-settled");
      }
      // The page's own completeness check, which is the one that decides.
      // Every check above passed on a graph Hawkes then called incomplete, so
      // the question is put to the page rather than inferred here: this is the
      // predicate behind that message. A model that does not publish it is
      // held to the flag the check reads instead.
      const complete = typeof model.isAllGraphObjectsPlotted === "function"
        ? model.isAllGraphObjectsPlotted() === true
        : spots.every((q) => q.plotted === true);
      if (!complete) return refuse("graph-points-not-plotted");
      return { ok: true, code: "graph-plotted", points: spots.length,
        events: struck, plotKeys };
    }

    if (!renderedCurve) return refuse("graph-renderer-unsupported");
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
