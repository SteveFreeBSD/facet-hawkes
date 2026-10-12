# Two-line relationship classification proof — 2026-10-01

Historical evidence, not operating instructions. The active authorities are
[the boundary](../FACET_BRIDGE.md), [answer capabilities](../ANSWER_CAPABILITIES.md)
and [runtime deployment](../RUNTIME_AND_DEPLOYMENT.md).

Status: Fixed live. Exact normal-profile solve and semantic choice matching
were proven; Steve confirmed that he submitted and Hawkes accepted the answer.

The normal Firefox session held Lesson 2.5, Question 6 of 7, Step 1 of 1.
The page published two distinct MathML equations and three radio choices:
Parallel, Perpendicular and Neither. The instruction requested classification,
but the router treated both relationship names as an ambiguous construction
request and refused with “the line relationship is ambiguous”.

Runtime commit `509987dfc093fed19ea6d6eea2e0c4aeff03bfa7` adds a separate
classification route ahead of relative-line construction. It preserves both
source identities, normalizes each independently to rational `Ax+By+C=0`,
derives the slope and explicit line form, and compares exact normals. Equal
directions and distinct canonical equations mean Parallel; orthogonal normals
mean Perpendicular; otherwise Neither. This includes distinct vertical lines,
vertical/horizontal pairs and horizontal lines. Coincident canonical equations
are explicitly refused, as are ambiguous source counts, unreadable mathematics,
variable denominators and ambiguous choice labels. No model fallback is allowed.

The unique semantic classification is matched against the published choice
labels, retaining the exact page wording. Choice permutations, case and
supported equivalent wording are covered. Ordinary radio selection remains
Steve's action; the extension publishes the matching label and does not submit.
No browser or insertion code changed, and no extension reload was needed.

For the original live proof only, the two sources were
`(7x-2y)/2=x+2` and `-5y-x=x+3`. These reduce independently to
`y=5/2*x-2` and `y=-2/5*x-3/5`, with exact slopes `5/2` and `-2/5`.
Their product is `-1`, so Perpendicular is the unique matching choice.
Normalized `(A,B,C)` tuples are `1,-2/5,-4/5` and `1,5/2,3/2`;
the determinant is `29/10`, the normal dot product is `0`, and the lines are
distinct. These numbers are proof inputs, never implementation constants or
regression fixtures. The regressions use different equations.

The installed `facet-remote` was reinstalled from the committed runtime. A
subprocess proof with the live pair and permuted choices returned route
`exact`, source `Facet Exact`, method `Exact two-line relationship classification`,
form `choice`, entry `Perpendicular` and `model_calls=0`, together with both
source equations, normalized coefficients, slopes and line forms.

Normal-profile solve `rmupjfqcv4c9c` at 07:56:21 CDT:

- Window 1, tab 2, frame 0, signature `r88b25|7905|`.
- Exact markup reading, two expressions and three page-owned option controls.
- Question-reader marker `69f631b08010` matched the tree.
- Facet Exact, router solved, `model_calls=0`, the new classification method.
- A `choice` answer of length 13 was retained and rendered in the panel;
  it passed the host and panel checks against the question's published labels.
- Subsequent normal-profile relationship runs also solved exactly without
  model calls, including `rmupjh3sv7bf2`.

The original question was inspected locally before implementation. By the
final observation, Steve had navigated to the lesson landing page; grading
acceptance was not inferred from that navigation. Steve subsequently confirmed
submission and Hawkes acceptance in this conversation. All screenshot bundles were
deleted after local inspection. No agent Submit, Check, Next, Skip, radio
selection or coursework-navigation action was performed.

Verification: runtime 1,148 tests passed; companion 2,238 tests passed.
Regressions cover independent source identities and substitution proofs,
fractions, parentheses and variables on both sides, rational and decimal
coefficients, all three classifications, swapped equations, all choice
permutations, vertical/horizontal cases, scaled/coincident equations and exact
terminal refusals with a callback that fails if a model is called. The DOM
regression preserves both MathML source equations separately.

Both repositories' static gates, documentation/pin and compatibility checks,
native-host registration, package and offline sweep passed. The sweep answered
37/37 exactly with one correct decline. Package SHA-256 remained
`65782f841a9657cedbdcf127c9172f98b551f1da91f8044ccc2d8ab9adae2966`.
The companion pin and quoted pins name the new runtime; source publication is
pending, so a public checkout of this pin requires publishing it first.
