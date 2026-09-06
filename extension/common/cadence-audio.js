"use strict";

/** Local orchestration. This module has no transport, timers, storage or I/O. */
const ARRANGEMENTS = Object.freeze({
  classical: { voice: "pluck", scale: [0, 2, 4, 7, 9], chord: [0, 7, 12], root: 48, decay: 0.85, color: 5200 },
  jazz: { voice: "keys", scale: [0, 2, 3, 7, 10], chord: [0, 3, 10, 14], root: 48, decay: 0.7, color: 3600 },
  lofi: { voice: "keys", scale: [0, 2, 5, 7, 9], chord: [0, 7, 14], root: 45, decay: 1.05, color: 1600 },
  electronic: { voice: "glass", scale: [0, 3, 5, 7, 10], chord: [0, 7, 12], root: 48, decay: 0.45, color: 6400 },
});

/** A voicing has precisely the score note's timestamp, in every genre. */
export function arrangeNote(note, index, options = {}) {
  const preset = ARRANGEMENTS[options.genre] ?? ARRANGEMENTS.classical;
  const kit = options.genre === "custom"
    ? { ...preset, voice: ["pluck", "keys", "glass"].includes(options.voice) ? options.voice : "glass" }
    : preset;
  const structures = note.structures ?? [];
  const degree = note.role === "number" ? Number(note.character) % kit.scale.length
    : (note.character?.codePointAt(0) ?? index) % kit.scale.length;
  const register = structures.includes("Exponent") || note.character === "^" ? 24
    : note.slot === "denominator" || note.character === "/" ? 0 : 12;
  const root = kit.root;
  let midi = root + register + kit.scale[degree];
  if (note.role === "parenthesis") { midi = root + 7; }
  if (note.role === "separator") { midi = root; }
  const resolving = note.resolution;
  const harmonic = resolving || note.role === "operator";
  const pitches = note.role === "rest" ? [] : harmonic
    ? kit.chord.map((interval) => root + interval + (resolving ? 0 : 5))
    : [midi];
  // A quiet foundation on accents makes a phrase breathe without a drum loop.
  if (!harmonic && pitches.length && note.accent) { pitches.push(root); }
  return {
    offsetMs: note.offsetMs,
    voice: kit.voice,
    pitches,
    gain: note.role === "separator" ? 0.045 : note.accent || resolving ? 0.1 : 0.075,
    decay: resolving ? 1.35 : note.role === "separator" ? 0.24 : kit.decay,
    color: kit.color,
    shimmer: structures.some((name) => /Radical/u.test(name)) || note.character === "√",
  };
}

/**
 * One small instrument per extension document. All oscillators start only in
 * strike(), called by a score event. AudioParam envelopes shape that voice;
 * they never schedule the next note. At most 24 voices survive a late burst.
 */
export class CadenceInstrument {
  constructor(contextFactory = () => new AudioContext({ latencyHint: "interactive" })) {
    this.contextFactory = contextFactory;
    this.context = null;
    this.master = null;
    this.voices = new Set();
    this.volume = 0.35;
    this.muted = false;
    this.failed = false;
    this.strikes = 0;
    this.lastOffsetMs = null;
  }

  // Invoke synchronously in the actual Preview/Insert click handler. Never
  // await resume: Firefox may leave that promise pending under autoplay denial.
  unlock() {
    this.draining = false;
    try {
      if (!this.context || this.context.state === "closed") {
        this.context = this.contextFactory();
        this.master = this.context.createGain();
        const limiter = this.context.createDynamicsCompressor();
        limiter.threshold.value = -12;
        limiter.knee.value = 12;
        limiter.ratio.value = 8;
        this.master.connect(limiter);
        limiter.connect(this.context.destination);
        this.setLevel(this.volume, this.muted);
      }
      this.failed = false;
      const context = this.context;
      this.resuming = true;
      context.resume().then(() => {
        if (this.context === context) { this.resuming = false; }
      }, () => {
        if (this.context === context) { this.resuming = false; this.failed = true; }
      });
    } catch { this.failed = true; }
    return this.status();
  }

  setLevel(volume, muted = false) {
    this.volume = Number.isFinite(volume) ? Math.max(0, Math.min(1, volume)) : 0.35;
    this.muted = muted === true;
    try {
      this.master?.gain.setTargetAtTime(this.muted ? 0 : this.volume, this.context.currentTime, 0.015);
    } catch { this.failed = true; }
  }

  status() {
    return this.failed ? "unavailable" : this.muted || this.volume === 0 ? "muted"
      : this.context?.state === "running" ? "ready" : this.draining ? "idle" : "blocked";
  }

  strike(note, index, options) {
    // Device startup is asynchronous even after a valid gesture. Queue this
    // event's voice in the resuming graph, so a fast first write is not lost.
    // No future score events are queued here, and insertion never waits for it.
    if (this.status() !== "ready" && !(this.resuming && !this.failed && !this.draining
        && !this.muted && this.volume > 0 && this.context?.state === "suspended")) { return false; }
    try {
      const voiced = arrangeNote(note, index, options);
      const at = this.context.currentTime;
      for (const pitch of voiced.pitches) { this.voice(pitch, voiced, at); }
      this.strikes += voiced.pitches.length ? 1 : 0;
      this.lastOffsetMs = voiced.offsetMs;
      return voiced.pitches.length > 0;
    } catch {
      this.failed = true;
      this.stop();
      return false;
    }
  }

  voice(midi, kit, at) {
    while (this.voices.size >= 24) { this.voices.values().next().value.stop(); }
    const context = this.context;
    const envelope = context.createGain();
    const filter = context.createBiquadFilter();
    filter.type = "lowpass";
    filter.frequency.setValueAtTime(kit.color, at);
    filter.frequency.exponentialRampToValueAtTime(Math.max(400, kit.color * 0.4), at + kit.decay);
    envelope.connect(filter);
    filter.connect(this.master);
    const attack = kit.voice === "glass" ? 0.012 : 0.006;
    envelope.gain.setValueAtTime(0, at);
    envelope.gain.linearRampToValueAtTime(kit.gain, at + attack);
    envelope.gain.exponentialRampToValueAtTime(0.0001, at + kit.decay);
    const hz = 440 * 2 ** ((midi - 69) / 12);
    const nodes = [];
    const oscillators = [];
    const partials = kit.voice === "pluck" ? [[1, 1], [2, 0.3], [3, 0.09]]
      : kit.voice === "keys" ? [[1, 1], [2, 0.18], [4, 0.08]]
        : [[1, 1], [2.001, 0.22], [3, 0.1]];
    if (kit.shimmer) { partials.push([4, 0.045]); }
    for (const [ratio, level] of partials) {
      const oscillator = context.createOscillator();
      const partialGain = context.createGain();
      oscillator.type = kit.voice === "pluck" && ratio === 1 ? "triangle" : "sine";
      oscillator.frequency.setValueAtTime(hz * ratio, at);
      partialGain.gain.value = level;
      oscillator.connect(partialGain);
      partialGain.connect(envelope);
      oscillators.push(oscillator);
      nodes.push(oscillator, partialGain);
    }
    let stopped = false;
    const voice = { stop: () => {
      if (stopped) { return; }
      stopped = true;
      for (const oscillator of oscillators) { try { oscillator.stop(); } catch { /* ended */ } }
      for (const node of [...nodes, envelope, filter]) { try { node.disconnect(); } catch { /* closed */ } }
      this.voices.delete(voice);
      if (this.draining && this.voices.size === 0) { this.finish(); }
    } };
    this.voices.add(voice);
    oscillators[0].onended = voice.stop;
    for (const oscillator of oscillators) {
      oscillator.start(at);
      oscillator.stop(at + kit.decay + 0.02);
    }
  }

  stop() {
    for (const voice of [...this.voices]) { voice.stop(); }
  }

  finish() {
    this.draining = true;
    // Autoplay denial may leave resume pending indefinitely. Discard silent
    // queued voices so a later gesture cannot replay a completed answer.
    if (this.context?.state === "suspended" && this.voices.size) { this.stop(); }
    if (this.voices.size === 0) {
      try { this.context?.suspend().catch(() => {}); } catch { /* audio only */ }
    }
  }

  close() {
    this.stop();
    const context = this.context;
    this.context = null;
    this.master = null;
    this.resuming = false;
    this.draining = true;
    try { context?.close().catch(() => {}); } catch { /* audio only */ }
  }
}
