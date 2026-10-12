# Boolean line relationship proof — 2026-10-01

Historical evidence, not operating instructions. The authorities are
[answer capabilities](../ANSWER_CAPABILITIES.md),
[the boundary](../FACET_BRIDGE.md) and
[runtime deployment](../RUNTIME_AND_DEPLOYMENT.md).

Status: Fixed live. Steve reported “works great” after the installed Boolean
repair. Read-only observation subsequently showed Hawkes at Question 2,
Step 2 of 2, with 4/13 correct, beyond the original Question 1, Step 3 of 3,
which had shown 2/13 correct. The agent did not submit or navigate.

Runtime `db2871ba53e21b7b56398934e4951042b4ab3462` adapts the semantic
answer contract. It calls the existing exact relationship classifier once,
preserving its two independent source identities and rational normalization.
A unique explicit prompt proposition supplies the Boolean meaning: parallel,
perpendicular, or neither parallel nor perpendicular. Equality with the exact
classification derives the truth value; case-normalized published Yes/No
labels identify the answer independently of option order. No proposition is
inferred from Yes/No alone. Missing, compound and unsupported propositions,
invalid choices and coincident lines refuse without model fallback. Direct
Parallel/Perpendicular/Neither surfaces retain the existing classifier.

For live proof only, the sources were `3-(2y+4x)=5(x-y)` and
`3y+7=8+9x`. They independently reduce to `y=3x-1` and `y=3x+1/3`.
Their exact slopes are both 3 and their intercepts differ, so the classification
is Parallel. The prompt “Determine if the two lines are parallel.” supplies
the parallel proposition; its truth value is true and the matching label is
Yes. These coefficients are proof inputs, not implementation constants or
regression fixtures.

A request to the reinstalled native helper with those equations and reversed
choices returned classification parallel, proposition parallel,
proposition_value true, answer Yes, route exact, source Facet Exact and
model_calls=0. Its evidence retained both sources, canonical coefficients,
slopes and line forms. Normal-profile run `rmupk1emrcb84` independently read
two MathML expressions and two controls, then returned Facet Exact, the existing
Exact two-line relationship classification method, model_calls=0 and a solved
choice answer of length 3. Background marker `3e6a5b6fe325` and question-reader
marker `69f631b08010` matched the running tree; no extension reload was needed.
Ordinary radio selection remains Steve's action.

Runtime tests: 1,228 passed. Companion tests: 2,238 passed. Regressions cover
all three classifications against all three propositions, both source orders,
permuted Boolean labels, supported prompt forms, axis-aligned lines, coincident
lines and terminal ambiguity refusals. A spy asserts the authoritative
classifier is called once with the original ordered sources. Model callbacks
fail the test if invoked. Both repositories' static gates, documentation and
pin checks, compatibility checks, package and native-host health passed.
Offline sweep: 37/37 exact and one correct decline. No agent Submit, Check,
Next, Skip, radio selection or coursework navigation occurred. Screenshots
were read locally and deleted. Runtime publication remains pending.
