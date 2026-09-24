"use strict";

/**
 * MAIN-world probe: what will this question's editor actually accept?
 *
 * Hawkes drives its answer editor through page-owned JavaScript — a global
 * `quant_wp_UI` holding the controls and their rules — which an isolated
 * content script cannot see. This is the one file injected into the page's own
 * world, and it only reads.
 *
 * It matters because the rules are per question. The same lesson offers a box
 * accepting `0123456789y` for one question and `[0-9.-]` for the next, and
 * typing a character outside that set raises a blocking Hawkes dialog rather
 * than being ignored. Reading `qdyBase_AllowedChar` lets the add-on refuse
 * before it touches the page instead of guessing from the answer's shape.
 *
 * Deliberately narrow: fixed operation, no arguments, read-only, and nothing
 * declared on the page. Everything is inside one IIFE whose value returns to
 * the popup as the script's completion value. The page can observe code
 * running in its world while it runs; that is the documented cost of MAIN, and
 * it buys the only access that works.
 */

(() => {
  // Kept in step with `common/config.js` by the build's shared-constant
  // check; this file runs in the page's own world and imports nothing.
  const MAX_ANSWER_PARTS = 5;
  const HAWKES_FIELD_SELECTOR = 'input.qbaseCSS, input[id^="txtAns"], input.boxStyle';
  const ui = window.quant_wp_UI;
  if (!ui || ui.controlsCollection === undefined) {
    return { ok: false, code: "editor-model-missing" };
  }

  /** Call one of the editor's zero-argument accessors, tolerating absence. */
  const read = (accessor) => {
    try {
      return typeof accessor === "function" ? accessor() : accessor;
    } catch {
      return undefined;
    }
  };

  /** Describe one page-owned editor control without changing it. */
  const describe = (index) => {
    const control = ui.controlsCollection[index];
    const data = ui.controlsCollectionData ? ui.controlsCollectionData[index] : null;
    if (!control || !data) {
      return null;
    }

    // A dynamic box builds structure from keypad templates. A plain answer box
    // takes characters only, and states its rule as a regular expression. A
    // question can also be answered by choosing an option -- "Not a Real
    // Number" and the like -- which is a selection, not text.
    const dynamic = data.isQDy === true || control.Type !== undefined;
    const option = !dynamic && data.boxValue === undefined;
    if (option) {
      return {
        ok: true,
        code: "described",
        kind: "option",
        name: String(read(data.Name) ?? ""),
        enabled: control.enabled !== false && read(data.enableState) !== false,
        text: "",
        allowedCharacters: "",
        maxLength: null,
        templates: { fraction: false, radical: false, exponent: false },
      };
    }

    // The templates the base slot publishes, by the exact names Hawkes gives
    // them. `seperateValidTemplates` builds this as an array from the
    // question's `<qpbrac/>`, `<qpsbrac/>`… markup, and `qualifyLoadParenthesis`
    // asks it `indexOf(TemplateName)` -- an exact name, never a substring. The
    // substring test this replaces read `"SPBrace".includes("PBrace")` as a
    // parentheses template, and collapsed four different brackets into one
    // boolean besides.
    const baseTemplates = new Set(
      String(control.qdyBase_AllowedTemplates ?? "").split(/[^A-Za-z]+/).filter(Boolean)
    );

    return {
      ok: true,
      code: "described",
      kind: dynamic ? "dynamic" : "textbox",
      name: String(read(data.Name) ?? ""),
      enabled: control.enabled !== false && read(data.enableState) !== false,
      text: dynamic
        ? control.CurrentTextboxText ?? ""
        : String(read(control.boxValue) ?? ""),
      // For a dynamic box this is a literal set of characters; for a plain box it
      // is a character-class pattern such as "[0-9.-]".
      allowedCharacters: dynamic
        ? String(control.qdyBase_AllowedChar ?? "")
        : String(read(data.validString) ?? ""),
      maxLength: dynamic
        ? control.qdyBaseMaxChars ?? null
        : Number(read(data.maxLength)) || null,
      // A template can be offered but still have a question-specific object
      // limit. The planner must know this before pressing the first one: a
      // second Radical is otherwise refused after part of the answer is in.
      limits: dynamic
        ? {
            radicals: Number.isInteger(Number(control.qdyRoot_MaximumObjects))
              ? Number(control.qdyRoot_MaximumObjects) : null,
            radicandLength: Number.isInteger(Number(control.qdyRoot_AllowedRadicandLen))
              ? Number(control.qdyRoot_AllowedRadicandLen) : null,
          }
        : null,
      slots: dynamic
        ? {
            base: String(control.qdyBase_AllowedChar ?? ""),
            numerator: String(control.qdyFrac_AllowedNumeChar ?? ""),
            denominator: String(control.qdyFrac_AllowedDenoChar ?? ""),
            exponent: String(control.qdyExpo_AllowedChar ?? ""),
            exponentBase: String(control.qdyExpo_AllowedBaseChar ?? ""),
            radicand: String(control.qdyRoot_AllowedRadicandChar ?? ""),
            index: String(control.qdyRoot_AllowedIndexChar ?? ""),
          }
        : null,
      templates: {
        fraction: control.qdyFractionAllowed === true,
        radical: control.qdyRadicalAllowed === true,
        exponent: control.qdyExponentAllowed === true,
        parentheses: baseTemplates.has("PBrace"),
        // The bracket family, each under Hawkes' own name. What each one
        // draws is Hawkes' own statement, read from the lesson bundle's aria
        // labels, SVG paths and keyboard shortcuts: `PBrace` "parentheses",
        // `SBrace` "square brackets", `PSBrace` "left parenthesis, right
        // square bracket" (Ctrl+]), `SPBrace` "left square bracket, right
        // parenthesis" (Ctrl+[). The planner picks among them; this only
        // says which ones the question offers.
        PBrace: baseTemplates.has("PBrace"),
        SBrace: baseTemplates.has("SBrace"),
        PSBrace: baseTemplates.has("PSBrace"),
        SPBrace: baseTemplates.has("SPBrace"),
        absoluteValue: [
          control.qdyBase_AllowedTemplates,
          control.qdyFrac_AllowedNumeTemplates,
          control.qdyFrac_AllowedDenoTemplates,
        ].some((allowed) => String(allowed ?? "").includes("Mod")),
      },
    };
  };

  /**
   * How many own keys a page-owned collection has, or -1 if it cannot say.
   *
   * The loop below walks `0 .. length - 1`. A collection that is not
   * array-like has no `length`, the comparison is false at once, and the loop
   * finds nothing -- which is indistinguishable, in the result, from a
   * collection of one usable control. Both then return a single described
   * textbox, and live that is exactly what came back for a question whose page
   * was showing five boxes. Counting the keys separates them.
   */
  const keysOf = (collection) => {
    try {
      return Object.keys(collection ?? {}).length;
    } catch {
      return -1;
    }
  };

  const candidates = [];
  for (let offset = 0; offset < ui.controlsCollection.length; offset += 1) {
    if (ui.controlsCollection[offset] && ui.controlsCollectionData?.[offset]) {
      candidates.push(offset);
    }
  }
  // A control nobody can type into is not one of the question's answers.
  //
  // Live, lesson 3.3's "find two points on the parabola" step publishes three
  // controls: the two coordinate boxes it shows, and a *disabled* option
  // control it does not. Counting that third one made the answer three values
  // long -- so the reasoning route was asked for three and produced a third
  // coordinate the page had nowhere to put -- and then refused the insertion,
  // because a disabled control accepts nothing. Both boxes had planned
  // perfectly well. Dropping it is what makes the count the page's own.
  //
  // Enabled state is read from the same control the answer would be typed
  // into, so this decides nothing that `answerFitsEditor` would not decide
  // again later; it decides it before the count is taken.
  const described = candidates.map(describe);
  const usable = described.filter(
    (editor) => editor !== null && editor.enabled !== false
  );

  /**
   * The collection this probe read, in counts, beside the control it chose.
   *
   * Every return below reports one control or several, and until now that was
   * the whole of what it said. It is not enough to diagnose the case that
   * matters: a page publishing five boxes and a probe reporting one textbox is
   * consistent with a collection holding one usable control, with four of five
   * being disabled, with `controlsCollectionData` covering only one index, and
   * with a collection that is not array-like at all. Those are four different
   * faults and one description. `multiFieldEvidence` has reported exactly this
   * for the isolated DOM sweep since the labelled-pair fix, and it is what let
   * the sweep's own five-box bug be found in one run rather than guessed at.
   *
   * Counts and a branch name. No control's contents, no name, no character
   * set: those are the description's own fields and are governed there.
   */
  /**
   * How many answer boxes the page is actually drawing.
   *
   * The control collection is not a count of the question's blanks and never
   * was. One blank owns a numerator control and a denominator control -- that
   * is how a Hawkes answer box turns into a fraction when `/` is typed into it
   * -- so a question with a single box can publish two usable controls before
   * anyone has typed anything at all.
   *
   * Live, on 2026-09-07: `2x + y = 2`, "determine the missing coordinate in
   * (4, ?)", one box on screen, one answer. The collection published two
   * usable controls, this probe called it a two-part question, the host was
   * asked for two answers, and a reasoning model duly produced two -- `10` and
   * `10` -- for a question whose answer is `-6`. The panel then offered them as
   * `#1` and `#2` against a page with nowhere to put either.
   *
   * The page's own drawn boxes settle it. This is the same fact the table
   * reader established for a cell -- one logical blank, one or two physical
   * inputs -- asked of the whole question rather than of one cell.
   */
  const drawnBoxes = () => {
    try {
      return [...document.querySelectorAll(HAWKES_FIELD_SELECTOR)].filter((node) => {
        const box = node.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
      }).length;
    } catch {
      return -1;   // unknown, and treated below as "do not overrule the model"
    }
  };
  const drawn = drawnBoxes();

  /** Which published model owns each visible field, and which options coexist.
   * Read-only diagnostic evidence for composite answer surfaces. */
  const ownershipProbe = () => {
    try {
      const fields = [...document.querySelectorAll(HAWKES_FIELD_SELECTOR)].filter((node) => {
        const box = node.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
      });
      const fieldsOf = (control) => {
        const ids = [];
        const seen = new Set();
        const walk = (node, depth = 0) => {
          if (!node || depth > 8 || seen.has(node)) return;
          seen.add(node);
          if (node.Type === "Base") {
            const div = node.objMyDiv?.jquery ? node.objMyDiv[0] : node.objMyDiv;
            const input = div?.querySelector?.("input.qbaseCSS, input[id^=\"txtAns\"], input.boxStyle");
            if (input?.id) ids.push(input.id);
          }
          if (node.arrChildObjects) {
            for (let at = 0; at < node.arrChildObjects.length; at += 1) {
              walk(node.arrChildObjects[at], depth + 1);
            }
          }
        };
        walk(control);
        return [...new Set(ids)];
      };
      const labelOf = (radio) => {
        const direct = String(radio.getAttribute?.("aria-label") ?? "").trim();
        if (direct) return direct;
        const labelled = String(radio.getAttribute?.("aria-labelledby") ?? "")
          .split(/\s+/).filter(Boolean)
          .map((id) => document.getElementById?.(id)?.textContent ?? "").join(" ").trim();
        if (labelled) return labelled;
        const escaped = globalThis.CSS?.escape;
        const label = radio.id && escaped
          ? document.querySelector?.(`label[for="${escaped(radio.id)}"]`)
          : radio.closest?.("label");
        return String(label?.textContent ?? radio.value ?? "").replace(/\s+/g, " ").trim();
      };
      const models = candidates.map((index, position) => ({
        index,
        kind: described[position]?.kind ?? "",
        name: described[position]?.name ?? "",
        enabled: described[position]?.enabled === true,
        fields: fieldsOf(ui.controlsCollection[index]),
      }));
      const radios = [...document.querySelectorAll('input[type="radio"]')]
        .filter((radio) => {
          const box = radio.getBoundingClientRect();
          return !radio.disabled && box.width > 0 && box.height > 0;
        })
        .map((radio) => ({ id: radio.id ?? "", group: radio.name ?? "", label: labelOf(radio) }));
      return {
        fields: fields.map((field) => ({
          id: field.id,
          owners: models.filter((model) => model.fields.includes(field.id))
            .map((model) => model.index),
        })),
        // A populated QDy fraction draws several visible inputs for one
        // expression model. Hawkes leaves only that model's root in the normal
        // tab order; its numerator, denominator and trailing-base inputs use
        // tabindex -1. Preserve both views so composite ownership remains
        // exact before and after a fraction is entered.
        roots: fields.filter((field) => Number(field.tabIndex) >= 0)
          .map((field) => field.id),
        radios,
        models,
      };
    } catch {
      return null;
    }
  };

  const collection = {
    // `length` as the loop above sees it, or -1 when there is no usable one.
    controls: Number.isInteger(ui.controlsCollection?.length)
      ? ui.controlsCollection.length
      : -1,
    controlKeys: keysOf(ui.controlsCollection),
    dataKeys: keysOf(ui.controlsCollectionData),
    // Indices carrying both a control and its data, then how many of those
    // could be described, then how many of those anyone can type into.
    paired: candidates.length,
    described: described.filter(Boolean).length,
    usable: usable.length,
    focused: Number.isInteger(ui.focusedElementIndex)
      ? ui.focusedElementIndex
      : -1,
    // What the page is showing, beside what its model publishes. Where those
    // two disagree the screen is right, and saying both is what makes the
    // disagreement visible in one run instead of inferable from an answer.
    drawn,
  };

  /** The DOM states two axis rows, each with a coordinate and absent option. */
  const axisInterceptSurface = (() => {
    try {
      const fields = [...document.querySelectorAll(HAWKES_FIELD_SELECTOR)].filter((node) => {
        const box = node.getBoundingClientRect();
        return box.width > 0 && box.height > 0;
      });
      const radios = [...document.querySelectorAll('input[type="radio"].opt')].filter((node) => {
        const box = node.getBoundingClientRect();
        return !node.disabled && box.width > 0 && box.height > 0;
      });
      const axes = [...document.querySelectorAll("*")]
        .map((node) => /^([xy])[-\s]intercept\s*:?$/i.exec(
          String(node.textContent ?? "").replace(/\s+/g, " ").trim()
        ))
        .filter(Boolean)
        .map((match) => match[1].toLowerCase());
      const names = radios.map((radio) => {
        const labelled = String(radio.getAttribute?.("aria-label") ?? "").trim();
        if (labelled) return labelled;
        const owner = String(radio.getAttribute?.("aria-labelledby") ?? "")
          .split(/\s+/)
          .filter(Boolean)
          .map((id) => document.getElementById?.(id))
          .filter(Boolean)
          .map((node) => String(node.textContent ?? "").trim())
          .filter(Boolean)
          .join(" ");
        if (owner) return owner;
        const escape = globalThis.CSS?.escape;
        const label = radio.id && escape
          ? document.querySelector?.(`label[for="${escape(radio.id)}"]`)
          : radio.closest?.("label");
        return String(label?.textContent ?? radio.value ?? "").trim();
      });
      return fields.length === 4
        && radios.length === 2
        && new Set(axes).size === 2
        && axes.includes("x")
        && axes.includes("y")
        && names.every((name) => name.toLowerCase() === "absent");
    } catch {
      return false;
    }
  })();
  if (axisInterceptSurface) {
    const optionCount = usable.filter((editor) => editor.kind === "option").length;
    const coordinateEditors = usable.filter((editor) => editor.kind !== "option");
    const signature = (editor) => JSON.stringify({
      kind: editor.kind,
      enabled: editor.enabled,
      allowedCharacters: editor.allowedCharacters,
      maxLength: editor.maxLength,
      templates: editor.templates,
      limits: editor.limits,
      slots: editor.slots,
    });
    if (
      optionCount === 2
      && coordinateEditors.length >= 4
      && new Set(coordinateEditors.map(signature)).size === 1
    ) {
      return {
        ok: true,
        code: "described-axis-intercepts",
        kind: "axis-intercepts",
        coordinateEditor: {
          ...coordinateEditors[0],
          // Four drawn coordinate boxes publish eight controls on the live
          // surface: each numerator has the denominator Hawkes reveals when
          // a slash is entered. Preserve that generic box capability instead
          // of making intercepts integer-only.
          pairedControl: coordinateEditors.length > drawn,
        },
        collection: { ...collection, branch: "axis-intercepts" },
      };
    }
  }
  // Five enabled controls is what lesson 2.1's table-completion question
  // publishes, one per blank cell. Bounded at four, this fell straight past
  // the multi branch to `focusedElementIndex` below and described a single
  // textbox -- so the page that had just said "five boxes" was reported as
  // one, and the question was solved as one.
  // Several controls for one drawn box are one blank's parts -- its numerator
  // and its denominator -- and not several answers. Described as the single
  // control it is, through the same path a one-control question takes.
  // The drawn box is a box, so whichever control stands for it is a typeable
  // one. An option is never a drawn box and so can never be what this branch
  // is about.
  //
  // `focusedElementIndex` is the page's own cursor, and it is not always in
  // the box. Live, on 2026-09-10, lesson 1.6: selecting "One Solution" reveals
  // that question's answer box *and* leaves Hawkes' cursor on the radio that
  // revealed it. The cursor said 1, control 1 is an option, and this branch
  // described the group as the editor -- `kind: "option"` for a page drawing
  // one textbox. The answer was then refused as a choice, on a surface with
  // nothing left to choose:
  //
  //     answer-target-inspected {"code":"focused-answer-field",
  //                              "via":"revealed-option"}
  //     editor-described  {"kind":"option","collection":{"focused":1,"drawn":1,
  //                        "branch":"one-drawn-box"}}
  //     answer-not-insertable {"editor":"editor-option-answer"}
  //
  // The isolated DOM sweep had already followed the radio to its box and said
  // so. Narrowing to the typeable controls first makes the cursor a preference
  // among them rather than the decision itself, and leaves a numerator and
  // denominator pair -- both typeable -- choosing exactly as they did.
  const typeable = candidates.filter((offset, position) => {
    const one = described[position];
    return one !== null && one.enabled !== false && one.kind !== "option";
  });
  if (usable.length >= 2 && drawn === 1 && typeable.length >= 1) {
    const index = typeable.includes(ui.focusedElementIndex)
      ? ui.focusedElementIndex
      : typeable[0];
    const one = describe(index);
    if (one !== null && one.enabled !== false) {
      return {
        ...one,
        // Whether this box has a *second* control behind it, which is the
        // whole of what this probe claims. What that control is for is decided
        // where an answer is planned: a Hawkes answer box turns into a
        // numerator and a denominator when a `/` is typed into it, which is
        // how a rational is entered in a question offering no Fraction
        // template at all. One typeable control is one box with nowhere to put
        // a denominator, and saying otherwise is how a half-built fraction is
        // left in somebody's coursework.
        pairedControl: typeable.length >= 2,
        collection: { ...collection, branch: "one-drawn-box" },
      };
    }
  }
  // A radio group is one answer, however many buttons are in it.
  //
  // Live, on 2026-09-08: a question offering five choices published five
  // option controls, this branch called them five answers, and the host asked
  // Facet for five separate values to a question that has one. A model duly
  // produced five, none of them placeable -- the same question failed this way
  // eleven times in an hour. The count of an option group is the number of
  // things to choose *between*, and a choice is one answer by construction.
  //
  // Decided on what the controls are, not on how many there are, so it holds
  // for a two-option "Real Number / Not a Real Number" question and for a
  // ten-option one alike.
  //
  // A group is still a group when the page publishes typeable controls beside
  // it that it is not drawing. Live, on 2026-09-10: "No Solution / One
  // Solution / Infinite Solutions" publishes its three options *and* the two
  // controls behind the box that "One Solution" reveals -- five usable
  // controls, no box on screen -- and this branch handed all five to `multi`
  // because the group was mixed. The host asked Facet for five values to a
  // question whose answer is one of three printed phrases, Facet solved the
  // equation, and every run was refused as not-insertable. An undrawn control
  // is neither one of the alternatives nor a second answer: it belongs to the
  // alternative that reveals it, and cannot be typed into until that choice is
  // made.
  //
  // `drawn === 0` is the page's own statement that nothing is typeable yet,
  // read here exactly as the one-drawn-box branch above reads it, and never
  // inferred from the controls. A group beside a box the page *is* drawing
  // still falls to the branch below: that is a question with an option *and* a
  // field, and guessing which of them holds the answer is not this probe's to
  // do.
  const options = usable.filter((editor) => editor.kind === "option");
  const wholeGroup = options.length === usable.length;
  if (options.length >= 2 && (wholeGroup || drawn === 0)) {
    return {
      ok: true,
      code: "described-option-group",
      kind: "option",
      // Named as the group, from the options' own names, so a reader can see
      // which group was described. The choices a person actually reads are
      // published in the DOM and are collected there, by `inspectField`.
      name: String(options[0].name ?? ""),
      enabled: true,
      text: "",
      allowedCharacters: "",
      maxLength: null,
      templates: { fraction: false, radical: false, exponent: false },
      // The alternatives, not the controls: a box behind one of them is not a
      // choice anybody can make.
      options: options.length,
      collection: {
        ...collection,
        branch: wholeGroup ? "option-group" : "option-group-undrawn",
      },
    };
  }
  // Two owned expression editors plus one semantic AND/OR group are one
  // composite answer. Hawkes publishes each radio as a model entry, which is
  // why the live surface has four entries for two visible answer fields.
  // Ownership, not the count or model order, decides which two are typeable.
  const pairOwnership = ownershipProbe();
  if (pairOwnership) {
    const logicalFields = pairOwnership.roots.length === 2
      ? pairOwnership.fields.filter((field) => pairOwnership.roots.includes(field.id))
      : pairOwnership.fields.length === 2 ? pairOwnership.fields : [];
    const owners = logicalFields.map((field) => field.owners);
    const ownerIndexes = owners.flat();
    const owned = ownerIndexes.map((index) =>
      pairOwnership.models.find((model) => model.index === index)
    );
    const optionModels = pairOwnership.models.filter((model) => model.kind === "option");
    const radios = pairOwnership.radios.map((radio) => ({
      ...radio,
      semantic: String(radio.label ?? "").trim().toLowerCase(),
    }));
    const groups = new Set(radios.map((radio) => radio.group).filter(Boolean));
    if (
      logicalFields.length === 2
      && owners.every((indexes) => indexes.length === 1)
      && new Set(ownerIndexes).size === 2
      && owned.every((model) => ["dynamic", "textbox"].includes(model?.kind))
      && optionModels.length === 2
      && pairOwnership.models.length === 4
      && radios.length === 2
      && groups.size === 1
      && new Set(radios.map((radio) => radio.semantic)).size === 2
      && radios.every((radio) => ["and", "or"].includes(radio.semantic))
    ) {
      const byIndex = new Map(candidates.map((index, position) => [index, described[position]]));
      return {
        ok: true,
        code: "described-inequality-pair",
        kind: "inequality-pair",
        editors: ownerIndexes.map((index) => byIndex.get(index)),
        connector: {
          group: [...groups][0],
          choices: radios.map(({ id, semantic }) => ({ id, semantic })),
        },
        collection: { ...collection, branch: "inequality-pair" },
        ownership: pairOwnership,
      };
    }
  }
  if (usable.length >= 2 && usable.length <= MAX_ANSWER_PARTS) {
    return described.every(Boolean)
      ? {
          ok: true,
          code: "described-multi",
          kind: "multi",
          editors: usable,
          collection: { ...collection, branch: "multi" },
          ownership: ownershipProbe(),
        }
      : {
          ok: false,
          code: "no-focused-control",
          collection: { ...collection, branch: "multi-incomplete" },
        };
  }
  if (usable.length === 1) {
    // One control left once the unusable ones are out: unambiguous, and the
    // same answer the single-control path below would give.
    return { ...usable[0], collection: { ...collection, branch: "one-usable" } };
  }

  let index = ui.focusedElementIndex;
  let branch = "focused";
  if (!Number.isInteger(index) || index < 0 || index >= ui.controlsCollection.length) {
    // Opening the sidebar clears Hawkes' cursor. Exactly one live model remains
    // unambiguous; a multi-control model is returned above and must additionally
    // match the isolated DOM solution set before insertion is offered.
    if (candidates.length !== 1) {
      return {
        ok: false,
        code: "no-focused-control",
        collection: { ...collection, branch: "none" },
      };
    }
    [index] = candidates;
    branch = "only-candidate";
  }
  const one = describe(index);
  return one === null
    ? { ok: false, code: "no-focused-control", collection: { ...collection, branch: "none" } }
    : { ...one, collection: { ...collection, branch } };
})();
