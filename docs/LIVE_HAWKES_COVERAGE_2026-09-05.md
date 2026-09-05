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
2. **The drawn-vs-described cross-check ignored the grid's bbox origin.** It
   scaled `cx`/`cy` without subtracting `rect.x`/`rect.y`, so it could only
   agree where the plotting area starts at 0,0 — true of a hand-authored
   fixture and of no real SVG. The committed fixture coordinates had been
   written to satisfy the wrong formula, which is why the check passed offline
   and could not pass live.

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
