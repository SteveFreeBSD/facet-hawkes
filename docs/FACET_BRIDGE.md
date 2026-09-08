# The Ethnos-Facet boundary

Ethnos owns the page. Facet owns the answering. That is the whole relationship,
and it is not the relationship it started as.

```text
Ethnos                                      Facet
  Hawkes/browser logic
  MathML capture and conversion
  window/tab/frame ownership
  answer-shape discovery
  retrieval                --- typed solve request on facet-remote stdin --->
                                              solver routing
                                              exact deterministic mathematics
                                              reasoning model for the rest
                                              parabola / regression plans
                                              CPU / GPU / NPU selection
  structured result        <-- structured answer + provenance -------------
  validation
  keyboard entry, insertion policy,
  Answer Cadence, never-submit
```

## Where these run

Both sides are `casbox`. It is the browser machine, the native-host machine and
the Facet runtime host at once: Firefox, the add-on, the `ethnos` companion,
`facet-remote`, Ollama and the accelerators are all on the one computer.

That is worth stating plainly because the arrangement this replaced said
otherwise. The companion reached Facet with `ssh steve@192.168.0.247
facet-remote` -- casbox's own LAN address -- so every question left casbox for
the network and came back to casbox, through sshd and a login shell. Nothing
was isolated by it; the process boundary that matters is `facet-remote` itself,
and that is a boundary a subprocess draws just as well. The cost was a round
trip and a key per question -- an exact solve measured 363 ms over SSH against
202 ms locally, median of seven -- and a topology that read like evidence of a
second machine. Two documents and a status line described that second machine.

`caspian`, an HP t740, was the earlier host and is where the older baseline
numbers were measured. It is not in this path.

The boundary is unchanged by any of it. Ethnos still hands Facet a question and
reads back an answer with provenance; Facet still decides the route. Where the
helper runs is a deployment fact, and it is [configured in one
place](#where-the-transport-is-configured).

Ethnos used to run the exact solvers itself and ask Facet only about what they
declined. That put the routing decision -- exact mathematics or a reasoning
model, the single most consequential thing about a solve -- on the side that
owns a browser. Facet makes it now. Ethnos hands over a *question*; Facet
decides how it gets answered, answers it, and says which route it took.

Neither reaches into the other. Ethnos never names a device, a model, a runtime,
or a host in a request, and Facet never learns which document, window, frame,
field or editor a question came from -- or that there is a browser at all.

## A note on the two names

"Ethnos" on this page means the browser side of the boundary: this repository,
its `ethnos` Python package, and the native companion the add-on talks to. It
is not what the product is called. The add-on is **Facet Hawkes Assistant**,
and nothing a user reads says Ethnos.

The name survives in the places where changing it would cost a reinstall and
buy nothing anyone can see: the Python package namespace, the add-on ID
`ethnos-hawkes@local` that Firefox keys an installation and its `storage.local`
to, the registered native-messaging host `ethnos_hawkes`, the
`~/.local/share/ethnos-hawkes/` launcher the installer writes, the `ethnos:*`
internal messages, and the wire value `solve_engine="ethnos"` that names the
companion's own image path. Those are identifiers, not branding. Where this
document says Ethnos it is naming a side of a boundary; where it says Facet
Hawkes Assistant it is naming the product.

**`src/ethnos/` is a legacy internal package name, and renaming it is not a
tidy-up.** It is the import path the installed native-messaging launcher names
(`python -m ethnos.hawkes_host`), so a rename is a reinstall of the host
manifest and the launcher, in step, or the add-on stops being able to reach the
companion at all -- and it silently invalidates every reference in these
documents. If it is ever worth doing it is worth doing on its own, deliberately,
with the installer and the manifest in the same change. Do not fold it into
unrelated work.

## One solver, not two

The exact solvers live in `facet_runtime.exact` and are a package dependency of
Ethnos. `ethnos.symbolic_solver` and `ethnos.polynomial_solver` re-export them,
so Ethnos's own local paths -- the image fallback, the coverage sweep and the
CLI -- call the same implementation Facet runs when it routes.

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

A question answered by *completing a table* sends the grid it is completed in,
as a grid. The blanks are numbered as the answer's parts are numbered, so
neither side has to infer which cell a part belongs to, and a cell MathJax
rendered is converted by the same converter the expressions use -- a radical is
drawn rather than written, and its visible glyphs are not the number.

```json
{"answer_table": {"columns": ["x", "y"],
                  "rows": [[{"value": "0"}, {"blank": 1}],
                           [{"blank": 2}, {"value": "2\\sqrt{2}"}],
                           [{"value": "64"}, {"blank": 3}],
                           [{"value": "25"}, {"blank": 4}],
                           [{"blank": 5}, {"value": "-\\sqrt{3}"}]]},
 "answer_representation": {"kind": "signed-integer", "max_length": 4}}
```

This used to be flattened into the instruction, and that was the whole defect.
A grid stated as prose can be read by a model and by nothing else -- so the one
route that could answer the question was the one whose answers cannot be
checked, and a live run returned five values of the right shape and the wrong
mathematics. As structure it is computed from: Facet completes it exactly, and
holds any reasoned answer to it by substitution before that answer counts as
one. Facet renders it into its own prompt on the occasions a model is asked.

The form an answer must take crosses twice, in two registers: as a sentence in
the instruction, which a model reads, and as `answer_representation`, which the
deterministic route filters its solutions by. A requirement only a model can
read is not a requirement anything can check.

The answer boxes themselves stay in the browser. Which *cell* a part belongs to
is a fact about the question; which box it is typed into is not, and no field
id, character set or control rule crosses with it.

A question about *data* sends the same coordinates in place of an expression.
Some questions have no expression to send: nobody wrote the function down, and
it exists only as the fit to the measurements the page states.

```json
{
  "facet_protocol_version": 2,
  "operation": "solve_math",
  "request_id": "ethnos-hawkes-3",
  "problem": {
    "instruction": "Treating revenue as a function of the number of photos sold, ... what number of photos sold and what price per photo will maximize her revenue?",
    "points": [{"x": "4", "y": "224"}, {"x": "5", "y": "260"}, {"x": "12", "y": "288"}],
    "answer_parts": 2
  },
  "constraints": {"accelerator_required": false, "allow_fallback": false}
}
```

A value question is about written expressions or about measured points, never
both and never neither; both sides refuse the other shapes. What crosses is the
coordinates and nothing else -- not the table they were read out of, not its
column headings, and not which column is which. Naming the columns is a reading
of the question, and Ethnos does it in `src/ethnos/hawkes_table.py` before
anything crosses.

A quadratic regression *plan* still sends `"result_kind":
"quadratic_regression"` with the same `points`. The two are different questions
about the same page: one asks for the curve, and comes back as a plan Ethnos
proves before drawing; the other asks where that curve is highest, and comes
back as values. Each result kind takes its own fields and no others: geometry
on a regression, or points on a parabola, is a question about something else
and is refused rather than ignored.

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

## The route is fixed

There is no engine to choose, and the browser is not offered one. A question
the page states as mathematics goes to Facet, always: the add-on sends a
constant, `solve_engine="facet"`, and reads back which route Facet took. The
`solveEngine` preference that used to pick between answering in the companion
and asking Facet is gone. It described a division of labour that stopped
existing when the routing moved, and a browser that offers a choice it cannot
honour is worse than one that offers none. A value left behind in an upgraded
profile is inert -- the schema no longer knows the key, so nothing reads it --
and `migrateSettings()` removes it on the next start.

### The one path that is not Facet

Some Hawkes questions are drawn rather than stated: the mathematics is in a
picture, and the page exposes no MathML to convert. There is nothing for Facet
to route in that case, because there is no expression to route, so those
questions are read by the companion's own image pipeline instead -- two
independent transcriptions by local vision models, compared before anything may
be inserted.

That path is reached only after the Facet request has come back `unsupported`,
so an ordinary question leaves no screenshot and pays no vision-model cost. The
capture is never sent to Facet, which has no reader for one and would refuse it.
On the wire the image path still names itself `solve_engine="ethnos"`, because
that is the value the native protocol has always used for the companion's own
route; it is a retained protocol identifier and not an engine anyone selects.

An answer from that path says so. The panel badges it **Local exact** or
**Local model** rather than naming a Facet route, and the provenance block
records `Facet: not invoked`, because a question Facet never saw must not
inherit its provenance.

### How Facet routes what it is given

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

Some Hawkes questions want more than one answer: a paired `y = [] or []`
editor, a single box the question says to fill with comma-separated values, or
a table of values with a blank cell in each row. The add-on already normalises
every answer control it supports into one word -- `field`, `option`, `multi`,
or `graph` -- and Ethnos reads what that word means for *this* question,
because a single box is still a two-value answer when the instruction says to
separate answers with a comma.

Up to five values cross. The bound was four, sized for `y = [] or []` and the
roots behind it, until lesson 2.1's table of values for `x = y²` published five
blank cells: every gate between the page and Facet refused the fifth, fell back
to "one box", and the question was answered -- exactly, and once. A question
with more parts than the bound is refused whole rather than half-answered.

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

- **A fixed argv, whichever transport.** Local is `facet-remote` and nothing
  else. SSH adds one fixed prefix: `BatchMode` refuses to prompt for a
  credential, `ClearAllForwardings` refuses agent, X11, port and socket
  forwarding, `-T` refuses a terminal.
- **A fixed helper.** The argv names `facet-remote` absolutely. It contains no
  shell metacharacters and takes no arguments, so even on the SSH transport --
  where the remote command is run through a login shell -- there is nothing
  there to interpret. Locally there is no shell in the path at all.
- **One transport per process, chosen before any request exists, and no
  promotion between them.** A local helper that is missing or fails is a
  failure; it never becomes an SSH attempt, and SSH never quietly becomes a
  local run. An answer that crossed a machine boundary nobody chose would carry
  a provenance describing hardware the request was never routed to. An
  unrecognised `FACET_TRANSPORT` is refused rather than defaulted, so a
  misspelled `ssh` cannot silently mean `local`.
- **The same configuration surface either way.** SSH handed the far side a
  fresh login environment, so Facet always ran on its own configured models and
  endpoint. A local subprocess would inherit whatever the browser was started
  with, so every `FACET_*` name is stripped from the child environment. This is
  not cosmetic: an inherited `FACET_OLLAMA_URL` alone is enough to move a solve
  from the GPU to the NPU, changing the provenance without changing a request.
- **The prompt never enters argv.** It travels on standard input, and
  `facet-remote` executes Facet in-process rather than shelling out to a
  command line.
- **`shell=False`, always.**
- **A closed set of operations.** `generate_text` and `solve_math`, and nothing
  else. No shell command, path, URL, environment, runtime, model, or device can
  be named in a request, on either side, and a `problem` carries only what the
  requested result kind takes: an instruction, the mathematics it is about
  (written expressions, or measured coordinates), a count, and a label -- plus
  normalised geometry for a plan. A field that means nothing to the kind being
  asked for is refused, not ignored.
- **No page crosses.** MathML is converted on the Ethnos side and the markup
  itself never leaves it. Nothing about the document, window, tab, frame,
  editor, field or screenshot appears anywhere in a request. Facet has no
  browser API and no way to start a process, and is gated for both.
- **Bounded JSON.** 16 KiB per request, 12 KiB per prompt, 1 MiB per response.
- **The browser chooses nothing.** It names no engine, host, model, or device:
  the pipeline field carries a constant, and every execution field is rejected
  by the add-on protocol. A browser-supplied request id is reduced to a bounded
  shape before it crosses.
- **Fail closed.** Status is read before the exit code, so a helper that exits
  zero on failure still cannot produce an answer, and a helper that claims
  success while exiting non-zero is not believed.
- **No silent fallback.** A Facet failure is reported as a failure. It never
  becomes a local Ethnos answer, because a substituted answer would carry a
  provenance nobody asked for.

## Where the transport is configured

`FACET_TRANSPORT` selects one of two, and there is no third:

| value | what runs | when to use it |
|---|---|---|
| unset, or `local` | `/home/steve/.local/bin/facet-remote` as a subprocess | the normal path, and the default |
| `ssh` | that same helper over `ssh` to `FACET_SSH_TARGET` | Facet genuinely runs on another machine |

Anything else is refused where the client is loaded, before a request is built.

`FACET_SSH_TARGET` defaults to `steve@192.168.0.247` and is read only on the
SSH transport. It is how another host is named -- casbox's Tailscale address,
`steve@100.105.86.101`, reaches this one that way. Facet itself is
transport-agnostic: no address is part of its protocol, validation, or
provenance contract, and an exact solve returns byte-identical provenance
across both transports.

Ask the code rather than this table when it matters. `python3
scripts/observe_live_hawkes.py` prints the chosen transport, its target and the
whole argv under `FACET`, and the companion's `health` operation answers with
it in a moment without loading a model.

Both transports run the same one program, and it is the boundary that counts.
`facet-remote` is installed by `uv tool install` from the `facet-runtime`
repository, into its own isolated environment at
`~/.local/share/uv/tools/facet-runtime/`, with its own interpreter. Ethnos
never imports `facet_runtime.remote` into the companion process to shortcut the
hop: the runtime, process and protocol boundary stays exactly where it was, and
Facet keeps its own dependency set rather than sharing the companion's. (Ethnos
*does* depend on the same repository as a sibling checkout, `../facet-runtime`,
for `facet_runtime.exact` -- one exact solver, not two. That is a library
import, not the solve path.)

The Facet side is `src/facet_runtime/remote.py`, with the routing in
`src/facet_runtime/solve.py` and the deterministic solvers in
`src/facet_runtime/exact/`. A deployment that updates one repository must update
both, and must reinstall the uv tool: protocol 2 refuses a protocol 1 helper
outright rather than silently ignoring the fields it does not know.
