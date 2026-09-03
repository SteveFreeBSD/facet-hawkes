# Captured Hawkes question markup

Real markup, saved from a live question, for `scripts/run_extension_harness.py`
to run the shipped content scripts against.

**Nothing in here is committed.** It is coursework, and the repository holds
none: `.gitignore` covers `*.html` in this directory.

## Why markup and not a screenshot

The probe reads the page's own MathML and prose (`content/hawkes-question.js`).
A screenshot exercises only the vision fallback, which is a different path and
is not what decides whether two steps of one question are told apart.

## Capturing one

With the question open in Firefox:

1. `F12`, Inspector
2. Select the element containing the instruction, the maths, and the answer
   box -- a container above them all is fine, more context is better
3. Right-click it, **Copy -> Outer HTML**
4. Save as `<group>-<step>.html` here

`Ctrl+S` -> "Web Page, complete" also works; save the `.html` beside this file.

## Naming

Files sharing everything before the last dash form a group, and every member of
a group must produce a *different* question signature:

```text
q7-step2.html
q7-step3.html      <- same group "q7", must differ from step2
```

That is the check. Hawkes keeps one prompt and one expression across every step
of a question and changes only the step line, so two steps that hash the same
are one question to the add-on -- which is how the previous step's answer came
to sit, insertable, against the next step's empty box.
