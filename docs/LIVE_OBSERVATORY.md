# Live Hawkes Observatory

One command that gathers, from one clock, enough correlated evidence to
reconstruct a live failure from first observation through solve and insertion
without guessing.

```console
$ python3 scripts/observe_live_hawkes.py --bundle
```

That command deterministically re-execs through `.venv/bin/python` when the
system interpreter lacks QuickJS, because a report that cannot compare the
running build is not a usable observation. If the project interpreter is
missing or incomplete, it refuses with the exact `uv sync --extra dev` repair
instead of quietly reporting the build as uncomparable.

Run it *before* forming a theory about a live failure, and again after a fix so
the two bundles can be compared.

## Why this exists

Every live sweep before it ended the same way: the evidence existed, in six
places, and correlating it was the work. A screenshot said what was on screen; a
diagnostic ring said what the add-on thought; `git status` said what the trees
held; `about:debugging` said nothing at all about which build was loaded; and
the timestamps came from three different clocks.

Twice the conclusion was wrong for the same reason. A temporary add-on was
running code the tree no longer contained, so a fix that had never been loaded
was recorded as a fix that did not work.

## What one run reports

| Section | Answers |
|---|---|
| Header | Local and UTC time from a single reading; `facet-hawkes` and `facet-runtime` HEAD, branch, and uncommitted files |
| Code Firefox is running | The running build's marker against the working tree's, plus any file written since the event page loaded |
| Browser | Every normal Firefox window, which one was chosen, which was active |
| Runs | One block per user operation: target, question, editor, stages, route, runtime, ownership, outcome, failure class |
| Native host | Host processes now, and how a run id maps to a host request |
| Facet | The transport a solve would actually take -- `local` or `ssh`, its target and the whole argv -- then route, model, backend and device for every run that reached a runtime |
| Ollama | Service and runner state, asked only when a run named a runtime |
| Cadence | Timing measurements, only for runs where Cadence performed |
| Retained failures | The bounded ledger of runs that ended badly while nobody was watching |
| Screenshot | Present only when `--screenshot` is given with `--bundle` |

`--bundle` also writes machine-readable `observation.jsonl` — one JSON object
per record, `run` records keyed by run id — beside the human `summary.txt`.

## The run id

`common/log.js` stamps every diagnostic entry with two identifiers.

`gen` is the event page's generation, minted when the page loads. The page is
non-persistent, so `seq` restarts whenever Firefox unloads it; without a
generation, two lifetimes interleave into nonsense, and an operation that
outlived its own event page was indistinguishable from one that did not.

`run` is one user operation, minted in `begin()` and in the settings page's
health check. It is also the native-host `request_id`, as `<run>.<n>` — and
`ethnos.facet_client.safe_request_id` passes it on to Facet unchanged. So one
gesture in the browser, one host request and one Facet run share a name:

```console
$ python3 scripts/read_extension_log.py --grep r2f8xk91c4
$ python3 scripts/observe_live_hawkes.py --run r2f8xk91c4 --json
```

Solving and inserting are two gestures and therefore two runs. The insertion's
pinned snapshot carries the run that produced the answer, reported as
`solved-in=<run>`, so "what changed between the solve and the insertion" is one
lookup rather than an inference from adjacency.

A log written before run ids existed is still read. Its operations are grouped
by adjacency and every one of them is marked `correlated: false`, because
adjacency is a guess and a guess presented as a fact is how two solves in two
windows became one story.

## Which code Firefox is running

`common/build-marker.js` folds the source text of what Firefox actually parsed,
reading it back through `Function.prototype.toString()`. The observer folds the
same symbols off disk, evaluating the modules under QuickJS, and compares.

Reading the package back over its own extension URLs would be the obvious way
and is not available: `scripts/build_extension.py` forbids both the request and
the URL helper, because the add-on promises to make no request and to leave no
profile-unique URL where a page could see one. Neither promise is worth
weakening for a diagnostic.

Verdicts:

- `running-this-tree` — the running build folds to the working tree's marker.
- `running-this-tree-but-edited-since` — it matched, but files have been written
  since the event page loaded. If the add-on has not been reloaded, those edits
  are not live.
- `running-other-code` — Firefox is not running what is on disk. Reload it.
- `unmarked-build` — the running add-on predates this tooling. Reload it to get
  a marker.
- `uncomparable` — the tree's marker could not be computed; the reason is given.

The marker covers the event page's own code and every binding it imports. The
panel, the settings page and the injected content scripts load in other contexts
and are covered by the repository state and file times instead. The report says
so rather than implying more than it proves.

## Failure classes

Each failing run is placed in exactly one class, with the evidence that put it
there. First matching rule wins, so the order is the reading order.

| Class | Means |
|---|---|
| `lifecycle` | The event page turned over mid-run, or the target moved between pinning and writing |
| `safety` | A guard refused to write: the question or answer was no longer the one reviewed |
| `browser` | The page, frame or field could not be reached |
| `evidence` | The question could not be read exactly and the picture path did not rescue it |
| `runtime` | The native companion did not answer |
| `timing` | The work did not finish inside its deadline |
| `capability` | The solver was reached and declined this question |
| `answer-shape` | An answer was produced that this editor will not take |

`answer-shape` is reported for a run that *solved*: the panel shows an answer,
Insert stays disabled, nothing presses anything, and the ring used to record a
clean solve followed by silence.

## Safety boundaries

**It reads.** The profile database on a throwaway copy, the two working trees,
`/proc`, KWin's window list, and Ollama's loopback endpoint. It never launches
Firefox, navigates a tab, or sends the page a keystroke or a click. It never
presses Submit, Check, Next, Skip or Try Similar. `tests/test_live_observatory.py`
asserts the command allowlist, the exact surface it uses on
`inspect_live_firefox`, and that nothing it writes lands outside its own bundle.

**It does not wake the event page.** It sends no port, no message and no
native-messaging connection — the four things that start a suspended event page
— and it polls nothing. What it sees is what the session was doing anyway.

**It records no coursework.** The diagnostic ring redacts answers, displayed
notation, problem text and screenshots to their shapes before storage; see
[the privacy notice](../extension/PRIVACY.md). Everything in a bundle except a
screenshot inherits that. A screenshot is coursework: it needs `--screenshot`
*and* `--bundle`, is written `0600` into a `0700` directory, and the command
prints the `rm -rf` that removes it. **Delete the bundle after reading it.**

## When nobody was watching

Everything above assumes the session is still there. A refusal from an hour ago
has had the entries explaining it pushed out of the ring by ordinary use, so
this command answers about it only by accident.

The add-on therefore keeps its own bounded ledger of runs that ended in a
diagnostic terminal state, and one offline command reads it back grouped by
fault:

```console
$ python3 scripts/triage_hawkes_failures.py
```

This report names the ledger's shape under **Retained failures**; that command
is where a failure is actually triaged. See
[Retained failure ledger](FAILURE_LEDGER.md).

## Known blind spots

- The event-page build marker does not cover the panel or settings page. Their
  staleness shows only as `changed_since_event_page_loaded`. The Hawkes
  question content script has its own whole-source marker in every reader
  decision, which the observatory compares to the checked-out source.
- Stage transitions are logged at `debug`, which is off by default. The trail is
  reported once, on the entry that ends the run, and a run that never ends
  leaves none — but a run that *ends badly* now carries its whole trail into a
  retained record, whatever the log level.
- Nothing correlates a Facet run on the far side of `facet-remote` beyond the
  request id. The observer reports what the host said it did, not an independent
  reading of the helper -- which is a process boundary on the default local
  transport and a machine boundary on the SSH one. The `FACET` record names
  which, with the argv, so at least the topology is not left to be assumed.
- A screenshot is of the window, not of the frame the run targeted.

## See also

- [Retained failure ledger](FAILURE_LEDGER.md) — triaging failures after the fact
- [Hawkes live findings](history/HAWKES_LIVE_FINDINGS.md) — historical: what the
  2026-09-03 session exposed on 0.39.0
- [Hawkes development flow](HAWKES_DEVELOPMENT_FLOW.md) — where this fits
- [Ollama troubleshooting](OLLAMA_TROUBLESHOOTING.md) — when the runtime is the fault
