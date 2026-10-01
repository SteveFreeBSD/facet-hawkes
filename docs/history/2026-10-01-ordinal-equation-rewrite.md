# Ordinal equation rewrite proof — 2026-10-01

Historical evidence, not operating instructions. The active authorities are
[the boundary](../FACET_BRIDGE.md), [answer capabilities](../ANSWER_CAPABILITIES.md)
and [runtime deployment](../RUNTIME_AND_DEPLOYMENT.md).

Status: implemented and installed locally; exact first-equation solve and native
insertion verified. A subsequent second-equation rewrite was observed accepted
by Hawkes after Steve-controlled submission. No agent grading or navigation
action was performed.

The normal Firefox session held Lesson 2.5, Question 4 of 7, Step 1 of 3.
Two equations were displayed; the step explicitly requested the first.
Earlier runs used Facet Reasoning and produced the wrong algebra. The existing
reader preserved two page-owned MathML expressions in order, and the native
host preserved that order through conversion. The exact rewrite route required
one expression and declined the pair, allowing reasoning fallback.

Runtime commit `358dad7bed0ec3f825d4d0b08dcdcd6de36b8038` selects the
referenced equation within the requested rewrite operation. It reduces both
sides over exact rationals, isolates `y`, verifies substitution and records the
source equation, ordinal and count. Ambiguous/missing references among multiple
equations and unsupported selected sources are terminal refusals. The installed
`facet-remote` was reinstalled with `uv tool install --force --reinstall .`.
Source publication was pending at this proof; the companion pin and quoted
pins agree. Steve authorized landing afterward, and runtime publication was
completed on 2026-10-01 before committing the companion changes.

For this live proof only, the first source was
`7-(2y+2x)=6(x-y)` and the second was `4y+6=7+8x`.
The requested source reduces to `4y=8x-7`, giving `y=2x-7/4`.
An installed-helper request returned source ordinal `1`, source count `2`,
selection `explicit ordinal`, slope `2`, intercept `-7/4` and a substitution
identity, with route `exact`, source `Facet Exact` and `model_calls=0`.
These numbers are proof inputs, not implementation constants or regression
fixtures; the new regressions use different equations.

Normal-profile operation `rmuphk0f9f86d` at 07:03:41 CDT:

- Window 1, tab 2, frame 0; question signature `zcfe3g|10331|`.
- Reader: exact markup, two expressions, build `69f631b08010` matches the tree.
- Solver: Facet Exact, SymPy 1.14.0, router solved, `modelCalls: 0`.
- Insertion: native `hawkes-dynamic-keypad`, MAIN world, `enterPlan`, seven
  accepted keypad writes; pinned question unchanged.
- Existing structured insertion/read-back settled; panel showed Placed.
  A local screenshot confirmed `y=2x-7/4` with a native fraction in the editor
  and the same question and step still present. The screenshot bundle was
  deleted after inspection.
- No Submit, Check, Next, Skip or other grading/navigation action was performed.
  Steve used Hawkes Try Again beforehand to restore the editable step.

Regressions cover first/second and equation 1/2 references, both-side
parentheses and variables, reduced rational results, decimal rational input,
unselected unsupported equations, duplicate equation identities, precedence
over surrounding relationship wording, and terminal ambiguity/missing-source
refusals with a reasoning callback that fails if called. DOM regressions
verify both sources remain ordered and answer-feedback math is excluded.

Verification: runtime 1,077 tests and companion 2,237 tests passed; documentation, pin,
capability and compatibility checks passed; the offline sweep answered 37/37
exactly with one correct decline. Lint, formatting, compile, dead-code,
native-host registration and helper checks passed. Two unchanged-source package
builds produced SHA-256
`65782f841a9657cedbdcf127c9172f98b551f1da91f8044ccc2d8ab9adae2966`.
The full companion suite initially found five pre-existing links to removed
thin-app documents; those references were repaired in this change.

Subsequent acceptance observation at 07:07 CDT: Steve continued using the
lesson. The page showed Question 4, Step 2 of 3, requesting the second of two
equations, with source `5y+4=9+10x`, entered result `y=2x+1`, and Hawkes’ green
“Good job” message. The correct count was 8/13, compared with 6/13 at the
initial observation. Solve `rmuphlsp2c148` reported two markup expressions,
Facet Exact, router solved and `modelCalls: 0`; insertion `rmuphlulq7276` used
the native structured keypad writer and settled six writes. This is direct
Hawkes acceptance evidence for the second-equation rewrite; the earlier
first-equation run remains the recorded exact solve/insertion proof. The
acceptance screenshot was inspected locally and its bundle deleted.

Landing verification on 2026-10-01: runtime `358dad7` was published first and
reinstalled from its clean committed source. All 41 installed runtime Python
source files matched the pinned Git object byte for byte. The installed helper
solved both synthetic ordinal smoke questions exactly with `model_calls=0`.
The normal Firefox background marker `3e6a5b6fe325` and question-reader marker
`69f631b08010` matched the extension tree; no extension reload was required.
Final landing suites passed: companion 2,237 and runtime 1,077 tests.
