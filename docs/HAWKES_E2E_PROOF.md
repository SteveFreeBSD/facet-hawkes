# Hawkes End-to-End Proof

**Date:** 2026-09-02; release evidence updated 2026-09-03
**Environment:** throwaway Firefox profile at `/tmp/ethnos-live-browser`
**Lesson:** 1.3 Polynomials and Factoring

## What This Proves

The live extension can complete the full safe path for a typed Hawkes question:

```text
Hawkes page and MathML
  -> exact question recognition
  -> deterministic answer
  -> panel review
  -> automated insertion
  -> Hawkes field readback
```

The extension does not click Hawkes's Submit Answer control.

For 0.38.0, the existing live session additionally verified:

- a sole visible input can be discovered while the docked sidebar leaves page
  focus on `BODY`;
- `a^(11/12)` is built as a base with a fractional exponent;
- the canonical entry `y*sqrt(30)/30` renders as `y√30/30`, keeping `y`
  outside the radical;
- reopening after insertion does not trigger a duplicate solve.

Those checks did not submit or advance a Hawkes question. The 0.38.0
question-region screenshot crop was added after that lesson session ended and
therefore remains a required manual release check rather than a claimed live
result.

## Live Proof

Question 2 of 14 displayed:

```text
(4y^3 + 11 - 4y) - (9 - 6y + 9y^3)
```

The panel reported:

```text
answer: -5y^3 + 2y + 2
status: Ready. Check it against the screen, then press Insert - it builds this with the keypad for you.
detail: source: markup
insertEnabled: true
```

The answer is verified by collecting like terms:

```text
4y^3 - 9y^3 = -5y^3
-4y - (-6y) = 2y
11 - 9 = 2
```

After clicking the extension's Insert action, Hawkes read back these fields:

```text
QBase1_input: -5y
QBase2_input: 3
QBase4_input: +2y+2
```

The extension panel then reported:

```text
status: Inserted. Submit it, then reopen for the next question.
detail: entered: -5y3+2y+2
```

The rendered fields reconstruct exactly:

```text
-5y^3 + 2y + 2
```

No Hawkes submission was made during this proof.

## Executable Gate

The browser-independent part of this contract is enforced by
`tests/test_hawkes_e2e.py`. It runs the real exact solver, extracts its final
answer, passes that answer through the shipped Hawkes planner, and checks the
complete template plan before any page writer is called:

```fish
PYTHONPATH=src .venv/bin/pytest -q tests/test_hawkes_e2e.py
```

The gate includes the live Question 2 expression and rejects an empty solver
input, so a model-only answer cannot silently enter the verified path.

## Reproduce the isolated Marionette evidence

The commands in this section control the dedicated throwaway profile; they do
not attach to the owner's normal Firefox. Do not start them during a normal
signed-extension test. For the existing normal session, follow
[`HAWKES_DEVELOPMENT_FLOW.md`](HAWKES_DEVELOPMENT_FLOW.md) and use
`scripts/inspect_live_firefox.py`.

From the repository root, with the isolated browser already running:

```fish
python3 scripts/live_browser.py popup
python3 scripts/live_browser.py page
python3 scripts/live_browser.py field
python3 scripts/live_browser.py shot
```

To run the safe live solve-and-insert loop, use the live browser harness. It captures a screenshot, asks the native host to solve, checks the editor plan, inserts through the extension's page-owned editor path, and reads the result back. It never submits or checks the Hawkes answer.

For automated validation:

```fish
PYTHONPATH=src .venv/bin/pytest -q
```

The 0.38.0 release audit completed with the full repository suite at
`568 passed`; the original proof run completed at `565 passed` when the
executable gate was first added.

## Safety Conditions

- The user reviews the panel answer before Insert.
- Exact MathML answers report `source: markup`.
- Unsupported or unverifiable questions are refused rather than inserted.
- Keypad templates are driven by the extension; the user does not type them.
- The extension never submits, checks, navigates, or selects Hawkes answers automatically.
