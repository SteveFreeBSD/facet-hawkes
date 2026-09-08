# Project operating rules

## Where this project is right now

Focused debugging and development on the Hawkes add-on and its solver. The
owner is usually sitting in front of a live Hawkes practice question while the
work happens, and expects an agent to go and look at it rather than reason
about it from a distance.

These rules are written to get you to the evidence quickly. Everything that is
still forbidden below is forbidden for a stated reason; if a reason no longer
applies, say so rather than working around it silently.

## Where things run, and what things are called

**One machine: `casbox`.** Firefox, the add-on, the `ethnos` native host,
`facet-remote`, Ollama and the accelerators are all on the computer you are
sitting at. There is no second host in the live path, and a solve crosses no
network.

The companion reaches Facet by running `/home/steve/.local/bin/facet-remote`
as a local subprocess and writing one request to its standard input. That
helper is the runtime, process and protocol boundary, and it stays one: it is
its own `uv tool` installation with its own interpreter, and the companion
never imports `facet_runtime.remote` to skip the hop.

Until 2026-09-08 this went `ssh steve@192.168.0.247 facet-remote` -- casbox's
own address -- so every question left the machine and came straight back to it.
SSH is still there, as `FACET_TRANSPORT=ssh`, for a Facet that genuinely runs
elsewhere. It is never fallen back to, in either direction. If you find
yourself reasoning about "the remote machine", check first:

```console
$ python3 scripts/observe_live_hawkes.py --bundle    # the FACET record names the transport
```

`caspian` is a *historical* host. Documents that describe it as the primary
workstation are describing the past.

**`src/ethnos/` is a legacy internal package name.** So are the add-on ID
`ethnos-hawkes@local`, the native-messaging host `ethnos_hawkes`, and the
`ethnos:*` internal messages. The product is Facet Hawkes Assistant; nothing a
user reads says Ethnos. Do not rename the package as a tidy-up -- the installed
launcher runs `python -m ethnos.hawkes_host`, so it is a coordinated reinstall
of the manifest and the launcher, and it belongs in a change of its own.
[The Ethnos-Facet boundary](docs/FACET_BRIDGE.md) is the reference for all of
this.

## Looking at the live session

**Start here, before forming a theory.**

```console
$ python3 scripts/observe_live_hawkes.py --bundle
```

One command, one clock. It reports which build Firefox is actually running,
both repositories' state, the window/tab/frame each operation targeted, what
the add-on thought the question and editor were, the stages it passed through,
which runtime and device answered, what changed between solve and insertion,
and which of eight kinds of failure this was -- as a human summary beside a
machine-readable `observation.jsonl`. It reads only; it never drives the
browser, and it cannot wake a suspended event page.

Use that command exactly even when system Python has no QuickJS: it
deterministically re-execs through `.venv/bin/python` for the build comparison,
or explains how to restore the project interpreter if it cannot.

Add `--screenshot` when a picture would settle something. That needs `--bundle`,
writes 0600, and prints the command that deletes it -- a Hawkes page is
coursework. Add `--match` with part of a window title when several Firefox
windows are open, and `--run <id>` to isolate one operation.

Read [Live Hawkes Observatory](docs/LIVE_OBSERVATORY.md) once; it explains the
run id, the build marker and the failure classes. The two tools below remain
worth reaching for directly when you already know what you are looking at.

## Looking at failures nobody was watching

**If the failure is not on screen right now, start here instead.**

```console
$ python3 scripts/triage_hawkes_failures.py
```

The owner uses Hawkes with nothing attached. A run that fails, is refused, or
produces an answer the editor will not take leaves one bounded record behind,
and this reads them back offline -- grouped by fault, ordered so the one worth
your afternoon is first, classified by the same eight rules the observatory
uses. Firefox does not have to be running and this touches nothing at all.

```console
$ python3 scripts/triage_hawkes_failures.py --group f1:<fingerprint>
$ python3 scripts/triage_hawkes_failures.py --export f1:<fingerprint>
```

`--group` prints one fault in full, including the page's own description of the
answer control that refused it -- which is what a diagnosis of a refused
insertion actually needs, and which used to cost a screenshot of the owner's
coursework to guess at. `--export` writes a sanitized bundle and prints its
`rm -rf`. Read [Retained failure ledger](docs/FAILURE_LEDGER.md) once.

The ledger holds no coursework and never will; it is bounded to 40 records,
64 groups, 14 days and 96 KB, and evicts the oldest by itself.

`scripts/inspect_live_firefox.py` reads the owner's running
Firefox: it enumerates windows through KWin, can briefly focus one, captures it
with Spectacle, and restores whatever was active before. It never launches
Firefox, opens a URL, or sends input to the page.

```console
$ python3 scripts/inspect_live_firefox.py status
$ python3 scripts/inspect_live_firefox.py inspect
$ python3 scripts/inspect_live_firefox.py inspect --match hawkes
```

Several Firefox windows open at once is normal. Use `--match` with a substring
of the window title to say which one you mean; without it the command needs
exactly one Firefox window and will list the captions it found so you can pick.

Screenshots of a Hawkes page are coursework. Inspect them locally and delete
them when you are done.

Reading the add-on's own diagnostic log is often faster than a screenshot and
touches nothing at all:

```console
$ python3 scripts/read_extension_log.py --last 60
$ python3 scripts/read_extension_log.py --grep insert --level warn
```

It decodes `storage.local` from a throwaway copy of the profile database, so it
is safe while Firefox is running.

## Driving the browser

The owner controls Hawkes navigation. Do not restart or close their Firefox,
switch their profile, or navigate the tab holding the question under
investigation — losing that question mid-diagnosis costs more than the
inspection was worth. Ask if you need a different question on screen.

Beyond that, go ahead: focus a window to capture it, re-run a solve, read the
DOM, capture markup, open the panel, exercise the add-on. That is the work.

`scripts/live_browser.py` and `scripts/run_extension_harness.py` drive a
separate throwaway profile and run headless. They may be used while the owner's
session is open — they are a different browser and cannot reach it. Label their
results as isolated-harness evidence: they prove the code works, not that the
signed artifact works in the owner's normal profile, which is a separate claim
needing mode A.

## Hard limits

- **Never handle school or Hawkes credentials.** If a signed-in page is needed
  and there is not one, ask the owner to sign in.
- **Never press Hawkes Submit, Check, Next, or Skip**, and never make the
  extension press them. Those spend a graded attempt on the owner's coursework.
  Solving and inserting on request are fine; committing an answer is theirs.
- **Do not infer an authentication route from browser history.** The owner logs
  in to Hawkes directly — not through Canvas, a school portal, CAS/SSO, or an
  LMS redirect. Do not open Canvas URLs to start a test.
- **Delete Hawkes screenshots after reading them.** An observatory bundle
  prints its own `rm -rf`; run it. A triage bundle prints one too, and never
  contains a screenshot.

## Working notes

- While a panel says Solving, the work is in flight: look at the native-host
  process and wait. Clicking again cancels it — that control is Cancel while a
  solve is running.
- A fix that "did not work" is a stale build until the observatory says
  otherwise. `about:debugging`'s Reload re-reads whichever directory was first
  selected, and a temporary add-on's version never moves; the marker is what
  tells the two apart. Two afternoons went into this before it existed.
- Prefer the offline gates before reaching for a browser. `tests/` runs the
  panel decision under QuickJS, the coverage sweep answers "would this question
  have gone to a model?" in about a second, and both catch more than a
  screenshot does.
- You do not need to sit and watch for a failure any more, and should not.
  Ask the owner to work normally, then triage what accumulated. A failure
  caught live and a failure read back an hour later carry the same evidence.
- "Zero footprint" means no persistent extension-created state or UI in the
  visited website. It is not a claim of undetectability; see
  `extension/README.md` and `extension/PRIVACY.md`.
