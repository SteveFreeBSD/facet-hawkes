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
```

That command:

- finds exactly one existing normal Firefox window and fails closed otherwise;
- confirms the installed extension version, enabled state, and signing state;
- briefly focuses Firefox, captures only that window through KDE Spectacle,
  and restores the previously active window;
- reports whether the native host is currently running;
- never launches Firefox, opens a URL, changes a profile, reads browser
  history, or sends input to Hawkes.

Inspect the reported PNG locally, then delete it because it contains
coursework. Use `status` when no screenshot is needed and `shot` for another
visual check:

```console
$ python3 scripts/inspect_live_firefox.py status
$ python3 scripts/inspect_live_firefox.py shot
```

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
not launched with a remote-control server cannot safely acquire full DOM
automation halfway through a session. Do not solve that limitation by
restarting it, changing its profile, or opening a competing browser.

## B. Isolated Marionette Firefox — automated development only

`scripts/live_browser.py` and `scripts/run_extension_harness.py` launch a
separate throwaway Firefox profile with remote automation enabled. They are
for local fixtures and invasive editor development—not the owner's current
session and not signed-artifact physical acceptance.

Use this mode only when the owner explicitly authorizes a separate automated
browser and no live-session instruction conflicts with it. Label its evidence
as isolated-harness evidence; never present it as proof that the signed XPI
works in the normal profile.

## Decision rule

```text
Owner's real Hawkes session or signed release test?
  yes -> inspect_live_firefox.py; never start or navigate Firefox
  no  -> local fixture automation may use the isolated Marionette harness
```

If there is any doubt, stay in mode A. Capturing too little is recoverable;
launching the wrong browser or authentication flow disrupts the test.

