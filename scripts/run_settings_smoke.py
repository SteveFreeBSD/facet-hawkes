#!/usr/bin/env python3
"""Drive the add-on's Settings page in a real Firefox and judge what it does.

`scripts/run_extension_harness.py` opens the toolbar panel against page
fixtures, and `tests/` runs the settings schema under QuickJS. Neither touches
`options/options.html`, so the whole Answer Cadence card -- the draft, the Apply
transaction, the phrase preview and its transport -- was reachable only by
reading the source and hoping.

That is the wrong gap to leave open for this card in particular. Its behaviour
is almost entirely state that only exists once a browser has run it: whether
"unapplied changes" and "applied" can appear at the same time, whether Apply
really reaches `storage.local`, whether pressing Preview twice leaves one
performance running or two, whether the playhead moves while a structural rest
is being held. This harness answers those by pressing the controls.

It never touches the user's profile or their running Firefox: the browser is a
separate headless instance on a throwaway profile, and the Settings page reaches
no website by design -- there is no fixture server here because there is nothing
for it to serve.

The add-on's own diagnostic log is read at the end as a check in its own right.
Every handler on the page reports its failures through it, so an error-level
entry means something went wrong even if the visible state happened to settle.

The packaged browser may not support this at all. `firefox-pure` 155 ships with
Marionette stripped out, so `--marionette` is an unrecognized flag and no port
opens. Point `ETHNOS_FIREFOX` at a build that has it; Mozilla's release tarball
does and needs no root::

    export ETHNOS_FIREFOX="$HOME/.local/opt/firefox-mozilla/firefox"

Usage::

    python3 scripts/run_settings_smoke.py
    python3 scripts/run_settings_smoke.py --show      # watch it work
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.marionette import Marionette, launch  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXTENSION_DIR = PROJECT_ROOT / "extension"

ADDON_ID = "ethnos-hawkes@local"

# Firefox mints a per-profile UUID for every add-on and serves its pages from
# `moz-extension://<uuid>/`. Pinning it in the profile is what makes the
# Settings URL something this script can navigate to directly, rather than
# something it has to go and discover through about:addons first.
ADDON_UUID = "3f2b1c4d-0000-4000-8000-abcdefabcdef"
OPTIONS_URL = f"moz-extension://{ADDON_UUID}/options/options.html"

# How long a full default phrase can take, plus room for a slow machine. The
# window's own ceiling is 12 seconds and the preview honours it.
PHRASE_TIMEOUT = 20.0

# One snapshot of everything the card is currently saying. Read as a unit so a
# check never compares two fields sampled a frame apart.
SNAPSHOT = """
const q = (selector) => document.querySelector(selector);
const count = (selector) => document.querySelectorAll(selector).length;
return {
  genre: q("#entryGenre").value,
  tempo: Number(q("#entryTempoBpm").value),
  windowMin: Number(q("#entryDurationMinSeconds").value),
  windowMax: Number(q("#entryDurationMaxSeconds").value),
  pattern: q("#entryPattern").value,
  summary: q("#cadence-summary").textContent,
  note: q("#cadence-note").textContent,
  draft: q("#cadence-draft-status").textContent,
  applyStatus: q("#cadence-apply-status").textContent,
  applyDisabled: q("#cadence-apply").disabled,
  draftDot: q("#cadence-card").classList.contains("is-draft"),
  elapsed: q("#cadence-elapsed").textContent,
  target: q("#cadence-target").textContent,
  step: q("#cadence-step").textContent,
  action: q("#cadence-action").textContent,
  effectiveTempo: q("#cadence-effective-tempo").textContent,
  planned: q("#cadence-planned-steps").textContent,
  windowState: q("#cadence-window-state").textContent,
  windowOk: q("#cadence-window-state").classList.contains("cadence-window-ok"),
  windowWarn: q("#cadence-window-state").classList.contains("cadence-window-warn"),
  head: parseFloat(q("#cadence-score-head").style.left) || 0,
  fill: parseFloat(q("#cadence-score-fill").style.width) || 0,
  beats: count("#cadence-score-beats .cadence-beat"),
  accents: count("#cadence-score-beats .cadence-beat.is-accent"),
  rests: count("#cadence-score-beats .cadence-rest"),
  struck: count("#cadence-score-beats .cadence-beat.is-struck"),
  entered: count("#cadence-equation [data-note].is-entered"),
  current: count("#cadence-equation [data-note].is-current"),
  structures: count("#cadence-equation .is-current-structure"),
  stopHidden: q("#cadence-stop").hidden,
  playDisabled: q("#cadence-play").disabled,
  customHidden: q("#cadence-custom").hidden,
  customOpen: q("#cadence-custom").open,
  reducedMotion: q("#cadence-equation").dataset.reducedMotion,
  previewStatus: q("#cadence-preview-status").textContent,
};
"""

CADENCE_KEYS = (
    "entryGenre",
    "entryMusicEnabled",
    "entryMusicMuted",
    "entryMusicVolume",
    "entryVoice",
    "entryTempoBpm",
    "entryDurationMinSeconds",
    "entryDurationMaxSeconds",
    "entryPattern",
    "entrySwingPercent",
    "entryVariationPercent",
    "entrySymbolRestPercent",
)


def say(line: str) -> None:
    print(line, flush=True)


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def profile_prefs(reduced_motion: bool) -> tuple[str, ...]:
    """What this harness needs on top of the standard throwaway profile."""
    prefs = [
        'user_pref("extensions.webextensions.uuids", '
        f"{json.dumps(json.dumps({ADDON_ID: ADDON_UUID}))});",
    ]
    if reduced_motion:
        # Gecko's own switch behind `prefers-reduced-motion: reduce`. Setting the
        # media feature is the only honest way to test that branch; asserting
        # that the JS calls `matchMedia` proves nothing about what it then does.
        prefs.append('user_pref("ui.prefersReducedMotion", 1);')
    return tuple(prefs)


class Settings:
    """The Settings page, and the small vocabulary this script drives it with."""

    def __init__(self, marionette: Marionette) -> None:
        self.marionette = marionette
        self.failures = 0

    # --- driving ----------------------------------------------------------

    def evaluate(self, body: str, args: list | None = None):
        # `.apply` rather than a bare call: the body is wrapped in a function of
        # its own, and `arguments` inside that wrapper would otherwise be the
        # wrapper's own empty list rather than what Marionette was handed.
        script = f"return (function () {{{body}}}).apply(null, arguments);"
        result = self.marionette.execute(script, args)
        return result.get("value") if isinstance(result, dict) else result

    def snapshot(self) -> dict:
        return self.evaluate(SNAPSHOT)

    def stored(self) -> dict:
        """What `storage.local` actually holds, read as the add-on would."""
        return json.loads(
            self.marionette.send(
                "WebDriver:ExecuteAsyncScript",
                {
                    "script": "const done = arguments[arguments.length - 1];"
                    f"browser.storage.local.get({json.dumps(list(CADENCE_KEYS))})"
                    ".then((values) => done(JSON.stringify(values)),"
                    " (error) => done(JSON.stringify({error: String(error)})));",
                    "args": [],
                },
            )["value"]
        )

    def diagnostics(self) -> list[dict]:
        return json.loads(
            self.marionette.send(
                "WebDriver:ExecuteAsyncScript",
                {
                    "script": "const done = arguments[arguments.length - 1];"
                    'browser.storage.local.get("diagnostics")'
                    ".then((held) => done(JSON.stringify(held.diagnostics || [])),"
                    " () => done('[]'));",
                    "args": [],
                },
            )["value"]
        )

    def set_control(self, control: str, value, commit: bool = True) -> None:
        """Move a control the way a person does: `input`, then `change`."""
        self.evaluate(
            "const [selector, value, commit] = arguments;"
            "const control = document.querySelector(selector);"
            "control.value = String(value);"
            'control.dispatchEvent(new Event("input", {bubbles: true}));'
            'if (commit) { control.dispatchEvent(new Event("change", {bubbles: true})); }'
            "return true;",
            [f"#{control}", value, commit],
        )
        time.sleep(0.25)

    def click(self, css: str) -> None:
        self.marionette.click(css)
        time.sleep(0.3)

    def open_page(self) -> None:
        self.marionette.navigate(OPTIONS_URL)
        # The page reads storage, localizes itself, and stages the idle phrase
        # before any of this is worth looking at.
        time.sleep(2.0)

    def play_until(self, predicate, timeout: float = PHRASE_TIMEOUT) -> dict:
        """Poll the transport until it says what we are waiting for."""
        deadline = time.monotonic() + timeout
        state = self.snapshot()
        while time.monotonic() < deadline:
            if predicate(state):
                return state
            time.sleep(0.2)
            state = self.snapshot()
        return state

    # --- judging ----------------------------------------------------------

    def check(self, name: str, problems: list[str]) -> None:
        if problems:
            self.failures += 1
            say(f"FAIL {name}")
            for problem in problems:
                say(f"       {problem}")
            return
        say(f"ok   {name}")


def expect(condition: bool, complaint: str) -> list[str]:
    return [] if condition else [complaint]


# --- the checks -----------------------------------------------------------


def check_loads_applied(page: Settings) -> None:
    state = page.snapshot()
    page.check(
        "opens reporting the applied configuration",
        expect(
            state["genre"] == "lofi", f"genre is {state['genre']!r}, not the default"
        )
        + expect(
            state["draft"] == "Cadence is applied", f"draft says {state['draft']!r}"
        )
        + expect(state["applyDisabled"], "Apply is offered with nothing to apply")
        + expect(not state["draftDot"], "the heading shows unapplied changes on load")
        + expect(state["action"] == "Ready", f"the transport says {state['action']!r}")
        + expect(state["customHidden"], "the Custom panel is shown for a preset"),
    )


def check_idle_strip(page: Settings) -> None:
    state = page.snapshot()
    page.check(
        "stages the phrase without playing it",
        # Eleven notes is the demo expression `(2ix^4√(2x)+3)/(5y^2)`, and the
        # single rest is its one operator: the `+`.
        expect(state["beats"] == 11, f"{state['beats']} beats drawn, expected 11")
        + expect(state["rests"] == 1, f"{state['rests']} structural rests, expected 1")
        + expect(
            0 < state["accents"] < 11, f"{state['accents']} accents is all or none"
        )
        + expect(state["struck"] == 0, "beats are marked struck before anything played")
        + expect(state["entered"] == 11, "the idle equation is not fully legible")
        + expect(state["head"] == 0, f"the playhead rests at {state['head']}%")
        + expect(state["elapsed"] == "0.0s", f"elapsed reads {state['elapsed']!r}")
        + expect("/ 5–10s" in state["target"], f"target reads {state['target']!r}"),
    )


def check_draft_does_not_write(page: Settings) -> None:
    before = page.stored()
    page.set_control("entryTempoBpm", 140)
    state = page.snapshot()
    after = page.stored()
    page.check(
        "keeps a moved control as a draft",
        expect(
            state["draft"] == "Unapplied cadence changes",
            f"draft says {state['draft']!r}",
        )
        + expect(
            not state["applyDisabled"], "Apply stayed disabled with changes pending"
        )
        + expect(state["draftDot"], "the heading does not mark unapplied changes")
        + expect(
            before == after, f"storage changed without Apply: {before} -> {after}"
        ),
    )


def check_apply_is_atomic(page: Settings) -> None:
    page.set_control("entryGenre", "jazz")
    drafted = page.snapshot()
    page.click("#cadence-apply")
    state = page.snapshot()
    stored = page.stored()
    page.check(
        "applies the whole draft in one transaction",
        expect(state["draft"] == "Cadence is applied", f"draft says {state['draft']!r}")
        + expect(state["applyStatus"] != "", "Apply reported nothing")
        + expect(state["applyDisabled"], "Apply stayed live after applying")
        + expect(not state["draftDot"], "the heading still marks unapplied changes")
        + expect(
            stored.get("entryGenre") == "jazz",
            f"storage kept genre {stored.get('entryGenre')!r}",
        )
        + expect(
            stored.get("entryTempoBpm") == drafted["tempo"],
            f"the genre reached storage but tempo {drafted['tempo']} did not",
        ),
    )


def check_apply_confirmation_cannot_contradict(page: Settings) -> None:
    """ "Answer Cadence applied." must not stand beside "Unapplied changes"."""
    page.set_control("entryTempoBpm", 96, commit=False)
    state = page.snapshot()
    page.check(
        "retires the confirmation the moment the draft moves again",
        expect(
            state["draft"] == "Unapplied cadence changes",
            f"dragging a slider left the draft reading {state['draft']!r}",
        )
        + expect(
            state["applyStatus"] == "",
            f"the card claims {state['applyStatus']!r} and unapplied changes at once",
        ),
    )


# Each preset's suggested tempo and the label the summary chip should carry.
PRESETS = {
    "classical": (72, "Classical"),
    "jazz": (112, "Jazz"),
    "lofi": (82, "Lo-fi"),
    "electronic": (128, "Electronic"),
}


def check_presets_preserve_the_score(page: Settings) -> None:
    problems = []
    descriptions = set()
    before = page.snapshot()
    offsets = page.evaluate(
        'return [...document.querySelectorAll(".cadence-beat")].map(n=>n.style.left);'
    )
    for genre, (_, label) in PRESETS.items():
        page.set_control("entryGenre", genre)
        state = page.snapshot()
        problems += expect(state["tempo"] == before["tempo"], f"{genre} moved tempo")
        problems += expect(
            state["summary"] == f"{label} · {before['tempo']} BPM",
            f"{genre} summary is wrong",
        )
        after = page.evaluate(
            'return [...document.querySelectorAll(".cadence-beat")].map(n=>n.style.left);'
        )
        problems += expect(after == offsets, f"{genre} moved score timestamps")
        descriptions.add(state["note"])
    problems += expect(
        len(descriptions) == len(PRESETS), "arrangements share a description"
    )
    page.check("changes arrangement without changing the score", problems)


def check_custom_opens_its_panel(page: Settings) -> None:
    page.set_control("entryGenre", "custom")
    state = page.snapshot()
    page.set_control("entryPattern", "waltz")
    page.set_control("entrySwingPercent", 45)
    swung = page.snapshot()
    page.check(
        "reveals the Custom arrangement when Custom is chosen",
        expect(not state["customHidden"], "the Custom panel stayed hidden")
        + expect(state["customOpen"], "the Custom panel was revealed already collapsed")
        + expect(
            swung["pattern"] == "waltz",
            f"the beat shape control kept {swung['pattern']!r}",
        )
        + expect(
            swung["effectiveTempo"] != "" and swung["beats"] == 11,
            "the strip stopped responding once Custom took over",
        )
        + expect(
            swung["accents"] != state["accents"],
            "changing the beat shape and swing moved no accent on the strip",
        ),
    )


def check_tempo_extremes_explain_themselves(page: Settings) -> None:
    page.set_control("entryGenre", "lofi")
    page.set_control("entryDurationMinSeconds", 5)
    page.set_control("entryDurationMaxSeconds", 10)

    page.set_control("entryTempoBpm", 300)
    fast = page.snapshot()
    page.set_control("entryTempoBpm", 30)
    slow = page.snapshot()
    page.set_control("entryTempoBpm", 82)
    natural = page.snapshot()

    page.check(
        "says which end of the hard window overrode the tempo",
        expect(
            (natural["windowMin"], natural["windowMax"]) == (5, 10),
            f"the window reads {natural['windowMin']}-{natural['windowMax']}s",
        )
        + expect(
            "minimum" in fast["windowState"],
            f"300 BPM reports {fast['windowState']!r} rather than the window floor",
        )
        + expect(
            fast["target"].startswith("5.0s"),
            f"300 BPM produced target {fast['target']!r}",
        )
        + expect(
            "maximum" in slow["windowState"],
            f"30 BPM reports {slow['windowState']!r} rather than the window ceiling",
        )
        + expect(
            slow["target"].startswith("10.0s"),
            f"30 BPM produced target {slow['target']!r}",
        )
        + expect(
            natural["windowState"] == "Tempo-led",
            f"82 BPM reports {natural['windowState']!r} rather than tempo-led",
        )
        + expect(
            fast["effectiveTempo"] != "300 BPM",
            "the effective tempo repeats the requested one instead of the real one",
        ),
    )


def check_preview_performs_and_resolves(page: Settings) -> None:
    page.click("#cadence-play")
    playing = page.play_until(lambda state: state["struck"] >= 2)
    mid = page.play_until(
        lambda state: state["struck"] >= 4 and state["head"] > playing["head"]
    )
    done = page.play_until(lambda state: state["stopHidden"])
    page.check(
        "performs the phrase and resolves inside its window",
        expect(playing["previewStatus"] != "", "playback announced nothing")
        + expect(not playing["stopHidden"], "Stop was not offered while playing")
        + expect(
            mid["head"] > playing["head"],
            f"the playhead did not advance ({playing['head']}% then {mid['head']}%)",
        )
        + expect(
            mid["entered"] > playing["entered"],
            "the equation stopped filling in as the phrase played",
        )
        + expect(done["struck"] == 11, f"{done['struck']} of 11 beats were struck")
        + expect(done["entered"] == 11, "the equation did not finish")
        + expect(
            done["current"] == 0, "a note was left marked current after resolution"
        )
        + expect(done["structures"] == 0, "a structure was left open after resolution")
        + expect(
            done["windowOk"] and not done["windowWarn"],
            f"the measured window verdict was {done['windowState']!r}",
        )
        + expect(
            done["fill"] == 100 and done["head"] == 100,
            f"the transport finished at {done['head']}% rather than the end",
        )
        + expect("Resolution" in done["action"], f"ended on {done['action']!r}"),
    )


def check_playhead_moves_through_a_rest(page: Settings) -> None:
    """A held rest must read as a held note, not as a stalled transport."""
    page.click("#cadence-play")
    first = page.play_until(lambda state: state["struck"] >= 1)
    samples = []
    deadline = time.monotonic() + PHRASE_TIMEOUT
    while time.monotonic() < deadline:
        state = page.snapshot()
        samples.append((state["struck"], state["head"]))
        if state["stopHidden"]:
            break
        time.sleep(0.18)
    held = [
        (before[1], after[1])
        for before, after in zip(samples, samples[1:])
        if before[0] == after[0]
    ]
    page.check(
        "sweeps the playhead while a note is being held",
        expect(bool(first), "the phrase never started")
        + expect(
            bool(held), "no two samples fell inside one note, so nothing was proved"
        )
        + expect(
            any(after > before for before, after in held),
            "the playhead froze for the whole of every held note",
        ),
    )


def check_restart_replaces_the_run(page: Settings) -> None:
    page.click("#cadence-play")
    page.play_until(lambda state: state["struck"] >= 3)
    running = page.snapshot()
    page.click("#cadence-play")
    restarted = page.snapshot()
    page.check(
        "restarts cleanly rather than running two performances",
        expect(
            restarted["struck"] < running["struck"],
            f"the restart kept {restarted['struck']} struck beats from the last run",
        )
        + expect(
            restarted["head"] < running["head"],
            f"the playhead stayed at {restarted['head']}% across a restart",
        )
        + expect(not restarted["stopHidden"], "Stop disappeared on restart"),
    )


def check_stop_halts_the_performance(page: Settings) -> None:
    page.click("#cadence-stop")
    stopped = page.snapshot()
    time.sleep(1.2)
    later = page.snapshot()
    page.check(
        "stops the performance and leaves no timer behind",
        expect(stopped["stopHidden"], "Stop stayed offered after stopping")
        + expect(not stopped["playDisabled"], "Preview cannot be started again")
        + expect("Stopped" in stopped["action"], f"action reads {stopped['action']!r}")
        + expect(
            later["struck"] == stopped["struck"] and later["head"] == stopped["head"],
            "the transport kept moving after Stop",
        )
        + expect(
            later["elapsed"] == stopped["elapsed"],
            f"the clock ran on after Stop: {stopped['elapsed']} -> {later['elapsed']}",
        ),
    )


def check_telemetry_is_populated(page: Settings) -> None:
    state = page.snapshot()
    empty = [
        name
        for name in (
            "elapsed",
            "target",
            "step",
            "action",
            "effectiveTempo",
            "planned",
            "windowState",
        )
        if not state[name] or state[name] == "—"
    ]
    page.check(
        "reports every transport field",
        expect(not empty, f"unreported after a performance: {', '.join(empty)}"),
    )


def check_draft_survives_a_reopen(page: Settings) -> None:
    """Unapplied changes are a draft, so reopening must forget them."""
    page.set_control("entryGenre", "electronic")
    drafted = page.snapshot()
    page.open_page()
    reopened = page.snapshot()
    page.check(
        "forgets an unapplied draft when Settings is reopened",
        expect(
            drafted["genre"] == "electronic",
            "the draft did not take the change in the first place",
        )
        + expect(
            reopened["genre"] == "jazz",
            f"reopening kept the unapplied genre {reopened['genre']!r}",
        )
        + expect(
            reopened["draft"] == "Cadence is applied",
            f"a freshly opened page reports {reopened['draft']!r}",
        ),
    )


def check_reduced_motion(page: Settings) -> None:
    state = page.snapshot()
    page.click("#cadence-play")
    playing = page.play_until(lambda state: state["struck"] >= 3)
    transform = page.evaluate(
        'const note = document.querySelector("#cadence-equation [data-note]");'
        "return getComputedStyle(note).transform;"
    )
    done = page.play_until(lambda current: current["stopHidden"])
    page.check(
        "keeps the equation still and legible under reduced motion",
        expect(
            state["reducedMotion"] == "true",
            f"the page reports reducedMotion={state['reducedMotion']!r}",
        )
        + expect(
            playing["entered"] == 11,
            f"only {playing['entered']} of 11 notes stayed legible while playing",
        )
        + expect(
            transform in {"none", "matrix(1, 0, 0, 1, 0, 0)"},
            f"a note is still being moved: transform is {transform!r}",
        )
        + expect(playing["elapsed"] != "0.0s", "the clock did not run")
        + expect(done["struck"] == 11, "the phrase did not finish"),
    )


def check_nothing_errored(page: Settings) -> None:
    entries = page.diagnostics()
    errors = [entry for entry in entries if entry.get("level") == "error"]
    page.check(
        "left no error in the add-on's own diagnostic log",
        expect(
            not errors,
            "errors recorded: "
            + "; ".join(f"{entry['event']} {entry.get('data')}" for entry in errors),
        ),
    )


MAIN_CHECKS = (
    check_loads_applied,
    check_idle_strip,
    check_draft_does_not_write,
    check_apply_is_atomic,
    check_apply_confirmation_cannot_contradict,
    check_presets_preserve_the_score,
    check_custom_opens_its_panel,
    check_tempo_extremes_explain_themselves,
    check_preview_performs_and_resolves,
    check_playhead_moves_through_a_rest,
    check_restart_replaces_the_run,
    check_stop_halts_the_performance,
    check_telemetry_is_populated,
    check_draft_survives_a_reopen,
    check_nothing_errored,
)

REDUCED_MOTION_CHECKS = (
    check_reduced_motion,
    check_nothing_errored,
)


def drive(checks, headless: bool, reduced_motion: bool) -> int:
    profile = tempfile.mkdtemp(prefix="ethnos-settings-")
    port = free_port()
    process = launch(
        profile,
        port=port,
        headless=headless,
        extra_prefs=profile_prefs(reduced_motion),
    )
    marionette = Marionette(port=port)
    page = Settings(marionette)
    try:
        marionette.connect()
        marionette.new_session()
        # The shipped tree, unmodified. Settings reaches no website, so there is
        # nothing here to repoint at a fixture the way the panel harness must.
        marionette.install_addon(str(EXTENSION_DIR))
        time.sleep(2)
        marionette.set_context("content")
        page.open_page()
        for check in checks:
            check(page)
    finally:
        marionette.quit()
        process.terminate()
        try:
            process.wait(timeout=15)
        except Exception:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)
    return page.failures


def run(headless: bool = True) -> int:
    say("settings page")
    failures = drive(MAIN_CHECKS, headless, reduced_motion=False)
    checks = len(MAIN_CHECKS)

    say("\nsettings page, reduced motion")
    failures += drive(REDUCED_MOTION_CHECKS, headless, reduced_motion=True)
    checks += len(REDUCED_MOTION_CHECKS)

    say(f"\n{checks - failures}/{checks} checks passed")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--show", action="store_true", help="run with a visible browser window"
    )
    args = parser.parse_args(argv)
    return run(headless=not args.show)


if __name__ == "__main__":
    raise SystemExit(main())
