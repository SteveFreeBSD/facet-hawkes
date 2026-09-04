# Hawkes extension development flow

There are two browser modes. They are not interchangeable.

## A. Existing normal Firefox — default for live work and release acceptance

Use this mode when the owner says Hawkes is open, is answering practice
questions, or asks to test the Mozilla-signed extension. It uses the owner's
already-running normal Firefox and direct Hawkes login.

The owner:

1. Signs in directly to Hawkes.
2. Opens the intended practice question.
3. Controls Hawkes navigation and submission.

The agent begins with one command:

```console
$ python3 scripts/inspect_live_firefox.py inspect
$ python3 scripts/inspect_live_firefox.py inspect --match hawkes
```

That command:

- picks the Firefox window to look at — `--match` names it by a substring of
  its title, and without that it needs exactly one window and lists the
  captions it found so you can choose;
- confirms the installed extension version, enabled state, and signing state;
- briefly focuses that window, captures only it through KDE Spectacle, and
  restores the previously active window;
- reports whether the native host is currently running;
- never launches Firefox, opens a URL, changes a profile, reads browser
  history, or sends input to Hawkes.

The owner having several Firefox windows open is normal and is not a reason to
stop; name the one you mean. Ambiguity still fails closed, because focusing and
photographing the wrong window is both useless and an intrusion.

For the insertion presentation contract, use [Answer Cadence](ANSWER_CADENCE.md)
as the source of truth. Cadence begins only after the answer and target have
been validated, changes timing only, and keeps synthetic events and
MAIN-world editor calls observable.

Inspect the reported PNG locally, then delete it because it contains
coursework. Use `status` when no screenshot is needed and `shot` for another
visual check:

```console
$ python3 scripts/inspect_live_firefox.py status
$ python3 scripts/inspect_live_firefox.py shot
```

Often no screenshot is needed at all. `scripts/read_extension_log.py` decodes
the add-on's own diagnostic ring out of a throwaway copy of the profile
database, which is safe while Firefox is running and says more about a failed
solve than a picture does.

The live loop is deliberately short:

1. Capture the current question and panel.
2. Verify that the recognized problem and proposed answer match the screen.
3. If the panel is solving, correlate it with the native-host process; do not
   start another solve.
4. The owner presses **Insert answer**. Nobody presses Hawkes Submit/Check/Next
   as part of extension acceptance.
5. Capture again and verify the field and the panel's Inserted state.
6. Record pass/fail and remove the temporary screenshot.

This mode is visual and process-level inspection. A normal Firefox that was
not launched with a remote-control server cannot acquire full DOM automation
halfway through a session. Do not solve that limitation by restarting it or
changing its profile — reach for mode B's separate browser instead, or ask.

## B. Isolated Marionette Firefox — automated development only

`scripts/live_browser.py` and `scripts/run_extension_harness.py` launch a
separate throwaway Firefox profile with remote automation enabled. They are
for local fixtures and invasive editor development—not the owner's current
session and not signed-artifact physical acceptance.

They run headless on a throwaway profile, so they may be used while the owner's
session is open: they are a different browser and cannot reach it. The earlier
rule against that came from a real incident — under Wayland, `xvfb-run` alone
does not isolate Firefox and the harness opened windows over the owner's
screen. Headless removed the cause; the launcher still drops the Wayland handle.

Label their evidence as isolated-harness evidence. It proves the code works,
never that the signed XPI works in the owner's normal profile, which is a
separate claim that only mode A can support.

## Decision rule

```text
A claim about the owner's real session or the signed artifact?
  yes -> mode A. Inspect it; do not restart, re-profile, or navigate it.
  no  -> mode B is free to use, live session open or not.
```

Mode A's caution is about the owner's session and their coursework, not about
looking. Look freely: focus a window to capture it, read the log, re-run a
solve, exercise the panel. What stays off limits is navigating away from the
question under investigation, restarting or re-profiling their browser, and
pressing Hawkes Submit/Check/Next — which spends a graded attempt.
