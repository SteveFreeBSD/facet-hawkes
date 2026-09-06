"use strict";

/**
 * Answer Cadence's shared score and transport.
 *
 * This file is deliberately a classic script rather than a module. Firefox
 * injects it immediately before the isolated Hawkes editor prelude, where the
 * two scripts share an extension-only global scope; Settings loads the same
 * file before its module. It contains presentation timing only. Answer text,
 * target ownership, editor planning, and insertion safety live elsewhere.
 */

var ethnosCadence = (function () {
  const FALLBACK = Object.freeze({
    tempoBpm: 82,
    durationMinMs: 5000,
    durationMaxMs: 10000,
    rhythmWeights: Object.freeze([1, 0.68, 1.18, 0.78]),
    swingRatio: 0.12,
    variationRatio: 0.18,
    symbolRestRatio: 0.42,
  });

  const OPERATOR_PATTERN = /[-=+*/^,;:]/u;
  const CLOSING_PATTERN = /[)\]}]/u;

  function bounded(value, minimum, maximum, fallback) {
    return typeof value === "number" && Number.isFinite(value)
      ? Math.min(maximum, Math.max(minimum, value))
      : fallback;
  }

  /** Treat a cadence snapshot as data even when its sender is trusted. */
  function normalize(offered = {}) {
    const weights = Array.isArray(offered.rhythmWeights)
      ? offered.rhythmWeights
          .slice(0, 8)
          .map((weight) => bounded(weight, 0.25, 2.5, 1))
      : [];
    const firstDuration = bounded(
      offered.durationMinMs, 2000, 12000, FALLBACK.durationMinMs
    );
    const secondDuration = bounded(
      offered.durationMaxMs, 2000, 12000, FALLBACK.durationMaxMs
    );
    return {
      tempoBpm: bounded(offered.tempoBpm, 30, 300, FALLBACK.tempoBpm),
      durationMinMs: Math.min(firstDuration, secondDuration),
      durationMaxMs: Math.max(firstDuration, secondDuration),
      rhythmWeights: weights.length > 1 ? weights : [...FALLBACK.rhythmWeights],
      swingRatio: bounded(offered.swingRatio, 0, 0.6, FALLBACK.swingRatio),
      variationRatio: bounded(
        offered.variationRatio, 0, 0.35, FALLBACK.variationRatio
      ),
      symbolRestRatio: bounded(
        offered.symbolRestRatio, 0, 1, FALLBACK.symbolRestRatio
      ),
    };
  }

  // A score is repeatable, including its timing variation. Genre is deliberately
  // absent from this seed: changing the orchestra cannot move a character.
  function scoreRandom(characters) {
    let seed = 2166136261;
    for (const character of characters.join("")) {
      seed = Math.imul(seed ^ character.codePointAt(0), 16777619) >>> 0;
    }
    return () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 0x100000000;
    };
  }

  /**
   * Whether this position is emphasized by the chosen beat shape.
   *
   * Accents come from the pattern weight and the swing adjustment, exactly as
   * the design note describes them: a position the arrangement leans on, not
   * the longer structural rest that operators and separators earn. Both the
   * timeline and the rhythm strip read this one rule so they cannot disagree.
   */
  function accented(index, cadence) {
    const weight = cadence.rhythmWeights[index % cadence.rhythmWeights.length];
    return weight > 1 || (index % 2 === 0 && cadence.swingRatio > 0);
  }

  /** Whether this character earns the longer structural rest after it. */
  function restsAfter(character) {
    return /\s/u.test(character) || OPERATOR_PATTERN.test(character);
  }

  function rhythmicWeight(character, index, cadence, random) {
    let weight = cadence.rhythmWeights[index % cadence.rhythmWeights.length];
    if (index % 2 === 0) {
      weight *= 1 + cadence.swingRatio;
    } else {
      weight *= 1 - cadence.swingRatio * 0.5;
    }
    if (/\s/u.test(character)) {
      weight *= 1 + cadence.symbolRestRatio * 1.35;
    } else if (OPERATOR_PATTERN.test(character)) {
      weight *= 1 + cadence.symbolRestRatio;
    } else if (CLOSING_PATTERN.test(character)) {
      weight *= 1 + cadence.symbolRestRatio * 0.5;
    }
    return weight * (1 + ((random() * 2) - 1) * cadence.variationRatio);
  }

  /** Build the real, hard-window-bounded note score used by insertion. */
  function planCharacters(characters, offered = {}, random = scoreRandom(characters)) {
    const cadence = normalize(offered);
    if (characters.length === 0) {
      return {
        cadence, offsets: [], weights: [], durationMs: 0,
        effectiveTempoBpm: cadence.tempoBpm, withinWindow: true,
        blendedDurationMs: 0, clampedBy: "none",
      };
    }
    if (characters.length === 1) {
      return {
        cadence, offsets: [0], weights: [], durationMs: 0,
        effectiveTempoBpm: cadence.tempoBpm, withinWindow: true,
        blendedDurationMs: 0, clampedBy: "none",
      };
    }

    const weights = characters
      .slice(0, -1)
      .map((character, index) => rhythmicWeight(character, index, cadence, random));
    const totalWeight = weights.reduce((total, weight) => total + weight, 0);
    const beatMs = 60000 / cadence.tempoBpm;
    const musicalDuration = Math.max(1, totalWeight) * beatMs;
    const windowDuration = cadence.durationMinMs
      + Math.floor(random() * (cadence.durationMaxMs - cadence.durationMinMs + 1));
    // The length tempo and the window jointly asked for, before the window has
    // the last word. Keeping it is what lets a caller say *why* a phrase came
    // out at 5.0s when 300 BPM was requested, instead of only that it did.
    const blendedDurationMs = Math.round(
      (musicalDuration * 0.72) + (windowDuration * 0.28)
    );
    const durationMs = Math.min(
      cadence.durationMaxMs, Math.max(cadence.durationMinMs, blendedDurationMs)
    );
    const offsets = [0];
    let elapsedWeight = 0;
    for (const weight of weights) {
      elapsedWeight += weight;
      offsets.push(Math.round(durationMs * elapsedWeight / totalWeight));
    }
    offsets[offsets.length - 1] = durationMs;
    return {
      cadence,
      offsets,
      weights,
      durationMs,
      effectiveTempoBpm: Math.round(60000 * totalWeight / durationMs),
      withinWindow:
        durationMs >= cadence.durationMinMs && durationMs <= cadence.durationMaxMs,
      blendedDurationMs,
      // Which end of the hard window, if either, overrode the tempo-led length.
      clampedBy:
        blendedDurationMs < cadence.durationMinMs
          ? "minimum"
          : blendedDurationMs > cadence.durationMaxMs
            ? "maximum"
            : "none",
    };
  }

  function pause(ms, signal) {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(cancelled());
        return;
      }
      const timer = setTimeout(finish, Math.max(0, ms));
      function finish() {
        signal?.removeEventListener("abort", cancel);
        resolve();
      }
      function cancel() {
        clearTimeout(timer);
        signal.removeEventListener("abort", cancel);
        reject(cancelled());
      }
      signal?.addEventListener("abort", cancel, { once: true });
    });
  }

  function cancelled() {
    const error = new Error("Cadence preview cancelled");
    error.name = "AbortError";
    return error;
  }

  /**
   * Wait until a deadline, approaching it in two steps.
   *
   * One long `setTimeout` is coalesced with whatever else its process has
   * pending: a four-second gap between notes was measured waking a third of a
   * second late, which is audible. A timer that is already nearly due is fired
   * promptly, so stopping short and re-arming turns that into a few
   * milliseconds. It costs one extra timer per note and cannot overshoot,
   * because every wait is still computed from the same absolute origin.
   */
  const APPROACH_MS = 200;
  async function waitUntil(remaining, signal) {
    for (let guard = 0; guard < 8; guard += 1) {
      const wait = remaining();
      if (wait <= 0) {
        if (signal?.aborted) { throw cancelled(); }
        return;
      }
      await pause(wait > APPROACH_MS * 1.25 ? wait - APPROACH_MS : wait, signal);
    }
  }

  /** Run one callback per scheduled note, with cancellation between notes. */
  async function playCharacters(
    characters, write, offered = {}, { signal, random, visit } = {}
  ) {
    const phrase = offered.score ?? planSemanticPhrase(
      [{ op: "type", text: characters.join("") }], offered, random
    );
    const startedAt = offered.startedAt ?? performance.now();
    for (let index = 0; index < characters.length; index += 1) {
      await waitUntil(
        () => phrase.offsets[index] - (performance.now() - startedAt), signal
      );
      const failure = write(characters[index], index, phrase);
      if (failure) {
        return { failure, phrase };
      }
      // The write is authoritative. Presentation is an optional observer of
      // this very callback and never a gate, promise, or second transport.
      try { visit?.(phrase.notes[index], index, phrase); } catch { /* silent */ }
    }
    return { failure: null, phrase };
  }

  /**
   * Add editor-plan semantics to the same note score for Settings telemetry.
   * Template and slot actions share the next note's clock, just as structured
   * insertion does; they never manufacture a second performance.
   */
  function planSemanticPhrase(steps, offered = {}, random) {
    const notes = [];
    for (let planIndex = 0; planIndex < steps.length; planIndex += 1) {
      const step = steps[planIndex];
      if (step.op !== "type") {
        continue;
      }
      for (const character of [...(step.text ?? "")]) {
        notes.push({ character, planIndex });
      }
    }
    const score = planCharacters(notes.map((note) => note.character), offered, random);
    // Give every note the facts a rhythm strip and an arrangement need -- when
    // it lands, whether the arrangement leans on it, whether a structural rest
    // follows, how far through the phrase it is, and which position of the beat
    // shape it occupies -- so no caller re-derives the accent rule for itself.
    // These describe the score. They are read by orchestration; they are never
    // written by it, and none of them can move an offset.
    const beats = score.cadence.rhythmWeights.length;
    for (let index = 0; index < notes.length; index += 1) {
      notes[index].offsetMs = score.offsets[index] ?? score.durationMs;
      notes[index].accent = accented(index, score.cadence);
      notes[index].rest =
        restsAfter(notes[index].character) && index < notes.length - 1;
      notes[index].beat = index % beats;
      notes[index].position =
        notes.length < 2 ? 1 : index / (notes.length - 1);
      notes[index].penultimate = index === notes.length - 2;
    }
    const timeline = [];
    let noteIndex = 0;
    const openStructures = [];
    let structureIndex = 0;
    let harmony = 0;
    for (let planIndex = 0; planIndex < steps.length; planIndex += 1) {
      const step = steps[planIndex];
      const at = score.offsets[noteIndex] ?? score.durationMs;
      if (step.op === "template") {
        const structure = { name: step.name, index: structureIndex };
        structureIndex += 1;
        openStructures.push(structure);
        timeline.push({
          offsetMs: at,
          kind: "structure-enter",
          label: step.name,
          structureIndex: structure.index,
        });
        continue;
      }
      if (step.op === "slot") {
        const structure = openStructures[openStructures.length - 1];
        if (structure) { structure.slot = step.name; }
        timeline.push({
          offsetMs: at, kind: "structure-enter", label: step.name,
          structure: structure?.name ?? "",
          structureIndex: structure?.index,
        });
        continue;
      }
      if (step.op === "base") {
        const structure = openStructures.pop();
        timeline.push({
          offsetMs: at,
          kind: "structure-exit",
          label: structure?.name ?? "structure",
          structureIndex: structure?.index,
        });
        continue;
      }
      for (const character of [...(step.text ?? "")]) {
        const offsetMs = score.offsets[noteIndex] ?? score.durationMs;
        const nextOffset = score.offsets[noteIndex + 1];
        const kind = OPERATOR_PATTERN.test(character) ? "operator" : "character";
        notes[noteIndex].role = /\s/u.test(character) ? "rest"
          : /[,;:]/u.test(character) ? "separator"
          : /[()\[\]{}]/u.test(character) ? "parenthesis"
          : /[0-9]/u.test(character) ? "number"
          : OPERATOR_PATTERN.test(character) ? "operator" : "variable";
        notes[noteIndex].structures = openStructures.map((structure) => structure.name);
        notes[noteIndex].slot = openStructures[openStructures.length - 1]?.slot ?? "";
        notes[noteIndex].resolution = noteIndex === notes.length - 1;
        notes[noteIndex].depth = openStructures.length;
        // The expression's own grammar is the harmonic rhythm: an operator or a
        // separator turns the chord, so `2x + 3/5` changes harmony where the
        // mathematics does. An arrangement decides what the turn sounds like; it
        // does not decide when one happens.
        notes[noteIndex].harmony = harmony;
        if (OPERATOR_PATTERN.test(character) && noteIndex < notes.length - 1) {
          harmony += 1;
        }
        timeline.push({
          offsetMs, kind, label: character, noteIndex,
          accent: accented(noteIndex, score.cadence),
        });
        if (restsAfter(character) && nextOffset !== undefined) {
          timeline.push({
            offsetMs: offsetMs + Math.round((nextOffset - offsetMs) / 2),
            kind: "rest", label: "structural rest", noteIndex,
          });
        }
        noteIndex += 1;
      }
    }
    while (openStructures.length > 0) {
      const structure = openStructures.pop();
      timeline.push({
        offsetMs: score.durationMs,
        kind: "structure-exit",
        label: structure.name,
        structureIndex: structure.index,
      });
    }
    timeline.push({ offsetMs: score.durationMs, kind: "resolution", label: "phrase" });
    timeline.sort((left, right) => left.offsetMs - right.offsetMs);
    return { ...score, notes, timeline };
  }

  /** Transport a semantic phrase without touching any website or editor. */
  async function playSemanticPhrase(phrase, visit, { signal, startedAt = performance.now() } = {}) {
    for (let index = 0; index < phrase.timeline.length; index += 1) {
      const step = phrase.timeline[index];
      await waitUntil(() => step.offsetMs - (performance.now() - startedAt), signal);
      visit(step, index, phrase, performance.now() - startedAt);
    }
    return phrase;
  }

  return Object.freeze({
    accented,
    normalize,
    planCharacters,
    planSemanticPhrase,
    playCharacters,
    playSemanticPhrase,
  });
})();

// Classic in isolated worlds and Settings; side-effect import in the event page.
globalThis.ethnosCadence = ethnosCadence;
