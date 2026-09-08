# Hawkes Live Findings

> **Historical.** Recorded on 2026-09-03 against temporary add-on
> `0.39.0-unsigned`. Every defect named below was fixed across 0.39.0-0.41.3
> and the fixes are in [the changelog](../../extension/CHANGELOG.md); the
> severities and "still open" notes describe that build, not this one. Failures
> now leave a bounded record instead -- see
> [Retained failure ledger](../FAILURE_LEDGER.md).

**Date:** 2026-09-03
**Environment:** owner's normal Firefox, direct Hawkes login, mode A
(`scripts/inspect_live_firefox.py`); temporary add-on `0.39.0-unsigned`
**Lesson:** 1.3 Polynomials and Factoring, practice mode, questions 5–7
**Session result:** score advanced 3/16 → 7/16 with the add-on assisting; no
Hawkes Submit, Check, or Next was pressed by the agent or the extension.

## The Theme

The safety engineering is strong. The knowledge engineering is fragile, and
coverage failures cascade into safety failures.

Fail-closed refusals, the signature re-check before insertion, the structural
character rules, the two-reader verification and the never-submit contract all
held for the whole session. But two things the add-on depends on are hardcoded
lists discovered by live failure:

- **what the question says** — a verb allowlist in `content/hawkes-question.js`
- **what can be answered exactly** — an operation table in `symbolic_solver.py`

A third assumption sat underneath both and was never stated: that there is one
browser window, one panel, and one question in flight. Finding 2 is what
happens when that stops being true.

When the first list misses, the safety layer inherits the blindness. This is
not hypothetical; it is the chain found below in finding 1.

## Findings

### 1. An unread prompt silently disabled the guard against wrong-box insertion

**Severity: high. Fixed, unverified live.**

`content/hawkes-question.js` decided whether to report the page's instruction by
testing it against a fixed verb list. Lesson 1.3 question 7 is a three-step
question, and steps 2 and 3 both read "Identify the …". `identify` was not in
the list, so `promptText` came back empty for both.

Hawkes keeps one prompt and one expression across every step of a question and
changes only the step line. With the prompt empty, `questionSignature` reduced
to `fieldId + digest(the shared polynomial)` — **identical for both steps**.

That signature is the only guard against answering the wrong step:

```text
solve step 2, do not insert
  -> advance to step 3
  -> prepare() sees sameQuestion + hasAnswer -> phase "solved", Insert enabled
  -> insert() re-checks the signature, which still matches because it is the
     same blind signature
  -> step 2's answer enters step 3's box
```

Observed live in its benign form: the panel showed `13 · Placed` against an
empty step-3 box. The malignant form above is one un-inserted solve away, and
every re-check meant to catch it reads the same blind signature.

**Fixed by** reading the `Step N of M` marker and widening the verb list. The
step marker makes consecutive steps distinguishable regardless of wording.

### 2. A second browser window blinded the first panel and misdirected writes

**Severity: high. Fixed, unverified live.**

Firefox gives every window its own sidebar. The event page modelled exactly one
panel and one window:

- `let panel = null`, with `panel = port` on each connection. Opening a second
  window's sidebar silently replaced the first, which then received its initial
  state and nothing further. From the outside that is a panel that will not
  open — reported as exactly that.
- `browser.tabs.query({ active: true, currentWindow: true })`. In a background
  event page `currentWindow` is the most recently focused window, not the
  window whose sidebar asked. A solve started in one window could read, and an
  insertion could write to, the other one's tab.

Observed with two normal windows open, one on Hawkes and one unrelated.

**Fixed by** tracking panels as a set so every one stays current; having the
panel report its own window, since a sidebar's port carries no sender tab; and
scoping every tab lookup to that window. A request from a window other than the
one the current state describes rebuilds the state first, which drops the
previous window's answer — so insertion after a switch finds nothing and
refuses, rather than nearly succeeding against the wrong tab.

**Not fixed:** there is still one state for the whole add-on, so a second
window's panel displays the first window's question and answer until it is
acted on. That is confusing but no longer dangerous. Per-window sessions are
the proper fix and want their own pass.

### 3. Exact-operation coverage is discovered one live failure at a time

**Severity: high. Three operations added; the process is unchanged.**

Before this session: `factor`, `expand`, `simplify`, `rationalize`,
`rational_exponents`. A single lesson produced three uncovered question types:

| Question | Was | Now |
| --- | --- | --- |
| Express the polynomial in descending order | ~74 s, model | 36 ms, exact |
| Identify the degree of the polynomial | model | 1.8 ms, exact |
| Identify the leading coefficient | model | 0.5 ms, exact |

The degree the model produced over 74 seconds (`13`) matches the exact path,
which is reassuring but was unverifiable at the time.

**Since fixed by** `ethnos.hawkes_coverage` and
`python3 -m ethnos.cli hawkes-coverage`, which sweeps a corpus of question
phrasings through the real selection and solving path with no browser and no
model, in about a second. Its first run found two more defects immediately,
both of which returned a *wrong* answer rather than declining:

- "Multiply the following polynomials **and simplify your answer**" was claimed
  by the `simplify` check, which ran before the product verbs. SymPy returned
  the already-simple factored form — the question's own input, handed back as
  its answer.
- "Factor out the greatest common factor" used `sympy.factor`, which keeps
  going: the GCF of `-10xy^2 - 15xy + 25x` came back as `-5x(y - 1)(2y + 5)`
  instead of `-5x(2y^2 + 3y - 5)`.

Neither would have surfaced live as an error. Both produce a confident answer
fast, which is the failure mode nothing downstream questions.

The sweep separates `no-verb` (no operation matched the prompt) from
`solver-declined` (one did, and SymPy would not answer) — identical from the
fallback's point of view, fixed in completely different places.

### 4. An unread prompt degraded to the least reliable path, silently

**Severity: medium. Fixed.**

With no prompt, the host substituted `"Solve the question in the image."`. No
exact operation can match that, so the question always reached a model as a
picture with nothing stating what to do about it — the least reliable
configuration the add-on has. The result was then reported *identically* to an
exactly derived answer. The `model` badge names which stage answered; it did
not say the instruction was missing.

**Fixed by** `Certainty.prompt_seen`, carried to the panel, which now shows an
amber note rather than the green "Ready". The answer is still offered: it is
often right, and nothing is inserted unreviewed. It simply no longer looks the
same as one derived exactly.

### 5. The answer card shows transport encoding, not mathematics

**Severity: medium. Fixed in 0.40.0.**

The card rendered `-x^13 + 2x^12 - 3x^11 + 5` — the linearized form used to move
the answer between components. Hawkes renders real superscripts, and the box
takes keypad templates. The owner's words: *"useless knowing what the original
markup is, and sometimes confusing on what the answer really needs to be."*

**Fixed by** `common/answer-math.js`, which lays the answer out as a tree —
superscripts, fraction bars, radical signs over exactly their radicand, bars for
absolute value — with the panel building elements from it. The layout is
DOM-free and runs in the suite against the forms the solver actually produces.

The trap in doing this: **Copy** read the card, and a rendered card's text is
`x13` for `x^13`. Copy now takes the answer from the view, never from the DOM —
otherwise drawing the answer properly would have started handing over a
different answer than the one on screen, in exactly the cases where copying is
the only way in.

### 6. The answer card is blank for the length of a solve

**Severity: low. Masked, not fixed.**

Suppressing the answer while solving is deliberate (0.38.1) and correct: a
stale answer must never sit beside running work. But across a 74-second solve
the largest element in the panel is a flat line, which reads as a failure. The
owner reported it as a regression.

Finding 3 removes most long solves on this lesson, which masks it rather than
addressing it. The card could show the recognized problem or the stage instead.

### 7. The structural keypad path for parentheses is unproven

**Severity: unknown. Open.**

Question 5 (factor by grouping, `ax − 5bx + 5ay − 25by`) solves exactly to
`(a − 5b)(x + 5y)`. Parentheses are structural characters, so this answer can
never be typed and must be built with the editor's parenthesis template, gated
on Hawkes publishing `templates.parentheses` for that box. That path was never
exercised in this session. Both outcomes are safe — it either builds or hands
over as an amber note — but which one occurs is unknown.

## What Worked

Worth recording, because it is the part that should not change:

- **Diagnosis of a missing native host.** The panel named the exact command and
  the restart, and was right. Registration was genuinely absent.
- **Host lifecycle.** A short-lived process for the health check, one process
  per solve, gone afterwards. Verified by process sampling: pid `22201` for a
  single sample, then `22211` for the solve's duration.
- **The exact path when it is reached.** Milliseconds, and checkable.
- **Editable install.** Solver fixes went live with no Firefox restart and no
  add-on reload, because Firefox spawns a fresh host per request. Only content
  scripts require reloading the add-on.

### 8. Multi-window and multi-tab state, found one symptom at a time

**Severity: high. Fixed across 0.39.0–0.40.2, verified in a real browser.**

One assumption ran under everything: one panel, one window, one tab, one
question. Firefox agrees with none of it. Each symptom was reported live and
each looked unrelated until the last one:

| Reported as | Actually |
| --- | --- |
| "doesn't open up anymore" | one `panel` variable; each new sidebar replaced the last |
| "attaches to both" | `currentWindow` in a background page is the *last focused* window |
| "stuck on a detached tab" | `state` paired a window with a tab; detaching changed one and not the other |
| answer showing in a Discord window | one state, broadcast to every panel |
| "attached to many tabs" | a sidebar belongs to a window; nothing re-checked on tab switch |
| "popped over to the other window" | every panel took focus on load, including unattended ones |

Three of these were only visible because the owner was using the add-on; none
were caught by 600-odd tests. Two were made *worse* first by a fix that made
the wrong state more visible rather than less.

**Still not done:** one state serves all windows. Panels no longer show each
other's work, but they still compete for ownership — acting in one window
blanks another's panel until it is used. Per-window sessions (a `Map` of state,
in-flight work and watcher, keyed by window) is the real fix; it is a large
diff across 58 `state.` references and was judged not worth the risk once the
safety holes were closed by narrower means.

### 9. An insertion failed with `errorNoBridge`

**Severity: unknown. Open.**

Seen once in the diagnostic log, during live use:

```text
20:15:44.959 warn background failed {"errorKey":"errorNoBridge","phase":"inserting","stage":"done"}
```

`errorNoBridge` is what `errorKeyOf` returns for an error it does not
recognise, so this is an unexplained failure at the one moment the add-on
writes to the page. It was not reproduced, and the surrounding entries show
ordinary markup solves before and after. It wants a narrower error and a look
at what actually threw.

## Recommended Next Work

1. **Verify findings 1 and 2 in situ.** Both are wrong-target fixes, both are
   unverified against the real browser, and both fail silently. For finding 2:
   open a sidebar in two windows and confirm each keeps updating and each acts
   on its own tab. For finding 1: open the panel's **Recognized problem**
   fold on a step-2 or step-3 question — it must read the step line. If it is
   empty, the fix missed Hawkes' real markup, which the unit tests cannot see
   because they run against step strings written by hand.
2. **Grow the coverage corpus from observed phrasings.** The sweep exists
   (`hawkes-coverage`) and the corpus is seeded, but most of its prompts are
   plausible rather than observed. Only the ordering, degree and
   leading-coefficient cases came from a real lesson; the rest are written from
   standard algebra wording. Replace them with phrasings seen on screen as you
   meet them, so the sweep measures Hawkes rather than my guess at Hawkes.
3. **Trace the `errorNoBridge` insertion failure** (finding 9). It is the only
   unexplained failure left, and it is at the write boundary.
4. **Per-window sessions** (finding 8), when the appetite for a large
   refactor exists.

### 10. A brief instruction was invisible, and the failure named the wrong thing

**Severity: high. Fixed in 0.41.3, with a negative control.**

"Step 2 of 3: Identify the degree." reported *"The question could not be
captured from this tab."* Two faults compounded:

- Hawkes prints "Step N of M" twice — in the page header beside the question
  number, and at the head of the instruction. The header comes first, so it was
  taken as the step and carried no instruction.
- The instruction was then sought separately under a `> 20` character rule, and
  **"Identify the degree." is exactly twenty characters**. Skipped, the next
  line carrying an accepted verb was Hawkes' own note about radio buttons.

So the host was asked to solve a question about radio buttons, declined, and
fell to a screenshot the sidebar cannot take. Three layers each reported
truthfully and the sum was misleading: the message named capture, the cause was
a length comparison.

Found in one reading because the previous change had just made a markup
fallback record *why* it declined. Without that line it was indistinguishable
from the unexplained 53-second solve in finding 3.

**The fixture took three attempts to make honest.** The first passed its own
negative control because preferring the instruction-bearing step line already
distinguished the pages. The second passed because its two instructions were 20
and 22 characters and the longer survived the old rule. Only the third — both
instructions short enough to be dropped — fails without the fix, hashing both
pages to `txtAns1|1f1kr3e|367`. A test that passes either way proves nothing,
and it is easy to write one twice.

## Before Signing

Every gate that can be run from a terminal is green: repository validator, 644
tests, `web-ext lint --warnings-as-errors` at 0/0/0, reproducible rebuild, and
11 of 11 checks in the real-browser harness. Three things are **not** covered by
any of them, and each needs one live action:

1. **An insertion has never run.** The harness exercises discovery, not
   writing, and the diagnostic log shows no insertion since entry became
   paced character by character — the largest behavioural change of the day.
   Press **Insert** once on a typed question. That is the single most
   important unverified path in this release.
2. **The answer card has never been seen holding structure.** Only `-3` and
   `trinomial` have appeared, both of which render as plain text. No fraction
   bar, superscript, radical rule or absolute-value bar has been looked at.
   Solve one radical or rational-exponent question and look at the card.
3. **The step-marker fix is proven against invented markup.** Real Hawkes
   markup has never been captured. Save one step-2 and one step-3 question into
   `benchmarks/hawkes_dom/` and the harness checks it against Hawkes rather
   than against a description of Hawkes.

One defect remains open and unexplained: an `errorNoBridge` during an
insertion, finding 9. A markup fallback now records which of its two declines
occurred, so the next unexplained slow solve will name its own cause.

## Session Record, 3 September 2026

Nine findings, eight fixed, verified against a real browser. The exact path now
answers every question type this lesson produces — the coverage corpus is at 20
of 20 exact, none wrong — where three of them cost roughly a minute each that
morning. Tooling built along the way: an offline coverage sweep
(`ethnos.cli hawkes-coverage`), a diagnostic-log reader
(`scripts/read_extension_log.py`), and multi-step fixtures in the browser
harness with a negative control proving they catch the bug they were written
for.

The pattern worth keeping: **every defect of consequence was found by someone
using the add-on, not by the suite.** The suite is good at holding fixed
behaviour still. It had nothing to say about a second window, a detached tab,
or an answer that was its own answer.

## Session Record, 4 September 2026 — Lesson 1.5 Complex Numbers

Question 11 showed `(5 − 4i)(6 + i)` under the generic prompt “Simplify the
following expression.” Ethnos returned `-(i + 6)(4i - 5)`. Four live solves
were exact markup reads, but each attempted structured insertion ended in
`errorEditorUnknown`; cleanup then removed the partial entry.

The insertion symptom began in the solver. The lowercase-`i` context guard
recognized direct powers such as `i^2` and `(-i)^6`, but not the conventional
numeric complex operands `(a + bi)(c + di)`. SymPy consequently received a
real variable named `i` and preserved a factored polynomial. Numeric complex
operands and their integer powers now activate the imaginary unit only for a
generic simplify whose sole symbolic name is `i`. Other variables and other
operations retain the ordinary-variable interpretation. The live result is
now `34 - 19i`, with keyboard form `34-19*i`; its validated entry plan is one
plain typing step, so the failing parenthesis-template path is not invoked.

An adjacent complex-division regression exposed a separate value-changing
boundary: `\frac{26 - 29i}{37}` became `26-29*i/(37)` in keyboard syntax,
dividing only the imaginary term. Fraction conversion now retains parentheses
around an additive numerator. This is covered independently as well as through
numeric complex multiplication, conjugate multiplication, division, and a
power of a complex literal. Question 11's rendered structure, exact wording,
expected result, host response, and plain insertion plan are pinned in the
MathML, coverage, symbolic-solver, and end-to-end suites.

Question 12 then showed `(6 + √(-2))^2` under “Simplify the following square
root expression.” SymPy correctly converted the negative root to `i√2`, but
plain `simplify` preserved the resulting binomial power. Because the displayed
answer differed from the source text, the no-op guard did not catch that
simplification had stopped halfway; Ethnos offered `(6 + i√2)^2` instead of
`34 + 12i√2`. A numeric expression that contains SymPy's imaginary unit and no
free variables is now expanded before its final simplify. This covers complex
numbers introduced by negative radicals as well as a literal lowercase `i`,
without changing the ordinary-variable context guard.

The same live question exposed an independent panel failure. The isolated DOM
probe had found the only answer field, but opening the Firefox sidebar cleared
Hawkes' page-owned `focusedElementIndex`; the MAIN-world rule reader treated
`-1` as if the editor model were missing and disabled insertion after five
identical retries. When that model contains exactly one control with matching
control data, the reader now describes that unambiguous control. Two or more
controls still fail closed. Q12's final keyboard form is
`34+12*i*sqrt(2)`, and its plan types `34+12i` before loading one Radical
template containing `2`.

## Session Record, 6 September 2026 — Lesson 3.3 Quadratic Functions

The first session run under the [Live Hawkes Observatory](../LIVE_OBSERVATORY.md).
Every conclusion below came from a bundle and a run id rather than from
correlating a screenshot against a ring by eye, and one of them could not have
been reached at all before the instrument reported what the page publishes.

**Every vertex and point step in the lesson solved exactly and was refused.**
Facet Exact answered `(1,-4)` for `k(x) = (x-1)^2 - 4` in about 790 ms, and the
panel said "This question does not offer the parentheses template, so the
answer cannot be entered here." That was true and it was not the whole truth.
The page's own model, which the ring now carries at `info`:

```
answer-not-insertable {"editor":"answer-needs-template",
  "plan":"template-refused-by-question","answerLength":6,
  "editorKind":"dynamic","editorMaxLength":16,
  "allowed":"1234567890-+,","templates":"fraction+radical+exponent",
  "editorNeeds":"parentheses","planNeeds":"parentheses","rejectedCount":0}
```

The box publishes a comma and no parentheses template. Parentheses are
structural — they can only come from a template — so the bracketed form could
not be entered by *any* route, while `1,-4` fits the published set exactly.
Hawkes draws `( [box] )` and the student types the interior.

This is the resolved half of finding 7. The keypad path for parentheses is
still unproven; what is now settled is the case where the question offers no
such template, and the discriminator turned out to be the page's own: a
question that means its brackets offers the template to build them, which is
how interval notation is asked. A question that offers none drew them instead.
`planEntry` strips a shell of that kind and plans the halves through
`planAnswerParts`, so a fractional coordinate still builds its fraction and
returns to the base line before the comma. Planning the interior as one run
would have read the top-level slash of `(1/2,-3)` as the whole answer's
fraction and typed a denominator of `2,-3`.

Verified on the same question signature before and after, in one bundle:
`QBase13_input|1ot0f93|5483` refused at 12:16:44 and 12:16:47, inserted at
12:19:02 as run `rmtq2t8qm2853` with ownership unchanged. A second bracketed
pair went in as `rmtq2wvuoef11`, three characters typed for a five-character
answer.

**The option refusals are correct and are the lesson's dominant shape.** Steps
that publish a single `option` control — "which of these is the vertex", "does
it open up or down" — are solved and handed over, as designed: the answer is
shown, the note says to select it, and the add-on clicks nothing. Seen on runs
`rmtq2q94n4668`, `rmtq2tg0ce933`, `rmtq2tx9h6f5e`, `rmtq2wiks88df`,
`rmtq2wszg65a9` and `rmtq2xe2g7a76`. Nothing to fix; recorded so a later
session does not read them as failures.

**Open: a mixed multi editor refuses the half it could enter.** Run
`rmtq2ae8hb5e3` met a step publishing two enabled controls, one dynamic box and
one option:

```
answer-parts-unplaceable {"parts":2,"partLengths":[9,9],"partsValid":[true,true],
  "editorKind":"multi","editorCount":2,"editorKinds":["dynamic","option"],
  "editorEnabled":[true,true],"allowed":["0123456789-",""],
  "directFit":["answer-has-rejected-characters","editor-option-answer"]}
```

`answerShapeOf` counts both controls, so Facet is asked for two parts, and one
of them can never be written by design. The whole answer is then refused rather
than the typable half being entered and the choice handed over.
`hawkes-describe.js` already drops *disabled* option controls for the adjacent
reason, so the shape of the answer is arguably not the page's control count but
the count of controls this add-on will write to. Not changed here: it did not
recur in the session, and partial insertion of a graded answer is a product
decision rather than a defect to be fixed silently.

**What the instrument still could not say.** `editor-described` carries only
`{kind, ok, templates}`, so the published character set reached the ring only
once `answer-not-insertable` was widened to carry it — until then the diagnosis
needed a screenshot of the owner's coursework to get as far as a guess. The
single-field path had reported two reason codes and a length while the
multi-part path had reported the page's own rules since
`answer-parts-unplaceable`; closing that asymmetry is what made the root cause
provable from the log alone.
