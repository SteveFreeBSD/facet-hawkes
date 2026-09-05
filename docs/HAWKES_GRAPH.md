# Structured parabola graph answers

The first graph answer shape supports Hawkes QGraphEngine's Cartesian SVG
vertical parabola with a vertex and two symmetric control points. Ethnos reads
exact MathML and normalizes the graph bounds, snap spacing and geometry family.
All question nodes, graph model references, control IDs and DOM remain in Firefox.

Facet does the graph planning. There is no solver preference to override any
more -- Facet routes every question the page states as mathematics, and a graph
is one of them -- and the request uses `solve_math` with
`result_kind: "parabola_plan"`,
`accelerator_required=false` and `allow_fallback=false`. It carries only the
instruction, the exact MathML-derived expression and the normalized graph
context; the markup itself, the browser commands and any screenshot do not
cross. Facet picks the parabola specialist, writes the prompt, and parses the
reply -- so this side no longer constructs a model prompt for a graph at all.

The reply Facet parses must be one JSON object, without markdown, prose,
duplicate keys or extra properties. Coordinate values are integer or rational
strings, and a decimal approximation is refused:

```json
{
  "kind": "parabola",
  "orientation": "vertical",
  "opening": "up",
  "vertex": {"x": "3", "y": "-1"},
  "points": [{"x": "4", "y": "0"}, {"x": "2", "y": "0"}]
}
```

It crosses back as `answer.plan`, structured, carrying no display text, entry or
parts: a plan is a proposal, and one arriving shaped like a settled answer is
refused.

This is the actual plan returned by Facet for `f(x)=(x-3)^2-1` during development.
Facet's strict parse is a check on the model, not a warrant. Ethnos re-validates
the schema, then independently parses the function from the page's own markup,
obtains the rational polynomial coefficients, and proves the vertex, opening,
both point incidences and symmetry. A plan that is well-formed but untrue of the
function is refused here, after Facet was perfectly happy with it.
For this function the coefficients are `(1,-6,8)`, so the vertex is
`(-b/(2a),f(-b/(2a)))=(3,-1)` and each defining point gives curvature `a=1`.
A failure carries no insertable answer. Successful provenance identifies the
specialist that ran -- `Facet Parabola Plan · GPU` -- with its actual model,
runtime, backend, device and elapsed time, and a router state of `not-run`: the
deterministic solvers answer expressions rather than geometry, so they were
never asked, which is a different claim from having tried and declined.

Before insertion, the event page pins its window, tab, frame, question signature,
reviewed plan and original graph snapshot. The injected operation additionally
pins the live graph model, curve, question nodes, SVG anchors, circles and renderer
structure. It refuses stale snapshots, replacements, dialogs, unsupported grids,
off-grid destinations or excessive movement before dispatching any event.

Actuation uses the named SVG anchors' own Arrow key handlers, then Space to
release any grabbed point. It never dispatches Enter, clicks a link, changes
coordinates directly, or invokes a grading/navigation method. Every move must
match the declared snap spacing. Linked points are reread before deciding whether
they need any movement. The original live function required only six ArrowRight
and two ArrowDown events on the vertex; Hawkes translated the defining points.

Final verification checks all three model coordinates, Hawkes' answer coefficients
and orientation, SVG circle positions and the rendered polyline's samples against
the validated polynomial. No answer or raw graph snapshot enters the diagnostic
ring. `graph-plan-validated` records Facet provenance; `graph-verified` records only
the movement count. Temporary coursework captures must be deleted after inspection.

## Evidence and remaining acceptance

- Real Facet request: `gpt-oss:20b`, Ollama 0.33.2, GPU, AMD Radeon 890M Graphics
  (RADV STRIX1), 26049.559 ms, requested backend `auto`, no fallback.
- Normal-profile add-on log on 2026-09-05: `graph-plan-validated` at 05:48:45 UTC,
  same model/backend/device, 23178.179 ms; `graph-verified` at 05:48:50 UTC with
  eight movements. This was the temporary development add-on.
- Isolated browser harness exercises successful SVG placement, stale question,
  replaced control, replacement during movement, invalid geometry, and untouched
  Submit/Check/Next/Skip sentinels. This is fixture evidence, not signed-XPI proof.
- The owner advanced away before the successful graph could be visually captured.
  Final visual capture of the live graph and provenance remains required before
  committing this pass.

The next extension of this shape is support for other graph/control families;
this actuator deliberately accepts only rational vertical Cartesian parabolas
with the observed SVG renderer and symmetric control model.

## Vertex field regression found during the same live pass

A later live question asked for the vertex of `p(x)=(x-6)(x+2)+16`. The old
text fallback inserted the unchecked Facet value `2,4`, which was both wrong
and missing the ordered-pair parentheses. The shared rational-quadratic
derivation now handles single-letter function names and gives `(2,0)` directly
with exact provenance. That log line reads `Ethnos Exact` because it predates
the rename; the same route is badged **Facet Exact** now, and the companion's
own copy of the solvers -- reached only from the image path -- is badged
**Local exact**. The existing entry planner builds Hawkes' `PBrace`
template and types `2,0` inside it, respecting the field's published character
set. The normal-profile log records exact solving and structured insertion
at 05:57:39 and 05:57:45 UTC; the owner then advanced to Step 2.

## SVG quadratic regression from the next live question

The owner then requested Facet for a quadratic regression question. Its SVG is
inside `#partInformation #partDescription`, not the answer area. Three disabled
`g.graph-objects > g.point.disable` nodes describe `(-5,5)`, `(-2,-4)`, and `(-1,5)`.
Ethnos checks those accessible descriptions against circle coordinates, axis
endpoints and the Cartesian grid's SVG bounding box. The point clipping rectangle
is padded and is deliberately not used to establish the scale. No pixels or
screenshots are needed. The exact instruction and normalized coordinates enter
the question signature, so changed evidence invalidates insertion.

Facet receives the instruction and exact point strings, and must return only
`{"kind":"quadratic-regression","coefficients":["3","18","20"]}` for this case.
As with graph plans, additional keys, prose, duplicate keys and decimal
approximations are rejected. Ethnos checks rank three and the exact least-squares
normal equations `Xᵀ(Xc-y)=0`, with rows of `X` equal to `[x²,x,1]`. Only after
that proof does it apply any supported three-decimal rounding instruction.
The accepted result is `3x²+18x+20`; all three live points lie on it.

The direct Facet request took 37410.096 ms on the same model/runtime/GPU/device
above. After reloading the temporary add-on, the normal-profile log recorded a
Facet solve at 06:14:17 UTC (39306 ms total) and structured insertion at 06:14:29
UTC (10019 ms). A live capture showed the Facet GPU badge, Placed status, complete
answer and Hawkes' “Well done!” feedback after the owner's submission. The agent
did not submit. That screenshot was inspected and deleted immediately.

Final automated gates: 978 unit tests, 19 isolated browser checks and 17 Settings
smoke checks passed. Packaging validated all 31 files; Mozilla lint reported zero
errors, warnings or notices. Ruff check and format check passed (110 Python files).
The SVG reader currently fails closed on coordinate-description forms other than
the observed nonzero integer offsets, including points on an axis.
