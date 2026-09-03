# Hawkes Live Findings

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
