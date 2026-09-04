# The Ethnos-Facet boundary

Ethnos asks Facet to execute one bounded intelligence request and to say what
it did. That is the whole relationship.

```text
Ethnos (caspian)                            Facet (currently casbox)
  Hawkes/browser logic
  MathML and exact solvers
  retrieval
  prompting                --- typed request over SSH stdin --->
  answer interpretation                       model execution
  keyboard entry and                          CPU / GPU / NPU selection
  insertion policy                            model and runtime selection
                           <-- typed result + provenance ------  metrics and evidence
                                                                 explicit failure
```

Ethnos owns the question. Facet owns the run. Neither reaches into the other:
Ethnos never names a device, a model, a runtime, or a host in a request, and
Facet never learns that the request came from a Hawkes page.

## The request

`src/ethnos/facet_client.py` is the only place in Ethnos that speaks to Facet.

```json
{
  "facet_protocol_version": 1,
  "operation": "generate_text",
  "request_id": "ethnos-hawkes-1",
  "prompt": "…",
  "constraints": {"accelerator_required": true, "allow_fallback": false}
}
```

A constraint is a *need*, not a device. `accelerator_required` says the work
must not land on a CPU; which accelerator satisfies that is Facet's decision.
This is what keeps the contract stable when Facet later gains a real router:
the request already says what Ethnos requires rather than what Facet should do.

A request is validated on both sides before anything runs. An unknown field, an
unknown constraint, a wrong type, a wrong version, an unlisted operation, or
more than 16 KiB is refused.

## The response

Success carries the whole runtime result, provenance included:

```json
{
  "facet_protocol_version": 1,
  "status": "ok",
  "request_id": "ethnos-hawkes-1",
  "operation": "generate_text",
  "result": {
    "text": "…", "requested_backend": "gpu", "actual_backend": "gpu",
    "runtime": "Ollama 0.33.2", "model": "gpt-oss:20b",
    "device": "AMD Radeon 890M Graphics (RADV STRIX1)",
    "elapsed_ms": 8533.637, "fallback": false,
    "metrics": {"prompt_tokens": 147, "generated_tokens": 69,
                "prefill_tps": 229.38, "decode_tps": 21.88},
    "evidence": {"source": "ollama /api/ps", "loaded_bytes": 12748786236,
                 "device_memory_bytes": 12748786236,
                 "device_resident_fraction": 1.0}
  }
}
```

Failure carries a reason and no answer:

```json
{"facet_protocol_version": 1, "status": "error", "request_id": "ethnos-hawkes-1",
 "error": {"kind": "constraint_unsatisfied", "message": "no Facet accelerator is available"}}
```

`kind` is one of `invalid_request`, `unsupported_version`,
`unsupported_operation`, `constraint_unsatisfied`, `execution_failed`, or
`internal_error`.

Ethnos requires every named field and rejects a missing or mistyped one, because
each is a provenance claim. It ignores fields it does not recognise, and passes
`metrics` and `evidence` through whole: a later Facet may measure more than this
client knows how to read, and that is a compatible change rather than a failed
solve. Adding a request field, an operation, or a constraint is not compatible
and moves the version.

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
- **A closed set of operations.** `generate_text` is the only one. No shell
  command, path, URL, environment, runtime, model, or device can be named in a
  request, on either side.
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

The Facet side is `src/facet_runtime/remote.py` in the `facet-runtime` repository,
installed as the `facet-remote` executable.
