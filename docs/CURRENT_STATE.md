# Current state

One page, for an agent or a maintainer arriving with no context. Everything
below is true of the system as it stands; anything that is not is in
[the historical record](history/README.md).

**Last consolidated:** 2026-09-08, at facet-hawkes `b8d9591` / facet-runtime
`6a337c4`.

## What this is

**Facet Hawkes Assistant** is a local-first Firefox add-on for Hawkes
mathematics. It reads the question the page states, gets it answered exactly
where that is possible, shows what it read beside what it solved, and places
the answer into the focused answer box on a separate, deliberate click. It
never submits, checks, advances or silently selects.

The same repository also holds a local PDF study and quiz engine. That is a
second, older product surface with its own commands and its own documents; it
does not participate in a Hawkes solve.

## Where everything runs

**One machine, `casbox`.** Firefox, the add-on, the `ethnos` native host,
`facet-remote`, Ollama and the accelerators are all on it, and a solve crosses
no network. The companion reaches Facet by running
`/home/steve/.local/bin/facet-remote` as a **local subprocess** and writing one
request to its standard input.

SSH exists only as `FACET_TRANSPORT=ssh`, for a Facet that genuinely runs
elsewhere. It is never a fallback in either direction. Until 2026-09-08 the
local path went `ssh steve@192.168.0.247 facet-remote` — `casbox`'s own address
— so every question left the machine and came straight back; if you find
yourself reasoning about "the remote machine", you are reading something from
before that.

`caspian` is a **historical** host. It is not in the live path.

→ [Runtime, models and deployment](RUNTIME_AND_DEPLOYMENT.md)

## Who owns what

| Side | Owns |
|---|---|
| **facet-hawkes** (this repo) | Firefox and Hawkes reading, MathML capture, window/tab/frame ownership, answer-shape discovery, answer contracts, insertion policy, graphs, Answer Cadence, never-submit |
| **facet-runtime** (`../facet-runtime`) | Solver routing, exact deterministic mathematics, the reasoning model, the parabola and regression specialists, CPU/GPU/NPU selection |

The companion hands over a *question* and reads back an answer with
provenance. It never names a device, a model, a runtime or a host; Facet never
learns there is a browser at all. Facet is imported as a **path dependency**,
so the two repositories move together — see [the pin](#the-runtime-pin).

→ [The Ethnos-Facet boundary](FACET_BRIDGE.md)

## The names

The product is **Facet Hawkes Assistant**. Nothing a user reads says Ethnos.

`ethnos` survives as a set of *internal compatibility identifiers*. Every one
below was checked against the running installation during this consolidation
and is deliberately retained. **Do not rename them as a tidy-up**; each is a
coordinated reinstall or a data loss, and none is shown anywhere a user reads.

| Identifier | Where it is | Why it stays |
|---|---|---|
| `ethnos-hawkes@local` | `extension/manifest.json` | Firefox keys the installation *and its `storage.local`* to this. Changing it orphans the profile: settings, the diagnostic ring and the failure ledger all go with it. |
| `ethnos_hawkes` | `extension/background.js`, `~/.mozilla/native-messaging-hosts/ethnos_hawkes.json` | The registered native-messaging host, already written to disk. Renaming means every install re-runs the installer before the add-on can reach anything. |
| `~/.local/share/ethnos-hawkes/` | written by `deploy/firefox/install_native_host.py` | The launcher directory the manifest above points at. It moves only with that manifest. |
| `src/ethnos/`, `python -m ethnos.hawkes_host` | the package, and the installed launcher's exec line | The launcher runs this module by name. Renaming the package is a coordinated change to the launcher and the manifest, and belongs in a change of its own. |
| `ethnos:panel`, `ethnos:state`, `ethnos:solve`, `ethnos:diagnostics`, … | `extension/popup/`, `options/`, `background.js`, `common/log.js` | Internal port names, message types and a Web Locks name. Private to the add-on, and `ethnos:diagnostics` is the lock the whole origin shares. |
| `solve_engine="ethnos"` | `src/ethnos/hawkes_protocol.py` | A native-protocol wire value naming the companion's own image path, beside `"facet"`. Changing it is a protocol change on both sides for no reader's benefit. |
| `ETHNOS_*` environment variables | `src/ethnos/config.py`, `.env.example` | The study engine's configuration surface. Facet's own variables are `FACET_*` and are separate. |
| `errorEthnosUnreachable`, `errorEthnosTimeout`, `errorEthnosVersion` | `extension/_locales/en/messages.json` | Message *keys*, not message text. Every string they resolve to says "Facet". |
| `ethnos-caspian` git remote | `git remote -v` | Legacy history on the old host. Kept as an archive; not a publication target. |

`ethnos` in `facet_runtime/prompts.py`'s `CONSUMER_VOCABULARY` is the opposite
case: it is a *forbidden* word there, one of the terms a prompt may not contain.
It must stay for that reason.

The full list with the release rationale is also in
[`extension/RELEASE.md`](../extension/RELEASE.md).

Facet is the solver. Old Ethnos/caspian/two-machine/SSH-default descriptions
are historical.

## What it can answer, and what it can enter

A family is not finished when Facet returns the right value — it is finished
when the add-on can *enter* that value, or when the table says plainly that it
cannot. Every exact answer carries `answer.form` (`scalar`, `ordered-pair`,
`parts`, `choice`) beside `entry_mode`, and `tests/test_answer_capabilities.py`
fails until a new form has a row.

Live-proven today: scalar integers and rationals, rationals through the page's
own slash where no template is offered, radicals, rational exponents, named
phrases, ordered pairs with integer and with rational components, multipart
scalars, comma answers in one box, table cells including fractions, radio-group
choices, and both graph plan families.

Offline, the exact solver sweep stands at **36/36 answered exactly, 1 correctly
declined — 0 wrong, 0 unrecognized**:

```console
$ uv run ethnos hawkes-coverage
```

→ [Answer capabilities](ANSWER_CAPABILITIES.md) is the authority for the
answer-shape and entry coverage map, including the compositions that are
deliberately unsupported.

## Answer Cadence

Current supported architecture, not experimental debris. The answer itself is a
deterministic score: one clock drives when each character is typed, when the
playhead moves, what the panel says and what you hear. A note exists because a
character was accepted, so if Hawkes refuses one the music stops with it.
Insertion music is off unless it is turned on, and it adds no permission,
sample, model or network dependency.

→ [Answer Cadence](ANSWER_CADENCE.md)

## Working on it safely

Two browser modes, not interchangeable: the owner's normal Firefox (mode A, for
any claim about the real session or the signed artifact) and an isolated
headless Marionette profile (mode B, for development). Start every live
investigation with one command:

```console
$ python3 scripts/observe_live_hawkes.py --bundle
```

If the failure is not on screen now, read back what accumulated instead:

```console
$ python3 scripts/triage_hawkes_failures.py
```

**Hard limits.** Never handle school or Hawkes credentials. Never press Hawkes
Submit, Check, Next or Skip, and never make the extension press them — that
spends a graded attempt. Do not navigate the tab holding the question under
investigation, restart the owner's Firefox, or change their profile. Delete
Hawkes screenshots after reading them; a bundle prints its own `rm -rf`.

→ [Hawkes development flow](HAWKES_DEVELOPMENT_FLOW.md),
[Live Hawkes Observatory](LIVE_OBSERVATORY.md),
[Retained failure ledger](FAILURE_LEDGER.md), and `AGENTS.md`

## The runtime pin

`deploy/facet-runtime.pin` names the facet-runtime commit this checkout
requires, and is the only place it is decided. CI reads it;
`tests/test_runtime_pin.py` holds every document that quotes it to the same
value and fails if the sibling checkout is behind.

The pinned commit is **published** as of 2026-09-08. See *Where the code is
published* below for which branch, and why the default one is not it.

→ [Runtime, models and deployment](RUNTIME_AND_DEPLOYMENT.md#the-runtime-pin)

## Where the code is published

Both repositories follow the same rule, and it is the opposite of the usual
one:

| Branch | What it is |
|---|---|
| `main` | **frozen release baseline.** `facet-hawkes` `66c2325`, `facet-runtime` `f2e0907`. Kept as the last published checkpoint; not advanced by ordinary work |
| `feature/live-hawkes-next-slice` | **the current hardened system**, in both. This is what every document here describes |

So a default clone lands on neither the code these documents describe nor, in
`facet-runtime`'s case, a tree this checkout can import — `f2e0907` predates
`ANSWER_FORMS`. **Check out the branch, and detach the runtime at the pin.**
The install instructions in the [README](../README.md) and the [migration
checklist](MIGRATION.md) both do this; following them by hand and skipping the
checkout step is the one way to get a broken pair.

Verified on 2026-09-08 by doing it: both repositories cloned from their public
URLs, `facet-hawkes` on the branch, `facet-runtime` detached at the pin, then
`uv sync --frozen --extra dev` and the whole CI sequence — 1720 tests, lint,
format, compileall, vulture, the package build and the offline solver sweep,
all passing. That was the audit ledger's last outstanding fresh-clone gate.

## Release position

Add-on **0.46.0**, an unsigned candidate. It has passed the package,
repository, Mozilla-lint, reproducibility and clean-profile gates, but the
source line has moved since that audit and no external publication action is
authorized. Signing and signed-artifact physical acceptance remain later
external gates.

→ [Release audit ledger](HAWKES_RELEASE_AUDIT.md),
[Firefox release runbook](../extension/RELEASE.md)

## Known stale spots, deliberately left

- The **study engine** documents ([Migration](MIGRATION.md), [Ollama
  troubleshooting](OLLAMA_TROUBLESHOOTING.md), [Pre-calculus](PRECALCULUS.md),
  [Vision and exact math](VISION_MATH_ARCHITECTURE.md), [Agent
  review](AGENT_REVIEW.md)) carry `caspian`-era procedure. Each now says so at
  the top. They are not in the Hawkes path and were not rewritten from
  measurements nobody has re-taken.
- `ethnos precalc-bench` still defaults to `--model precalc-local`, an alias
  that exists only on `caspian`. Pass `--model` explicitly on this host.
- No current multiple-choice acceptance figure exists. The old one belongs to
  `caspian`'s model alias and is not restated anywhere as current.

## Checking all of this

Everything above is confirmable offline, in about a minute, with no browser and
no model call: [Verification checklist](VERIFICATION_CHECKLIST.md).

## The whole map

→ [Documentation index](README.md)
