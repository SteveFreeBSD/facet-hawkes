# Stated linear function: slope and one function value

Historical evidence, not operating instructions. Current authority:
[Answer capabilities](../ANSWER_CAPABILITIES.md),
[Current state](../CURRENT_STATE.md), and
[Runtime and deployment](../RUNTIME_AND_DEPLOYMENT.md).

## Defect and change

The live Chapter 3 question states a slope and a function value. Hawkes puts
`Slope of` in prose beside a MathJax formula, so the previous reader sent a bare
function-name equality and lost its slope meaning. The existing exact solver
refused, then Reasoning supplied a sometimes incorrect coefficient.

The reader now attaches a recognized prose label only to the single formula in
its own question row, preserving all exact MathML values without mutating the
page. Order does not identify the slope. Unsupported or ambiguous ownership
leaves the evidence unclaimed and the property route refuses.

The existing exact line constructor derives `f(x)=m(x-a)+b`, simplifies over
rationals, and verifies the given properties. The relation contract preserves
both the function subject and right side, and the existing answer adapter enters
the right side when Hawkes owns the subject. Zero, unit and negative slopes,
nonzero inputs, decimals and fractions have offline coverage. Conflicting names,
conflicting facts, partial numeric expressions, unsupported requested forms and
missing properties terminate without a model call. Hidden dialog prose is not
a property assignment.

## Live proof and acceptance

The current Chapter 3 family was used only as live proof. No specimen numbers
were added to fixtures. Steve continued operating the lesson; the agent did not
Submit, Check, Next, Skip, navigate the lesson, or restart Firefox.

One coherent extension reload was performed after focused offline tests.
The event-page marker remained `f20f6036c8d0` because this change is in the
injected reader, whose new whole-source marker is `90c3c3f1211c`. The observatory
proved that reader marker matched the tree on the live solves.

On 2026-10-12 at 08:46 CDT, solve `rmv5b2pts8fe8` reported Facet Exact,
SymPy 1.14.0, relation form, exact MathML reading and zero model calls.
Insertion `rmv5b2se21515` used the structured dynamic-keypad writer with
unchanged pinned ownership. Another solve `rmv5b32jf1863` showed the same
exact route; its temporary screenshot confirmed the proposed function matched
the stated slope and value while insertion was in flight. Screenshots and raw
question captures were deleted after inspection.

Steve explicitly confirmed: “Hawkes accepted it.” **Fixed live** for the tested
integer slope/value surface. Rational and nonzero-input variants remain offline
coverage, not additional live acceptance claims.

## Verification and deployment

- Hawkes full suite: 2,307 passed; lint, formatting, compileall and vulture clean.
- Runtime full suite: 1,328 passed; lint, formatting and documentation clean.
- Final host/reader/compatibility/documentation/pin checks passed.
- Offline coverage: 37/37 exact answers, one correct decline.
- Package: 48 files; two builds had SHA-256
  `d377f90e7820e691ee55ff2a2ca1e1eee8d743aaf08c0d1e44fd47861fea0b8a`.
- Native registration and native health passed; installed local helper independently
  returned an exact rational slope/value result with zero model calls.
- Runtime `ec6bfa1fa88bf85491cc827b9c8150fb1f8eab99` is committed, pinned and
  installed locally. Source publication and a fresh public paired clone remain
  pending; no remote publication was performed.
