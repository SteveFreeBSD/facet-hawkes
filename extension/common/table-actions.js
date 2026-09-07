"use strict";

/**
 * The one function that writes a completion table's cells.
 *
 * It is passed to `scripting.executeScript` as `func` with `world: "MAIN"`, so
 * it runs in the page's own world, and it must stay self-contained:
 * `executeScript` serialises it, so it may not reference anything outside its
 * own body.
 *
 * ## Why this is not the isolated writer any more
 *
 * The isolated writer did the obvious thing for a page of five ordinary text
 * boxes: focus the box, set its value through the prototype setter, dispatch
 * `input`. Every cell was resolved from the reader's own blank-to-control
 * mapping, all five targets were distinct, and all five write calls returned
 * without complaint. Live, on 2026-09-07, the log said so twice:
 *
 *     inserted {"via":"table-cells","fields":5,"parts":5,
 *               "held":[0,0,0,0,0],"placed":[1,1,1,1,1]}
 *
 * and the page still held four right answers and one wrong one. Writing the
 * fifth part into `MatrixTextBoxes6_num` also changed `MatrixTextBoxes3_num`,
 * which is the second part's cell.
 *
 * The mapping was right and the targets were right. What was wrong is that a
 * Hawkes answer cell is not an ordinary text box. The page owns a controlled
 * editor model — `quant_wp_UI.controlsCollection`, one entry per cell with its
 * own text buffer, and `focusedElementIndex` naming the one entry the page
 * believes is being edited — and its `input` handling is delegated: the event
 * updates *the selected control's* buffer and then rerenders the box that
 * control owns. `HTMLElement.focus()` moves `document.activeElement` and
 * nothing else: Hawkes selects from its own focus handling, which never ran,
 * because the panel had system focus the whole time. So all five writes routed
 * through whichever control the page had selected before the add-on was ever
 * opened, and each in turn overwrote that one cell from the value it had just
 * read off a different box.
 *
 * `focusedElementIndex` is only the *mirror* of that selection. The router for
 * a plain answer box is the element reference Hawkes keeps beside it -- the
 * `focusedElement` its own `AnswerBoxKeyPadClick` reads -- so assigning the
 * index and reading it back confirms nothing at all. A first attempt at this
 * fix did exactly that, and on one mapping produced a matched pair of live
 * failures: pre-focused on blank 1's control, the first write landed and the
 * second crossed into blank 1; pre-focused on blank 2's, the very first write
 * crossed into blank 2. Selection has to be made by the page, not asserted
 * to it.
 *
 * ## What this does instead
 *
 * Every cell is resolved to exactly one page-owned control before anything is
 * written, that control is *selected* through the page's own state, the part
 * is written, the editor is allowed to settle, and the result is read back
 * cell by cell — the intended cell holds the intended part, and no other cell
 * moved. Any of those failing is a refusal, not a smaller success.
 *
 * ## Reading a cell back
 *
 * The isolated writer was forbidden from reading a cell at all, and that rule
 * was right for what it was protecting: a blank is a position the page states,
 * so going to the control for its contents would have let the writer decide
 * from a student's own work. Nothing here decides from a cell. It composes
 * every value it writes character by character from what it has placed itself,
 * exactly as before, and the only reads are comparisons made in the page's own
 * world: does this cell now hold the part meant for it, and did any other cell
 * change. What crosses back out of this function is names, counts, booleans
 * and reason codes; no cell's text ever does. Without those comparisons
 * `placed=[1,1,1,1,1]` was the whole of what success meant, and it meant five
 * write calls that returned.
 */

/**
 * @param {string[]} parts reviewed answers, in semantic blank order
 * @param {string[]} cells control ids, in the same order; `cells[N]` holds
 *   blank `N + 1`, as the reader that accepted the table states it
 * @param {object} cadence the shared score, as data
 * @returns {Promise<{ok: boolean, code: string}>}
 */
export async function enterTableCells(parts, cells, cadence = {}) {
  // Kept in step with `common/config.js` by the build's shared-constant
  // check; this function is serialized into the page's own world by
  // `scripting.executeScript`, so no import survives here.
  const ALLOWED_ORIGIN = "https://learn.hawkeslearning.com";
  const MAX_ANSWER_LENGTH = 40;
  const MAX_ANSWER_PARTS = 5;
  const ANSWER_PATTERN = /^[0-9A-Za-z+\-*/^().,√π ]+$/;

  const HAWKES_FIELD_SELECTOR = 'input.qbaseCSS, input[id^="txtAns"], input.boxStyle';
  /** How long the editor is given to finish rerendering after one part. */
  const SETTLE_MS = 2000;
  /** How far into a control's own object graph ownership is looked for. */
  const WALK_DEPTH = 6;
  const WALK_BUDGET = 400;

  if (window.location.origin !== ALLOWED_ORIGIN) {
    return { ok: false, code: "wrong-site" };
  }

  const dialogUp = () =>
    [...document.querySelectorAll('[id*="customMessageBox"]')].some(
      (node) => node.getBoundingClientRect().height > 0
    );
  if (dialogUp()) {
    return { ok: false, code: "editor-dialog-open" };
  }

  const supported = (value) =>
    typeof value === "string"
    && value.length > 0
    && value.length <= MAX_ANSWER_LENGTH
    && ANSWER_PATTERN.test(value);

  /**
   * One answer part, as the halves the cell will hold it in.
   *
   * A Hawkes answer cell owns a numerator control and a denominator control.
   * Only the numerator's box is drawn until a `/` is typed into it, at which
   * point the cell shows both and the editor moves to the second -- so `16/9`
   * is one answer in one cell, entered the way a student enters it, and not
   * two answers in two blanks.
   */
  const halvesOf = (part) => {
    const at = part.indexOf("/");
    if (at < 0) {
      return { numerator: part, denominator: null };
    }
    const numerator = part.slice(0, at);
    const denominator = part.slice(at + 1);
    return numerator.length > 0 && denominator.length > 0 && !denominator.includes("/")
      ? { numerator, denominator }
      : null;
  };

  /** The other half's box, by the name Hawkes gives it. */
  const denominatorId = (id) =>
    id.endsWith("_num") ? `${id.slice(0, -"_num".length)}_den` : null;
  if (
    !Array.isArray(parts)
    || parts.length < 2
    || parts.length > MAX_ANSWER_PARTS
    || !parts.every(supported)
    || !Array.isArray(cells)
    || cells.length !== parts.length
    || !cells.every((id) => typeof id === "string" && id.length > 0)
    || new Set(cells).size !== cells.length
  ) {
    return { ok: false, code: "answer-invalid" };
  }
  const halves = parts.map(halvesOf);
  if (halves.some((half) => half === null)) {
    return { ok: false, code: "answer-invalid" };
  }
  // A fraction needs the cell's second box, which Hawkes names for it. A part
  // this writer could not route to a box of its own is refused here.
  if (
    halves.some(
      (half, index) => half.denominator !== null && denominatorId(cells[index]) === null
    )
  ) {
    return { ok: false, code: "table-cell-not-expandable" };
  }

  // The extension passes the shared, already-built score as data. MAIN owns
  // editor mechanics only; it carries no second rhythm algorithm.
  const noteOffsets = cadence.score?.offsets;
  const noteCount = parts.join("").length;
  if (
    !Array.isArray(noteOffsets)
    || noteOffsets.length !== noteCount
    || noteOffsets.some(
      (at, index) =>
        !Number.isFinite(at)
        || at < 0
        || at > 12000
        || (index > 0 && at < noteOffsets[index - 1])
    )
  ) {
    return { ok: false, code: "answer-invalid" };
  }

  const ui = window.quant_wp_UI;
  if (!ui || ui.controlsCollection === undefined) {
    return { ok: false, code: "editor-model-missing" };
  }

  // --- the score, performed exactly as the structured writer performs it ---

  const performanceStartedAt = performance.now();
  let origin = performanceStartedAt;
  let notesStruck = 0;
  let heldMs = 0;
  const lateness = [];

  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

  /**
   * Tell an optional listener that one note landed, in the write's own turn.
   *
   * One-way, string-only, and never awaited. A page can observe or forge this;
   * it confers no capability, and a failure here cannot change what was typed.
   */
  const emit = (payload) => {
    try {
      if (cadence.channel) {
        document.dispatchEvent(
          new CustomEvent(cadence.channel, { detail: JSON.stringify(payload) })
        );
      }
    } catch { /* audio failure cannot change entry */ }
  };

  /** Hold until this note is due. A late clock simply plays it now. */
  const waitForNote = async () => {
    const due = noteOffsets[notesStruck];
    notesStruck += 1;
    if (due === undefined) {
      return;
    }
    for (let approach = 0; approach < 8; approach += 1) {
      const wait = due - (performance.now() - origin);
      if (wait <= 0) {
        break;
      }
      await pause(wait > 250 ? wait - 200 : wait);
    }
    lateness.push(Math.round(performance.now() - origin - due));
  };

  /**
   * Absorb the wall time the editor took to rerender a cell.
   *
   * Waiting for a controlled editor to settle is real work of a length only
   * the editor knows, and the score never allotted time for it. Leaving the
   * origin where it was would make every remaining note overdue the moment the
   * cell came back, so the rest of the table would arrive in one burst.
   */
  const holdForSettling = () => {
    const due = noteOffsets[notesStruck] ?? noteOffsets[noteOffsets.length - 1] ?? 0;
    const overrun = performance.now() - origin - due;
    if (overrun > 0) {
      origin += overrun;
      heldMs += overrun;
    }
  };

  /** How this performance actually ran, as numbers only. */
  const measured = () => ({
    notes: lateness.length,
    heldMs: Math.round(heldMs),
    elapsedMs: Math.round(performance.now() - performanceStartedAt),
    maxLatenessMs: lateness.length ? Math.max(...lateness) : 0,
    meanLatenessMs: lateness.length
      ? Math.round(lateness.reduce((total, late) => total + late, 0) / lateness.length)
      : 0,
    driftMs: lateness.length ? lateness[lateness.length - 1] - lateness[0] : 0,
  });

  // --- the cells the mapping names ----------------------------------------

  /**
   * Resolve the mapping against the live page's own elements.
   *
   * The mapping is `blank N -> control id`, decided by the one reader that
   * accepted the table and re-derived by that same reader immediately before
   * this runs. What is checked here is the elements: that each id still names
   * a Hawkes answer box, that it is visible and editable, that its own stated
   * bound can hold the part, and that no two blanks resolved to one box.
   */
  const resolveFields = () => {
    const found = [];
    for (const [index, id] of cells.entries()) {
      const field = document.getElementById(id);
      if (!field || field.isConnected === false) {
        return { ok: false, code: "table-target-missing", blank: index + 1 };
      }
      if (!(field instanceof HTMLInputElement) || !field.matches?.(HAWKES_FIELD_SELECTOR)) {
        return { ok: false, code: "table-target-missing", blank: index + 1 };
      }
      const rect = field.getBoundingClientRect();
      if (!(rect.width > 0 && rect.height > 0) || field.disabled || field.readOnly) {
        return { ok: false, code: "table-target-not-editable", blank: index + 1 };
      }
      if (found.includes(field)) {
        return { ok: false, code: "table-target-repeated", blank: index + 1 };
      }
      const bound = field.maxLength;
      // Each half is typed into a box of its own, so each half is what the
      // box's own bound has to hold -- `100/9` fits two four-character boxes
      // and would never fit one.
      const longest = Math.max(
        halves[index].numerator.length, halves[index].denominator?.length ?? 0
      );
      if (Number.isInteger(bound) && bound > 0 && longest > bound) {
        return { ok: false, code: "answer-invalid", blank: index + 1 };
      }
      found.push(field);
    }
    return { ok: true, fields: found };
  };

  const resolved = resolveFields();
  if (!resolved.ok) {
    return resolved;
  }
  const fields = resolved.fields;

  // --- the controls the page owns them with --------------------------------

  /** Every index the collection publishes, array-like or keyed. */
  const indicesOf = (source) => {
    const found = [];
    if (Number.isInteger(source?.length)) {
      for (let at = 0; at < source.length; at += 1) {
        found.push(at);
      }
      return found;
    }
    let keys = [];
    try {
      keys = Object.keys(source ?? {});
    } catch {
      return found;
    }
    for (const key of keys) {
      if (/^\d+$/.test(key)) {
        found.push(Number(key));
      }
    }
    return found;
  };

  const collection = ui.controlsCollection;
  const rows = ui.controlsCollectionData;
  const published = indicesOf(collection);

  const candidates = [];
  for (const index of published) {
    const control = collection[index];
    if (!control || typeof control !== "object") {
      continue;
    }
    const data = rows ? rows[index] : null;
    // The same classification the read-only probe makes. A control that is
    // neither a dynamic editor nor a text box is an option -- Hawkes publishes
    // one beside every table cell, which is why its collection is twice the
    // answer surface -- and no answer is ever typed into one.
    const dynamic = data?.isQDy === true || control.Type !== undefined;
    if (data && !dynamic && data.boxValue === undefined) {
      continue;
    }
    if (control.enabled === false) {
      continue;
    }
    candidates.push({ index, control, data: data ?? null });
  }

  // A control's own graph is walked for ownership; the other controls' graphs
  // are not. Hawkes' objects hold references back to their siblings and to the
  // collection, and following those would let every control claim every cell.
  const foreign = new Set();
  for (const index of published) {
    const control = collection[index];
    if (control && typeof control === "object") {
      foreign.add(control);
    }
    const data = rows ? rows[index] : null;
    if (data && typeof data === "object") {
      foreign.add(data);
    }
  }
  foreign.add(ui);
  if (collection && typeof collection === "object") {
    foreign.add(collection);
  }
  if (rows && typeof rows === "object") {
    foreign.add(rows);
  }

  /** An element, whether it is one or a jQuery wrapper around one. */
  const asElement = (value) => {
    try {
      if (value && value.nodeType === 1 && typeof value.getAttribute === "function") {
        return value;
      }
      if (value && value.jquery !== undefined && value[0]?.nodeType === 1) {
        return value[0];
      }
    } catch { /* a getter that throws is not evidence */ }
    return null;
  };

  /**
   * The elements and names one control publishes, found by identity.
   *
   * Deliberately not a named property. Hawkes links a plain answer box to its
   * control differently from a dynamic one, the link has moved between
   * lessons, and a writer that guessed `objMyDiv` and found nothing would
   * either refuse every table or, worse, fall back to position. So the
   * control's own object graph is walked, bounded in depth and in work, and
   * whatever it turns out to hold -- the element itself, the cell around it,
   * or the id as a string -- is recorded with the depth it was found at.
   */
  const evidenceOf = (entry) => {
    const elements = [];
    const names = [];
    const seen = new Set();
    let budget = WALK_BUDGET;
    const visit = (value, depth) => {
      if (budget <= 0 || depth > WALK_DEPTH || value === null || value === undefined) {
        return;
      }
      if (typeof value === "string") {
        if (value.length > 0 && value.length <= 120) {
          names.push([value, depth]);
        }
        return;
      }
      if (typeof value !== "object" && typeof value !== "function") {
        return;
      }
      if (seen.has(value)) {
        return;
      }
      seen.add(value);
      budget -= 1;
      const element = asElement(value);
      if (element) {
        elements.push([element, depth]);
        return;   // the page's tree is evidence, not something to walk into
      }
      if (depth > 0 && foreign.has(value)) {
        return;
      }
      let keys = [];
      try {
        keys = Object.keys(value);
      } catch {
        return;
      }
      if (keys.length > 80) {
        return;   // a page-sized collection, not one control's own fields
      }
      for (const key of keys) {
        let next;
        try {
          next = value[key];
        } catch {
          continue;   // a getter that throws is not evidence either
        }
        visit(next, depth + 1);
      }
    };
    visit(entry.control, 0);
    visit(entry.data, 0);
    return { elements, names };
  };

  /** `MatrixTextBoxes3_num` names the control `MatrixTextBoxes3`. */
  const baseName = (id) => id.replace(/_[A-Za-z]+$/, "");

  /**
   * How strongly one control claims one cell: the kind of evidence first, and
   * within a kind the shallowest reference. Zero is no claim at all.
   */
  const claimOf = (found, cell, others) => {
    let best = 0;
    const note = (kind, depth) => {
      const rank = kind * 1000 + Math.max(0, 100 - depth);
      if (rank > best) {
        best = rank;
      }
    };
    const holds = (element, node) => {
      try {
        return element.contains(node) === true;
      } catch {
        return false;
      }
    };
    for (const [element, depth] of found.elements) {
      if (element === cell) {
        note(4, depth);
        continue;
      }
      // A container is evidence only when it holds this one target and no
      // other: the grid itself contains all five and says nothing about any.
      if (holds(element, cell) && !others.some((other) => holds(element, other))) {
        note(3, depth);
      }
    }
    const base = baseName(cell.id);
    for (const [text, depth] of found.names) {
      if (text === cell.id) {
        note(2, depth);
      } else if (base.length > 0 && text === base) {
        note(1, depth);
      }
    }
    return best;
  };

  const EVIDENCE = ["", "name", "id", "cell", "element"];
  const evidence = candidates.map(evidenceOf);
  const claims = fields.map((field, at) =>
    candidates.map((_control, which) =>
      claimOf(evidence[which], field, fields.filter((_one, other) => other !== at))
    )
  );

  const owners = [];
  const ownership = [];
  for (let at = 0; at < fields.length; at += 1) {
    const row = claims[at];
    const best = Math.max(0, ...row);
    if (best === 0) {
      return { ok: false, code: "table-cell-model-missing", blank: at + 1 };
    }
    const winners = [];
    for (let which = 0; which < row.length; which += 1) {
      if (row[which] === best) {
        winners.push(which);
      }
    }
    if (winners.length !== 1) {
      return { ok: false, code: "table-cell-model-ambiguous", blank: at + 1 };
    }
    owners.push(winners[0]);
    ownership.push(EVIDENCE[Math.floor(best / 1000)]);
  }
  if (new Set(owners).size !== owners.length) {
    return { ok: false, code: "table-cell-model-shared" };
  }
  // And the other direction. A control that claims some other cell of this
  // table more strongly than the one it was given does not own that one; the
  // two readings of ownership disagree, and a disagreement is a refusal.
  for (let at = 0; at < fields.length; at += 1) {
    const which = owners[at];
    for (let other = 0; other < fields.length; other += 1) {
      if (other !== at && claims[other][which] > claims[at][which]) {
        return { ok: false, code: "table-cell-model-disagrees", blank: at + 1 };
      }
    }
  }

  /**
   * The page's own reference to the box it believes is being edited.
   *
   * `focusedElementIndex` is a mirror, and a plain answer box is not routed by
   * it: Hawkes keeps an element reference -- the `focusedElement` its own
   * `AnswerBoxKeyPadClick` reads -- and that is the authoritative router. So
   * every element-valued property the model publishes is compared against the
   * table's own cells, and a reference to some other cell of this table is
   * proof the page is not editing the one we mean.
   */
  const routedAt = () => {
    const found = [];
    let keys = [];
    try {
      keys = Object.keys(ui);
    } catch {
      return found;
    }
    if (keys.length > 200) {
      return found;
    }
    for (const key of keys) {
      let value;
      try {
        value = ui[key];
      } catch {
        continue;   // a getter that throws says nothing
      }
      const element = asElement(value);
      // Any answer box, not only a mapped one: a cell showing a fraction is
      // edited through its denominator, which is not a cell of its own.
      if (element && element.matches?.(HAWKES_FIELD_SELECTOR)) {
        found.push(element);
      }
    }
    return found;
  };

  /** Whether the page is provably editing this exact box. */
  const focusedOnBox = (box) => {
    const routed = routedAt();
    return routed.length > 0 && routed.every((element) => element === box);
  };

  /** Whether the page is provably editing this cell, router included. */
  const focusedOn = (at) => {
    if (ui.focusedElementIndex !== candidates[owners[at]].index) {
      return false;
    }
    return routedAt().every((element) => element === fields[at]);
  };

  /**
   * Make Hawkes select one box that is not a cell of its own.
   *
   * The denominator a `/` just created has no mapping entry and no ownership
   * claim -- it is the other half of a cell that already has both. What can
   * be proven about it is the same thing that matters for a cell: that the
   * page's own router is on it before anything is typed. Hawkes moves there
   * itself when the fraction opens, exactly as it focuses a template's first
   * slot; this confirms that, and runs the page's own focus handling when it
   * has not.
   */
  const selectBox = (box) => {
    if (focusedOnBox(box)) {
      return "page";
    }
    try {
      box.focus();
    } catch { /* the page's own path, tried first */ }
    if (focusedOnBox(box)) {
      return "page";
    }
    try {
      box.dispatchEvent(new FocusEvent("focus", { relatedTarget: null }));
      box.dispatchEvent(new FocusEvent("focusin", { bubbles: true, relatedTarget: null }));
    } catch { /* an event the page will not take is not a selection */ }
    return focusedOnBox(box) ? "focus" : null;
  };

  /**
   * Make Hawkes select this cell itself, and say how it was reached.
   *
   * This function used to assign `focusedElementIndex` and read it back, and
   * the read-back was worthless: the index is a mirror the page keeps beside
   * its real selection, so writing it confirmed only that the property had
   * taken the value. Live, on the same mapping, that produced a matched pair
   * of failures -- with the page pre-focused on blank 1's control the first
   * write landed and the second crossed into blank 1, and with it pre-focused
   * on blank 2's the very first write crossed into blank 2. In both the input
   * went to whichever control Hawkes had selected before the panel opened.
   *
   * Nothing here assigns the index any more. Instead the page's own focus
   * handling is made to run -- `focus()`, and then the focus events Hawkes
   * binds at document level, which is what a click on the cell would deliver
   * and what never fires while the panel holds system focus -- and the index
   * moving *by itself* is then evidence that the handler ran and set the
   * router with it. That, plus the router agreeing, is the whole of what
   * counts as selected; a cell that cannot be proven focused is refused.
   */
  const selectFor = (at) => {
    const { control } = candidates[owners[at]];
    const field = fields[at];
    try {
      field.focus();
    } catch { /* the page's own path, tried first */ }
    if (focusedOn(at)) {
      return "page";
    }
    // The events the page listens for. A cell reached this way is selected by
    // Hawkes' own handler, so its router and its mirror cannot disagree.
    try {
      field.dispatchEvent(new FocusEvent("focus", { relatedTarget: null }));
      field.dispatchEvent(
        new FocusEvent("focusin", { bubbles: true, relatedTarget: null })
      );
    } catch { /* an event the page will not take is not a selection */ }
    if (focusedOn(at)) {
      return "focus";
    }
    try {
      if (typeof control.setFocus === "function") {
        control.setFocus();
      }
    } catch { /* the editor's own selector, where a control has one */ }
    return focusedOn(at) ? "editor" : null;
  };

  /**
   * What one control's own buffer holds, or null when it publishes none.
   *
   * This is the reading the DOM cannot give: the whole failure was the model
   * and the box disagreeing about which cell an answer belonged to. Where the
   * control states its text it is compared against the part; where it states
   * none, the cross-cell check below is what catches a misrouted write, and
   * the result says how many models could actually be read.
   */
  const modelText = (entry) => {
    const { control, data } = entry;
    let text;
    try {
      const dynamic = data?.isQDy === true || control.Type !== undefined;
      const states = dynamic ? control.CurrentTextboxText : control.boxValue;
      text = typeof states === "function" ? states.call(control) : states;
    } catch {
      return null;
    }
    return typeof text === "string" ? text : null;
  };

  // --- writing -------------------------------------------------------------

  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;

  /**
   * Put one exact string in a cell and tell the page it changed.
   *
   * `text` is composed by this function from what it has placed itself,
   * starting from nothing, so the cell ends holding exactly the reviewed part
   * whatever the control was carrying before -- and so a rerender that has
   * put someone else's value in the box cannot be appended to.
   */
  const writeCell = (field, text, character) => {
    setter.call(field, text);
    field.setSelectionRange?.(text.length, text.length);
    field.dispatchEvent(
      new InputEvent("input", {
        bubbles: true,
        data: character,
        inputType: text === "" ? "deleteContentBackward" : "insertText",
      })
    );
  };

  /**
   * The box holding the other half of one cell, when the cell is showing it.
   *
   * Looked up live rather than resolved once: the box does not exist until a
   * `/` is typed, and this writer is what types it.
   */
  const halfBox = (at) => {
    const id = denominatorId(cells[at]);
    if (id === null) {
      return null;
    }
    const box = document.getElementById(id);
    if (
      !box
      || box.isConnected === false
      || !(box instanceof HTMLInputElement)
      || !box.matches?.(HAWKES_FIELD_SELECTOR)
    ) {
      return null;
    }
    const rect = box.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0 ? box : null;
  };

  /**
   * What the mapped cells hold, one *logical* value each.
   *
   * A cell showing a fraction holds `16/9` across two boxes, and that is the
   * value the mapping's fourth blank was reviewed against. Reading the boxes
   * separately would make the same table four answers or eight depending on
   * what had been typed into it, and would report a cell as having lost its
   * part the moment the part arrived.
   *
   * Compared, never reported and never decided from: see the note at the top
   * of this file about what a cell's contents are and are not for.
   */
  const snapshot = () =>
    fields.map((field, at) => {
      const other = halfBox(at);
      return other === null ? field.value : `${field.value}/${other.value}`;
    });

  /** Wait for the editor to stop rerendering, or for the deadline. */
  const settle = async () => {
    const deadline = Date.now() + SETTLE_MS;
    let last = snapshot().join("\n");
    let stable = 0;
    while (Date.now() < deadline) {
      await pause(60);
      const now = snapshot().join("\n");
      if (now !== last) {
        last = now;
        stable = 0;
        continue;
      }
      stable += 1;
      if (stable >= 3) {
        break;
      }
    }
    return snapshot();
  };

  // Ask every cell before changing any of them. Hawkes uses this event to
  // reject characters its published model does not accept, and a question that
  // would refuse the fourth value must not be given the first three.
  const asked = fields.every((field, at) =>
    field.dispatchEvent(
      new InputEvent("beforeinput", {
        bubbles: true,
        cancelable: true,
        data: parts[at],
        inputType: "insertText",
      })
    )
  );
  if (!asked) {
    return { ok: false, code: "input-cancelled" };
  }

  // What the surface held before this ran, so a refusal can put it back.
  const original = snapshot();
  const expected = [...original];
  let mutated = false;
  let written = 0;

  /** Put back what was there, so a refusal leaves no partial answer behind. */
  const undo = async () => {
    if (!mutated) {
      return false;
    }
    const was = original.map(halvesOf);
    for (let at = 0; at < fields.length; at += 1) {
      try {
        if (!fields[at].isConnected) {
          continue;
        }
        // The other half first: a cell showing a fraction has to be emptied
        // from the box the page is editing back to the one it opened from.
        const other = halfBox(at);
        if (other !== null && selectBox(other) !== null) {
          writeCell(other, was[at]?.denominator ?? "", "");
        }
        if (selectFor(at) === null) {
          continue;   // reported as left behind rather than written blind
        }
        writeCell(fields[at], was[at]?.numerator ?? original[at], "");
      } catch { /* an undo that cannot run is reported, not thrown */ }
    }
    await settle();
    return snapshot().some((value, at) => value !== original[at]);
  };

  const refuse = async (report) =>
    (await undo()) ? { ...report, leftBehind: true } : report;

  const selected = [];
  let modelsRead = 0;
  let expanded = 0;

  for (let at = 0; at < fields.length; at += 1) {
    // The mapping, re-resolved between cells. Paced entry runs for seconds and
    // Hawkes swaps a question in place: the cell this is about to write can
    // have been replaced while the previous one was being typed.
    const again = resolveFields();
    if (!again.ok) {
      return await refuse({ ...again, written: at });
    }
    if (again.fields.some((one, other) => one !== fields[other])) {
      return await refuse({ ok: false, code: "table-targets-changed", written: at });
    }

    const how = selectFor(at);
    if (how === null) {
      return await refuse({
        ok: false, code: "table-cell-not-selected", blank: at + 1, written: at,
      });
    }
    selected.push(how);

    const field = fields[at];
    mutated = true;
    // A cell already showing both halves -- someone typed a fraction in by
    // hand, or a previous run left one -- is emptied from its second box back
    // to its first, so nothing it was carrying survives this write.
    const carried = halfBox(at);
    if (carried !== null) {
      if (selectBox(carried) === null) {
        return await refuse({
          ok: false, code: "table-cell-not-selected", blank: at + 1, written: at,
        });
      }
      writeCell(carried, "", "");
      if (selectFor(at) === null) {
        return await refuse({
          ok: false, code: "table-cell-not-selected", blank: at + 1, written: at,
        });
      }
    }
    // Emptied first, through the control that now owns the cell, so the part
    // lands in a cleared model rather than behind whatever it was carrying.
    writeCell(field, "", "");
    // The box being typed into, which for a fraction changes once: the `/`
    // opens the cell's second box and the editor moves to it, so the rest of
    // the part is typed there. It is still this one cell and this one blank.
    let box = field;
    let placed = "";
    for (const character of parts[at]) {
      await waitForNote();
      if (!box.isConnected) {
        return await refuse({
          ok: false, code: "table-target-missing", blank: at + 1, written: at,
        });
      }
      if (box.disabled || box.readOnly) {
        return await refuse({
          ok: false, code: "table-target-not-editable", blank: at + 1, written: at,
        });
      }
      if (character === "/" && halves[at].denominator !== null && box === field) {
        // Typed, not built: a plain Hawkes answer box turns `/` into its own
        // fraction, which is how a student enters one and the only route this
        // add-on has -- there is no keypad template here to press. A cell
        // already showing its second box needs no `/`; it needs to be
        // continued in the box it already has.
        if (halfBox(at) === null) {
          writeCell(box, `${placed}/`, "/");
          await settle();
          holdForSettling();
        }
        const other = halfBox(at);
        if (other === null) {
          return await refuse({
            ok: false, code: "table-cell-not-expandable", blank: at + 1, written: at,
          });
        }
        // Hawkes moves to the new box itself, as it does for a template's
        // first slot. Confirmed rather than assumed, and its own focus
        // handling is run when it has not.
        const reached = selectBox(other);
        if (reached === null) {
          return await refuse({
            ok: false, code: "table-cell-not-selected", blank: at + 1, written: at,
          });
        }
        expanded += 1;
        box = other;
        placed = "";
        emit([notesStruck - 1, performance.now() - origin]);
        continue;
      }
      placed = `${placed}${character}`;
      writeCell(box, placed, character);
      emit([notesStruck - 1, performance.now() - origin]);
    }
    written = at + 1;

    const settled = await settle();
    holdForSettling();
    if (dialogUp()) {
      return await refuse({
        ok: false, code: "editor-dialog-open", blank: at + 1, written,
      });
    }
    expected[at] = parts[at];
    if (settled[at] !== parts[at]) {
      return await refuse({
        ok: false, code: "table-cell-not-settled", where: "cell", blank: at + 1, written,
      });
    }
    // The failure this writer exists to catch: the editor took the part and
    // put it, or the cell it was holding, somewhere else in the same table.
    const moved = settled.findIndex(
      (value, other) => other !== at && value !== expected[other]
    );
    if (moved >= 0) {
      return await refuse({
        ok: false, code: "table-cell-crossed", blank: at + 1, moved: moved + 1, written,
      });
    }
    // The control this cell is mapped to holds the numerator. A fraction's
    // other half belongs to the cell's second control, which has no mapping
    // entry of its own; the logical value checked above is what covers it.
    const text = modelText(candidates[owners[at]]);
    if (text !== null) {
      modelsRead += 1;
      if (text !== halves[at].numerator) {
        return await refuse({
          ok: false, code: "table-cell-not-settled", where: "model", blank: at + 1, written,
        });
      }
    }
  }

  // Every cell, once more, after the last one settled.
  const final = resolveFields();
  if (!final.ok || final.fields.some((one, at) => one !== fields[at])) {
    return await refuse({ ok: false, code: "table-targets-changed", written });
  }
  if (snapshot().some((value, at) => value !== parts[at])) {
    return await refuse({ ok: false, code: "table-cell-not-settled", where: "cell", written });
  }

  return {
    ok: true,
    code: "entered-table-cells",
    cells: [...cells],
    // What this insertion actually established, rather than how many write
    // calls returned. `settled` is cells whose own state was read back and
    // matched, with no other cell moving; `models` is how many of the page's
    // own control buffers could be read and agreed as well.
    settled: fields.length,
    models: modelsRead,
    // How many cells were opened into a numerator/denominator pair by this
    // write. The table still has one blank per cell either way.
    expanded,
    // How each cell was tied to a control, and how each control was selected.
    // Names, not values: this is what a live refusal would otherwise cost a
    // screenshot of the owner's coursework to guess at.
    ownership,
    selected,
    timing: measured(),
  };
}
