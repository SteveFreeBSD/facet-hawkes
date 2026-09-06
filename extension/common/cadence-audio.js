"use strict";

/**
 * Local orchestration. This module has no transport, timers, storage or I/O.
 *
 * `arrangeNote()` is a pure function from one already-scored note to the voices
 * that sound it. It reads the score; it never writes to it. Nothing here can
 * move an offset, reach the editor, or decide whether a character is entered.
 *
 * The five arrangements are five readings of the *same* score. They differ in
 * mode, harmony, voicing, register, timbre, envelope, percussion and how the
 * phrase resolves -- the things that actually make two performances sound like
 * different music. What they must never differ in is when a note happens.
 */

/** Timbres, as a partial series and an envelope. Procedural; no samples. */
const VOICES = Object.freeze({
  // Chamber pluck: a bright triangle fundamental with quickly-decaying odd
  // partials, the way a plucked string loses its upper harmonics first.
  pluck: { type: "triangle", partials: [[1, 1], [2, 0.26], [3, 0.1], [5, 0.04]],
    attack: 0.004, decay: 0.9, color: 5200, sweep: 0.34, q: 0.9, detune: 0 },
  // Electric keys: a sine fundamental under a bell-like inharmonic partial.
  keys: { type: "sine", partials: [[1, 1], [2, 0.2], [4.02, 0.11], [7, 0.03]],
    attack: 0.009, decay: 0.85, color: 3400, sweep: 0.46, q: 0.7, detune: 5 },
  // Felt keys: hammer softened by cloth. Slow attack, dark, long release.
  felt: { type: "sine", partials: [[1, 1], [2, 0.13], [3, 0.05]],
    attack: 0.03, decay: 1.3, color: 1450, sweep: 0.55, q: 0.6, detune: 8 },
  // Glass: a slightly stretched octave, which is what makes struck glass ring.
  glass: { type: "sine", partials: [[1, 1], [2.01, 0.24], [3, 0.12], [4, 0.05]],
    attack: 0.012, decay: 0.52, color: 6400, sweep: 0.3, q: 1.4, detune: 0 },
  // Analogue lead: a resonant filter over a saw, closing fast.
  lead: { type: "sawtooth", partials: [[1, 1], [2, 0.22]],
    attack: 0.002, decay: 0.4, color: 5400, sweep: 0.2, q: 6, detune: 10 },
});

/** Percussion, as one shaped noise or sine burst. */
const DRUMS = Object.freeze({
  kick: { noise: false, from: 118, to: 44, decay: 0.19, gain: 0.09, color: 240, q: 1 },
  sub: { noise: false, from: 74, to: 38, decay: 0.28, gain: 0.075, color: 180, q: 1 },
  hat: { noise: true, decay: 0.03, gain: 0.028, color: 8200, q: 1.1, highpass: true },
  ride: { noise: true, decay: 0.14, gain: 0.02, color: 5400, q: 2.2 },
  rim: { noise: true, decay: 0.05, gain: 0.032, color: 1900, q: 6 },
});

/**
 * The five arrangements.
 *
 * `progression` is in scale degrees of `mode`, and the score says which region
 * a note is in: the expression's own operators turn the harmony. `approach` and
 * `cadence` are the last two chords, so each genre ends the way its own idiom
 * ends -- an authentic cadence, a ii-V-I, a plagal fall, a stacked fifth.
 */
const ARRANGEMENTS = Object.freeze({
  classical: {
    root: 48, mode: [0, 2, 4, 5, 7, 9, 11], voice: "pluck", variableVoice: "pluck",
    progression: [[0, 2, 4], [3, 5, 7], [4, 6, 8], [0, 2, 4]],
    approach: [4, 6, 8, 11], cadence: [0, 2, 4, 7],
    melodyRegister: 12, chordRegister: 0, chordGain: 0.05, chordSpreadMs: 16,
    chordDecay: 1.05, bassGain: 0.045, feelMs: 0, drums: () => null,
  },
  jazz: {
    root: 48, mode: [0, 2, 3, 5, 7, 9, 10], voice: "keys", variableVoice: "keys",
    // Rootless voicings: third, seventh and ninth, which is where the colour is.
    progression: [[2, 4, 6, 8], [6, 8, 10, 12], [0, 2, 4, 6], [5, 7, 9, 11]],
    approach: [6, 8, 10, 12], cadence: [0, 2, 4, 8],
    melodyRegister: 12, chordRegister: 0, chordGain: 0.042, chordSpreadMs: 8,
    chordDecay: 1.35, bassGain: 0.05, feelMs: 20,
    // Brushed ride between the accents, a rim shot on them.
    drums: (note) => (note.accent ? "rim" : note.beat % 2 === 1 ? "ride" : null),
  },
  lofi: {
    root: 45, mode: [0, 2, 3, 5, 7, 8, 10], voice: "felt", variableVoice: "felt",
    progression: [[0, 2, 4, 8], [6, 8, 10], [5, 7, 9], [0, 2, 4]],
    approach: [3, 5, 7], cadence: [0, 2, 4, 9],
    melodyRegister: 12, chordRegister: 0, chordGain: 0.05, chordSpreadMs: 26,
    chordDecay: 1.9, bassGain: 0.06, feelMs: 26,
    drums: (note) => (note.beat === 0 ? "kick" : note.beat % 2 === 1 ? "hat" : null),
  },
  electronic: {
    root: 48, mode: [0, 2, 3, 5, 7, 8, 10], voice: "lead", variableVoice: "glass",
    progression: [[0, 4, 7], [5, 9, 12], [2, 6, 9], [6, 10, 13]],
    approach: [6, 10, 13], cadence: [0, 4, 7, 7],
    melodyRegister: 12, chordRegister: 0, chordGain: 0.036, chordSpreadMs: 0,
    chordDecay: 0.7, bassGain: 0.07, feelMs: 0,
    drums: (note) => (note.beat === 0 ? "sub" : note.beat % 2 === 1 ? "hat" : null),
  },
});

/** Custom keeps the Classical harmonic palette under a chosen instrument. */
const CUSTOM_VOICES = ["pluck", "keys", "glass"];

function arrangementFor(options) {
  if (options.genre === "custom") {
    const voice = CUSTOM_VOICES.includes(options.voice) ? options.voice : "glass";
    return { ...ARRANGEMENTS.classical, voice, variableVoice: voice };
  }
  return ARRANGEMENTS[options.genre] ?? ARRANGEMENTS.classical;
}

/** A scale degree, including degrees above the octave, as a semitone offset. */
function semitone(mode, degree) {
  const size = mode.length;
  const step = ((degree % size) + size) % size;
  return mode[step] + 12 * Math.floor(degree / size);
}

/**
 * Which chord this note sits on.
 *
 * The last two notes take the arrangement's own approach and cadence chords, so
 * a phrase resolves rather than merely stopping. Everywhere else the region the
 * score assigned -- one per operator -- picks from the progression.
 */
function chordOf(kit, note) {
  if (note.resolution) { return kit.cadence; }
  if (note.penultimate) { return kit.approach; }
  return kit.progression[(note.harmony ?? 0) % kit.progression.length];
}

/**
 * Where the mathematics puts this note.
 *
 * An exponent lifts an octave, a denominator drops one, deeper nesting narrows
 * toward the middle, and the character itself picks the degree: a digit by its
 * value, a letter by a stable identity, so `x` is the same pitch every time it
 * appears in the answer.
 */
function melodyOf(kit, note, index, chord) {
  const structures = note.structures ?? [];
  const exponent = structures.includes("Exponent") || note.character === "^";
  const denominator = note.slot === "denominator" || note.character === "/";
  const register = kit.melodyRegister + (exponent ? 12 : denominator ? -12 : 0)
    - Math.max(0, (note.depth ?? 0) - 1) * 2;
  if (note.role === "operator") {
    // The operator is the turn itself: it states the new chord's root.
    return kit.root + register + semitone(kit.mode, chord[0]);
  }
  if (note.role === "parenthesis") {
    // A framing fifth. Opening one spreads down, closing one resolves up.
    const opening = /[([{]/u.test(note.character ?? "");
    return kit.root + register + (opening ? -5 : 7);
  }
  if (note.role === "separator") {
    return kit.root + register - 12;
  }
  const degree = note.role === "number"
    ? Number(note.character)
    : (note.character?.codePointAt(0) ?? index);
  return kit.root + register + semitone(kit.mode, degree % kit.mode.length);
}

/**
 * One score note, as everything that should sound at its timestamp.
 *
 * `layers[0]` is always the character's own voice and always carries the score
 * offset exactly. Accompaniment -- chord, bass, percussion -- may carry the
 * arrangement's `feelMs`, which is how a genre sits behind or on top of the
 * beat without the entered character ever moving.
 */
export function arrangeNote(note, index, options = {}) {
  const kit = arrangementFor(options);
  const chord = chordOf(kit, note);
  const layers = [];
  const resolving = note.resolution === true;
  const shimmer = (note.structures ?? []).some((name) => /Radical/u.test(name))
    || note.character === "√";
  if (note.role !== "rest") {
    const timbre = VOICES[note.role === "variable" ? kit.variableVoice : kit.voice]
      ?? VOICES.pluck;
    const exponent = (note.structures ?? []).includes("Exponent") || note.character === "^";
    layers.push({
      kind: "melody",
      midi: melodyOf(kit, note, index, chord),
      ...timbre,
      // A variable rings on; an exponent is a small, quick thing.
      decay: timbre.decay * (resolving ? 1.5 : exponent ? 0.6
        : note.role === "separator" ? 0.3 : note.role === "variable" ? 1.15 : 1),
      color: timbre.color * (exponent ? 1.35 : note.slot === "denominator" ? 0.7 : 1),
      // A phrase opens as it goes: the same shape a player gives one without
      // being asked to. `position` is the score's, so this changes no timing.
      gain: (note.role === "separator" ? 0.05 : note.accent || resolving ? 0.1 : 0.075)
        * (0.88 + 0.24 * (note.position ?? 0.5)),
      partials: shimmer ? [...timbre.partials, [6, 0.05]] : timbre.partials,
      delayMs: 0,
    });
  }
  // Operators, the resolution and the note before it state the harmony. Nothing
  // else does, so the chord moves where the expression moves.
  if (note.role === "operator" || resolving || note.penultimate) {
    const timbre = VOICES[kit.voice] ?? VOICES.pluck;
    chord.forEach((degree, position) => {
      layers.push({
        kind: "chord",
        midi: kit.root + kit.chordRegister + semitone(kit.mode, degree),
        ...timbre,
        type: "sine",
        partials: [[1, 1], [2, 0.12]],
        attack: Math.max(timbre.attack, 0.012),
        // Lo-fi lets a chord hang; electronic cuts it off. The closing one
        // rings twice as long in every arrangement, and is the phrase's end.
        decay: kit.chordDecay * (resolving ? 2 : 1),
        color: Math.min(timbre.color, 3200),
        gain: kit.chordGain * (resolving ? 1.25 : 1),
        delayMs: kit.chordSpreadMs * position,
        feel: true,
      });
    });
  }
  // A quiet foundation, once per turn of the beat shape. The score accents both
  // strong positions; putting the bass on only the first of them is what keeps
  // it a foundation rather than a second melody.
  if (note.accent && note.beat === 0 && note.role !== "rest" && !resolving) {
    layers.push({
      kind: "bass", midi: kit.root - 12 + semitone(kit.mode, chord[0]),
      type: "sine", partials: [[1, 1], [2, 0.08]], attack: 0.008,
      decay: 0.55, color: 620, sweep: 0.6, q: 1, detune: 0,
      gain: kit.bassGain, delayMs: 0, feel: true,
    });
  }
  const drum = note.role === "rest" ? null : kit.drums(note);
  if (drum) {
    layers.push({ kind: "percussion", percussion: drum, ...DRUMS[drum], delayMs: 0, feel: true });
  }
  return { offsetMs: note.offsetMs, feelMs: kit.feelMs, genre: options.genre ?? "classical", layers };
}

/**
 * A template loading in the editor, as sound.
 *
 * Building a fraction or an exponent is real editor work, and the score never
 * allotted time for it: the phrase holds while the structure appears. Sounding
 * that hold is what turns a silent gap into a musical one -- a low, wide frame
 * that the notes inside it then fill. It is deliberately quiet and short, and
 * it is not a scored note: it carries no offset and cannot advance the phrase.
 *
 * @param {string} structure the editor template's own name
 */
export function arrangeStructure(structure, options = {}) {
  const kit = arrangementFor(options);
  const timbre = VOICES[kit.voice] ?? VOICES.pluck;
  // Where the structure will put the notes it is about to hold: an exponent
  // opens above, a fraction opens below, a radical opens wide.
  const lift = /Exponent/u.test(structure) ? 12
    : /Fraction/u.test(structure) ? -12 : /Radical/u.test(structure) ? -5 : 0;
  const layers = [0, 7, 12].map((interval, position) => ({
    kind: "structure",
    midi: kit.root + kit.chordRegister + lift + interval,
    ...timbre, type: "sine", partials: [[1, 1], [2, 0.09]],
    attack: 0.05, decay: 1.1, color: Math.min(timbre.color, 2200), q: 0.7,
    gain: 0.03, delayMs: position * 22, feel: false,
  }));
  return { structure, feelMs: 0, genre: options.genre ?? "classical", layers };
}

/** How far ahead of a written character its voice is scheduled, in ms. */
const LEAD_MS = 30;
/** The least a voice may be scheduled ahead of now, so its attack renders whole. */
const MIN_LEAD_MS = 8;
/** The most a voice may ever be held after its character. Well inside the
 *  window in which a sound and a sight are heard as one event. */
const MAX_LAG_MS = 60;
const MAX_VOICES = 24;

/**
 * One small instrument per extension document.
 *
 * Nothing here is a clock. Voices exist only because `strike()` was called from
 * an accepted write, and `strike()` never queues a note that has not happened.
 * What it does own is *where in the audio stream* that note starts: scheduling
 * every voice against one anchor derived from the score's own offsets removes
 * the browser's wake-up jitter from the rhythm, while a bounded clamp keeps
 * every voice within {@link MAX_LAG_MS} of the character that caused it.
 */
export class CadenceInstrument {
  /**
   * @param {() => AudioContext} contextFactory
   * @param {{idle?: "suspend"|"close"}} [policy] `close` for a document that
   *   cannot re-obtain user activation to resume a suspended device.
   */
  constructor(contextFactory = () => new AudioContext({ latencyHint: "interactive" }),
    { idle = "suspend" } = {}) {
    this.contextFactory = contextFactory;
    this.idlePolicy = idle;
    this.context = null;
    this.master = null;
    this.noise = null;
    this.voices = new Set();
    this.volume = 0.35;
    this.muted = false;
    this.failed = false;
    this.strikes = 0;
    this.lastOffsetMs = null;
    this.anchorTime = null;
    this.anchorOffsetMs = 0;
    this.reanchors = 0;
    this.holds = [];
  }

  // Invoke synchronously in the actual Preview/Insert click handler. Never
  // await resume: Firefox may leave that promise pending under autoplay denial.
  unlock() {
    this.draining = false;
    this.anchorTime = null;
    this.reanchors = 0;
    this.holds = [];
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
        this.noise = null;
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

  /**
   * When this note's voices should start, in this device's own time base.
   *
   * The first note of a performance sets an anchor a fixed {@link LEAD_MS}
   * ahead; every later note is placed at that anchor plus its own score offset.
   * A note whose write arrived early is therefore held to the time the score
   * gave it, which is what removes jitter from the rhythm. A note whose write
   * arrived late cannot be played in the past: it starts as soon as it can and
   * the anchor moves with it, so one late wake-up costs one late note instead of
   * a correction the rest of the phrase then has to fight.
   */
  scheduleAt(offsetMs) {
    const now = this.context.currentTime;
    if (this.anchorTime === null) {
      this.anchorTime = now + LEAD_MS / 1000;
      this.anchorOffsetMs = offsetMs;
    }
    const ideal = this.anchorTime + (offsetMs - this.anchorOffsetMs) / 1000;
    const at = Math.min(now + MAX_LAG_MS / 1000,
      Math.max(now + MIN_LEAD_MS / 1000, ideal));
    if (at !== ideal) {
      this.anchorTime = at;
      this.anchorOffsetMs = offsetMs;
      this.reanchors += 1;
    }
    return at;
  }

  /** How this instrument actually placed the phrase it just played. */
  timing() {
    const holds = [...this.holds];
    return {
      leadMs: LEAD_MS, maxLagMs: MAX_LAG_MS, reanchors: this.reanchors,
      holds,
      meanHoldMs: holds.length
        ? Math.round(holds.reduce((total, hold) => total + hold, 0) / holds.length) : null,
      baseLatencyMs: this.context ? Math.round((this.context.baseLatency ?? 0) * 1000) : null,
      outputLatencyMs: this.context ? Math.round((this.context.outputLatency ?? 0) * 1000) : null,
    };
  }

  strike(note, index, options) {
    // Device startup is asynchronous even after a valid gesture. Queue this
    // event's voice in the resuming graph, so a fast first write is not lost.
    // No future score events are queued here, and insertion never waits for it.
    if (this.status() !== "ready" && !(this.resuming && !this.failed && !this.draining
        && !this.muted && this.volume > 0 && this.context?.state === "suspended")) { return false; }
    try {
      const voiced = arrangeNote(note, index, options);
      // The anchor tracks every scored position, silent ones included, so a
      // rest does not make the note after it look early. Only a position that
      // actually sounds is recorded as a measured hold.
      const at = this.scheduleAt(voiced.offsetMs);
      if (voiced.layers.length) {
        if (this.holds.length >= 128) { this.holds.shift(); }
        this.holds.push(Math.round((at - this.context.currentTime) * 1000));
      }
      for (const layer of voiced.layers) {
          // Two different things, bounded separately. `feelMs` is how far behind
        // the beat a genre's accompaniment sits, and stays small. `delayMs` is
        // the roll of a chord, which is the chord itself and may be wider.
        const lag = Math.min(30, layer.feel ? voiced.feelMs : 0)
          + Math.min(120, layer.delayMs ?? 0);
        this.voice(layer, at + lag / 1000);
      }
      this.strikes += voiced.layers.length ? 1 : 0;
      this.lastOffsetMs = voiced.offsetMs;
      return voiced.layers.length > 0;
    } catch {
      this.failed = true;
      this.stop();
      return false;
    }
  }

  /**
   * Sound a template landing, without disturbing the phrase's anchor.
   *
   * The editor's structural work is a fermata: the score's clock is held while
   * it happens. So this schedules against the device's own clock and then drops
   * the anchor, letting the note that follows re-establish the phrase in tempo
   * rather than measuring its lateness against an origin the hold moved.
   */
  strikeStructure(structure, options) {
    if (this.status() !== "ready") { return false; }
    try {
      const voiced = arrangeStructure(structure, options);
      const at = this.context.currentTime + MIN_LEAD_MS / 1000;
      for (const layer of voiced.layers) {
        this.voice(layer, at + (layer.delayMs ?? 0) / 1000);
      }
      this.anchorTime = null;
      return true;
    } catch {
      this.failed = true;
      this.stop();
      return false;
    }
  }

  /** A half second of white noise, made once per device and shared by the kit. */
  noiseBuffer() {
    if (!this.noise) {
      const frames = Math.floor(this.context.sampleRate * 0.5);
      const buffer = this.context.createBuffer(1, frames, this.context.sampleRate);
      const channel = buffer.getChannelData(0);
      for (let frame = 0; frame < frames; frame += 1) {
        channel[frame] = Math.random() * 2 - 1;
      }
      this.noise = buffer;
    }
    return this.noise;
  }

  /** Render one layer: a shaped noise burst, or a small additive tone. */
  voice(layer, at) {
    while (this.voices.size >= MAX_VOICES) { this.voices.values().next().value.stop(); }
    const context = this.context;
    const nodes = [];
    const sources = [];
    const envelope = context.createGain();
    const filter = context.createBiquadFilter();
    const decay = layer.decay;
    if (layer.percussion) {
      filter.type = layer.highpass ? "highpass" : layer.noise ? "bandpass" : "lowpass";
      filter.Q.value = layer.q;
      filter.frequency.setValueAtTime(layer.color, at);
    } else {
      filter.type = "lowpass";
      filter.Q.value = layer.q ?? 1;
      filter.frequency.setValueAtTime(layer.color, at);
      filter.frequency.exponentialRampToValueAtTime(
        Math.max(320, layer.color * (layer.sweep ?? 0.4)), at + decay
      );
    }
    envelope.connect(filter);
    filter.connect(this.master);
    const attack = layer.percussion ? 0.001 : layer.attack;
    envelope.gain.setValueAtTime(0, at);
    envelope.gain.linearRampToValueAtTime(layer.gain, at + attack);
    envelope.gain.exponentialRampToValueAtTime(0.0001, at + decay);
    if (layer.percussion && layer.noise) {
      const source = context.createBufferSource();
      source.buffer = this.noiseBuffer();
      source.connect(envelope);
      sources.push(source);
      nodes.push(source);
    } else if (layer.percussion) {
      // A drum with a pitch: the fall from `from` to `to` is what makes it read
      // as a kick rather than as a very short bass note.
      const oscillator = context.createOscillator();
      oscillator.type = "sine";
      oscillator.frequency.setValueAtTime(layer.from, at);
      oscillator.frequency.exponentialRampToValueAtTime(layer.to, at + decay * 0.7);
      oscillator.connect(envelope);
      sources.push(oscillator);
      nodes.push(oscillator);
    } else {
      const hz = 440 * 2 ** ((layer.midi - 69) / 12);
      for (const [ratio, level] of layer.partials) {
        const oscillator = context.createOscillator();
        const partialGain = context.createGain();
        oscillator.type = ratio === 1 ? layer.type : "sine";
        oscillator.frequency.setValueAtTime(hz * ratio, at);
        if (layer.detune) { oscillator.detune.setValueAtTime(layer.detune * (ratio - 1), at); }
        partialGain.gain.value = level;
        oscillator.connect(partialGain);
        partialGain.connect(envelope);
        sources.push(oscillator);
        nodes.push(oscillator, partialGain);
      }
    }
    let stopped = false;
    const voice = { stop: () => {
      if (stopped) { return; }
      stopped = true;
      for (const source of sources) { try { source.stop(); } catch { /* ended */ } }
      for (const node of [...nodes, envelope, filter]) { try { node.disconnect(); } catch { /* closed */ } }
      this.voices.delete(voice);
      if (this.draining && this.voices.size === 0) { this.finish(); }
    } };
    this.voices.add(voice);
    sources[0].onended = voice.stop;
    for (const source of sources) {
      source.start(at);
      source.stop(at + decay + 0.02);
    }
  }

  stop() {
    for (const voice of [...this.voices]) { voice.stop(); }
  }

  finish() {
    this.draining = true;
    this.anchorTime = null;
    // Autoplay denial may leave resume pending indefinitely. Discard silent
    // queued voices so a later gesture cannot replay a completed answer.
    if (this.context?.state === "suspended" && this.voices.size) { this.stop(); }
    if (this.voices.size > 0) { return; }
    // A document that can obtain user activation again -- Settings, where
    // Preview is a real click -- suspends and keeps its device. The event page
    // cannot: Firefox admits a *new* AudioContext in an extension background
    // page under its autoplay exemption, but a resume() there has no activation
    // to draw on and can stay pending forever. So that instrument closes
    // instead, and the next Insert opens a device that starts running.
    try {
      if (this.idlePolicy === "close") { this.close(); }
      else { this.context?.suspend().catch(() => {}); }
    } catch { /* audio only */ }
  }

  close() {
    this.stop();
    const context = this.context;
    this.context = null;
    this.master = null;
    this.noise = null;
    this.resuming = false;
    this.draining = true;
    this.anchorTime = null;
    try { context?.close().catch(() => {}); } catch { /* audio only */ }
  }
}
