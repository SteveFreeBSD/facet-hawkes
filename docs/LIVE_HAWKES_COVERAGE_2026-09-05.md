# Live Hawkes coverage sweep — 2026-09-05

Observation-only sweep of the owner's normal Firefox while he works lesson 3.3.
He moves between questions, submits, and advances; nothing here presses Submit,
Check, Next, Skip or Try Similar, and nothing navigates Hawkes.

No coursework and no answers are recorded below — only the semantic shape of
each question, the route it took, and how it failed.

Add-on 0.45.0, temporarily installed, picking up disk changes on each event-page
restart.

## Failure classes used

| Class | Meaning |
|---|---|
| `capability` | The mathematics is not one any solver here owns. |
| `answer-shape` | The answer or its editor is a shape the add-on cannot fill. |
| `evidence` | The page states the question exactly and the add-on failed to read it. |
| `region` | The screenshot fallback could not isolate the question safely. |
| `safety` | A stale-target or ownership check refused, correctly. |
| `runtime` | A model, host or transport failure. |

## Cases

### Case 1 — L3.3 Q3/3 Step 1 of 2: quadratic regression from a plotted scatter

- **Semantic shape:** prose instruction, a scatter of three plotted points, one
  answer field prefixed `f(x) =`. Round to three decimals.
- **Evidence available:** SVG scatter with per-point descriptions; no MathML
  above the answer area (correctly — the instruction is prose and the figure is
  an SVG).
- **Answer shape:** one field, `multiFieldEvidence.fields: 1`.
- **Route:** none. `readableQuestion` was false, so the solve fell to the
  screenshot path, which then refused.
- **Result:** failed, twice per attempt, repeatedly under `autoSolve`.
- **Reported reason:** `errorQuestionRegion`, phase `solving`, stage
  `capturing`.
- **Failure classes:** `evidence` **and** `region` — two independent failures on
  one question.
- **Findings:**
  - This is the exact family `tests/fixtures/scatter.html` models, and that
    fixture passes in the isolated harness. So the SVG scatter reader works
    against the repository's *guess* at Hawkes' markup and not against Hawkes.
  - Separately, `measureQuestionBounds` looks for an instruction-bearing
    element that does **not** contain a `p`, `div` or `table`. In this layout —
    and in the committed fixture — the instruction is a bare text node inside
    `#partDescription`, whose only element ancestor also holds the figure, so
    no candidate matches and no crop can be computed. A question whose
    instruction is not wrapped in its own element can therefore never reach the
    image fallback.
  - The two verb lists diverge: `measureQuestionBounds` matches
    `simplify|evaluate|determine|convert|factor|express|rationaliz|find|solve|write|calculate|perform|use the|following|assum`,
    while `hawkes-question.js` matches a different set including `graph`,
    `identify`, `select` and `round`. An instruction recognised by one path can
    be invisible to the other.

### Case 1 (continued) — the same question with `cropCapture` off

The owner turned crop capture off, which skips `measureQuestionBounds` and
sends a full-page screenshot to the companion's image reader instead.

- **Route:** local image fallback (`answeredBy: "model"`, `facetInvoked: false`).
- **Solve:** succeeded, twice, at 45.5 s and 42.1 s.
- **Insertion:** offered once (`insertable: true`), then refused at insert time
  with `errorQuestionUnverified`, phase `inserting`. The next solve came back
  `insertable: false`.
- **Failure class:** `safety` — a correct refusal with a structural cause.
- **Finding — this is the sweep's common cause.** `questionSignature` returns
  `null` whenever `readableQuestion` is false, and the insertion-time re-check
  refuses a null signature outright: "inserting against an unknown question is
  never safe". So a question whose markup cannot be read can be *solved* by the
  image fallback and can *never be inserted* — which is exactly the class of
  question the image fallback exists to serve. The evidence failure and the
  insertion refusal are one fault, not two.
- **Second finding.** The two model runs returned answers of 18 and 11
  characters for the same question, so the image path is not stable here
  either. A 45-second answer that cannot be inserted and does not reproduce is
  worth less than the exact route it fell through from.

## Diagnostic added mid-sweep

"No readable markup" stood for nine different conditions in the SVG reader
alone, so the sweep could not tell a genuine image question from an extraction
fault. The question probe now names every refusal and the event page logs it as
`evidence-refused` — counts, selector names, and the magnitude of a
disagreement, with no question content. This is instrumentation, not a
behaviour change; the isolated harness stays at 22/22.

## The two root causes, named

The `evidence-refused` diagnostic answered both questions on its first firing:

```text
evidence-refused {"expressions":0,"graph":"point-desc-unrecognised","table":"no-data-table","promptChars":11}
evidence-refused {"expressions":0,"graph":"point-desc-unrecognised:A dot drawn # units below the origin.","promptChars":192}
```

### RC1 — a container's own words were never read (`evidence`, `region`)

Hawkes writes a figure question as prose *and* a figure inside one container:
the instruction is a bare text node and the graph is a sibling `div`. Both the
question probe and the crop measurer skipped any element containing a `p`,
`div` or `table`, so the only element the instruction lived in was skipped with
the containers — and nothing else matched.

Live consequences, all three from one cause:

- the prompt came out as **11 characters** — `Step 1 of 2`, and nothing else —
  so no exact operation could match and the question reached a model as a
  picture with no statement of what to do about it;
- `measureQuestionBounds` found no candidate, so no crop could be computed:
  that is the whole of `errorQuestionRegion` on this layout;
- the two paths also used *different* verb lists, so an instruction one
  recognised could be invisible to the other.

**Fixed and confirmed live:** a container now contributes its own direct text,
with nested elements left out, and both paths share one verb list. The live log
went from `promptChars: 11` to `promptChars: 192` on the same question.

### RC2 — the SVG scatter reader was written against a guess (`evidence`)

Two independent faults, both invisible offline because the fixture was authored
to satisfy the code rather than to resemble Hawkes:

1. **A point on an axis has no clause for that axis.** Live wording is
   `A dot drawn 5 units below the origin.` — Hawkes omits a clause whose offset
   is zero, and the origin has neither. The reader required both clauses, so it
   refused every point on an axis. `scatter.html` contained no such point.
2. **The drawn-vs-described cross-check compared two coordinate spaces.**
   *(This diagnosis was wrong on first attempt — see RC5 below. The original
   formula was right; the fixture was right; subtracting the grid's `getBBox`
   origin broke it live.)*

**Fixed:** each clause is read on its own with a missing one as zero, the
sentence as a whole must still be one of Hawkes' own, and the cross-check now
measures from the grid's corner. Every fixture's circles were repositioned to
real offsets.

### Why this matters more than the individual failures

This question is answerable exactly. It is the family Facet's quadratic
regression specialist exists for, and instead it spent 45 seconds on a local
image model, twice, returning different answers, neither insertable. Both root
causes are the same kind of mistake — **a fixture that encodes a guess about
Hawkes' markup confirms the guess** — and the sweep's remaining risk is
wherever else that pattern holds.

## Operational note: fixes do not reach the live add-on on their own

The add-on is installed temporarily from the working tree, and changes reached
the running browser twice during this sweep with a delay of a few minutes —
`evidence-refused` began firing shortly after it was written, and `promptChars`
went 11 → 192 about four minutes after RC1 landed. But the RC2 clause fix,
written at 23:44:04 UTC, was still absent from refusals logged at 23:45:46,
while the isolated harness parses that exact sentence.

The two facts pin it exactly. Both changes live in the same file, yet the
refusal logged at 23:44:34 carried the `:shape` suffix added at ~23:33 and did
*not* carry the clause fix written at 23:44:04. So the browser was holding one
snapshot of that file, taken somewhere between those two edits — a single
reload at about 23:39 UTC, which is also when `promptChars` changed. Nothing has
re-read it since; `event-page-loaded` fires every forty seconds and does not.

**A content-script change needs the temporary add-on reloaded.** The clause fix
and the bbox fix are in the tree, pass 24/24 in the isolated harness, and are
not yet what the live session is running.

Timestamps in the diagnostic log are **UTC** while the machine clock is CDT —
a five-hour trap when correlating a fix with a failure, and one that briefly
made a working fix look broken.

The cheap way to never repeat this: have the probe report a short build marker
alongside its evidence, so the log says which code ran rather than leaving it
to be inferred from which diagnostic strings appear.

## Further observations on Case 1

- `errorAnswerInvalid`, phase `solving`: a local-model answer that did not
  survive `validateAnswer` at all. Third distinct outcome from the same
  question, alongside `insertable: true` and `insertable: false`.
- Answer lengths across five image-fallback runs on one unchanged question: 18,
  11, 19. The image path is not reproducible here.

## Case 2 — L3.3 Q2/3 Step 1 of 2: two fields, answered exactly, not insertable

- **Semantic shape:** two answer fields; `multiFieldEvidence.fields: 2`.
- **Route:** **Facet Exact**, 814 ms, `insertable: true`.
- **Insertion:** refused — `errorEditorUnknown`, phase `inserting`.
- **Failure class:** `answer-shape`.
- **Finding:** the DOM reported two solution fields and the page's own editor
  model did not describe a two-editor `multi`. The gate covers four different
  disagreements — too few fields, too many, an editor of another kind, or a
  different count of editors — and logged the same message for all of them with
  no detail at all. This is the same family as the `answer-not-insertable
  {editor: "answer-parts"}` seen earlier: a question Facet answers exactly and
  the page will not take.
- **Instrumented:** the refusal now names which disagreement it was, and the
  editor's kind, count and readiness.

## Case 3 — L3.3 Q2/3 Step 1 of 2: quadratic regression from a scatter

The same family as Case 1, after the RC1 and RC2 fixes reached the browser.

- **Evidence:** the SVG scatter read exactly — proven by the route it took,
  which cannot be reached without `graph_points`.
- **Route:** `Facet Quadratic Regression · GPU` — the graph specialist, ~20 s,
  coefficients then validated here against the exact least-squares normal
  equations.
- **Solve:** succeeded. **Insertion: succeeded** — `inserted {via:
  "structured", answerLength: 10}` in 6.25 s, and again on a second run.
- **Result:** this is the fix delivering. Before it, the same family read no
  points, took a picture, spent 45 s on a local model, returned a different
  answer each time and could never be inserted. Now it reads the figure,
  routes to the specialist, proves the coefficients locally and types them in.
- **Note for future observers:** a screenshot taken mid-insertion shows a
  *partially* typed answer — nine of ten characters here — because Answer
  Cadence types over about six seconds. That is the cadence, not a truncated
  insertion. The log settles it: `inserted` carries the full length.

## Case 4 — `errorNoFocusedField`, phase `checking`

Ordinary and correct: focus left the answer box between solves. Recorded only
so it is not counted as a defect.

## Cases 5-7 — the routes working, and one refusal that is correct

Recorded as a group because they went past quickly and none needed a
screenshot.

| # | Route | Solve | Insertion | Class |
|---|---|---|---|---|
| 5 | `Facet Reasoning · GPU`, 9.7 s | ok | **inserted**, structured, 5.0 s | — |
| 6 | `Facet Exact`, 853 ms | ok | **inserted**, structured, 5.0 s | — |
| 7 | `Facet Reasoning · GPU`, 11.8 s | ok | refused | `answer-shape`, by design |

Case 7 is `answer-not-insertable {editor: "editor-option-answer", plan:
"editor-option-answer"}`. The question is answered by *choosing* an option, and
committing a choice is deliberately the reader's action, not the add-on's — so
this refusal is the design working. It shares a shape with the earlier
`answer-not-insertable {editor: "answer-parts"}` and with Case 2's
`errorEditorUnknown`: **solved, and the page will not take it.** Those three
have different sub-reasons and want telling apart, which is why Case 2's
refusal is now instrumented.

One inconsistency worth a look later: an exact solve reported
`answeredBy: "exact"` here and `answeredBy: "facet"` in Case 2, from the same
`Facet Exact` source.

## Tally

Seven observations across three questions of lesson 3.3.

**Worked:** Facet Exact (814 ms, 853 ms), Facet Reasoning · GPU, the quadratic
regression graph specialist, and the structured insertion path — four
insertions completed live, none submitted.

**Failure classes seen:** `evidence`, `region`, `safety`, `answer-shape`,
`runtime`. Only `capability` never appeared: no question in this lesson failed
because the mathematics was beyond the solvers.

**Shared causes:** `evidence` + `region` + `safety` were one fault (RC1/RC2,
now fixed and confirmed live). `answer-shape` is a second, separate family —
three distinct refusals whose common feature is that Facet answered correctly
and the page's editor would not accept it.

## Case 8 — "the answer went away": the popup loses it mid-read

Reported live by the owner while reading an answer he had to type himself.

- **Mechanism, confirmed in the source.** `background.js` holds the whole panel
  state in one module-level `let state = blankState()`, on a deliberately
  non-persistent event page, and nothing writes it anywhere. `popup.js` says so
  outright: *"A popup is torn down whenever anything else takes focus, which
  loses the answer on screen mid-read."* The log shows the consequence — every
  `panel-port-closed` is followed within 300 ms by `event-page-loaded`, and the
  answer that was on the card is gone with it.
- **Why it bit hardest here.** The question was `answer-not-insertable
  {editor: "answer-parts"}`, so the answer *had* to be read off the card and
  typed by hand. Typing means clicking into the Hawkes box, which moves focus,
  which tears down the popup, which loses the answer being copied. The one case
  where a person must read the card is the one case the card will not survive.
- **Failure class:** `answer-shape` (the refusal) compounded by a state
  lifetime bug.
- **Workaround available now:** use the docked **sidebar** (Alt+Shift+S), not
  the toolbar popup. The sidebar holds its port open, so the event page stays
  alive and the answer stays on the card. This is already the documented
  difference between the two surfaces.
- **Real fix, and it should be the next slice.** Persist the panel state
  together with its question signature, and on restore re-publish the answer
  *only* if the signature still matches what is on screen. That is safe by
  construction because it reuses the staleness check that already exists, and
  it is what stops a restored answer ever appearing against a different
  question.

## Case 9 — `answer-parts` on two- and four-field questions

- `multiFieldEvidence.fields: 2`, then `4`, on consecutive steps of L3.3 Q3/3.
- **Route:** `Facet Reasoning · GPU`, ~18 s, `answerLength: 11`,
  `insertable: true`.
- **Insertion:** refused, `answer-not-insertable {editor: "answer-parts",
  plan: "answer-parts"}`, three times.
- **Failure class:** `answer-shape`.
- **Finding:** this is the family the sweep was asked to classify, and it is
  now clearly the *second* root cause — distinct from RC1/RC2 and unfixed. A
  multi-field question is answered correctly and neither the direct multi-entry
  plan nor the comma plan fits the editor the page published. Case 2's
  `errorEditorUnknown` is the same disagreement caught one gate earlier. What
  is missing is which of the four conditions fails, which is now logged.

## Case 10 — the real `answer-parts` shape, captured live

**L3.3 Q2/3 Step 3 of 3.** A factored quadratic is given and the step asks for
*two points on the parabola other than the vertex and the x-intercepts*.

Three of the four layers were captured from the live window and the log; the
fourth needs the add-on reloaded.

- **Answer surface, seen directly:** two large empty boxes labelled `A:` and
  `B:`, beside a coordinate grid carrying the note *"Any lines or curves will
  be drawn once all required points are plotted."* So the answer is typed into
  boxes and the figure is drawn from it — a compound surface, not two plain
  text inputs.
- **Detected answer shape:** `multiFieldEvidence.fields: 2`, and on a sibling
  step of the same family, `4`. The DOM's own count of solution fields is not
  stable across steps of this shape.
- **Answer payload:** `Facet Reasoning · GPU` (gpt-oss:20b), and the panel
  displayed **three coordinate pairs for a page with two boxes**. Successive
  runs reported answer lengths of 17, 18 and 20 characters — so the display is
  carrying more values than the question has places for.
- **Router:** *"Facet Exact declined (no exact operation matched the
  instruction)"*.
- **Refusal:** `errorEditorUnknown` — "The answer editor could not be read, so
  nothing was inserted."

### Working hypothesis, not yet confirmed

`errorEditorUnknown` fires when the DOM's field count and the page's published
editor model disagree. A coordinate box plausibly publishes *two* controls, one
per ordinate, so a two-point question would publish four editors while the DOM
reports two solution fields — and `editor.editors.length !== fieldIds.length`
refuses. The alternating 2/4 field counts across sibling steps fit that.

**This is a hypothesis and must not be built on.** The decisive numbers come
from the two diagnostics now in the tree — `errorEditorUnknown` carries
`fields=N editor=KIND editors=M ok=…`, and `answer-parts-unplaceable` reports
the answer's part count and lengths, each editor's kind, enabled state,
allowed character set, templates and slots, and what *both* entry routes said
about *each* part. Neither has reached the live add-on yet.

**Blocked on:** a reload of the temporary add-on. Nothing further can be
established about this family without it.

### A separate finding: this family is exactly solvable

"Find two points on the graph other than the vertex and the x-intercepts" needs
no model at all — expand, find the vertex and roots, then evaluate at two
convenient inputs that avoid them. Facet Exact declined with *no exact
operation matched the instruction*, so a 15-to-26-second GPU reasoning call is
answering a question that is a handful of exact evaluations. This is the
sweep's first `capability` gap, and it is worth more than it looks: the same
route also produced *three* values for a two-box question, which an exact path
would not do.

### Narrowing it without a reload

`multi-answer-editor-described` is logged whenever an answer has parts *and*
the editor is not a `multi`. Across the whole log there are **7**
`answer-parts` refusals and **0** of those lines. Since a refusal proves the
answer had parts, the page published a `multi` editor every time.

That eliminates one of the four conditions and leaves three, all inside
`multiEntryPlans`:

1. `editor.editors.length !== parts.length` — a count disagreement. The panel
   displaying three coordinate pairs for a two-box page points here, and so do
   the alternating 2/4 DOM field counts on sibling steps.
2. a part failing `validateAnswer` — unlikely: the answer pattern already
   admits `(`, `)` and `,`, so a coordinate pair passes it.
3. `planEntry` failing per part — very plausible. A coordinate pair's
   parentheses and comma have to be in the box's own character set, and there
   is no keypad template for a pair. If Hawkes enters a point through separate
   ordinate sub-controls, the pair can never be typed into one box.

(1) and (3) are different fixes: one aligns counts, the other needs a new entry
plan for a coordinate pair. Both are distinguished by `editorCount`,
`allowed`, `directFit` and `plannedFit` in the new diagnostic. **No editor-plan
work should start until that line is in hand.**

## RC3 — a disabled control was counted as one of the question's answers

The diagnostic answered it on its first firing, and the answer was none of the
three guesses:

```text
answer-parts-unplaceable {
  parts: 3, partLengths: [5,6,6], partsValid: [true,true,true],
  editorKind: "multi", editorOk: true, editorCode: "described-multi",
  editorCount: 3,
  editorKinds:   ["dynamic", "dynamic", "option"],
  editorEnabled: [true,      true,      false],
  editorMaxLength: [16, 16, null],
  allowed: ["0123456789-,", "0123456789-,", ""],
  templates: ["fraction+exponent+parentheses", "…", ""],
  directFit:  ["answer-needs-template", "answer-needs-template", "editor-disabled"],
  plannedFit: ["ok",                    "ok",                    "editor-option-answer"],
  commaPrompt: false
}
```

The page publishes **three** controls for a two-box question: the two
coordinate boxes it shows, and a **disabled `option` control it does not**.
Everything followed from counting that third one:

- `answerShapeOf` reported `multi` count **3**, so Facet was asked for three
  separate answers — which is why the panel displayed *three* coordinate pairs
  for a two-box page, and why answer lengths wandered between 17 and 20;
- the insertion was then refused, because a disabled control accepts nothing;
- and at the earlier gate the same disagreement surfaced as
  `errorEditorUnknown`, three published editors against two DOM solution
  fields.

**Both real boxes had planned perfectly well** — `plannedFit: ["ok", "ok", …]`.
Neither the count-alignment fix nor a new coordinate-pair entry plan was
needed. The parentheses and comma are already in the boxes' own character set
(`0123456789-,` plus a parentheses template), so nothing about coordinate entry
was ever the problem. Both hypotheses from the previous section were wrong, and
the diagnostic is why nothing was built on them.

**Fix:** a control nobody can type into is not one of the question's answers.
The editor probe now drops controls reporting `enabled: false` before the count
is taken, so the count is the page's own. Enabled state is read from the very
control an answer would be typed into, so this decides nothing
`answerFitsEditor` would not decide again later — it decides it before the
count is taken, which is the only place it can prevent a third answer being
requested.

Pinned under QuickJS with the exact live shape, plus the case where dropping
the unusable controls leaves exactly one, which must fall through to the
single-editor answer.

**Expected live effect:** two parts requested, two returned, both planned, and
the insertion proceeds. Awaiting a reload to retry the same question.

## RC4 — the multi-answer shape is only recognised when the fields say "or"

RC3 is necessary and **not sufficient**, and the same diagnostic run showed why.
Insertion additionally requires one field id per answer part:

```js
if (multiEntry === null || target.fieldIds.length !== target.answerParts.length)
```

and on this question `target.fieldIds` is empty. The reason is in
`solutionFields()`:

```js
return separators.length >= fields.length - 1 ? fields : [];
```

with live evidence `{fields: 2, separatorCandidates: 0, separators: 0}` — and
`{fields: 4, …}` on a sibling inspect. The whole multi-field recogniser was
built for the shape *`x = ___ or x = ___`*: it finds the visible boxes, then
requires the word **"or"** between them before it will call them one answer.
Lesson 3.3's step labels its boxes **A:** and **B:**. There is no "or" on the
page, so the fields are discarded, `fieldIds` is empty, and no number of
correct parts can ever be placed.

A second deduction confirmed which branch reported: the live
`focused-answer-field` lines carry `multiFieldEvidence`, and only the final
branch attached it — so the sweep had already run and returned nothing, rather
than an earlier branch short-circuiting. The branch is now named outright
(`via`), and the revealed-option branch deliberately reports *no* evidence,
because at that point the sweep has not run and a zero there would be a
measurement never taken.

### Two ways to fix it, and the one to prefer

1. **Recognise a labelled pair.** Accept fields whose adjacent label is a short
   enumerator (`A:`, `B:`). Cheap, but it is another guess about Hawkes'
   wording, and the "or" rule is already exactly that kind of guess.
2. **Require two independent readings to agree.** The page publishes its own
   editor model, and after RC3 that model reports exactly the *enabled*
   controls. If the DOM finds N visible, editable, uniquely-identified fields
   and the model publishes N enabled editors, that agreement is stronger
   evidence than any wording, and it is the discipline already used elsewhere
   in this add-on — the data table is trusted because the plotted points agree
   with it.

(2) is preferable and cannot be done inside `solutionFields()`, which is an
isolated content script and cannot see `quant_wp_UI`. It belongs in the event
page, which already holds both readings side by side and already compares them
one gate later.

**Deliberately not implemented yet.** RC3 changes where the add-on may type and
has not been verified live; stacking a second unverified change to the same
decision would make neither attributable. RC3 first, live, then RC4.

## RC5 — a fix that was wrong, and the live log that said so

Correcting the record on RC2's second half. I reasoned that "a bbox origin must
be subtracted before scaling" and called the original formula unambiguously
wrong. It was not, and the fixture coordinates it had been written against were
not wrong either.

Live, immediately after that change reached the browser:

```text
evidence-refused {"graph":"drawn-mismatch-1.43", "promptChars":192}
```

1.43 is 25 px at 17.5 px per unit — the grid's own origin, in axis units, and
nothing to do with the data. `getBBox` reports an element's *own user space*,
so a dot inside a `translate(25,25)` group and the grid around it are measured
in different spaces; subtracting the grid's origin puts every dot out by
exactly that origin. The dots' plot-relative coordinates were the tell all
along, and the committed fixture had them right because it was modelled on real
markup.

**Fixed properly:** both the grid and each dot are measured with
`getBoundingClientRect`, which is one space whatever transforms lie between
them, and the tolerance is a third of a grid unit rather than `1e-9`. A
rendered position is measured in fractional pixels, so exact equality was never
available — it only ever held for coordinates authored to satisfy the
arithmetic. A third of a unit is far tighter than any real disagreement, since
a dot described in the wrong place is out by a whole unit at least, and the
harness's negative control still refuses a moved description.

**Fixtured:** `scatter-translated.html` puts the dots inside a translated group,
which is the live structure and the case every other fixture lacked.

**The lesson is the sweep's own, again.** RC2 was "a fixture that encodes a
guess only confirms the guess"; this was the same mistake in the other
direction — changing code to match a guess about markup I still had not seen,
and repositioning six fixtures to agree with it. The live diagnostic caught it
in one run, which is the argument for having built the diagnostic first.
