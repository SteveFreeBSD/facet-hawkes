#!/usr/bin/env python3
"""Render the five arrangements to WAV, through the add-on's own audio code.

The smoke test proves sound comes out. It cannot say whether the five
arrangements are five pieces of music or one piece with the waveform changed,
and that is the question this feature actually lives or dies on. So this drives
a real Firefox, loads the shipped `cadence.js` and `cadence-audio.js`, builds
one score, and renders it once per arrangement through `OfflineAudioContext` and
the shipped `CadenceInstrument.voice()`.

What comes back is PCM: files to listen to, and numbers to argue with -- onset
count, brightness, loudness. Every arrangement renders the same score at the
same offsets, which is the invariant the whole feature rests on, so a divergence
in *timing* here is a bug and a divergence in *sound* is the point.

`scheduleAt()` is deliberately not exercised here: an offline render has no
wake-up jitter to absorb, and the anchor is unit-tested against a virtual device
in `tests/test_cadence_score.py`. This measures the instrument, not the clock.

Usage::

    python3 scripts/render_cadence_audio.py --out /tmp/cadence
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import struct
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.marionette import Marionette, launch  # noqa: E402
from run_settings_smoke import (  # noqa: E402
    EXTENSION_DIR,
    OPTIONS_URL,
    free_port,
    profile_prefs,
)

SAMPLE_RATE = 44100
GENRES = ["classical", "jazz", "lofi", "electronic", "custom"]

# The Settings demo expression, as its editor plan. Numbers, a variable, an
# operator, an exponent, a radical, grouping and a fraction: every mathematical
# role the arranger claims to voice differently appears exactly once.
STEPS = [
    {"op": "template", "name": "Fraction"},
    {"op": "type", "text": "2ix"},
    {"op": "template", "name": "Exponent"},
    {"op": "type", "text": "4"},
    {"op": "base"},
    {"op": "template", "name": "Radical"},
    {"op": "type", "text": "2x"},
    {"op": "base"},
    {"op": "type", "text": "+3"},
    {"op": "slot", "name": "denominator"},
    {"op": "type", "text": "5y"},
]

RENDER = """
const done = arguments[arguments.length - 1];
(async () => {
  const { arrangeNote, arrangeStructure, CadenceInstrument } =
    await import("/common/cadence-audio.js");
  const steps = STEPS;
  const phrase = ethnosCadence.planSemanticPhrase(steps, CADENCE);
  const out = {};
  for (const genre of GENRES) {
    const seconds = phrase.durationMs / 1000 + 3;
    const context = new OfflineAudioContext(1, Math.ceil(SAMPLE_RATE * seconds), SAMPLE_RATE);
    const instrument = new CadenceInstrument(() => context);
    instrument.context = context;
    instrument.master = context.createGain();
    instrument.master.gain.value = 0.8;
    instrument.master.connect(context.destination);
    for (const step of phrase.timeline) {
      if (step.kind === "structure-enter") {
        const voiced = arrangeStructure(step.label, { genre });
        for (const layer of voiced.layers) {
          instrument.voice(layer, step.offsetMs / 1000 + (layer.delayMs ?? 0) / 1000);
        }
      }
    }
    for (const [index, note] of phrase.notes.entries()) {
      const voiced = arrangeNote(note, index, { genre, voice: "keys" });
      for (const layer of voiced.layers) {
        const lag = (layer.feel ? voiced.feelMs : 0) + (layer.delayMs ?? 0);
        instrument.voice(layer, note.offsetMs / 1000 + lag / 1000);
      }
      // The 24-voice ceiling is a live-playback guard against a late burst.
      // An offline render has no burst; clearing the bookkeeping leaves every
      // already-scheduled node exactly where the arrangement put it.
      instrument.voices.clear();
    }
    const rendered = await context.startRendering();
    const samples = rendered.getChannelData(0);
    let binary = "";
    const bytes = new Uint8Array(new Int16Array(
      Array.from(samples, (value) => Math.max(-1, Math.min(1, value)) * 32767)
    ).buffer);
    for (let at = 0; at < bytes.length; at += 8192) {
      binary += String.fromCharCode(...bytes.subarray(at, at + 8192));
    }
    out[genre] = btoa(binary);
  }
  return { offsets: phrase.offsets, durationMs: phrase.durationMs,
    notes: phrase.notes.length, pcm: out };
})().then(done, (error) => done({ error: String(error) }));
"""


def render(out_dir: Path, seconds: int) -> dict:
    """Drive one throwaway Firefox and bring back raw PCM per arrangement."""
    with tempfile.TemporaryDirectory(prefix="rc5-render-") as work:
        port = free_port()
        process = launch(
            str(Path(work) / "profile"),
            port,
            headless=True,
            extra_prefs=profile_prefs(False),
        )
        marionette = Marionette(port=port)
        try:
            marionette.connect()
            marionette.new_session()
            marionette.install_addon(str(EXTENSION_DIR))
            # Run inside the add-on's own Settings page, where `cadence.js` is
            # already loaded exactly as it ships and the module is same-origin.
            marionette.set_context("content")
            marionette.navigate(OPTIONS_URL)
            script = (
                RENDER.replace("STEPS", json.dumps(STEPS))
                .replace("GENRES", json.dumps(GENRES))
                .replace("SAMPLE_RATE", str(SAMPLE_RATE))
                .replace(
                    "CADENCE",
                    json.dumps(
                        {
                            "durationMinMs": seconds * 1000,
                            "durationMaxMs": seconds * 1000,
                        }
                    ),
                )
            )
            result = marionette.send(
                "WebDriver:ExecuteAsyncScript", {"script": script, "args": []}
            )["value"]
        finally:
            if marionette.socket:
                marionette.quit()
            process.terminate()
            process.wait(timeout=15)
    if not result or result.get("error"):
        raise SystemExit(f"render failed: {result}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for genre, payload in result["pcm"].items():
        write_wave(out_dir / f"cadence-{genre}.wav", base64.b64decode(payload))
    result.pop("pcm")
    return result


def write_wave(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm)


def measure(path: Path) -> dict:
    """Enough of a listen to tell two arrangements apart, in numbers."""
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        samples = struct.unpack(f"<{frames}h", handle.readframes(frames))
    window = SAMPLE_RATE // 100  # 10 ms
    energy = []
    for start in range(0, len(samples) - window, window):
        block = samples[start : start + window]
        energy.append(math.sqrt(sum(value * value for value in block) / window))
    peak = max(energy) or 1
    # An onset is a block that is much louder than the one before it.
    onsets = sum(
        1
        for index in range(1, len(energy))
        if energy[index] > peak * 0.06 and energy[index] > energy[index - 1] * 2.2
    )
    # A cheap spectral centroid: zero-crossing rate stands in for brightness,
    # and the difference signal's energy for high-frequency content.
    crossings = sum(
        1
        for index in range(1, len(samples))
        if (samples[index - 1] < 0) != (samples[index] < 0)
    )
    difference = sum(
        (samples[index] - samples[index - 1]) ** 2 for index in range(1, len(samples))
    )
    total = sum(value * value for value in samples) or 1
    return {
        "seconds": round(len(samples) / SAMPLE_RATE, 2),
        "peak_rms": round(peak / 32767, 4),
        "onsets": onsets,
        "brightness_hz": round(crossings * SAMPLE_RATE / (2 * len(samples))),
        "high_ratio": round(difference / total, 3),
        "loud_blocks": sum(1 for value in energy if value > peak * 0.1),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=8)
    args = parser.parse_args()
    score = render(args.out, args.seconds)
    print(json.dumps(score, indent=2))
    rows = {}
    for genre in GENRES:
        rows[genre] = measure(args.out / f"cadence-{genre}.wav")
    print(json.dumps(rows, indent=2))
    distinct = {json.dumps(row, sort_keys=True) for row in rows.values()}
    print(f"\n{len(distinct)}/{len(rows)} arrangements measure differently")
    print(f"wav files in {args.out}")


if __name__ == "__main__":
    main()
