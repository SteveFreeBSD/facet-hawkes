# Project operating rules

## Where this project is right now

Focused debugging and development on the Hawkes add-on and its solver. The
owner is usually sitting in front of a live Hawkes practice question while the
work happens, and expects an agent to go and look at it rather than reason
about it from a distance.

These rules are written to get you to the evidence quickly. Everything that is
still forbidden below is forbidden for a stated reason; if a reason no longer
applies, say so rather than working around it silently.

## Looking at the live session

Start here. `scripts/inspect_live_firefox.py` reads the owner's running
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
- **Delete Hawkes screenshots after reading them.**

## Working notes

- While a panel says Solving, the work is in flight: look at the native-host
  process and wait. Clicking again cancels it — that control is Cancel while a
  solve is running.
- Prefer the offline gates before reaching for a browser. `tests/` runs the
  panel decision under QuickJS, the coverage sweep answers "would this question
  have gone to a model?" in about a second, and both catch more than a
  screenshot does.
- "Zero footprint" means no persistent extension-created state or UI in the
  visited website. It is not a claim of undetectability; see
  `extension/README.md` and `extension/PRIVACY.md`.
