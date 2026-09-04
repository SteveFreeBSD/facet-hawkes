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
  separators, and closing delimiters. They express the expression's structure;
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
that window. The runtime clamps incoming values to its permitted ranges.

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
Tempo is 45–180 BPM. The hard performance window has independent endpoints,
with each endpoint constrained to 2–12 seconds; the resolved values are ordered
before entry. The default is 82 BPM and 5–10 seconds. These are timing
controls, not answer controls.

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
written. Contenteditable fields use the editor's supported text insertion path
one character at a time and stop if the selection leaves the answer target.

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
question signature, and reviewed answer. The structured path re-reads its
live boxes before each character; the contenteditable path rechecks its live
selection. A changed or unreadable target stops the operation rather than
retargeting it.

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
- Structured plans include template steps and still schedule every typed
  character; template settling does not create a second performance.
- Target and question ownership are revalidated during paced insertion, and a
  changed field, caret, tab, frame, or question stops the operation.
- Page-observable synthetic events and MAIN-world editor calls remain
  documented and are not treated as evidence of invisibility.

Use the focused cadence tests in `tests/test_hawkes_diagnostics.py` and
`tests/test_hawkes_extension.py`, plus the extension build and live/editor
checks described in [the extension testing guide](../extension/TESTING.md).

## Agent terminology

Agents should call this feature **Answer Cadence** or **Semantic Cadence** and
should describe it as a **presentation layer**, **schedule**, **phrase**,
**beat**, **accent**, **structural rest**, or **musical timing profile**.

Do not call it human-like typing, trusted input, stealth typing, anti-detection,
fingerprint avoidance, evasion, concealment, or invisible input. Say
**synthetic input** and **observable MAIN-world editor interaction** when those
facts matter. Say **zero persistent extension-created page footprint** when
that precise property is intended.
