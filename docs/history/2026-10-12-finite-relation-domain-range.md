# Finite relation domain and range — 2026-10-12

Historical evidence, not operating instructions. Current authority:
[Answer capabilities](../ANSWER_CAPABILITIES.md).

The live failure was an answer-shape mismatch: a finite relation asked for
Domain and Range, but two separately labeled QDy fields received one answer.
The control metadata explicitly supplied labels and both surrounding braces.
The current question was used only as live evidence, never as a solver fixture.

The fix adds a named exact `domain-range` result carrying unique rational x/y
sets, validates that composite through the helper and host, and associates sets
with fields through labels and model ownership rather than order. Missing or
duplicate labels, unsupported input, incomplete braces and changed mappings
fail closed. Rational lists are planned as separate members, with fractions
kept out of each other's denominators. No model call is used by this route.

The source marker `5a8f3a522496` matched the running temporary add-on.
Solve `rmv598i39bc8a` reported Facet Exact, `modelCalls: 0`, and two parts.
Insertion `rmv598k8y6b07` reported `structured-fields`,
`hawkes-dynamic-keypad`, two completed fields, and 12 cadence notes.
The page changed before a separate readback; that later snapshot is not used
as proof of the original values. Steve explicitly confirmed in chat:
“Yes, Hawkes accepted both.” The tested integer-set surface is **Fixed live**.
The agent did not submit, check or navigate Hawkes.

Validation: 2,255 Hawkes tests and 1,242 runtime tests passed, with lint,
format, compile, dead-code, documentation, runtime-pin, installed-helper,
registration and local-transport checks. The offline solver sweep remained
37/37 exactly answered with one correct decline. Two package builds matched
SHA-256 `b8d8fa17dd3042a24cbbb715bdc12dcf6e933a146db7b100a0ed13ce2f871abc`.
The runtime commit is local and installed; publication remains pending.
Fractions and alternate brace surfaces were tested offline, not graded live.

## Listed relation beside an unreadable graph model

A later question in the same family exposed a separate evidence-boundary
failure. Hawkes stated one complete finite relation in MathML and also drew its
points, but the continuous graph reader correctly refused the drawing because
it was not one line. The background treated that graph refusal as a veto over
the exact listed relation and stopped before the host.

The reader now records the strict shape of a complete finite set of numeric
ordered pairs without solving it. That evidence lets the existing finite
domain/range route proceed when the optional graph model is unavailable or
ambiguous. An accepted continuous graph relation beside a finite listing is a
topology conflict and still fails closed. Incomplete sets, symbolic
coordinates, isolated pairs and multiple expressions do not weaken the graph
guard.

The running source marker `8041639cdcce` matched the working tree. Solve
`rmv5gfodl3164` retained the graph reader's
`graph-projection-relation-not-one-line` result, recorded the listed finite
relation, and returned two named parts through **Exact finite relation domain
and range** with `modelCalls: 0`. Insertion used the existing
`structured-fields` / `hawkes-dynamic-keypad` path, completed both labeled
fields, and produced 13 cadence notes. A page readback showed both fields
populated and the panel reported `Placed`. Steve then confirmed in chat that
“everything is good,” confirming Hawkes accepted both values. This
evidence-boundary repair is **Fixed live**. The agent did not submit, check or
navigate Hawkes.

Validation after the repair: 2,409 Hawkes tests and 1,425 runtime tests passed,
with lint, format, compile, dead-code, documentation, runtime-pin,
installed-helper, registration and local-transport checks clean. The offline
solver sweep remained 37/37 exactly answered with one correct decline. Two
package builds matched SHA-256
`f59dcd2df734e8b7303e047dd79c90db63605fa793d1121108187b135982da05`.
