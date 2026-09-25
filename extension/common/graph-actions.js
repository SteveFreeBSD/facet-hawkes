"use strict";

/** One bounded MAIN-world operation. Reads Hawkes' model and writes only to the
 * identified page-owned graph controls. No page state is installed. The plan
 * is data, never code or prose. */
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
    const labelGap = Math.min(...gaps);
    const near = (a, b) => Math.abs(a - b) < 1e-9;
    const onGrid = (v, origin, spacing) => near((v - origin) / spacing, Math.round((v - origin) / spacing));
    if (!(labelGap > 0) || !sorted.every((v) => onGrid(v, sorted[0], labelGap))) {
      return refuse("graph-numberline-grid-unsupported");
    }
    // Where an end may go is the line's own grid, not its labels. The question
    // configures it -- `numline.baseline.line` states the range, how many
    // divisions carry a label and how many subdivisions sit between them, and
    // the baseline says whether subticks are drawn and whether plotting snaps
    // to the labelled ticks only -- and QNumberLine plots and snaps on every
    // tick it draws. Live, on 2026-09-12, a line labelled at each integer with
    // a subtick at every half was described as stepping by one, and `y < -3.5`
    // was refused as off the line it sat on.
    const read = (value) => (typeof value === "function" ? value() : value);
    const baseline = mode?.controlsJSON?.numline?.baseline;
    const axis = baseline?.line;
    const configured = {
      min: Number.parseFloat(read(axis?.minval)),
      max: Number.parseFloat(read(axis?.maxval)),
      divisions: Number(read(axis?.divisions)),
      // QNLGlobal's own defaults where a question states none.
      subdivisions: axis && read(axis.subdivisions) !== undefined ? Number(read(axis.subdivisions)) : 2,
      subticks: String(read(baseline?.showsubticks)) === "true",
      ticksOnly: String(read(baseline?.snaptoticks)) === "true",
    };
    const gridStated = Number.isFinite(configured.min) && Number.isFinite(configured.max)
      && configured.max > configured.min && Number.isInteger(configured.divisions)
      && configured.divisions > 0 && Number.isInteger(configured.subdivisions)
      && configured.subdivisions > 0;
    const major = gridStated ? (configured.max - configured.min) / configured.divisions : labelGap;
    // The configuration has to describe the line on screen: its labels are its
    // major ticks. A question whose labels say otherwise is not read at all.
    if (gridStated && !(near(sorted[0], configured.min) && near(sorted[sorted.length - 1], configured.max)
      && near(labelGap, major) && sorted.every((v) => onGrid(v, configured.min, major)))) {
      return refuse("graph-numberline-grid-unsupported");
    }
    const step = gridStated && configured.subticks && !configured.ticksOnly
      ? major / configured.subdivisions : major;
    note({ gridStated, step });
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
      step, maxIntervals, answer: answer() });
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
        // A finite end has to be on the line's grid and within its range:
        // a labelled tick, or a subtick between two of them. It is written as
        // the plan spells it, a terminating decimal, which is how Hawkes
        // reads a value back.
        if (!/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(end.value)) throw Error("graph-plan-invalid");
        const value = Number(end.value);
        if (!(value >= sorted[0] - 1e-9 && value <= sorted[sorted.length - 1] + 1e-9)
          || !onGrid(value, sorted[0], step)) throw Error("graph-plan-off-grid");
        return { infinite: false, closed: end.closed, label: end.value, value };
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
    const models = Object.values(window.quant_wp_UI?.controlsCollection ?? {});
    const visible = (node) => {
      const box = node?.getBoundingClientRect?.();
      return Boolean(box && box.width > 0 && box.height > 0);
    };
    const fields = [...document.querySelectorAll(
      'input.qbaseCSS,input[id^="txtAns"],input.boxStyle'
    )].filter((node) => visible(node) && !node.disabled && !node.readOnly);
    const radios = [...document.querySelectorAll('input[type="radio"]')]
      .filter((node) => visible(node) && !node.disabled);
    const nameOf = (radio) => String(radio.getAttribute("aria-label")
      || (radio.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean)
        .map((id) => document.getElementById(id)?.textContent || "").join(" ")
      || (radio.id && globalThis.CSS?.escape
        ? document.querySelector(`label[for="${CSS.escape(radio.id)}"]`)?.textContent : "")
      || radio.closest?.("label")?.textContent || radio.value || "").replace(/\s+/g, " ").trim();
    const grouped = Object.values(Object.groupBy?.(radios, (radio) => radio.name) ??
      radios.reduce((all, radio) => ({ ...all,
        [radio.name]: [...(all[radio.name] ?? []), radio] }), {}));
    const radioChoices = grouped.map((group) => group.map(nameOf));
    const boundaryKind = (choice) => String(choice).trim().toLowerCase()
      .match(/^(solid|dashed)(?:\s|\(|$)/)?.[1] ?? "";
    const setOperation = (choice) => {
      const words = String(choice).toLowerCase().match(/[a-z]+/g) ?? [];
      const named = ["union", "intersection"].filter((word) => words.includes(word));
      return named.length === 1 ? named[0] : "";
    };
    const boundaryGroup = radioChoices.findIndex((choices) =>
      choices.map(boundaryKind).sort().join("\u001f") === "dashed\u001fsolid");
    const graphModels = models.filter((one) => one?.isGraph === true);
    note({ models: models.length, isGraph: models[0]?.isGraph === true,
      graphModels: graphModels.length, fields: fields.length,
      radioGroups: radioChoices,
      modelShapes: models.map((one) => ({
        type: String(one?.constructor?.name ?? ""),
        isGraph: one?.isGraph === true,
        keys: Object.keys(one ?? {}).sort().slice(0, 64),
        methods: ["allGraphObjects", "getUserAnswer", "setUserAnswer", "isEmpty",
          "graphXML", "getEnableState"].filter((name) => typeof one?.[name] === "function"),
      })),
    });
    if (fields.length === 4 && grouped.length === 2 && grouped.every((group) => group.length === 2)
      && boundaryGroup >= 0 && graphModels.length === 1) {
      const model = graphModels[0];
      const xml = () => String(model.graphXML?.() ?? "");
      const parsed = new DOMParser().parseFromString(xml(), "application/xml");
      const value = (selector) => parsed.querySelector(selector)?.textContent;
      const bounds = ["xmin", "xmax", "ymin", "ymax"]
        .map((axis) => Number(value(`cartesian > ${axis}`)));
      if (!bounds.every(Number.isFinite) || bounds[0] >= bounds[1] || bounds[2] >= bounds[3]) {
        return refuse("graph-grid-unsupported");
      }
      const nodes = ["questionDescription", "questionString", "partInformation"]
        .map((id) => document.getElementById(id));
      if (nodes.some((node) => !node)) return refuse("graph-question-missing");
      const asked = () => nodes.map((node) => new XMLSerializer().serializeToString(node)).join("\u001f");
      const state = () => ({
        question: asked(),
        fields: fields.map((field) => ({ id: field.id, value: String(field.value ?? "") })),
        radios: grouped.flat().map((radio) => ({
          id: radio.id, name: radio.name, choice: nameOf(radio), checked: radio.checked === true,
        })),
      });
      const first = state();
      const context = { family: "linear-inequality", bounds, snap: [1, 1],
        controls: "boundary-two-points-regions" };
      if (!offered) return { ok: true, kind: "graph", code: "graph-described",
        // This composite graph's page model reports disabled because Hawkes
        // does not permit direct dragging; its visible native fields and radio
        // controls are nevertheless the enabled answer surface.
        enabled: true, context, snapshot: first,
        probe: { engine: "cartesian-composite", fields: 4, radioGroups: radioChoices,
          graphObjects: Object.values(model.allGraphObjects?.() ?? {}).length } };
      if (JSON.stringify(first) !== JSON.stringify(offered.snapshot)) return refuse("graph-target-stale");
      const plan = offered.plan;
      const keys = (object, names) => object && Object.keys(object).sort().join()
        === names.split(" ").sort().join();
      const rational = (text) => {
        if (typeof text !== "string" || !/^-?(?:0|[1-9][0-9]*)(?:\/[1-9][0-9]*)?$/.test(text)) {
          throw Error("graph-plan-invalid");
        }
        const [top, bottom = "1"] = text.split("/");
        return Number(top) / Number(bottom);
      };
      if (!keys(plan, "boundary coefficients kind points relation")
        || plan.kind !== "linear-inequality"
        || !["<", "<=", ">", ">="].includes(plan.relation)
        || plan.boundary !== (["<", ">"].includes(plan.relation) ? "dashed" : "solid")
        || !keys(plan.coefficients, "constant x y")
        || !Array.isArray(plan.points) || plan.points.length !== 2
        || !Array.isArray(offered.coefficients) || offered.coefficients.length !== 3
        || offered.coefficients.join("\u001f") !== [
          plan.coefficients.x, plan.coefficients.y, plan.coefficients.constant,
        ].join("\u001f")) return refuse("graph-plan-invalid");
      const coefficients = offered.coefficients.map(rational);
      const wanted = plan.points.map((point) => {
        if (!keys(point, "x y")) throw Error("graph-plan-invalid");
        return [rational(point.x), rational(point.y)];
      });
      const near = (a, b) => Math.abs(a - b) < 1e-9;
      if ((!coefficients[0] && !coefficients[1])
        || near(wanted[0][0], wanted[1][0]) && near(wanted[0][1], wanted[1][1])
        || !wanted.every(([x, y]) => x >= bounds[0] && x <= bounds[1]
          && y >= bounds[2] && y <= bounds[3]
          && near(coefficients[0] * x + coefficients[1] * y + coefficients[2], 0))) {
        return refuse("graph-plan-invalid");
      }
      const boundary = grouped[boundaryGroup];
      const regionControls = grouped[1 - boundaryGroup];
      const boundaryControl = boundary.find((radio) => boundaryKind(nameOf(radio)) === plan.boundary);
      if (!boundaryControl) return refuse("graph-boundary-control-missing");
      const spellings = wanted.flat().map((number, index) =>
        plan.points[Math.floor(index / 2)][index % 2 ? "y" : "x"]);
      if (fields.some((field, index) => String(field.value) !== ""
        && String(field.value) !== spellings[index])
        || boundary.some((radio) => radio.checked && radio !== boundaryControl)
        || boundary.filter((radio) => radio.checked).length > 1
        || regionControls.filter((radio) => radio.checked).length > 1) {
        return refuse("graph-linear-inequality-not-empty");
      }
      const pinned = () => {
        const currentModels = Object.values(window.quant_wp_UI?.controlsCollection ?? {})
          .filter((one) => one?.isGraph === true);
        return currentModels.length === 1 && currentModels[0] === model
        && nodes.every((node) => node.isConnected) && asked() === first.question
        && fields.every((field, index) => field.isConnected && field.id === first.fields[index].id)
        && grouped.flat().every((radio, index) => radio.isConnected && radio.id === first.radios[index].id)
        && ![...document.querySelectorAll('[id*="customMessageBox"]')]
          .some((node) => node.getBoundingClientRect().height > 0);
      };
      if (!pinned()) return refuse("graph-target-stale");
      const choose = (radio) => {
        radio.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
        return radio.checked === true;
      };
      if (!boundaryControl.checked && !choose(boundaryControl)) {
        return refuse("graph-boundary-not-settled");
      }
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      if (typeof setter !== "function") return refuse("graph-field-writer-missing");
      for (let index = 0; index < fields.length; index += 1) {
        const field = fields[index];
        const text = spellings[index];
        if (String(field.value) === text) continue;
        field.focus();
        if (!field.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true,
          data: text, inputType: "insertText" }))) return refuse("input-cancelled");
        for (const character of text) {
          setter.call(field, field.value + character);
          field.dispatchEvent(new InputEvent("input", { bubbles: true, data: character,
            inputType: "insertText" }));
        }
        field.dispatchEvent(new Event("change", { bubbles: true }));
        if (String(field.value) !== text) return refuse("graph-points-not-settled");
      }
      const descendants = (objects) => {
        const all = [];
        const visit = (one, depth = 0) => {
          if (!one || depth > 6 || all.includes(one)) return;
          all.push(one);
          if (one.Regions) visit(one.Regions, depth + 1);
          if (Array.isArray(one.children)) one.children.forEach((child) => visit(child, depth + 1));
        };
        objects.forEach((one) => visit(one));
        return all;
      };
      const relationHolds = (v) => ({ "<": v < -1e-9, "<=": v <= 1e-9,
        ">": v > 1e-9, ">=": v >= -1e-9 })[plan.relation];
      const pointFrom = (point) => {
        if (Number.isFinite(point?.x) && Number.isFinite(point?.y)) {
          return { x: point.x, y: point.y };
        }
        const words = String(point?.description ?? "").toLowerCase();
        if (!words.includes("origin")) return null;
        if (words.includes("at the origin")) return { x: 0, y: 0 };
        let x = 0;
        let y = 0;
        let found = false;
        for (const match of words.matchAll(/([0-9]+(?:\.[0-9]+)?)\s+units?\s+(right|left|above|below)/g)) {
          const distance = Number(match[1]);
          if (match[2] === "right") x = distance;
          if (match[2] === "left") x = -distance;
          if (match[2] === "above") y = distance;
          if (match[2] === "below") y = -distance;
          found = true;
        }
        return found ? { x, y } : null;
      };
      return new Promise((resolve) => {
        let regionPolls = 0;
        const findRegionChoice = () => {
          const labels = regionControls.map(nameOf);
          const regions = descendants(Object.values(model.allGraphObjects?.() ?? {}))
            .filter((one) => labels.includes(String(one?.label ?? "").trim())
              && Object.prototype.hasOwnProperty.call(one, "curvePlotOnSelect"));
          if (regions.length !== labels.length
            || new Set(regions.map((one) => String(one.label).trim())).size !== labels.length) return null;
          // Hawkes puts its named Test Point under the region that contains it;
          // the other page-owned region explicitly says that it does not. The
          // point's accessible description remains populated even when the
          // transient x/y getters do not, which is the normal live state after
          // the boundary fields redraw a vertical line.
          const containing = regions.map((region) => ({ region,
            points: descendants(Array.isArray(region.children) ? region.children : [])
              .filter((child) => String(child?.title ?? "").trim() === "Test Point")
              .map(pointFrom).filter(Boolean),
          })).filter((one) => one.points.length === 1);
          if (containing.length !== 1) return null;
          const point = containing[0].points[0];
          const containsLabel = String(containing[0].region.label).trim();
          const chosenLabel = relationHolds(coefficients[0] * point.x
            + coefficients[1] * point.y + coefficients[2])
            ? containsLabel
            : labels.find((label) => label !== containsLabel);
          return chosenLabel ? { label: chosenLabel, point, containsLabel } : null;
        };
        const awaitRegions = () => {
          regionPolls += 1;
          if (!pinned() || !boundaryControl.checked
            || !fields.every((field, index) => String(field.value) === spellings[index])) {
            resolve(refuse("graph-linear-inequality-not-settled"));
            return;
          }
          const chosen = findRegionChoice();
          if (!chosen) {
            if (regionPolls < 20) { setTimeout(awaitRegions, 80); return; }
            const objects = descendants(Object.values(model.allGraphObjects?.() ?? {}));
            note({ regionModelShapes: objects.slice(0, 32).map((one) => ({
              keys: Object.keys(one ?? {}).sort().slice(0, 40),
              children: Array.isArray(one?.children) ? one.children.length : -1,
              regions: Array.isArray(one?.Regions?.children) ? one.Regions.children.length : -1,
            })) });
            resolve(refuse("graph-region-semantics-missing"));
            return;
          }
          const regionControl = regionControls.find((radio) => nameOf(radio) === chosen.label);
          if (!regionControl) { resolve(refuse("graph-region-control-missing")); return; }
          if (regionControls.some((radio) => radio.checked && radio !== regionControl)) {
            resolve(refuse("graph-linear-inequality-not-empty"));
            return;
          }
          if (!regionControl.checked && !choose(regionControl)) {
            resolve(refuse("graph-region-not-settled"));
            return;
          }
          let settlePolls = 0;
          const settle = () => {
            settlePolls += 1;
            const holding = pinned() && boundaryControl.checked && regionControl.checked
              && fields.every((field, index) => String(field.value) === spellings[index]);
            if (!holding) { resolve(refuse("graph-linear-inequality-not-settled")); return; }
            if (settlePolls >= 10) { resolve({ ok: true, code: "graph-linear-inequality-verified",
              boundary: plan.boundary, points: wanted,
              region: chosen.label,
              testPoint: [chosen.point.x, chosen.point.y] }); return; }
            setTimeout(settle, 80);
          };
          setTimeout(settle, 80);
        };
        setTimeout(awaitRegions, 80);
      });
    }
    // One surface per line, not per container: Hawkes' template and its engine
    // both mark a container `role="application"`, one inside the other.
    const lineSurfaces = [...new Set([...document.querySelectorAll("svg#svg_numberline")]
      .map((svg) => svg.closest?.('[role="application"]'))
      .filter((node) => node && node.getBoundingClientRect().width > 0))];
    if (document.querySelectorAll('#QGraph').length === 0
      && lineSurfaces.length > 0) {
      return numberLine(lineSurfaces);
    }
    const legacyRoots = [...document.querySelectorAll('#QGraph')];
    const renderedChoices = [...document.querySelectorAll('svg[role="presentation"]')]
      .filter(visible);
    const roots = legacyRoots.length > 0 ? legacyRoots
      : renderedChoices.length >= 2 ? renderedChoices : [];
    if (roots.length >= 2 && roots.every(visible)) {
      // A rendered graph alternative is a three-way page-owned relation:
      // its SVG is inside one selectable owner, and one QASystem's drawing
      // group is inside that SVG.  Resolve those relations independently for
      // every option; neither DOM/model order nor screen position participates.
      const systemsOf = (model) => Object.values(model.allGraphObjects?.() ?? {})
        .filter((one) => one?.type === "inequalities"
          && Array.isArray(one?.children) && Array.isArray(one?.Regions?.children));
      const choices = [];
      const owners = [];
      const usedModels = new Set();
      const close = (left, right) => Math.abs(left - right) < 1e-8;
      const writtenNumber = (value) => {
        const fixed = (Math.abs(value) < 1e-12 ? 0 : value).toFixed(12)
          .replace(/\.0+$/, "").replace(/(\.[0-9]*?)0+$/, "$1");
        return fixed === "-0" ? "0" : fixed;
      };
      const xmlOf = (object) => {
        if (typeof object?.objectXML !== "function") return null;
        try {
          return new DOMParser().parseFromString(String(object.objectXML()), "application/xml");
        } catch {
          return null;
        }
      };
      for (const root of roots) {
        const owner = root.closest?.('[role="radio"]');
        const linked = graphModels.flatMap((model) => systemsOf(model)
          .filter((system) => root.contains?.(system?.group))
          .map((system) => ({ model, system })));
        if (!owner || !owner.contains(root) || !visible(owner)
          || owner.getAttribute?.("role") !== "radio"
          || owner.getAttribute?.("aria-disabled") === "true"
          || linked.length !== 1 || usedModels.has(linked[0].model)) {
          return refuse("graph-choice-ownership-unreadable");
        }
        usedModels.add(linked[0].model);
        owners.push(owner);
        const { model, system } = linked[0];
        if (model.getEnableState?.() !== true) return refuse("graph-choice-disabled");
        const lines = system.children.filter((one) => Array.isArray(one?.Equation)
          && one.Equation.length === 3 && xmlOf(one));
        if (lines.length !== 2 || system.Regions.children.length !== 3) {
          return refuse("graph-choice-system-unsupported");
        }
        const boundaries = lines.map((line) => {
          const xml = xmlOf(line);
          const name = String(line.ID
            || xml?.querySelector("line > name")?.textContent || "").trim();
          const stroke = String(xml?.querySelector("line > stroke")?.textContent || "").trim();
          // Hawkes publishes these alternatives in both coordinate axes. A
          // vertical boundary is `a*x+c=0`; a horizontal one is `b*y+c=0`.
          // Some templates additionally serialize the coordinate explicitly,
          // but others publish only Equation, so the two sources corroborate
          // one another when both exist and Equation remains authoritative.
          const coefficients = line.Equation.map(Number);
          const equationAxis = Math.abs(coefficients[0]) > 1e-12
              && Math.abs(coefficients[1]) < 1e-12 ? "x"
            : Math.abs(coefficients[0]) < 1e-12
              && Math.abs(coefficients[1]) > 1e-12 ? "y" : "";
          const equationValue = equationAxis === "x" ? -coefficients[2] / coefficients[0]
            : equationAxis === "y" ? -coefficients[2] / coefficients[1] : NaN;
          const statedText = equationAxis
            ? xml?.querySelector(`${equationAxis}coordinate`)?.textContent : undefined;
          const stated = statedText === undefined ? NaN : Number(statedText);
          const intercepts = (Array.isArray(line.children) ? line.children : [])
            .map(xmlOf).filter(Boolean).map((point) => ({
              type: String(point.querySelector("point > type")?.textContent || "").trim(),
              x: Number(point.querySelector("point > x")?.textContent),
              y: Number(point.querySelector("point > y")?.textContent),
            })).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
          const matchingIntercepts = intercepts.filter((point) => equationAxis === "x"
            ? point.type === "xintercept" && Math.abs(point.y) < 1e-12
            : equationAxis === "y"
              ? point.type === "yintercept" && Math.abs(point.x) < 1e-12 : false);
          const interceptValue = matchingIntercepts.length === 1
            ? matchingIntercepts[0][equationAxis] : NaN;
          const corroborates = (!Number.isFinite(stated) || close(stated, equationValue))
            && (!Number.isFinite(interceptValue) || close(interceptValue, equationValue));
          return { name, axis: equationAxis, value: equationValue, stroke,
            corroborates };
        });
        if (boundaries.some((line) => !line.name || !line.axis
          || !Number.isFinite(line.value) || !line.corroborates
          || !["solid", "dashed"].includes(line.stroke))
          || new Set(boundaries.map((line) => line.name)).size !== 2
          || new Set(boundaries.map((line) => line.axis)).size !== 1
          || close(boundaries[0].value, boundaries[1].value)) {
          return refuse("graph-choice-boundaries-unreadable");
        }
        const axis = boundaries[0].axis;
        const byName = new Map(boundaries.map((line) => [line.name, line.value]));
        const intervals = [];
        for (const region of system.Regions.children) {
          const xml = xmlOf(region);
          if (!xml) return refuse("graph-choice-regions-unreadable");
          if (xml.querySelector("region > shade")?.textContent !== "true") continue;
          const references = (tag) => String(xml.querySelector(tag)?.textContent || "")
            .split(",").map((one) => one.trim()).filter(Boolean);
          const minimum = references(`${axis}minimum`);
          const maximum = references(`${axis}maximum`);
          if ([...minimum, ...maximum].some((name) => !byName.has(name))) {
            return refuse("graph-choice-region-boundary-missing");
          }
          const left = minimum.length ? Math.max(...minimum.map((name) => byName.get(name))) : -Infinity;
          const right = maximum.length ? Math.min(...maximum.map((name) => byName.get(name))) : Infinity;
          // Hawkes keeps a deliberately empty center region on an exterior
          // choice (minimum at the right line, maximum at the left line).
          // Its own boundary references prove it empty; it contributes no set.
          if (left > right && !close(left, right)) continue;
          intervals.push({ left, right });
        }
        const ordered = boundaries.slice().sort((a, b) => a.value - b.value);
        const between = intervals.length === 1
          && Number.isFinite(intervals[0].left) && Number.isFinite(intervals[0].right)
          && close(intervals[0].left, ordered[0].value)
          && close(intervals[0].right, ordered[1].value);
        const outside = intervals.length === 2
          && intervals.some((part) => part.left === -Infinity && close(part.right, ordered[0].value))
          && intervals.some((part) => close(part.left, ordered[1].value) && part.right === Infinity);
        if (between === outside) return refuse("graph-choice-shading-unreadable");
        choices.push(`Graph: ${axis}=${writtenNumber(ordered[0].value)} ${ordered[0].stroke}; `
          + `${axis}=${writtenNumber(ordered[1].value)} ${ordered[1].stroke}; `
          + `shade=${between ? "between" : "outside"}`);
      }
      if (usedModels.size !== roots.length || usedModels.size !== graphModels.length
        || new Set(owners).size !== roots.length || new Set(choices).size !== roots.length) {
        return refuse("graph-choice-contract-ambiguous");
      }
      // Graphs_For_Multiple_Choice owns the alternatives as one active-mode
      // radio answer. Its mousedown handler updates all three representations:
      // objProps.selectedGraphIndex, each owner's ARIA/class state, and the
      // mode's getUserAnswer()/isEmpty() result. Require that whole contract;
      // a CSS highlight by itself is not proof that Hawkes accepted an answer.
      const activeMode = () => window.objActiveMode
        ?? (typeof objActiveMode !== "undefined" ? objActiveMode : undefined);
      const mode = activeMode();
      const props = mode?.controlsJSON?.objProps;
      const templated = typeof mode?.getUserAnswer === "function"
        && typeof mode?.isEmpty === "function"
        && Number(props?.numberOfGraphs) === roots.length;
      if (!templated) return refuse("graph-choice-answer-model-missing");
      const selected = () => owners.map((owner) => owner.getAttribute?.("aria-checked") === "true");
      const modelState = () => ({
        selectedIndex: Number(props.selectedGraphIndex),
        answer: String(mode.getUserAnswer()),
        empty: mode.isEmpty() === true,
      });
      const snapshot = { choices: [...choices], selected: selected(), model: modelState() };
      if (offered !== null) {
        if (!offered || typeof offered !== "object"
          || typeof offered.choice !== "string"
          || JSON.stringify(offered.snapshot) !== JSON.stringify(snapshot)) {
          return refuse("graph-choice-target-stale");
        }
        const matching = choices.map((choice, index) => ({ choice, index }))
          .filter((entry) => entry.choice === offered.choice);
        if (matching.length !== 1) return refuse("graph-choice-answer-unmatched");
        const wanted = matching[0].index;
        const pinned = () => roots.every((root, index) => root.isConnected !== false
          && owners[index].isConnected !== false && owners[index].contains(root)
          && visible(root) && visible(owners[index]));
        if (!pinned()) return refuse("graph-choice-target-stale");
        if (!selected()[wanted]) {
          owners[wanted].dispatchEvent(new MouseEvent("mousedown", {
            bubbles: true, cancelable: true, view: window, button: 0, buttons: 1,
          }));
        }
        return new Promise((resolve) => {
          let polls = 0;
          const settle = () => {
            polls += 1;
            const readBack = selected();
            const state = modelState();
            if (pinned() && readBack[wanted]
              && readBack.filter(Boolean).length === 1
              && owners[wanted].classList?.contains("highlightGraph")
              && owners.every((owner, index) => index === wanted
                || !owner.classList?.contains("highlightGraph"))
              && state.selectedIndex === wanted + 1
              && state.empty === false) {
              if (polls < 8) { setTimeout(settle, 100); return; }
              resolve({ ok: true, code: "graph-choice-verified",
                choice: offered.choice, selected: wanted, events: snapshot.selected[wanted] ? 0 : 1 });
              return;
            }
            if (polls < 20) { setTimeout(settle, 100); return; }
            resolve(refuse("graph-choice-not-settled"));
          };
          setTimeout(settle, 100);
        });
      }
      return { ok: true, kind: "option", surface: "graph-choice",
        code: "graph-choice-described", enabled: true, choices,
        snapshot,
        probe: { engine: "cartesian-graph-choice", choices: choices.length,
          boundaries: 2, regions: 3, ownership: "model-group-inside-selectable-svg" } };
    }
    if (roots.length !== 1 || roots[0].getBoundingClientRect().width <= 0) return refuse("graph-missing");
    const root = roots[0];
    if (graphModels.length !== 1) return refuse("graph-model-missing");
    const model = graphModels[0];
    const structuralDescendants = (objects) => {
      const all = [];
      const visit = (one, depth = 0) => {
        if (!one || depth > 5 || all.some((entry) => entry.object === one)) return;
        all.push({ object: one, depth });
        if (one.Regions) visit(one.Regions, depth + 1);
        if (Array.isArray(one.children)) one.children.forEach((child) => visit(child, depth + 1));
      };
      objects.forEach((one) => visit(one));
      return all;
    };
    const rawObjects = Object.values(model.allGraphObjects?.() ?? {});
    const systemObjects = rawObjects.filter((one) => one?.type === "inequalities"
      && Array.isArray(one?.children) && Array.isArray(one?.Regions?.children));
    const systemChoices = grouped.length === 1 ? grouped[0].map(nameOf) : [];
    const operations = systemChoices.map(setOperation);
    if (fields.length === 0 && grouped.length === 1 && grouped[0].length === 2
      && operations.slice().sort().join("\u001f") === "intersection\u001funion"
      && systemObjects.length === 1) {
      const nodes = ["questionDescription", "questionString", "partInformation"]
        .map((id) => document.getElementById(id));
      if (nodes.some((node) => !node)) return refuse("graph-question-missing");
      const asked = () => nodes.map((node) => new XMLSerializer()
        .serializeToString(node)).join("\u001f");
      const system = systemObjects[0];
      const lineObjects = system.children.filter((one) => Array.isArray(one?.Equation)
        && one.Equation.length === 3 && typeof one?.objectXML === "function");
      const regionObjects = system.Regions.children;
      note({ systemContract: {
        lines: lineObjects.length,
        regions: regionObjects.length,
        systemXML: typeof system.objectXML,
        userAnswer: typeof system.userAnswer,
        regionRole: String(system.Regions.interactiveRole ?? ""),
        childRoles: regionObjects.map((region) => String(region?.interactiveRole ?? "")),
        regionXML: regionObjects.filter((region) => typeof region?.objectXML === "function").length,
      } });
      if (lineObjects.length !== 2 || regionObjects.length !== 4
        || typeof system.objectXML !== "function" || typeof system.userAnswer !== "function"
        || system.Regions.interactiveRole !== "norole"
        || regionObjects.some((region) => typeof region?.objectXML !== "function")) {
        return refuse("graph-system-model-unsupported");
      }
      const radioState = () => grouped[0].map((radio) => ({
        id: radio.id, name: radio.name, operation: setOperation(nameOf(radio)),
        checked: radio.checked === true,
      }));
      const first = { question: asked(), radios: radioState(),
        system: String(system.objectXML()), answer: String(system.userAnswer()) };
      const context = { family: "linear-inequality-system",
        controls: "mounted-boundaries-combined-regions" };
      if (!offered) return { ok: true, kind: "graph", code: "graph-described",
        enabled: true, context, snapshot: first,
        probe: { engine: "cartesian-system", boundaries: lineObjects.length,
          regions: regionObjects.length, operations: operations.slice().sort() } };
      if (JSON.stringify(first) !== JSON.stringify(offered.snapshot)) {
        return refuse("graph-target-stale");
      }
      const exactKeys = (object, names) => object && Object.keys(object).sort().join()
        === names.split(" ").sort().join();
      const plan = offered.plan;
      if (!exactKeys(plan, "connector inequalities kind operation")
        || plan.kind !== "linear-inequality-system"
        || !["and", "or"].includes(plan.connector)
        || plan.operation !== (plan.connector === "or" ? "union" : "intersection")
        || !Array.isArray(plan.inequalities) || plan.inequalities.length !== 2
        || plan.inequalities.some((member) => !exactKeys(member, "boundary coefficients relation")
          || !exactKeys(member.coefficients, "constant x y")
          || !["<", "<=", ">", ">="].includes(member.relation)
          || member.boundary !== (["<", ">"].includes(member.relation) ? "dashed" : "solid"))) {
        return refuse("graph-plan-invalid");
      }
      const rational = (text) => {
        if (typeof text !== "string" || !/^-?(?:0|[1-9][0-9]*)(?:\/[1-9][0-9]*)?$/.test(text)) {
          throw Error("graph-plan-invalid");
        }
        const [top, bottom = "1"] = text.split("/");
        return Number(top) / Number(bottom);
      };
      const lineState = (line) => {
        const xml = String(line.objectXML());
        const parsed = new DOMParser().parseFromString(xml, "application/xml");
        return { object: line, id: String(line.ID ?? ""), xml,
          equation: line.Equation.map(Number),
          stroke: String(parsed.querySelector("line > stroke")?.textContent ?? "").trim() };
      };
      const lines = lineObjects.map(lineState);
      const proportional = (left, right) => {
        if (!left.every(Number.isFinite) || !right.every(Number.isFinite)) return false;
        const pivot = right.findIndex((value) => Math.abs(value) > 1e-9);
        if (pivot < 0 || Math.abs(left[pivot]) < 1e-9) return false;
        const scale = left[pivot] / right[pivot];
        return right.every((value, index) => Math.abs(left[index] - scale * value) < 1e-9);
      };
      const matches = plan.inequalities.map((member) => {
        const coefficients = [member.coefficients.x, member.coefficients.y,
          member.coefficients.constant].map(rational);
        return lines.filter((line) => line.stroke === member.boundary
          && proportional(line.equation, coefficients));
      });
      if (matches.some((found) => found.length !== 1)
        || matches[0][0] === matches[1][0]) return refuse("graph-system-boundaries-mismatch");
      const wanted = grouped[0].find((radio) => setOperation(nameOf(radio)) === plan.operation);
      if (!wanted) return refuse("graph-system-operation-missing");
      if (grouped[0].some((radio) => radio.checked && radio !== wanted)) {
        return refuse("graph-system-not-empty");
      }
      const pinned = () => root.isConnected && nodes.every((node) => node.isConnected)
        && asked() === first.question
        && grouped[0].every((radio, index) => radio.isConnected
          && radio.id === first.radios[index].id)
        && ![...document.querySelectorAll('[id*="customMessageBox"]')]
          .some((node) => node.getBoundingClientRect().height > 0);
      if (!pinned()) return refuse("graph-target-stale");
      if (!wanted.checked) {
        wanted.dispatchEvent(new MouseEvent("click", {
          bubbles: true, cancelable: true, view: window,
        }));
      }
      return new Promise((resolve) => {
        let polls = 0;
        const settle = () => {
          polls += 1;
          const currentModels = Object.values(window.quant_wp_UI?.controlsCollection ?? {})
            .filter((one) => one?.isGraph === true);
          const currentSystems = currentModels.length === 1
            ? Object.values(currentModels[0].allGraphObjects?.() ?? {})
              .filter((one) => one?.type === "inequalities"
                && Array.isArray(one?.children) && Array.isArray(one?.Regions?.children))
            : [];
          const current = currentSystems[0];
          const currentLines = current?.children?.filter((one) => Array.isArray(one?.Equation)
            && one.Equation.length === 3 && typeof one?.objectXML === "function") ?? [];
          const currentRegions = current?.Regions?.children ?? [];
          const selected = currentRegions.map((region) => ({
            region, id: String(region?.index ?? ""),
          })).filter(({ region }) => region.select === true);
          const expectedCount = plan.operation === "union" ? 3 : 1;
          const answer = String(current?.userAnswer?.() ?? "");
          // Hawkes owns these IDs. They are not positions and are not inferred
          // from the drawing; QARegions.userAnswer serializes the same `index`
          // values from its selected QARegion children.
          const selectedText = selected.map(({ id }) => id).join("");
          const regionStateAgrees = selected.length === expectedCount
            && selected.every(({ id }) => id !== "")
            && new Set(selected.map(({ id }) => id)).size === selected.length
            && selected.every(({ region }) => {
              const xml = new DOMParser().parseFromString(String(region.objectXML()), "application/xml");
              return xml.querySelector("region > isselected")?.textContent === "true"
                && xml.querySelector("region > shade")?.textContent === "true";
            })
            && answer === `<selectedregions>${selectedText}</selectedregions><emptycheck>false</emptycheck>`;
          const boundariesHeld = currentLines.length === 2
            && currentLines.map((line) => String(line.objectXML())).join("\u001f")
              === lines.map((line) => line.xml).join("\u001f");
          note({ systemReadback: {
            operationSelected: wanted.checked === true,
            selected: selected.length,
            selectedIds: selectedText,
            answer,
            regionStateAgrees,
            boundariesHeld,
          } });
          if (pinned() && wanted.checked && regionStateAgrees && boundariesHeld) {
            if (polls < 8) { setTimeout(settle, 100); return; }
            resolve({ ok: true, code: "graph-linear-inequality-system-verified",
              operation: plan.operation, boundaries: 2, selectedRegions: selected.length,
              events: 1 });
            return;
          }
          if (polls < 20) { setTimeout(settle, 100); return; }
          resolve(refuse(boundariesHeld
            ? "graph-system-region-not-settled" : "graph-system-boundaries-changed"));
        };
        setTimeout(settle, 100);
      });
    }
    const objectShapes = structuralDescendants(rawObjects).slice(0, 32).map(({ object, depth }) => ({
      depth,
      type: String(object?.constructor?.name ?? ""),
      keys: Object.keys(object ?? {}).sort().slice(0, 64),
      propertyTypes: Object.fromEntries(Object.keys(object ?? {}).sort().slice(0, 64)
        .map((key) => [key, typeof object[key]])),
      prototype: Object.getOwnPropertyNames(Object.getPrototypeOf(object) ?? {})
        .filter((name) => name !== "constructor").sort().slice(0, 96),
      children: Array.isArray(object?.children) ? object.children.length : -1,
      regions: Array.isArray(object?.Regions?.children) ? object.Regions.children.length : -1,
      index: Number.isInteger(object?.Index) ? object.Index : null,
    }));
    const graphXml = new DOMParser().parseFromString(String(model.graphXML?.() ?? ""), "application/xml");
    note({
      rootShapes: [...root.querySelectorAll(":scope > *, :scope > * > *")].slice(0, 32)
        .map((node) => `${node.tagName}.${String(node.getAttribute?.("class") ?? "").trim()}`),
      graphXmlTags: [...new Set([...graphXml.querySelectorAll("*")].map((node) => node.tagName))].slice(0, 64),
      objectShapes,
    });
    const plotRect = root.querySelector("svg defs clipPath rect");
    if (!plotRect) return refuse("graph-renderer-unsupported");
    const plotWidth = Number(plotRect.getAttribute("width"));
    const plotHeight = Number(plotRect.getAttribute("height"));
    if (!(plotWidth > 0 && plotHeight > 0)) return refuse("graph-renderer-unsupported");
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

    // --- a graph answered by placing point controls --------------------------
    //
    // Hawkes uses the same draggable controls for literal points and for the
    // two defining points of a derived line. The plans stay distinct; only the
    // page-owned movement and read-back machinery is shared.
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
      const labelsOf = (anchor) => String(anchor.getAttribute("aria-labelledby") ?? "")
        .split(/\s+/).map((id) => String(document.getElementById(id)?.textContent ?? "").trim());
      const anchorFor = (spot) => {
        const byId = plotAnchors.filter((a) =>
          spot.ID !== undefined && String(a.id).split(/[_-]/).includes(String(spot.ID)));
        const title = String(spot.title ?? "").trim();
        const byName = title.length > 0
          ? plotAnchors.filter((a) => labelsOf(a).includes(title)) : [];
        if (byId.length > 1 || byId.length === 0 && byName.length > 1
          || byId.length === 1 && byName.length === 1 && byId[0] !== byName[0]) return null;
        return byId[0] ?? byName[0] ?? null;
      };
      const paired = spots.map(anchorFor);
      if (paired.some((a) => a === null)
        || new Set(paired).size !== spots.length) return refuse("graph-points-ambiguous");
      const circleOf = paired.map((a) => a.querySelector("circle"));
      if (circleOf.some((c) => !c)) return refuse("graph-controls-unsupported");
      const xml = new DOMParser().parseFromString(model.graphXML(), "application/xml");
      // Labels belong to graph objects by their explicit XML ID, never their
      // array position or current screen coordinate. An unlabeled line keeps
      // its existing set-of-points contract; a literal labeled plot cannot.
      const pointSpecs = [...xml.querySelectorAll("graphobjects point")];
      const directText = (node, name) => {
        const matches = [...node.children].filter((child) => child.tagName.toLowerCase() === name);
        return matches.length === 1 ? String(matches[0].textContent).trim() : "";
      };
      const labelFor = (spot) => {
        const current = new DOMParser().parseFromString(model.graphXML(), "application/xml");
        const matches = [...current.querySelectorAll("graphobjects point")]
          .filter((node) => node.getAttribute("id") === String(spot.ID));
        const label = matches.length === 1 ? directText(matches[0], "label") : "";
        return spot.label !== undefined && String(spot.label).trim() !== label ? "" : label;
      };
      const labels = spots.map(labelFor);
      const instruction = ["questionDescription", "partInformation"].map((id) =>
        document.getElementById(id)?.textContent ?? "").join(" ");
      const integerLine = /\b(?:graph|plot)\b[^.?!]*\b(?:any\s+)?(?:two|2)\s+(?:ordered\s+pairs|points)\b[^.?!]*\binteger(?:[-\s]+valued?)?\s+coordinates\b[^.?!]*\b(?:satisfy|satisfying)\b[^.?!]*\bequation\b/i.test(instruction);
      const literalPlot = !integerLine
        && /\b(?:plot|place|graph|draw)\b[^.?!]*\bpoints?\b/i.test(instruction);
      const hasLabels = literalPlot && (pointSpecs.some((node) => directText(node, "label"))
        || spots.some((spot) => String(spot.label ?? "").trim()));
      if (hasLabels && (pointSpecs.length !== spots.length
        || labels.some((label) => !/^[^\s(),;:]{1,16}$/.test(label))
        || new Set(labels).size !== spots.length
        || new Set(spots.map((spot) => String(spot.ID))).size !== spots.length)) {
        return refuse("graph-point-labels-ambiguous");
      }
      // Read each label with its own literal MathML pair from the page's
      // question HTML. Row boundaries preserve adjacency (A (x,y)), not order.
      // This is bounded transcription; Facet still reads and verifies the math.
      const readLabeledPoints = () => {
        if (!literalPlot) return null;
        const owned = window.questionPartViewModel?.questionString;
        const source = typeof owned === "string" ? owned
          : window.ko?.isObservable?.(owned) ? owned()
            : new XMLSerializer().serializeToString(document.getElementById("questionString"));
        if (typeof source !== "string" || source.length > 40000) {
          throw Error("graph-point-labels-ambiguous");
        }
        const parsed = new DOMParser().parseFromString(source, "text/html");
        for (const fraction of [...parsed.querySelectorAll("mfrac")].reverse()) {
          if (fraction.children.length !== 2) throw Error("graph-point-labels-ambiguous");
          fraction.replaceWith(`${fraction.children[0].textContent}/${fraction.children[1].textContent}`);
        }
        for (const node of parsed.querySelectorAll("br")) node.replaceWith("\n");
        for (const node of parsed.querySelectorAll("p,li,tr,div")) node.append("\n");
        const rows = String(parsed.body.textContent).replace(/\u2212/g, "-")
          .split(/\n/).map((row) => row.trim()).filter(Boolean);
        const pair = /^([^\s(),;:]{1,16})\s*:?[\s]*\(\s*([+-]?\s*\d+(?:\s*\/\s*[1-9]\d*)?)\s*,\s*([+-]?\s*\d+(?:\s*\/\s*[1-9]\d*)?)\s*\)$/;
        const matches = rows.map((row) => pair.exec(row));
        if (!hasLabels && !matches.some(Boolean)) return null;
        if (!hasLabels || rows.length !== spots.length || matches.some((match) => !match)) {
          throw Error("graph-point-labels-ambiguous");
        }
        const exact = (raw) => {
          const compact = raw.replace(/\s/g, "");
          if (compact.length > 30) throw Error("graph-plan-invalid");
          const [a, b = "1"] = compact.split("/");
          let n = BigInt(a), d = BigInt(b), x = n < 0n ? -n : n, y = d;
          while (y) [x, y] = [y, x % y];
          n /= x; d /= x;
          const text = d === 1n ? String(n) : `${n}/${d}`;
          if (text.length > 30) throw Error("graph-plan-invalid");
          return text;
        };
        const points = matches.map((match) => ({label: match[1], x: exact(match[2]), y: exact(match[3])}));
        if (new Set(points.map((point) => point.label)).size !== spots.length
          || !points.every((point) => labels.includes(point.label))) {
          throw Error("graph-point-labels-ambiguous");
        }
        return points;
      };
      const labeledPoints = readLabeledPoints();
      const readAxis = (sel) => {
        const matches = [...xml.querySelectorAll(sel)];
        const raw = matches.length === 1 ? String(matches[0].textContent).trim() : "";
        return raw ? Number(raw) : NaN;
      };
      if (xml.querySelector("grid > type")?.textContent !== "cartesian") {
        return refuse("graph-orientation-unsupported");
      }
      const bounds = ["xmin", "xmax", "ymin", "ymax"].map((n) => readAxis(`cartesian > ${n}`));
      const snap = [spots[0].snapX, spots[0].snapY];
      if (![...bounds, ...snap].every(Number.isFinite) || !snap.every((n) => n > 0)
        || bounds[0] >= bounds[1] || bounds[2] >= bounds[3]
        || !spots.every((q) => q.snapX === snap[0] && q.snapY === snap[1])) {
        return refuse("graph-grid-unsupported");
      }
      const nodes = ["questionDescription", "questionString", "partInformation"]
        .map((id) => document.getElementById(id));
      if (nodes.some((n) => !n)) return refuse("graph-question-missing");
      const asked = () => nodes.map((n) => new XMLSerializer().serializeToString(n)).join("\u001f");
      const state = () => spots.map((q, i) => ({ id: q.ID, anchor: paired[i].id,
        ...(labeledPoints ? { label: labelFor(q) } : {}),
        x: q.x, y: q.y, cx: circleOf[i].getAttribute("cx"), cy: circleOf[i].getAttribute("cy") }));
      const shot = () => ({ question: asked(), xml: model.graphXML(), points: state(),
        ...(labeledPoints ? { labeledPoints: readLabeledPoints() } : {}),
        answer: model.userAnswer() });
      const first = shot();
      const context = { family: "points", count: spots.length, bounds, snap,
        ...(labeledPoints ? { labeled_points: labeledPoints } : {}),
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
      const linePlan = plan?.kind === "line";
      const pointPlan = plan?.kind === "points";
      if ((!pointPlan || !has(plan, "kind points"))
        && (!linePlan || !has(plan, "coefficients kind points"))) {
        return refuse("graph-plan-invalid");
      }
      if (!Array.isArray(plan.points) || plan.points.length !== spots.length) {
        return refuse("graph-plan-invalid");
      }
      const wanted = plan.points.map((q) => {
        if (pointPlan && !has(q, labeledPoints ? "label x y" : "x y")) throw Error("graph-plan-invalid");
        if (linePlan && (!has(q, "role x y")
          || !["x-intercept", "y-intercept", "substitute"].includes(q.role))) {
          throw Error("graph-plan-invalid");
        }
        return [num(q.x), num(q.y)];
      });
      const near = (a, b) => Math.abs(a - b) < 1e-9;
      if (integerLine) {
        if (!pointPlan || wanted.length !== 2 || labeledPoints
          || !Array.isArray(offered.coefficients) || offered.coefficients.length !== 3
          || !offered.coefficients.every((v) => typeof v === "string"
            && /^-?(?:0|[1-9][0-9]*)$/.test(v) && v.length <= 100)
          || !wanted.every((point) => point.every(Number.isSafeInteger))
          || wanted[0].every((v, i) => v === wanted[1][i])) return refuse("graph-plan-invalid");
        const [a, b, c] = offered.coefficients.map((v) => BigInt(v));
        if ((!a && !b) || !wanted.every(([x, y]) =>
          a * BigInt(x) + b * BigInt(y) + c === 0n)) return refuse("graph-plan-invalid");
      } else if (pointPlan && offered.coefficients?.length) return refuse("graph-plan-invalid");
      if (linePlan) {
        if (!has(plan.coefficients, "constant x y")
          || !Array.isArray(offered.coefficients)
          || offered.coefficients.length !== 3
          || offered.coefficients.join("\u001f") !== [
            plan.coefficients.x, plan.coefficients.y, plan.coefficients.constant,
          ].join("\u001f")) return refuse("graph-plan-invalid");
        const coefficients = offered.coefficients.map(num);
        if ((!coefficients[0] && !coefficients[1])
          || wanted.length !== 2
          || near(wanted[0][0], wanted[1][0]) && near(wanted[0][1], wanted[1][1])
          || !wanted.every(([x, y]) => near(
            coefficients[0] * x + coefficients[1] * y + coefficients[2], 0
          ))) return refuse("graph-plan-invalid");
      }
      if (!wanted.every(([x, y]) => x >= bounds[0] && x <= bounds[1]
        && y >= bounds[2] && y <= bounds[3])) return refuse("graph-plan-off-grid");
      const order = (a, b) => (a[0] - b[0]) || (a[1] - b[1]);
      const targets = [...wanted].sort(order);
      let goal;
      if (labeledPoints) {
        if (!pointPlan || new Set(plan.points.map((point) => point.label)).size !== spots.length
          || !plan.points.every((point) => labeledPoints.some((owned) =>
            owned.label === point.label && owned.x === point.x && owned.y === point.y))) {
          return refuse("graph-point-labels-ambiguous");
        }
        goal = labels.map((label) => {
          const point = plan.points.find((point) => point.label === label);
          if (!point) throw Error("graph-point-labels-ambiguous");
          return [num(point.x), num(point.y)];
        });
      } else {
        // Only genuinely unlabeled points are interchangeable. Preserve the
        // existing positional optimization for that route and derived lines.
        const seats = spots.map((q, i) => [q.x, q.y, i]).sort(order).map((t) => t[2]);
        goal = [];
        seats.forEach((at, k) => { goal[at] = targets[k]; });
      }
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
        const currentObjects = Object.values(model.allGraphObjects());
        const currentSpots = currentObjects.every(movable) ? currentObjects
          : currentObjects.length === 1 ? currentObjects[0]?.children : null;
        if (root.querySelector("svg defs clipPath rect") !== plotRect
          || Number(plotRect.getAttribute("width")) !== plotWidth
          || Number(plotRect.getAttribute("height")) !== plotHeight
          || !root.isConnected
          || document.querySelectorAll('#QGraph[role="application"]').length !== 1
          || document.getElementById("QGraph") !== root || !model.getEnableState()
          || Object.values(window.quant_wp_UI.controlsCollection)[0] !== model
          || !Array.isArray(currentSpots) || currentSpots.length !== spots.length
          || !spots.every((point) => currentSpots.includes(point))
          || nodes.some((n) => !n.isConnected || document.getElementById(n.id) !== n)
          || spots.some((q, i) => !paired[i].isConnected
            || anchorFor(q) !== paired[i]
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
                || q.anchor !== first.points[j].anchor
                || q.label !== first.points[j].label)) throw Error("graph-target-stale");
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
      if (labeledPoints) {
        const verified = () => {
          pinned();
          if (!spots.every((point, i) => labelFor(point) === labels[i]
            && near(point.x, goal[i][0]) && near(point.y, goal[i][1])
            && point.plotted === true)) return false;
          const readback = new DOMParser().parseFromString(model.userAnswer(), "application/xml");
          const owned = [...readback.querySelectorAll("point")];
          return owned.length === spots.length && spots.every((point, i) => {
            const matches = owned.filter((node) => node.getAttribute("id") === String(point.ID));
            if (matches.length !== 1) return false;
            // Hawkes' answer XML names owners by ID, without repeating their
            // labels. Join that ID to the freshly verified graph model; if an
            // answer does repeat a label, it must agree too.
            const label = directText(matches[0], "label");
            const x = directText(matches[0], "x"), y = directText(matches[0], "y");
            return (!label || label === labels[i]) && x !== "" && y !== ""
              && near(Number(x), goal[i][0]) && near(Number(y), goal[i][1]);
          });
        };
        if (!verified()) return refuse("graph-point-label-readback-failed");
        return new Promise((resolve) => setTimeout(() => {
          try {
            resolve(verified() ? {ok: true, code: "graph-labeled-points-verified",
              points: spots.length, events: struck, plotKeys, labeled: true, settled: true}
              : refuse("graph-point-label-readback-failed"));
          } catch { resolve(refuse("graph-target-stale")); }
        }, 250));
      }
      if (integerLine) {
        const verified = () => {
          pinned();
          const readback = new DOMParser().parseFromString(model.userAnswer(), "application/xml");
          const owned = [...readback.querySelectorAll("point")];
          return owned.length === spots.length && spots.every((point, i) => {
            const matches = owned.filter((node) => node.getAttribute("id") === String(point.ID));
            if (matches.length !== 1 || point.plotted !== true
              || point.x !== goal[i][0] || point.y !== goal[i][1]) return false;
            const x = directText(matches[0], "x"), y = directText(matches[0], "y");
            return x !== "" && y !== ""
              && Number(x) === goal[i][0] && Number(y) === goal[i][1];
          });
        };
        if (!verified()) return refuse("graph-line-readback-failed");
        return new Promise((resolve) => setTimeout(() => {
          try {
            resolve(verified() ? {ok: true, code: "graph-integer-line-points-verified",
              points: spots.length, events: struck, plotKeys, settled: true}
              : refuse("graph-line-readback-failed"));
          } catch { resolve(refuse("graph-target-stale")); }
        }, 250));
      }
      if (linePlan) {
        const readback = new DOMParser().parseFromString(
          model.userAnswer(), "application/xml"
        );
        const pagePoints = [...readback.querySelectorAll("point")].map((point) => [
          Number(point.querySelector("x")?.textContent),
          Number(point.querySelector("y")?.textContent),
        ]).sort(order);
        if (pagePoints.length !== targets.length
          || !pagePoints.every(([x, y], i) =>
            near(x, targets[i][0]) && near(y, targets[i][1]))) {
          return refuse("graph-line-readback-failed");
        }
      }
      return { ok: true, code: linePlan ? "graph-line-verified" : "graph-plotted",
        points: spots.length,
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
