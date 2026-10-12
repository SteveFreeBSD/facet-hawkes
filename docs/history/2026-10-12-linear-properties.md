# Linear function slope and y-intercept

Historical evidence, not operating instructions. Current authority:
[Answer capabilities](../ANSWER_CAPABILITIES.md),
[Current state](../CURRENT_STATE.md), and
[Runtime and deployment](../RUNTIME_AND_DEPLOYMENT.md).

## Defect and change

A Chapter 3 question gave one affine function and asked for its slope and
y-intercept as separately labeled answers. Facet treated the two editors as a
generic multipart surface and the graph probe mistook the word “slope” for a
request to read a graph from the following lesson step. The solve was refused
before the exact equation could be used.

Facet now returns one `linear-properties` composite containing an exact scalar
slope and an exact coordinate `(0,b)`. It normalizes a function equation or
linear equation over rationals and refuses vertical, multiple or ambiguous
relations without calling a model. The Hawkes reader recognizes exactly one
Slope owner and one y-intercept owner, including labels containing markup. The
adapter maps values by those roles, preserves page-owned pair parentheses, and
reuses the existing fraction and coordinate planners. The graph reader reports
an equation-only slope request as having no current graph, so a later graph
step cannot claim the present question.

## Live proof

The current Chapter 3 family was used only as live proof. No specimen values
were added to production routing. The agent did not Submit, Check, Next, Skip
or navigate the lesson.

After one coherent extension reload, marker `a0f41b9a0a08` matched the working
tree. Solve `rmv5ejvwg1c95` reported Facet Exact, exact MathML reading,
`linear-properties`, SymPy 1.14.0 and zero model calls. Insertion
`rmv5ejxd348a2` used the structured dynamic-keypad writer with two unchanged
pinned owners. A second instance of the same family independently followed the
same exact route in solve `rmv5ekazmdc7c` and insertion `rmv5ekcw4bbd2`.
Temporary coursework screenshots and observatory bundles were deleted after
inspection.

The values were inserted and remained under Hawkes ownership. Hawkes grading
acceptance is deliberately unconfirmed until Steve reports the result, so this
record does not call the family Fixed live.

## Verification and deployment

- Hawkes full suite: 2,392 passed; lint, formatting, compileall and vulture clean.
- Runtime full suite: 1,417 passed; lint and formatting clean.
- Runtime `4193c5f16fcf635c87d58726bec4632df64cc6a5` is committed, pinned and
  installed locally.
- The installed helper independently returned the typed exact composite with
  zero model calls.
- Package validation found 48 files; the built XPI SHA-256 was
  `cb4ec93980fada4580eb8e7023d874b31208f4eaad4eb9d39cb3f9113caf6958`.
- No remote publication was performed.
