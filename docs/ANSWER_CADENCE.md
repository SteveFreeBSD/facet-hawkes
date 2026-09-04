# Answer Cadence

## Definition

**Answer Cadence**, also called **Semantic Cadence**, is Ethnos's
presentation layer for scheduling already-validated answer-entry actions
according to mathematical structure and a selectable musical timing profile.
It is not a solver, target selector, editor planner, or safety policy.

Correctness, target selection, editor compatibility, and the decision that an
operation is safe happen before cadence starts. Cadence receives the approved
answer and the approved entry route, then controls when the route performs its
already-approved actions.

## Why it exists

Cadence makes an answer's presentation legible as a short musical phrase. A
plain expression no longer arrives as an unexplained burst: its characters can
have a pulse, an accent, and a structural pause around operators and
separators. The result is a deliberate product and voice-over presentation
feature. Musical variation is an aesthetic choice; it is not an attempt to
imitate a person's typing.

## The model

The implementation treats an entry as a small score:

- **Notes** are the characters that the approved entry route will type.
- **Accents** come from the selected rhythm weights and swing adjustment.
  Even and odd positions receive different emphasis when swing is nonzero.
- **Structural rests** are longer weights around whitespace, operators,
  separators, and closing delimiters — the longest after whitespace, the
  shortest after a closing delimiter. They express the expression's structure;
  they are not pauses chosen to resemble a human.
- **Phrases** are the complete answer performance. The implementation builds
  one schedule for all typed characters, including all `type` steps in a
  structured plan.
- **Resolution** is the final scheduled note and the completion of the entry
  operation. Rounding is corrected so the final note lands at the selected
  duration rather than drifting beyond it.

A cadence snapshot contains a tempo, a minimum and maximum duration, a beat
shape, swing, timing variation, and a structural-rest ratio. Duration is
blended from tempo and a random point in the selected window, then bounded by
that window. The runtime clamps incoming values to its permitted ranges. The
score reports the blended length it asked for alongside the length it was
given, and which end of the window — if either — overrode it.

Accent and structural rest are separate properties, and each is decided by one
rule kept next to the schedule so that no display restates it. A position is
accented when its beat-shape weight or the swing adjustment leans on it. A note
is *marked* as carrying a structural rest when it is whitespace or an operator
and is not the final note — the two longest rests, and the two that are worth
naming aloud. A closing delimiter still receives its shorter extra weight; it
simply is not called out as a rest of its own.

## Settings and musical profiles

The selectable genres are starting arrangements, not claims about a user's
behavior:

- **Classical** uses a waltz beat with restrained variation and no swing.
- **Jazz** uses a syncopated beat, more swing, more variation, and more
  structural rest.
- **Lo-fi** uses a backbeat with soft swing and moderate variation. It is the
  default profile.
- **Electronic** uses a steady four-beat pulse with no swing and low
  variation.
- **Custom** exposes the beat shape, swing, variation, and structural-rest
  controls directly.

Beat shapes in code are `steady`, `waltz`, `backbeat`, and `syncopated`.
Tempo is 30–300 BPM. The hard performance window has independent endpoints,
with each endpoint constrained to 2–12 seconds; the resolved values are ordered
before entry. The default is 82 BPM and 5–10 seconds. These are timing
controls, not answer controls.

Cadence controls in Settings are a draft. Moving a slider or selecting a genre
updates the readouts and preview but does not change live insertion settings.
**Apply cadence** validates the complete draft and writes it in one
`storage.local` transaction; the card distinguishes unapplied changes from the
currently applied configuration, in the heading as well as beside the button,
because the button sits below a tall preview. A confirmation of a previous
Apply is retired the moment the draft moves again: the card must never report
that cadence is applied and that changes are unapplied at the same time.
Selecting **Custom** opens its arrangement panel, since a disclosure revealed
already collapsed reads as a choice that did nothing. Existing stored values
need no migration: the schema still coerces missing or invalid values to their
declared defaults, and values within the former tempo range remain valid.

Tempo and the window are independent, and at the extremes the window wins: a
300 BPM phrase of ordinary length is raised to the window's floor and a 30 BPM
one is held to its ceiling. Settings reports which of those happened rather
than reporting compliance with a bound the clamp guarantees.

## Settings phrase preview

Settings contains a local phrase preview for the supported expression
`(2ix^4√(2x)+3)/(5y^2)`. It sends that expression through the real
`planEntry()` structured planner, then layers semantic telemetry over the
resulting `type`, `template`, `slot`, and `base` steps. The display can therefore
show ordinary characters, the `+` operator, exponent, radical, and fraction
structure, rhythmic accents, a structural rest, and the final resolution.

The preview and plain insertion share `common/cadence.js`: cadence
normalization, randomized rhythmic weights, hard-window duration resolution,
note offsets, and the cancellable timer transport are the same implementation.
Structured insertion carries a synchronized copy of the bounded score builder
because Firefox serializes that function into the page's MAIN world and it may
not close over extension code. That copy is not left to good intentions:
`scripts/build_extension.py` compares the two files' tuning — fallbacks,
permitted ranges, weight multipliers, the tempo/window blend — and fails the
build when they disagree. Template and slot telemetry shares the next typed
note's clock; it does not add a second duration to the phrase.

Above the transport, the same phrase is drawn as a **rhythm strip**: one mark
per scheduled note, placed at the moment that note is due. Spacing is therefore
the tempo, the swing, and the timing variation; height is the accent; and the
band between an operator and the note after it is the structural rest. The
final mark is the resolution. The strip is drawn from the phrase that will
play, so it is legible while the controls move and does not require sitting
through a performance to read the arrangement. Its idle drawing uses a fixed
midpoint sample, so what changes on screen as a control moves is the change
that control made rather than a fresh roll of the timing variation; Play uses
secure randomness, exactly like insertion.

The compact transport reports elapsed and target time, the configured hard
window, current note and semantic step, current action, effective tempo,
planned note/action counts, and what the hard window did. Before a phrase
plays, that last field names the bound that decided its length — tempo-led, or
raised to the minimum, or held to the maximum — because a planned phrase is
clamped into the window by construction and reporting compliance would say
nothing. At resolution it is recomputed from actual elapsed time, so
event-loop delay is visible rather than hidden by the planned duration, and a
performance that missed its window says so.

The playhead sweeps continuously on the browser's frame clock rather than
advancing only when a note falls due, so a held structural rest reads as a
held note instead of a stalled transport. Preview uses a cadence snapshot
taken when Play is pressed. Applying settings during playback therefore cannot
retime an in-flight preview; a draft changed mid-performance restages the idle
display when that performance ends. Pressing Preview again cancels the prior
run before starting another, Stop cancels it, and closing Settings clears its
timers. Reduced-motion preference removes note motion, the accent's lift, and
the progressive character reveal while retaining timing and textual telemetry.
A demo expression the planner could no longer accept retires the preview alone
and leaves the rest of Settings working. No preview code obtains a tab, frame,
field, or Hawkes page handle.

## Validated entry relationship

The event page first chooses the approved answer representation and target.
For structured answers, `planEntry()` then checks the answer against the
question's published character set and permitted templates and returns an
ordered editor plan of `type`, `template`, `slot`, and `base` steps. Only a
successful plan is passed to `enterPlan()` in the page's MAIN world.

Cadence does not alter the answer, target, editor plan, template names, slot
selection, or safety decision. It schedules the typed characters in that plan.
Template calls still use Hawkes's own editor API and settle on the same
performance clock; a slow template settle consumes time from later notes
rather than extending the selected performance by another cadence.

## Plain and structured entry

Plain native inputs and contenteditable answer fields use the same
character-at-a-time cadence. Native fields receive the field's normal
`beforeinput` check, then synthetic `input` events as each character is
written, and stop if the field stops accepting input or leaves the document.
Contenteditable fields use the editor's supported text insertion path one
character at a time and stop if the selection leaves the answer target or that
target leaves the document.

Structured answers are built with Hawkes keypad templates. Their plan is
validated first, then `enterPlan()` schedules every character in every `type`
step on the same cadence. Template actions such as Fraction, Exponent, or
Radical are not characters and do not receive separate notes, but their settle
work occurs on that shared clock. Structured entry therefore **does
participate in cadence**; its editor mechanics differ from plain insertion,
not its presentation schedule.

A one-character answer is struck immediately rather than held until the end
of the duration window. Empty scores have no notes. Cadence never submits,
checks, advances, chooses an option, or navigates Hawkes.

## Safety and observability

Cadence begins only after correctness, target selection, editor planning, and
insertion safety checks have passed. During a paced operation, Ethnos
continues to revalidate ownership of the pinned window, tab, frame, field,
question signature, and reviewed answer.

A performance spans seconds rather than one tick, so every entry path also
rechecks its own target on each beat rather than trusting the handle it
started with: the structured path re-reads its box by id, the contenteditable
path rechecks the live selection, and the native and contenteditable paths
both confirm the target is still in the document. That last check matters
because a detached input still accepts writes and still reports itself as
editable — a question swapped in place mid-performance would otherwise have
been reported as a successful insertion that wrote nothing. A changed or
unreadable target stops the operation rather than retargeting it.

Synthetic input and Hawkes editor calls remain observable to page code. Native
and contenteditable synthetic events are not trusted events, and structured
entry briefly invokes Hawkes's page-owned editor methods in the MAIN world.
Ethnos makes no claim or goal of human-like trusted input, undetectability,
anti-detection, fingerprint avoidance, monitoring avoidance, evasion, or
concealment. The musical timing is presentation, not a disguise.

"Zero footprint" has a narrow meaning: after the operation, Ethnos leaves no
persistent extension-created page UI or page state. It does **not** mean that
an insertion is invisible while it happens. The answer and Hawkes's resulting
editor state necessarily remain, and page code can observe the synthetic
activity and MAIN-world editor interaction.

Solving, inserting, submitting, and navigating are separate actions. Ethnos
solves and may insert only after the user's separate request; it never presses
Hawkes Submit, Check, Next, or Skip. The user remains responsible for any
Hawkes action after insertion.

## Testing expectations

Documentation and tests should verify the contract, not infer it from timing
alone:

- `planEntry()` rejects unsupported notation, characters, and templates before
  `enterPlan()` can run.
- Plain native, contenteditable, and structured keypad paths all receive the
  same resolved cadence snapshot.
- Presets resolve to their declared beat shapes and values; Custom uses its
  independent controls; reversed window endpoints are ordered; final offsets
  remain within the selected window.
- Settings keeps cadence changes as a draft until one atomic Apply, while the
  preview responds to the draft and never writes it implicitly.
- The local structured preview uses the real editor plan and shared cadence
  score/transport, reports its semantic steps, cancels cleanly, and has no page
  insertion capability.
- The rhythm strip is built from the phrase that will play, and accent and
  structural rest are decided once beside the schedule rather than re-derived
  by a display.
- The hard-window readout names the bound that decided a planned phrase, and
  reports a measured pass or fail only after one has been performed.
- The Settings card never reports an applied cadence and unapplied changes at
  the same time, and a failed demo plan costs the preview rather than the page.
- Paced entry stops when its target leaves the document, in the native and
  contenteditable paths as well as the structured one.
- The MAIN-world copy of the score cannot drift from the shared one; the build
  compares their tuning and fails when they disagree.
- Structured plans include template steps and still schedule every typed
  character; template settling does not create a second performance.
- Target and question ownership are revalidated during paced insertion, and a
  changed field, caret, tab, frame, or question stops the operation.
- Page-observable synthetic events and MAIN-world editor calls remain
  documented and are not treated as evidence of invisibility.

Use the focused cadence tests in `tests/test_hawkes_diagnostics.py` and
`tests/test_hawkes_extension.py`, and `scripts/run_settings_smoke.py`, which
presses the real controls in a throwaway Firefox and judges the draft, the
Apply transaction, preset switching, the tempo extremes, the performance, the
restart, Stop, and the reduced-motion pass. Add the extension build and
live/editor checks described in
[the extension testing guide](../extension/TESTING.md).

## Agent terminology

Agents should call this feature **Answer Cadence** or **Semantic Cadence** and
should describe it as a **presentation layer**, **schedule**, **phrase**,
**beat**, **accent**, **structural rest**, or **musical timing profile**.

Do not call it human-like typing, trusted input, stealth typing, anti-detection,
fingerprint avoidance, evasion, concealment, or invisible input. Say
**synthetic input** and **observable MAIN-world editor interaction** when those
facts matter. Say **zero persistent extension-created page footprint** when
that precise property is intended.
