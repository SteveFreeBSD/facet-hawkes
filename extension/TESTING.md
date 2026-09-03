# Verifying the add-on

Two layers. The automated one runs anywhere; the manual one needs a real
lesson, because only Hawkes can tell you whether Hawkes accepts an answer.

> **Live-test route:** Sign in **directly to Hawkes** using the owner's normal
> Hawkes login and navigate to the intended practice question there. Do not use
> OSUIT Canvas, a school portal, CAS/SSO, or an LMS redirect for extension
> testing. Do not infer or reopen an authentication route from browser history.
> An agent must leave Firefox untouched unless the owner explicitly requests a
> specific browser action; when a lesson is needed, the owner performs the
> login and navigation.

The authoritative choice between the owner's existing signed Firefox and the
separate automated development browser is documented in
[`docs/HAWKES_DEVELOPMENT_FLOW.md`](../docs/HAWKES_DEVELOPMENT_FLOW.md). For
physical acceptance, begin with:

```console
$ python3 scripts/inspect_live_firefox.py inspect
```

Do not run `scripts/live_browser.py start` during that workflow. It creates a
different Firefox profile and cannot prove the installed signed artifact.

```console
$ python3 scripts/build_extension.py --check   # manifest, permissions, footprint rules
$ pytest                                       # logic, under QuickJS where it is JavaScript
$ xvfb-run -a python3 scripts/run_extension_harness.py   # a real Firefox, local fixtures
```

The harness installs the add-on in a throwaway Firefox profile and clicks the
real toolbar button, so `activeTab` is granted the way it is in normal use. It
covers the top frame, a same-origin editor frame, a page carrying an unrelated
cross-origin frame, a cross-origin editor, and nothing focused. It never
touches your profile, your running Firefox, or the real Hawkes site.

What none of that can settle is whether the *Hawkes* editor accepts what the
add-on builds. That is what the checks below are for.

## Normal signed-Firefox setup

1. Using the direct Hawkes login—not Canvas or another school/LMS portal—open
   the intended practice question in the existing Firefox session.
2. Confirm the signed add-on is active with
   `python3 scripts/inspect_live_firefox.py status`.
3. Open its toolbar panel or sidebar without changing the Hawkes page.

Loading `extension/manifest.json` through `about:debugging` is a separate
temporary-add-on development workflow. It is not part of signed release
acceptance and must not replace the installed Mozilla-signed XPI mid-test.
When that isolated workflow is explicitly intended, open
`about:debugging#/runtime/this-firefox`, choose **Load Temporary Add-on**, and
select `extension/manifest.json` in the isolated Firefox profile only.

Failures surface in the panel itself: the status line says what happened, and
**Details** carries the reason codes. Quote that line when reporting anything.

A failure in the panel's *own* code is different, and looks different: a red
banner under the header offering **Copy diagnostics** and **Reload panel**. If
you see it, the copied log is the report. Settings → Diagnostics holds the same
log at any time, and none of it contains the question or the answer.

## Checks

### 1. The page cannot see the add-on

Before clicking anything, in the **page's** console (F12 on the lesson tab):

```js
typeof window.ethnosHawkes                                      // "undefined"
document.querySelectorAll("[class*='ethnos'],[id*='ethnos']").length   // 0
```

Both must still hold *after* a solve. The content scripts run in an isolated
sandbox and add nothing to the page; the two page-world scripts declare
nothing and leave nothing behind.

### 2. The question is found, and solving starts on its own

Open the panel on a question.

**Expected:** it finds the sole visible answer field even if the sidebar left
focus on the page body, and begins solving without a second click. Exact MathML
normally finishes in under a second; screenshot fallback takes longer.

**If it says no answer field:** the selectors in `content/hawkes-editor.js`
do not match this editor. Read `document.activeElement` in the page console and
report its tag, id and class.

When more than one supported field is visible, it must refuse to guess until
you focus the intended field.

### 3. Cancel actually stops it

Press **Solve/Cancel** mid-solve. The panel returns to ready, and no
`ethnos-hawkes-host` process remains:

```console
$ pgrep -af ethnos-hawkes-host      # nothing
```

A cancel that leaves the host running is a bug: it keeps a model loaded.

### 4. The recognized problem matches the screen

Open the **Recognized problem** fold and compare it with the question.

This is the only place a misreading can be caught. If Ethnos read the question
wrongly, everything after it is wrong however confident it looks. When the two
readers disagree the panel says so and refuses to insert.

For a screenshot fallback, leave **Limit screenshots to the question region**
on. If safe bounds cannot be found, the panel must say that no screenshot was
sent; it must not silently process the full viewport. Exercise the explicit
off setting only with a test page containing no account or unrelated content.

### 5. Insert

Press **Insert**.

- A typeable answer goes straight into the box.
- A structured one — a fraction, a radical, an exponent — is **built** with the
  editor's own keypad templates, one step at a time.
- An answer needing a template the question does not offer is refused by name.
- An option question is never typed into: the answer is shown and you choose.

**Expected:** the whole answer appears, and no Hawkes message box opens.

**If only part of it appears:** the executor mis-read which boxes a template
created. Report the answer and what ended up in the box; `settle()` in
`common/page-actions.js` is where that goes wrong.

**If a Hawkes dialog opens** ("The character you entered is not required"),
something was typed that this question's editor does not accept. The panel is
supposed to refuse first, from the editor's own published character set.

### 6. It is ready for the next question

Submit, move on, and open the panel again.

**Expected:** no trace of the previous answer, and it finds the new question's
field by itself. Hawkes swaps the answer controls in place without navigating,
so a stale answer here means the question-change detection failed.

### 7. Insertion never repeats

Insert, close the panel, reopen, insert again.

**Expected:** one further copy, not two. Each operation is a fresh
`executeScript` that registers nothing, so re-running cannot stack listeners.

### 8. A placed answer stays on the card, and clears for the next step

Insert an answer, then read the panel without touching anything.

**Expected:** the card still shows what it placed, marked **Placed**, with its
source beside it; **Insert answer** is disabled; **Solve** reads **Solve
again** and no longer carries the accent; the footer offers no `Enter` action.
The docked sidebar says it is watching for the next question.

Then move to the next question — or the next **step** of a multi-step question,
which is the case that used to fail. Within about a second and a half the card
must clear and the panel re-arm. A previous step's answer still showing against
an empty box means the question signature could not tell the steps apart.

**Recognized problem** is the check for that: on a step-2 or step-3 question it
must name the step, for example `Step 3 of 3 : Identify the leading
coefficient`. If it is empty, or shows only the polynomial, the page probe is
not reading the step marker and every step of that question looks identical to
the add-on.

### 9. An answer reached without the question's instruction says so

Find a question whose instruction the probe cannot read, or watch for it: the
status line turns amber and says the instruction was not read, rather than the
ordinary green "Ready". **Details** carries `instruction not read from the
page`.

**Expected:** the answer is still offered for review and **Insert answer** is
still enabled. This is a caution, not a refusal — but it must never look
identical to an exactly derived answer, because without the instruction no
exact operation can be selected and the result came from the picture alone.

### 10. Two windows do not fight

Open a second Firefox window, and open the sidebar in both.

**Expected:** both panels keep updating — neither goes dead when the other
opens. Each acts on its own window's tab: solving in one must never read, and
inserting in one must never write to, the other window's page. Acting in the
second window's panel rebuilds its state, so an answer solved in the first
window cannot be inserted into the second; the panel simply has nothing to
insert.

### 11. Removal leaves nothing

Remove the add-on in `about:debugging`, then reload the lesson.

**Expected:** the page behaves normally and no extension process remains.
Answers are never saved in extension storage; **Reset** only clears the
current in-memory result and returns the panel to ready. Removing the native
host registration is separate:

```console
$ python3 deploy/firefox/install_native_host.py --uninstall --write
```

### 12. The settings actually govern a solve

Settings → Solving. Set **Give up on a solve after** to 30 seconds and turn
**Start solving as soon as the panel finds the answer field** off. Then open a
question.

**Expected:** the panel finds the field and waits, rather than solving. Press
Solve; if the host takes longer than 30 seconds the panel reports the timeout
rather than the old four-minute one. Settings → Panel: move **Panel width** and
reopen the panel; it opens at the width you set.

The event page holds preferences in memory, so a change applies to the next
question without restarting Firefox.

### 13. The connection check answers without a solve

Settings → Ethnos connection → **Test connection**.

**Expected:** with the host registered, a round-trip time in milliseconds,
within a moment — it loads no model. With the host removed
(`install_native_host.py --uninstall --write`), a legible "Ethnos is not
reachable" rather than a wait.

### 14. The diagnostic log records shapes, not coursework

Solve one question, then open Settings → Diagnostics.

**Expected:** entries for `event-page-loaded`, `solve-started` and `solved`.
`solved` carries `answerLength`, not the answer. **Search the copied log for
the answer you just solved and for any part of the question text: neither may
appear.** Then **Clear**, and confirm the view empties.

### 15. Both themes, and high contrast

Switch Firefox between light and dark (Settings → General → Website appearance)
and reopen the panel.

**Expected:** panel background, text, accent and focus ring all follow, with no
white flash on open in dark mode. On Windows, with High Contrast on, every
colour is replaced by the system pair and every button keeps a visible border.

## Reporting

Per check: passed or failed, the exact status line, and the **Details** text.
Settings → Diagnostics → **Copy** gives the log for the same session; it is
redacted and carries no profile UUID, so it can be pasted as it stands. A
screenshot cropped to the question helps. Do not include account details,
the lesson URL's query string, or unrelated page content.

Do not widen the site allowlist or add host permissions to make a check pass.
A failure is information about the editor; the next step is read-only
inspection of it.
