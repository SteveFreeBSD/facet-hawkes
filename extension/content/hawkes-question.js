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
  // A digest of this complete content-script source, with this literal
  // replaced by twelve zeroes before hashing. The live reader returns it with
  // every decision, and the observatory applies the same normalization to the
  // tree. Unlike the event-page marker, this proves which Hawkes reader was
  // injected into the authoritative page DOM.
  const HAWKES_READER_BUILD = "c34c39037c54";

  const ANSWER_CONTROLS =
    'input.qbaseCSS, input[id^="txtAns"], input.boxStyle, input[id$="_optchk"], '
    + 'input[type="radio"].opt, #QGraph[role="application"]';

  // Kept in step with `common/config.js` by the build's shared-constant
  // check; this file is injected as a classic script and imports nothing.
  const MAX_ANSWER_PARTS = 5;

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
  //
  // Every refusal is named. The codes carry no coursework -- a count, a
  // selector, or the size of a disagreement -- and exist because "no readable
  // markup" told a live sweep nothing at all about which of nine conditions
  // had not held.
  const graph = (() => {
    const refuse = (graphReason) => ({ points: null, graphReason });
    const parts = [...document.querySelectorAll("#partInformation")];
    if (parts.length !== 1) return refuse(`part-count-${parts.length}`);
    if (!/quadratic regression/i.test(parts[0].textContent)) {
      return refuse("no-regression-instruction");
    }
    const svgs = [...parts[0].querySelectorAll("svg")];
    if (svgs.length !== 1) return refuse(`svg-count-${svgs.length}`);
    const svg = svgs[0];
    const points = [...svg.querySelectorAll("g.graph-objects > g.point.disable")];
    const axes = ["horizontal", "vertical"].map(axis => {
      const text = svg.querySelector(`g.${axis}-axis desc`)?.textContent ?? "";
      const match = text.match(/starts at (-?\d+), and ends at (-?\d+);/);
      return match ? [Number(match[1]), Number(match[2])] : null;
    });
    const grid = svg.querySelector("g.cartesian-grid");
    // Viewport coordinates, for the grid and for every dot alike. `getBBox`
    // reports an element's own user space, so a dot inside a translated group
    // and the grid around it are measured in *different* spaces -- and the
    // difference is a constant offset that looks exactly like a real
    // disagreement. Live, subtracting the grid's `getBBox` origin put every
    // point out by 1.43 units, which is that origin in axis units and nothing
    // to do with the data. A client rect is the same space for both whatever
    // transforms lie between them.
    const rect = grid?.getBoundingClientRect();
    if (points.length < 3 || points.length > 32) return refuse(`point-count-${points.length}`);
    if (axes.some(a => !a)) {
      return refuse(`axis-desc-${axes.map(a => (a ? "ok" : "missing")).join("-")}`);
    }
    if (!rect) return refuse("no-cartesian-grid");
    const width = rect.width;
    const height = rect.height;
    if (!(width > 0 && height > 0)) return refuse("grid-has-no-size");
    const result = [];
    let worst = 0;
    for (const point of points) {
      const desc = point.querySelector("desc")?.textContent ?? "";
      const circle = point.querySelector("circle");
      if (!circle) return refuse("point-without-circle");
      if (point.querySelector("a")) return refuse("point-is-actionable");
      // Hawkes drops a clause whose offset is zero. A point on the vertical
      // axis is described only as "A dot drawn 5 units below the origin", and
      // the origin itself has neither clause -- so requiring both refused
      // every point that sits on an axis, which is what `scatter.html` never
      // contained and lesson 3.3's live figure did. Each clause is read on its
      // own and a missing one is zero, but the sentence as a whole still has to
      // be one of Hawkes' own: anything else is refused rather than guessed.
      const drawn = /^A dot drawn (?:at )?(.*?)\s*the origin\.$/i.exec(desc);
      const horizontal = drawn && /(\d+)\s+units?\s+(left|right)\s+of\b/i.exec(drawn[1]);
      const vertical = drawn && /(\d+)\s+units?\s+(above|below)\b/i.exec(drawn[1]);
      const match = drawn && (horizontal || vertical || drawn[1].trim().length === 0);
      if (!match) {
        // The wording, with every number masked. `scatter.html` guessed this
        // sentence and live Hawkes says something else; the shape is what is
        // needed to fix that, and masking the digits keeps the point's
        // coordinates -- which are question data -- out of the log.
        const shape = desc
          .replace(/\d+/g, "#")
          .replace(/\s+/g, " ")
          .trim()
          .slice(0, 60);
        return refuse(`point-desc-unrecognised:${shape}`);
      }
      const x = horizontal
        ? Number(horizontal[1]) * (horizontal[2].toLowerCase() === "left" ? -1 : 1)
        : 0;
      const y = vertical
        ? Number(vertical[1]) * (vertical[2].toLowerCase() === "below" ? -1 : 1)
        : 0;
      // Measured from the grid's own corner. The offset was missing, so this
      // check only agreed when the plotting area happened to start at 0,0 --
      // true of a hand-authored fixture and of no real SVG, which is why the
      // cross-check passed offline and could not pass live. A bbox origin has
      // to come off the coordinate before it is scaled.
      const dot = circle.getBoundingClientRect();
      const drawnX = axes[0][0]
        + (dot.left + dot.width / 2 - rect.left) * (axes[0][1]-axes[0][0]) / width;
      const drawnY = axes[1][1]
        - (dot.top + dot.height / 2 - rect.top) * (axes[1][1]-axes[1][0]) / height;
      worst = Math.max(worst, Math.abs(drawnX - x), Math.abs(drawnY - y));
      // A rendered position is measured in fractional pixels, so exact
      // equality is not available and never was: the old 1e-9 only ever held
      // for coordinates authored to satisfy the arithmetic. A third of a grid
      // unit is far tighter than any real disagreement -- a dot described in
      // the wrong place is out by a whole unit at least -- and loose enough to
      // survive rounding and a dot's own stroke width.
      if (Math.abs(drawnX-x) > 0.33 || Math.abs(drawnY-y) > 0.33) {
        // The size of the disagreement, not the coordinates: enough to tell a
        // wrong reading from a rounded one, and no question content at all.
        return refuse(`drawn-mismatch-${worst.toPrecision(3)}`);
      }
      result.push({ x: String(x), y: String(y) });
    }
    return { points: result, graphReason: "" };
  })();
  const graphPoints = graph.points;

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
  /**
   * One cell's text, with MathJax counted once.
   *
   * MathJax leaves two copies of every expression in the document: the
   * glyphs a reader sees, and a visually hidden MathML copy for assistive
   * technology. `textContent` returns both, so a live cell holding $80 came
   * back as "$\u206280$\u206280" and was refused as not a number. The
   * assistive copy is dropped -- unless dropping it leaves nothing, which is
   * what an SVG-output MathJax cell looks like, and then it is all there is.
   * Invisible operators go either way: they are markup, not digits.
   *
   * A control's current contents are not text nodes, so nothing typed into an
   * answer box can arrive through here. That is what makes a blank cell read
   * as empty rather than as whatever the student last entered.
   */
  const clean = (node, excluded = () => false) => {
    const skip = typeof excluded === "function" ? excluded : () => false;
    const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
    const seen = [];
    const hidden = [];
    for (let text = walker.nextNode(); text !== null; text = walker.nextNode()) {
      if (skip(text)) continue;
      const target = text.parentElement?.closest("mjx-assistive-mml") ?? null;
      (target === null ? seen : hidden).push(text.textContent);
    }
    const text = seen.join("").trim().length > 0 ? seen.join("") : hidden.join("");
    return text.replace(/[\u2061-\u2064\u200b\ufeff]/g, "").replace(/\s+/g, " ").trim();
  };

  const attribute = (element, name) => typeof element?.getAttribute === "function"
    ? element.getAttribute(name)
    : element?.attributes?.[name] ?? null;

  /** A bounded structural name. Arbitrary page classes and ids stay out. */
  const structuralToken = (element) => {
    const classes = String(attribute(element, "class") ?? "").split(/\s+/)
      .filter((name) =>
        name === "sr-only"
        || /^(?:Q|Fraction|GridTable__|MathJax)[A-Za-z0-9_-]{0,31}$/.test(name)
      )
      .slice(0, 3);
    return [element.tagName.toLowerCase(), ...classes.map((name) => `.${name}`)].join("");
  };

  const structurallyHidden = (element) =>
    attribute(element, "aria-hidden") === "true"
    || String(attribute(element, "class") ?? "").split(/\s+/).includes("sr-only")
    || element.hidden === true
    || /(?:^|;)\s*(?:visibility\s*:\s*hidden|display\s*:\s*none)\b/i.test(
      attribute(element, "style") ?? ""
    );

  /**
   * Sanitized structural facts for every page-owned text owner in one cell.
   *
   * This deliberately records counts and relationships, never the text, raw
   * markup, element ids, or an answer control's `.value`. It uses the same
   * text-node walk as `clean`, so a refusal immediately names the owner that
   * made the reader's emptiness test fail, while also showing which owners
   * were safely excluded and why.
   */
  const cellStructure = (cell, control, excluded, logicalRow, logicalColumn) => {
    const controlBox = control.closest("span.QFractionBox");
    const labelledBy = new Set(
      String(attribute(control, "aria-labelledby") ?? "").split(/\s+/).filter(Boolean)
    );
    const owners = [];
    const ownerFor = (text) => text.parentElement?.closest(
      "label, [aria-hidden=\"true\"], [name=\"NotAnObject\"], .sr-only"
    ) ?? text.parentElement ?? cell;
    const walker = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT);
    for (let text = walker.nextNode(); text !== null; text = walker.nextNode()) {
      const normalized = text.textContent
        .replace(/[\u2061-\u2064\u200b\ufeff]/g, "")
        .replace(/\s+/g, " ")
        .trim();
      if (normalized.length === 0) continue;
      const owner = ownerFor(text);
      let found = owners.find((entry) => entry.node === owner);
      if (!found) {
        const path = [];
        for (
          let element = owner;
          element !== null && element !== cell && path.length < 8;
          element = element.parentElement
        ) {
          path.push(structuralToken(element));
        }
        const target = attribute(owner, "for");
        const ownerId = attribute(owner, "id");
        const targetElement = target ? document.getElementById?.(target) ?? null : null;
        found = {
          node: owner,
          detail: {
            tag: owner.tagName.toLowerCase(),
            classes: String(attribute(owner, "class") ?? "").split(/\s+/)
              .filter((name) =>
                name === "sr-only"
                || /^(?:Q|Fraction|GridTable__|MathJax)[A-Za-z0-9_-]{0,31}$/.test(name)
              )
              .slice(0, 3),
            path,
            textNodes: 0,
            textChars: 0,
            ignored: true,
            assistiveMath: owner.closest("mjx-assistive-mml") !== null,
            hidden: structurallyHidden(owner),
            srOnly: owner.matches(".sr-only"),
            forControl: target === control.id,
            forOther: target !== null && target !== "" && target !== control.id,
            forCellControl: targetElement !== null
              && targetElement.matches(ANSWER_CONTROLS)
              && cell.contains(targetElement),
            targetVisible: targetElement !== null && visible(targetElement),
            target: targetElement === null ? "none" : structuralToken(targetElement),
            labelledByControl: ownerId !== null && ownerId !== "" && labelledBy.has(ownerId),
            containsControl: owner.contains(control),
            insideControlBox: controlBox?.contains(owner) === true,
            containsControlBox: controlBox !== null && owner.contains(controlBox),
            childElements: owner.children.length,
            controls: owner.querySelectorAll(ANSWER_CONTROLS).length,
            math: owner.querySelectorAll("math").length,
            mathJax: owner.querySelectorAll("mjx-container, mjx-assistive-mml, .MathJax").length,
          },
        };
        owners.push(found);
      }
      found.detail.textNodes += 1;
      found.detail.textChars += normalized.length;
      found.detail.ignored = found.detail.ignored
        && (excluded(text) || text.parentElement?.closest("mjx-assistive-mml") !== null);
    }
    return {
      logicalRow,
      logicalColumn,
      childElements: cell.children.length,
      controls: cell.querySelectorAll(ANSWER_CONTROLS).length,
      math: cell.querySelectorAll("math").length,
      mathJax: cell.querySelectorAll("mjx-container, mjx-assistive-mml, .MathJax").length,
      textOwners: owners.slice(0, 6).map((entry) => entry.detail),
    };
  };

  /**
   * The page-owned accessibility prose inside Hawkes' live answer widget.
   *
   * The real blank cell puts two `label.sr-only` elements inside this exact
   * wrapper chain. One labels the visible textbox and the other labels a
   * hidden answer-control input in the same cell; their text is accessibility
   * decoration, not a value in the table. A label outside this chain, one
   * without an explicit target, one targeting outside this cell, one
   * containing mathematics or another answer control, and every other text
   * node remain data and make the cell nonempty.
   */
  /**
   * The two boxes of one expanded answer cell, numerator first.
   *
   * A Hawkes answer cell owns a numerator control and a denominator control.
   * Only the numerator's box is drawn until someone types `/`, at which point
   * the cell shows both -- and that is still one answer, `16/9`, not two. So
   * a four-blank table with one fraction in it shows five boxes, and with all
   * four filled in shows eight, while the mathematics never stops asking for
   * four values. Reading those as separate blanks would renumber every answer
   * after the first fraction; refusing them made the whole table unreadable
   * the moment a fraction was entered in it, by hand or by this add-on.
   *
   * The cell is still named by its numerator, which is the id every earlier
   * reading of this table already used.
   */
  const fractionPair = (controls) => {
    if (controls.length !== 2) {
      return null;
    }
    const named = controls.map((one) => String(attribute(one, "id") ?? ""));
    const bases = named.map((id) => id.replace(/_(?:num|den)$/, ""));
    if (bases[0].length === 0 || bases[0] !== bases[1]) {
      return null;
    }
    const numerator = controls[named.findIndex((id) => id.endsWith("_num"))];
    const denominator = controls[named.findIndex((id) => id.endsWith("_den"))];
    return numerator && denominator ? { numerator, denominator } : null;
  };

  const hawkesAnswerLabel = (text, cell, control) => {
    const label = text.parentElement?.closest("label.sr-only") ?? null;
    const fractionBox = control.closest("span.QFractionBox");
    const boxStyle = fractionBox?.parentElement ?? null;
    const fractionCell = boxStyle?.parentElement ?? null;
    const gridCell = fractionCell?.parentElement ?? null;
    if (
      label === null
      || fractionBox === null
      || boxStyle?.matches("span.FractionBoxStyle") !== true
      || fractionCell?.matches("span.FractionCell") !== true
      || gridCell?.matches("span.GridTable__Div_NoPad") !== true
      || !cell.contains(gridCell)
      || !gridCell.contains(label)
      || label.querySelector(`math, ${ANSWER_CONTROLS}`) !== null
    ) {
      return false;
    }
    const targetId = attribute(label, "for");
    const target = targetId ? document.getElementById?.(targetId) ?? null : null;
    return target !== null
      && target.matches(ANSWER_CONTROLS)
      && cell.contains(target);
  };

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

  // Hawkes' live completion grid for `x = y²` is turned on its side: the
  // first column names the two coordinate rows and each following column is
  // one ordered pair. It has no `thead` and no row made of `th` cells. Keep
  // this recognition deliberately exact; accepting arbitrary first-column
  // labels would turn ordinary layout tables into questions.
  const rowHeadedGrid = (table) => {
    if (table.tHead !== null || table.rows.length !== 2) return null;
    const sourceRows = [...table.rows];
    const width = sourceRows[0]?.cells.length ?? 0;
    if (width < 3 || width > 33) return null;
    if (sourceRows.some((row) => row.cells.length !== width)) return null;
    const columns = sourceRows.map((row) => clean(row.cells[0]));
    if (columns[0] !== "x" || columns[1] !== "y") return null;
    if (sourceRows.some((row) => row.cells[0].querySelector(ANSWER_CONTROLS))) {
      return null;
    }
    return {
      columns,
      rows: Array.from(
        { length: width - 1 },
        (_, column) => sourceRows.map((row) => row.cells[column + 1])
      ),
    };
  };

  const dataTable = (() => {
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

  /**
   * The table a question is answered *in*, read as a table.
   *
   * A completion question draws the table and leaves a cell blank in each
   * logical record; the answer boxes are those cells. Nothing above the answer area states the
   * numbers, so the exact readings all came back empty and the question
   * crossed as its equation and a sentence -- `x = y²` and "Complete the table
   * of values below", with no table and no values. Live, on lesson 2.1, that
   * is a question nobody can answer: the givens are the question.
   *
   * This is the mirror of `dataTable` and shares its discipline. The table is
   * identified by *containing* answer controls rather than by being free of
   * them, the column headings survive, and every refusal is named. What is
   * carried is the grid: each cell is either a value the page states or a
   * blank, numbered in the order the page draws them, so a reply's part N and
   * the page's Nth box mean the same cell.
   *
   * Nothing is read out of an answer control. A blank is a *position*; a cell
   * holding a box and anything else is refused rather than guessed at.
   */
  const answerTable = (() => {
    const detail = {
      reader: "answer-table",
      schema: 1,
      build: HAWKES_READER_BUILD,
      decision: "refused",
      branch: "none",
      reason: "",
      candidates: {
        controls: 0,
        holding: 0,
        kept: 0,
        droppedHidden: 0,
        droppedNested: 0,
        droppedRows: 0,
        droppedHeader: 0,
      },
      table: null,
      cell: null,
    };
    const refuse = (tableReason, extra = {}) => ({
      table: null,
      tableReason,
      tableDetail: { ...detail, ...extra, decision: "refused", reason: tableReason },
    });
    const controls = [...document.querySelectorAll(ANSWER_CONTROLS)].filter(visible);
    detail.candidates.controls = controls.length;
    if (controls.length === 0) return refuse("no-answer-controls");
    // Which condition dropped each table that could have been this one.
    //
    // A bare `candidates-0` was one word for five conditions, and live it was
    // the whole of what a run had to say about a page whose table plainly held
    // five answer boxes: the reader refused it and named nothing. Hawkes lays
    // its pages out with tables, so a table holding a control is common; the
    // question is always which rule then rejected it, and that is a tally of
    // counts with no cell of anybody's coursework in it.
    const holding = [...document.querySelectorAll("table")].filter(
      (table) => table.querySelector(ANSWER_CONTROLS) !== null
    );
    detail.candidates.holding = holding.length;
    if (holding.length === 0) return refuse("no-table-holds-a-control");
    const dropped = { hidden: 0, nested: 0, rows: 0, header: 0 };
    const candidates = holding.filter((table) => {
      if (!visible(table)) return (dropped.hidden += 1) && false;
      if (table.querySelector("table") !== null) return (dropped.nested += 1) && false;
      if (table.rows.length > 33) return (dropped.rows += 1) && false;
      if (headerRow(table) === null && rowHeadedGrid(table) === null) {
        return (dropped.header += 1) && false;
      }
      return true;
    });
    detail.candidates.kept = candidates.length;
    detail.candidates.droppedHidden = dropped.hidden;
    detail.candidates.droppedNested = dropped.nested;
    detail.candidates.droppedRows = dropped.rows;
    detail.candidates.droppedHeader = dropped.header;
    if (candidates.length !== 1) {
      const why = Object.entries(dropped)
        .filter(([, count]) => count > 0)
        .map(([name, count]) => `-${name}-${count}`)
        .join("");
      return refuse(`held-${holding.length}-kept-${candidates.length}${why}`);
    }
    const table = candidates[0];
    const header = headerRow(table);
    const rowHeaded = header === null ? rowHeadedGrid(table) : null;
    detail.branch = header === null ? "row-headed" : "column-headed";
    const columns = header === null
      ? rowHeaded.columns
      : [...header.cells].map(clean);
    if (columns.length < 2 || columns.length > 8) {
      return refuse(`columns-${columns.length}`);
    }
    if (columns.some((name) => name.length === 0 || name.length > 80)) {
      return refuse("column-unnamed");
    }
    const body = header === null
      ? rowHeaded.rows
      : [...table.rows]
        .filter((row) => row !== header && !(table.tHead?.contains(row) ?? false))
        .map((row) => [...row.cells]);
    detail.table = {
      domRows: table.rows.length,
      domColumns: table.rows[0]?.cells.length ?? 0,
      logicalRows: body.length,
      logicalColumns: columns.length,
      controls: table.querySelectorAll(ANSWER_CONTROLS).length,
      math: table.querySelectorAll("math").length,
      mathJax: table.querySelectorAll("mjx-container, mjx-assistive-mml, .MathJax").length,
      blanks: 0,
    };
    if (body.length < 2 || body.length > 32) return refuse(`rows-${body.length}`);
    if (body.some((row) => row.length !== columns.length)) {
      return refuse("row-not-rectangular");
    }

    const blanks = [];
    const targets = [];
    const rows = [];
    for (const [rowIndex, row] of body.entries()) {
      const cells = [];
      for (const [columnIndex, cell] of row.entries()) {
        const found = [...cell.querySelectorAll(ANSWER_CONTROLS)].filter(visible);
        // One logical blank can be showing two boxes; see `fractionPair`.
        const pair = fractionPair(found);
        if (found.length > 1 && pair === null) return refuse("cell-has-two-controls");
        const inside = pair ? [pair.numerator] : found;
        if (inside.length === 1) {
          // A blank holds the box and nothing a reader would see beside it.
          // `clean` walks text nodes, and what is typed into a control is not
          // one, so this is the page's own emptiness rather than the answer
          // box being read back as the question.
          const decoration = (text) => hawkesAnswerLabel(text, cell, inside[0]);
          if (clean(cell, decoration).length > 0) {
            return refuse("blank-not-empty", {
              cell: cellStructure(
                cell, inside[0], decoration, rowIndex + 1, columnIndex + 1
              ),
            });
          }
          // A blank is a control an answer can actually be typed into, and one
          // this browser can name again at insertion time. Anything else is
          // refused here rather than carried as a cell nobody can write to:
          // the numbering below is the only thing that will ever say which
          // value belongs in which box.
          const control = inside[0];
          if (
            control.disabled === true
            || control.readOnly === true
            || attribute(control, "disabled") !== null
            || attribute(control, "readonly") !== null
          ) {
            return refuse("blank-not-editable");
          }
          const controlId = String(attribute(control, "id") ?? "");
          if (controlId.length === 0 || controlId.length > 120) {
            return refuse("blank-without-an-id");
          }
          if (targets.some((entry) => entry.id === controlId)) {
            return refuse("blank-id-repeated");
          }
          blanks.push(control);
          detail.table.blanks = blanks.length;
          // Hawkes states the box's own bound in the markup; it is the one
          // per-cell entry rule the DOM publishes, and the collection model
          // cannot be asked for it per blank.
          const declared = Number(attribute(control, "maxlength"));
          targets.push({
            blank: blanks.length,
            id: controlId,
            row: rowIndex + 1,
            column: columnIndex + 1,
            maxLength: Number.isInteger(declared) && declared > 0 ? declared : null,
            // The other half of this one cell, when it is already showing it.
            // Named so a writer can place a fraction into the cell it belongs
            // to rather than discovering a second blank where there is none.
            denominator: pair ? String(attribute(pair.denominator, "id") ?? "") : null,
          });
          cells.push({ blank: blanks.length });
          continue;
        }
        // MathJax draws a radical sign; it does not write one. The visible
        // glyphs of `2√2` are the two digits and nothing between them, so a
        // cell it rendered is read from the MathML it left beside them or not
        // at all -- reading it as text would state a different number
        // confidently.
        const math = cell.querySelector("math");
        if (math !== null) {
          cells.push({
            mathml: new XMLSerializer().serializeToString(math).slice(0, 4000),
          });
          continue;
        }
        if (cell.querySelector("mjx-container, .MathJax, svg") !== null) {
          return refuse("drawn-without-mathml");
        }
        const text = clean(cell);
        if (text.length === 0 || text.length > 40) return refuse("cell-unreadable");
        cells.push({ text });
      }
      rows.push(cells);
    }
    if (blanks.length === 0) return refuse("no-blank-cells");
    if (blanks.length > MAX_ANSWER_PARTS) return refuse(`blanks-${blanks.length}`);
    // Every box on the page is one of these cells. A box elsewhere would mean
    // this grid is not the page's complete answer surface, so refuse it -- but
    // a cell showing a fraction is showing two boxes for one blank, and its
    // second half is not a box elsewhere. Counting those made a table that had
    // been read a moment earlier unreadable as soon as a fraction was in it.
    const halves = new Set(
      targets.map((one) => one.denominator).filter((id) => typeof id === "string")
    );
    const surface = controls.filter(
      (one) => !halves.has(String(attribute(one, "id") ?? ""))
    );
    if (blanks.length !== surface.length) return refuse("controls-outside-table");
    // Whether the page happens to draw these blanks in the order the
    // mathematics numbers them.
    //
    // Recorded, never required. A record-per-row table numbers boxes in
    // geometric reading order; the live row-headed grid does not, because its
    // records are columns -- blank numbers run left to right by ordered pair
    // while a geometric sweep meets every x-row control before any y-row one.
    // This used to refuse the disagreement, which was the right answer only
    // while a geometric sweep was the thing that found the boxes. The blank
    // numbering below now carries its own control per cell, so the two orders
    // are free to differ and the fact is kept for the log rather than acted on.
    const placed = [...blanks].sort((left, right) => {
      const a = left.getBoundingClientRect();
      const b = right.getBoundingClientRect();
      return a.top - b.top || a.left - b.left;
    });
    detail.table.domOrderMatches = placed.every(
      (field, index) => field === blanks[index]
    );
    // What each blank is, said in the table's own vocabulary: the heading over
    // its column, and either the record's own stated key or the record's
    // position. Built here because this is where the table's words are, and
    // used only to label the panel's own review -- it names a cell, never a
    // control, and it never leaves this browser.
    const labelled = targets.map((entry) => {
      const name = String(columns[entry.column - 1] ?? "").slice(0, 24);
      const record = rows[entry.row - 1]
        .map((cell) => (typeof cell.text === "string" ? cell.text : ""))
        .find((text) => text.length > 0) ?? "";
      return {
        ...entry,
        label: record.length > 0
          ? `${name} \u00b7 ${record.slice(0, 16)}`
          : `${name} #${entry.row}`,
      };
    });
    return {
      table: { node: table, columns, rows },
      tableReason: "",
      tableDetail: { ...detail, decision: "accepted", reason: "" },
      // One authoritative mapping: semantic blank N, and the exact visible,
      // editable control occupying that cell. It stays in the browser -- the
      // host is told the grid and nothing about the boxes -- and it is what
      // both the panel's review and the insertion are keyed to, so nothing
      // downstream ever has to rediscover a target and guess at its order.
      targets: {
        schema: 1,
        build: HAWKES_READER_BUILD,
        branch: detail.branch,
        count: labelled.length,
        domOrderMatches: detail.table.domOrderMatches,
        blanks: labelled,
      },
    };
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

  /**
   * Verbs that mark a line as the question's own instruction.
   *
   * "plot" was missing, and lesson 2.1 question 1 is the whole reason it is
   * here: "Plot the following points in the Cartesian plane." matched no verb,
   * so the instruction was never found and the prompt fell back to the
   * eleven-character "Step 1 of 1" -- the same failure the note below records
   * for the regression question, reached by a different road. The companion
   * then refused the plan it could otherwise have written down, because
   * nothing it was sent was a request to plot anything.
   */
  const INSTRUCTION =
    /graph|plot|simplify|evaluate|determine|convert|factor|express|rationaliz|find|add|subtract|multiply|expand|identify|write|state|name|list|select|choose|arrange|round|solve/i;

  /**
   * An element's own words: the text directly inside it, with the text of any
   * nested element left out.
   *
   * Hawkes writes a figure question as prose *and* a figure inside one
   * container -- the instruction is a bare text node, and the graph is a
   * sibling `div`. Skipping every container therefore skipped the only place
   * the instruction was. Live, on lesson 3.3's regression question, that left
   * an eleven-character prompt reading "Step 1 of 2" and nothing else: no
   * exact operation can match that, so the question went to a model as a
   * picture with no statement of what to do about it.
   */
  const ownWords = (element) =>
    [...element.childNodes]
      .filter((node) => node.nodeType === 3)
      .map((node) => node.textContent)
      .join(" ")
      .replace(/\s+/g, " ")
      .trim();

  /** Prose above the answer area, in document order. */
  const lines = [...document.querySelectorAll("p, div, span, td")]
    .filter((element) => {
      if (!visible(element) || element.getBoundingClientRect().top >= limit) {
        return false;
      }
      // A cell of either table is a quantity, not a sentence. Both are read
      // exactly, as tables, and letting one back in here would put it up for
      // selection as the question's instruction as well.
      return !(
        (dataTable !== null && dataTable.node.contains(element))
        || (answerTable.table !== null && answerTable.table.node.contains(element))
      );
    })
    .map((element) =>
      // A container contributes only its own words, so the figure, the table
      // and every nested sentence stay out of it and are considered on their
      // own terms.
      element.querySelector("p, div, table") !== null
        ? ownWords(element)
        : (element.textContent || "").trim()
    )
    .filter((text) => text.length > 3 && text.length < 400);

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
    // Why the exact readings were refused, when they were. Codes only: a
    // count, a selector name, or the size of a disagreement. Carried so the
    // diagnostic log can say which condition did not hold, instead of leaving
    // "no readable markup" to stand for nine different faults.
    evidence: {
      graph: graph.graphReason,
      table: dataTable === null ? "no-data-table" : "",
      // Which condition stopped a completion table being read, when one did.
      // A count, a selector name or a named disagreement -- never a cell.
      answerTable: answerTable.tableReason,
      answerTableDetail: answerTable.tableDetail,
      promptChars: promptText.length,
    },
    ...(graphPoints ? { graphPoints } : {}),
    // The node stays here. What crosses is the reading of the table.
    ...(dataTable
      ? { dataTable: { columns: dataTable.columns, rows: dataTable.rows } }
      : {}),
    // The same, for the table the answer is typed into: the grid, with each
    // cell either a value the page states or a numbered blank. No element, no
    // selector, no geometry, and nothing read out of an answer control.
    ...(answerTable.table
      ? {
          answerTable: {
            columns: answerTable.table.columns,
            rows: answerTable.table.rows,
          },
          // The browser's half of the same reading, kept beside it and never
          // sent anywhere: which control holds each numbered blank. The event
          // page pins this, re-reads it before it writes, and refuses on any
          // disagreement -- `answerTable` is what the question is, this is
          // where its answers go.
          answerTargets: answerTable.targets,
        }
      : {}),
  };
})();
