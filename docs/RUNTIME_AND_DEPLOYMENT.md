# Runtime, models and deployment

What runs, where it runs, which model answers, and what has to be reinstalled
when either repository moves. This is the current state of the machine; the
*shape* of the boundary is [the Ethnos-Facet boundary](FACET_BRIDGE.md), and
older measurements belong to [the historical
record](history/README.md).

## One machine

**`casbox`** is the whole live system. Firefox, the add-on, the `ethnos` native
host, `facet-remote`, Ollama and the accelerators are all on the computer the
owner is sitting at, and a solve crosses no network.

| Piece | What it is |
|---|---|
| CPU | AMD Ryzen AI 9 HX 370, 12 Zen 5 cores |
| GPU | Radeon 890M, reached through Vulkan/RADV, 14.8 GiB GTT aperture |
| NPU | XDNA2, reached through `amdxdna`, XRT and FastFlowLM |
| Browser | Firefox; the add-on requires 142 or newer |
| Python | 3.12 or newer, matching `requires-python` in `pyproject.toml`. CI runs 3.12 and 3.14 |
| Model server | Ollama on loopback, `http://127.0.0.1:11434` |

`caspian`, an HP t740, is a **historical** host. Every figure measured there
lives under [`history/`](history/README.md) and describes neither this machine
nor its models.

## The transport

The companion reaches Facet by running

```text
/home/steve/.local/bin/facet-remote
```

as a **local subprocess** and writing one request to its standard input. That
helper is the runtime, process and protocol boundary, and it stays one: it is
its own `uv tool` installation with its own interpreter, and the companion
never imports `facet_runtime.remote` to skip the hop.

| `FACET_TRANSPORT` | What it runs | When |
|---|---|---|
| unset or `local` | that helper directly, with a fixed one-element argv | **the default**, and what every live solve uses |
| `ssh` | that same helper over `ssh` to `FACET_SSH_TARGET` | a Facet that genuinely runs on another machine |

Neither is ever fallen back to. A local transport that fails raises; it never
becomes an SSH attempt, and SSH never quietly becomes a local one. An
unrecognised `FACET_TRANSPORT` fails before a request is built, so a misspelled
`ssh` cannot silently mean `local`. The local transport strips `FACET_*` from
the child environment, so both transports hand Facet the same configuration
surface. See [the transport
configuration](FACET_BRIDGE.md#where-the-transport-is-configured) for the
security properties.

### Checking which transport a solve would take

Do not assume it; the failure this arrangement replaced was a topology nobody
was checking any more.

```console
$ python3 scripts/observe_live_hawkes.py --bundle    # the FACET record names it
```

```text
FACET
  transport local  -> this machine  /home/steve/.local/bin/facet-remote
```

One request end to end, without the browser:

```console
$ echo '{"facet_protocol_version": 2, "operation": "solve_math",
         "request_id": "probe-1",
         "problem": {"instruction": "Simplify.", "expressions": ["(x+1)*(x-1)"],
                     "answer_parts": 1}}' | /home/steve/.local/bin/facet-remote
```

An installed helper older than the client refuses with `unsupported_version`
rather than answering part of the request. That is the right failure and it is
easy to mistake for a transport problem — reinstall before diagnosing further.

## Which model answers what

Two separate assignments, for two separate jobs. Neither is a generic
recommendation for another machine.

### Facet — solving and reasoning

Declared once in `facet-runtime/src/facet_runtime/models.py`; `facet models`
prints the table. Exact mathematics reaches no model at all and reports
`actual_backend: null` rather than claiming a processor it did not use.

| Backend | Role | Runtime | Model | Budget |
|---|---|---|---|---|
| GPU | text | Ollama | `gpt-oss:20b` | 2048 output tokens, `low` reasoning effort |
| NPU | text | FastFlowLM | `gpt-oss:20b` | 2048 output tokens, no effort control exposed |
| CPU | text | Ollama | `qwen3.5:2b` | 768 output tokens |
| GPU | vision | Ollama | `qwen3.5:9b` | 512 output tokens |
| NPU | vision | FastFlowLM | `qwen3.5:9b` | 512 output tokens |

`gpt-oss:20b` reasons unconditionally and spends those tokens out of the output
budget ahead of the answer, so the effort and the budget only mean anything
together. Every run reports `stop_reason` and `output_token_limit`, and an empty
completion says whether the budget ran out or the model returned nothing —
those need opposite fixes. Each assignment can be overridden for an experiment
through its own variable (`FACET_GPU_TEXT_MODEL` and friends), which changes the
model but never the device.

### The companion — reading and studying

Defaults come from `src/ethnos/config.py`; `.env.example` is a template and is
**not** loaded automatically.

| Job | Model | Setting |
|---|---|---|
| Text and agent work | `qwen3.5:9b` | context `4096`, thinking disabled, thread count unset |
| Image question, first reader | `qwen3.5:4b` | `ETHNOS_OLLAMA_VISION_MODEL` |
| Image question, second reader | `qwen3.5:9b` | `ETHNOS_OLLAMA_VISION_VERIFIER_MODEL` |

The two readers are *different models on purpose*, so one cannot merely repeat
its own symbol mistake; insertion is disabled when they disagree about a sign,
exponent, radical or fraction.

There is no current acceptance figure for multiple-choice accuracy. The one
that used to be quoted was measured on `caspian` against a model alias that
exists only there, and it says nothing about the models above. The benchmark
needs re-running before any number is quoted as current.

## Deploying a change

### Facet — after any change to the runtime

`facet-remote` on this host is a `uv tool` install, **not** the working tree, so
a change to solving, routing, a prompt or the protocol reaches the add-on only
after:

```console
$ cd ../facet-runtime
$ uv tool install --force --reinstall .
```

Then re-run the probe above. A protocol change additionally requires both sides
to move together.

### The companion — after a change to the native host

The installed launcher runs `python -m ethnos.hawkes_host` out of this
checkout, so ordinary Python changes are live at the next solve. Registration
itself changes rarely:

```console
$ python3 deploy/firefox/install_native_host.py --write
$ python3 deploy/firefox/install_native_host.py --check
```

`--check` proves all three things separately — the launcher, the manifest
Firefox reads, and one native-messaging health round trip:

```text
ok: /home/steve/.local/share/ethnos-hawkes/ethnos-hawkes-host
ok: /home/steve/.mozilla/native-messaging-hosts/ethnos_hawkes.json
ok: native messaging health round trip
```

Restart Firefox after installing or changing the native host.

### The add-on — after a change to `extension/`

A temporary add-on's version never moves, and `about:debugging`'s Reload
re-reads whichever directory was first selected, so "the fix did not work" is a
stale build until the observatory's build marker says otherwise. Permanent
installation into a normal profile needs a Mozilla-signed XPI; follow the
[release and installation runbook](../extension/RELEASE.md) and do not weaken
Firefox's signature enforcement.

## The runtime pin

Facet is a **path dependency** at `../facet-runtime`, so a runtime older than
this checkout requires is not a slower system — it is a missing symbol at
import time.

`deploy/facet-runtime.pin` holds that commit and is the only place it is
decided. CI reads the file, and `tests/test_runtime_pin.py` fails if the README,
the migration checklist, the release runbook or the audit ledger names a
different one, or if the sibling checkout is behind it.

```console
$ grep -v '^#' deploy/facet-runtime.pin          # the commit, and nothing else
$ git -C ../facet-runtime checkout --detach <that commit>
```

Raise the pin in the same change that starts depending on something newer. The
literal commit is repeated in the README, the migration checklist and the
release runbook, because a first clone needs a command it can paste; every one
of those is held to this file by the test.

**Publication note.** The pinned commit **is** published, as of 2026-09-08. It
is reachable from `SteveFreeBSD/facet-runtime`'s
`feature/live-hawkes-next-slice` branch, so the clone-and-detach above works
from public URLs and CI's checkout by object name resolves. That branch is also
what publishes it: `main` there is still `f2e0907`, which predates
`ANSWER_FORMS`, so a clone that stops at the default branch gets a runtime this
checkout cannot import. **Detaching at the pin is not optional.**

The *pair* is still not publicly reproducible: `SteveFreeBSD/facet-hawkes`'s
`main` is well behind this work, so the fresh-clone proof in the [audit
ledger](HAWKES_RELEASE_AUDIT.md) cannot be run end to end from public URLs yet.
Publishing the runtime was the first step of that sequence and is done; the
Hawkes side is not.

## Foundation checks

```console
$ vulkaninfo --summary                      # GPU driver
$ curl http://127.0.0.1:11434/api/version   # Ollama service
$ ollama ps                                 # what is resident, and where
$ xrt-smi examine                           # NPU driver and XRT
$ flm validate --json                       # FastFlowLM
```

If a model is missing, CPU-only, empty, truncated or unstable, stop and use
[Ollama Troubleshooting](OLLAMA_TROUBLESHOOTING.md).

## See also

- [The Ethnos-Facet boundary](FACET_BRIDGE.md) — what each side owns, and why
- [Current state](CURRENT_STATE.md) — the whole system in one page
- [Answer capabilities](ANSWER_CAPABILITIES.md) — what can be answered and entered
- [Migration checklist](MIGRATION.md) — reproducing the study engine elsewhere
- [Historical record](history/README.md) — measurements that belong to `caspian`
