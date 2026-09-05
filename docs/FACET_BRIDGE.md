# The Ethnos-Facet boundary

Ethnos owns the page. Facet owns the answering. That is the whole relationship,
and it is not the relationship it started as.

```text
Ethnos (caspian)                            Facet (currently casbox)
  Hawkes/browser logic
  MathML capture and conversion
  window/tab/frame ownership
  answer-shape discovery
  retrieval                --- typed solve request over SSH stdin --->
                                              solver routing
                                              exact deterministic mathematics
                                              reasoning model for the rest
                                              CPU / GPU / NPU selection
  structured result        <-- structured answer + provenance ---------
  validation
  keyboard entry, insertion policy,
  Answer Cadence, never-submit
```

Ethnos used to run the exact solvers itself and ask Facet only about what they
declined. That put the routing decision -- exact mathematics or a reasoning
model, the single most consequential thing about a solve -- on the side that
owns a browser. Facet makes it now. Ethnos hands over a *question*; Facet
decides how it gets answered, answers it, and says which route it took.

Neither reaches into the other. Ethnos never names a device, a model, a runtime,
or a host in a request, and Facet never learns which document, window, frame,
field or editor a question came from -- or that there is a browser at all.

## One solver, not two

The exact solvers live in `facet_runtime.exact` and are a package dependency of
Ethnos. `ethnos.symbolic_solver` and `ethnos.polynomial_solver` re-export them,
so Ethnos's own local paths -- the screenshot pipeline, the coverage sweep, the
CLI, and the `ethnos` engine's markup route -- call the same implementation
Facet runs when it routes.

They were moved rather than copied because two copies of an exact solver do not
stay exact for long. They agree on the day they are made and drift afterwards,
and the drift appears as one engine answering a question the other declines, on
real coursework. `tests/test_facet_solver_routing.py` answers the same questions
through both engines and requires the structured answers to be identical.

## The request

`src/ethnos/facet_client.py` is the only place in Ethnos that speaks to Facet.
There are two operations. `solve_math` is the one that carries a question:

```json
{
  "facet_protocol_version": 2,
  "operation": "solve_math",
  "request_id": "ethnos-hawkes-1",
  "problem": {
    "instruction": "Find the domain of the following function.",
    "expressions": ["\\frac{x+1}{x^2-9}"],
    "answer_parts": 1,
    "label": "Question 4 of 12"
  },
  "constraints": {"accelerator_required": true, "allow_fallback": false}
}
```

A graph question asks for a plan instead of a value, and says so:

```json
{
  "facet_protocol_version": 2,
  "operation": "solve_math",
  "request_id": "ethnos-hawkes-2",
  "problem": {
    "result_kind": "parabola_plan",
    "instruction": "Graph the parabola.",
    "expressions": ["f(x)=(x-3)^2-1"],
    "graph": {"family": "parabola", "orientation": "vertical",
              "bounds": [-10.0, 10.0, -10.0, 10.0], "snap": [0.5, 0.5],
              "controls": "vertex-and-symmetric-points"}
  },
  "constraints": {"accelerator_required": false, "allow_fallback": false}
}
```

A quadratic regression sends `"result_kind": "quadratic_regression"` and the
normalized coordinates the add-on measured as `points`, and no expression at
all. Each result kind takes its own fields and no others: geometry on a
regression, or points on a parabola, is a question about something else and is
refused rather than ignored.

`generate_text` runs a prompt the consumer wrote. No Ethnos solve path uses it
any more -- the graph and regression paths were the last two, and they now ask
for a plan through `solve_math` -- so nothing in Ethnos constructs a model
prompt. The operation stays because it is part of the protocol Facet speaks.

A constraint is a *need*, not a device. `accelerator_required` says the work
must not land on a CPU; which accelerator satisfies that is Facet's decision.
It is a statement about where a *model* runs: a question the deterministic
solvers answer engages no backend at all, so it satisfies the constraint by
never needing one, and reports `actual_backend` as null rather than claiming a
processor it did not use.

A request is validated on both sides before anything runs. An unknown field, an
unknown constraint, a wrong type, a wrong version, an unlisted operation, a
`prompt` on a `solve_math` request, a `problem` on a `generate_text` one, or
more than 16 KiB is refused.

## The response

A solve carries the route Facet took, the answer in the shape the question
asked for, and the provenance for both:

```json
{
  "facet_protocol_version": 2,
  "status": "ok",
  "request_id": "ethnos-hawkes-1",
  "operation": "solve_math",
  "result": {
    "route": "reasoning",
    "answer": {
      "display": "(-∞,-3)∪(-3,3)∪(3,∞)", "entry": "(-∞,-3)∪(-3,3)∪(3,∞)",
      "parts": [], "entry_mode": "auto"
    },
    "provenance": {
      "source": "Facet Reasoning · GPU", "method": "gpt-oss:20b",
      "router": "declined",
      "router_detail": "no exact operation matched the instruction",
      "runtime": "Ollama 0.33.2", "model": "gpt-oss:20b",
      "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
      "requested_backend": "gpu", "actual_backend": "gpu",
      "elapsed_ms": 8533.637, "fallback": false,
      "metrics": {"prompt_tokens": 147, "generated_tokens": 69},
      "evidence": {"source": "ollama /api/ps", "device_resident_fraction": 1.0}
    }
  }
}
```

An exact solve is the same envelope with the other route:

```json
{"route": "exact",
 "answer": {"display": "y^(23/20)", "entry": "y^(23/20)", "parts": [],
            "entry_mode": "auto"},
 "provenance": {"source": "Facet Exact", "method": "SymPy exact symbolic",
                "router": "solved", "runtime": "SymPy 1.14.0",
                "model": null, "device": null, "actual_backend": null,
                "elapsed_ms": 1.4, "fallback": false,
                "evidence": {"source": "facet exact solver", "model_calls": 0}}}
```

`route` is the decision the whole boundary exists to move. `exact` means Facet
computed the answer deterministically and no model ran at all; `reasoning`
means a model answered -- because the deterministic stage declined, which
`router_detail` names, or because there was no deterministic stage to ask.

### A plan is a proposal, not an answer

A graph result carries a plan and nothing else:

```json
{"route": "reasoning",
 "answer": {"kind": "parabola_plan",
            "plan": {"kind": "parabola", "orientation": "vertical",
                     "opening": "up", "vertex": {"x": "3", "y": "-1"},
                     "points": [{"x": "4", "y": "0"}, {"x": "2", "y": "0"}]}},
 "provenance": {"source": "Facet Parabola Plan · GPU", "method": "gpt-oss:20b",
                "router": "not-run",
                "router_detail": "a graph plan has no deterministic route",
                "runtime": "Ollama 0.33.2", "actual_backend": "gpu", "...": "..."}}
```

There is deliberately no `display`, `entry` or `parts` on a plan. Ethnos refuses
one that carries them, because a value beside a plan is a value that skipped the
proof. `router: "not-run"` is the honest state: the exact solvers answer
expressions rather than geometry, so they were never asked.

Facet parses the model's reply strictly -- exact schema, no extra or duplicate
keys, exact integer or rational coordinates, never a decimal -- and that is a
check on the model, not a warrant. Ethnos re-validates the schema and then
proves the mathematics for itself: the polynomial coefficients, the vertex, the
opening, both point incidences and the symmetry for a parabola; the rank
requirement and the exact least-squares normal equations for a regression, with
rounding applied only after the exact fit is proved. A plan Facet accepted and
Ethnos disproves reaches nothing. Two independent readings of an untrusted reply
is the point of the split, and the second one is the one that decides.

### The answer stays structured

`entry` is the single value a one-value question takes; `parts` carries the
separate values when a question takes more than one. Exactly one of them is
populated, and Ethnos refuses a result carrying both or neither. There is no
single string that could be typed into several boxes, and recovering the
boundary between two answers by splitting display prose afterwards is guessing
at mathematics after the fact.

`entry_mode` says how literally to take a value: `verbatim` for one that is
already exactly what belongs in an answer (a coordinate pair, "Not a Real
Number"), `math` for mathematics to be written in the consumer's own entry
syntax, and `auto` for mathematics unless it is a plain phrase. Facet says
which; Ethnos does the writing, because the maths keyboard, its function forms
and its implicit multiplication are facts about the Hawkes editor and not about
the mathematics.

Failure carries a reason and no answer:

```json
{"facet_protocol_version": 2, "status": "error", "request_id": "ethnos-hawkes-1",
 "error": {"kind": "constraint_unsatisfied", "message": "no Facet accelerator is available"}}
```

`kind` is one of `invalid_request`, `unsupported_version`,
`unsupported_operation`, `constraint_unsatisfied`, `execution_failed`,
`unusable_result`, or `internal_error`. `unusable_result` means Facet ran and
what came back cannot be an answer -- no final answer in the reply, or the
wrong number of separate answers -- and Ethnos reports that as ambiguous rather
than as a failed call, because the distinction tells a reader whether to try
again or to look at the page.

Ethnos requires every named field and rejects a missing or mistyped one,
because each is a provenance claim. It also rejects provenance that contradicts
itself: an exact answer that names a model or a processor, or a reasoned answer
that names neither. Provenance that is wrong about itself may not be trusted
about anything else. It ignores fields it does not recognise, and passes
`metrics` and `evidence` through whole: a later Facet may measure more than this
client knows how to read, and that is a compatible change rather than a failed
solve. Adding a request field, an operation, or a constraint is not compatible
and moves the version.

## How Facet routes a question

Facet reads the question's own verb, runs the exact operation that matches, and
checks the answer against its own input. That path costs a millisecond, needs
no accelerator and no network, and produces a result that is checkable rather
than merely plausible. Trading it for a model would be the wrong trade on
exactly the questions least in need of one.

A reasoning model is reached only for what genuinely falls past those solvers:
a question whose verb matches no exact operation, or one where SymPy declines.
Those are the questions that otherwise cost a screenshot, two independent
vision readings, and the better part of a minute. Facet is handed the
instruction and the exact expressions Ethnos already holds, so nothing is
transcribed and no picture is taken; the answer comes back through the same
validation and the same insertion policy as any other.

A Facet failure at that point is reported as a failure. The deterministic
solvers have already declined, and nothing on the Ethnos side may answer in
their place: a substituted answer would carry a provenance nobody asked for.

### Saying what shape an answer must take

Some Hawkes questions want two answers rather than one: a paired `y = [] or []`
editor, or a single box the question says to fill with comma-separated values.
The add-on already normalises every answer control it supports into one word --
`field`, `option`, `multi`, or `graph` -- and Ethnos reads what that word means
for *this* question, because a single box is still a two-value answer when the
instruction says to separate answers with a comma.

What crosses is the resulting count, as `answer_parts`. Character sets,
templates, slot rules, field ids and the shape word itself stay in the browser,
because none of them change the mathematics. Facet turns the count into a
requirement on its own reply:

```text
This question takes 2 separate answers.
Reply with exactly 3 labelled lines and nothing else, …
FINAL ANSWER: both answers as the page would display them
PART 1: answer number 1 by itself
PART 2: answer number 2 by itself
```

The parts come back as parts, in `answer.parts`. A reply that does not carry
exactly the parts that were asked for, numbered from one and in order, is
refused outright rather than repaired -- by Facet, which asked for the shape,
and again by Ethnos, which is what would type them into real answer fields.

The exact route is deliberately not held to the count. A quartic has four roots
whatever control the page was showing, and that is the mathematics answering
rather than a model failing to follow an instruction.

Facet is never told about fields, editors, or where an answer is going. How
many values a question has is a property of the question; where they are typed
is Ethnos's alone.

## Security properties

- **Constrained SSH.** One fixed argv: `BatchMode` refuses to prompt for a
  credential, `ClearAllForwardings` refuses agent, X11, port and socket
  forwarding, `-T` refuses a terminal.
- **A fixed remote helper.** The argv names `facet-remote` absolutely. It
  contains no shell metacharacters and takes no arguments, so although SSH runs
  a remote command through the login shell, there is nothing there to interpret.
- **The prompt never enters argv.** It travels on standard input on both
  machines, and `facet-remote` executes Facet in-process rather than shelling
  out to a command line.
- **`shell=False`, always.**
- **A closed set of operations.** `generate_text` and `solve_math`, and nothing
  else. No shell command, path, URL, environment, runtime, model, or device can
  be named in a request, on either side, and a `problem` has exactly four
  fields: an instruction, expressions, a count, and a label.
- **No page crosses.** MathML is converted on the Ethnos side and the markup
  itself never leaves it. Nothing about the document, window, tab, frame,
  editor, field or screenshot appears anywhere in a request. Facet has no
  browser API and no way to start a process, and is gated for both.
- **Bounded JSON.** 16 KiB per request, 12 KiB per prompt, 1 MiB per response.
- **The browser chooses an engine and nothing else.** `solveEngine` is an
  enum of two values. Every execution field is rejected by the add-on protocol.
  A browser-supplied request id is reduced to a bounded shape before it crosses.
- **Fail closed.** Status is read before the exit code, so a helper that exits
  zero on failure still cannot produce an answer, and a helper that claims
  success while exiting non-zero is not believed.
- **No silent fallback.** A Facet failure is reported as a failure. It never
  becomes a local Ethnos answer, because a substituted answer would carry a
  provenance nobody asked for.

## Where the host is configured

Ethnos uses `steve@192.168.0.247` as the default LAN SSH target. Set the
`FACET_SSH_TARGET` environment variable to use an optional transport target;
for example, the current `casbox` Tailscale address is `100.105.86.101`, so its
target is `steve@100.105.86.101`. Facet itself is transport-agnostic: neither
address is part of its protocol, validation, or provenance contract.

The Facet side is `src/facet_runtime/remote.py` in the `facet-runtime`
repository, installed as the `facet-remote` executable, with the routing in
`src/facet_runtime/solve.py` and the deterministic solvers in
`src/facet_runtime/exact/`. Ethnos depends on that repository as a sibling
checkout (`../facet-runtime`), so a deployment that updates one must update
both: protocol 2 refuses a protocol 1 helper outright rather than silently
ignoring the fields it does not know.
