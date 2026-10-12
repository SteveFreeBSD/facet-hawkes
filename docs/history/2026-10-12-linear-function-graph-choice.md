# Linear function graph choice

Historical evidence, not operating instructions. Current authority:
[Answer capabilities](../ANSWER_CAPABILITIES.md),
[Current state](../CURRENT_STATE.md), and
[Runtime and deployment](../RUNTIME_AND_DEPLOYMENT.md).

## Defect and change

A Chapter 3 question asked for the graph of a written linear function. Hawkes
rendered four graph captions as ordinary radio options. The existing semantic
graph-choice reader expected each graph to have a QASystem graph model and a
`role=radio` ancestor, so it refused the surface as
`graph-choice-ownership-unreadable` before Facet received the question.

Hawkes' option model owns exact caption XML for each candidate: one line defined
by two exact points and extended in both directions. The reader now joins each
option model to its radio by model index and name, generated ID and value, ARIA
label ownership, and the rendered graph below that label. It resolves only
page-declared Knockout observables. It derives an exact rational slope and
y-intercept from the caption points, rejects vertical, duplicate, malformed or
unowned candidates, and crosses the candidates through the existing
`graph-choice` surface. DOM order, screen position and pixels do not identify a
choice.

Facet normalizes one named function or affine equation through the shared exact
line reader, simplifies its slope and intercept over rationals, and selects the
unique candidate with the same semantics. A malformed surface, ambiguous source
or non-unique match is a terminal refusal with no reasoning fallback. The older
inequality boundary-and-shading graph-choice route remains unchanged.

## Live proof

The current Chapter 3 question was used only as live proof. No specimen values,
candidate order or graph bounds were added to production routing. The agent did
not Submit, Check, Next, Skip or navigate the lesson.

After the final coherent reload, marker `870af893b823` matched the working tree.
Solve `rmv5g5059bdb1` described four candidates through the
`caption-linear-graph-choice` contract and reported Facet Exact, exact MathML
reading, `choice` form, SymPy 1.14.0 and zero model calls. Insertion
`rmv5g53lf661f` used the existing `hawkes-graph-choice` transport and
`graphOperation`; the option radio and its page model settled and read back as
`graph-choice-verified` with unchanged pinned question ownership.

The selected graph remains inserted. Hawkes grading acceptance is deliberately
unconfirmed until Steve reports the result, so this record does not call the
family Fixed live.

## Verification and deployment

- Hawkes full suite: 2,400 passed; lint, formatting, compileall and vulture clean.
- Runtime full suite: 1,425 passed; lint and formatting clean.
- Runtime `15fcc3a48e58c5df4b00a68df24800bf1f77c4b6` is committed, pinned and
  installed locally.
- Answer-capability closure, documentation, the 37-question offline sweep,
  native registration and local transport passed.
- Package validation found 48 files; two builds had SHA-256
  `c13d2baaec368c572eb0d48808a47ebb6a12dc60013e8c3668f767bacc68105c`.
- No remote publication was performed.
