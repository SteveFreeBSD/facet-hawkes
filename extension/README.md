# Ethnos Hawkes Assistant

A Firefox add-on that reads the Hawkes question on screen, asks the local
Ethnos pipeline to solve it, shows you the problem and answer together, and
places the answer in the field you focused — only when you ask.

The add-on reads Hawkes' own MathML first. Only a question the exact solver
cannot handle falls back to a screenshot, which goes over Firefox native
messaging to the local Ethnos host and is deleted when that call ends. The
browser package has no network API; the native host uses the Ollama endpoint
configured for Ethnos, which must remain local for an entirely local setup.
The optional **Facet (experimental)** engine sends only the instruction and
MathML-derived expression through a fixed SSH bridge to the Facet host
configured in Ethnos; it never sends a screenshot and exposes no destination or
execution setting to the browser.

## Scope

What it does:

- has standing permission for only `https://learn.hawkeslearning.com`, but
  injects nothing until you open its toolbar panel or sidebar;
- reads the visible question's MathML on demand and captures only an isolated
  question region when that exact path explicitly declines;
- shows the problem Ethnos read back beside the answer, so you can check the
  transcription before trusting the answer;
- inserts that answer at the caret of the field you focused, after a second,
  separate click;
- reports which stage answered — the exact symbolic solver, the polynomial
  solver, or the language model.

What it does not do, by construction:

- submit, check, advance, or select a question;
- make any network request — there is no `fetch` or `XMLHttpRequest` in the
  package, and the build fails if any appears. The only outbound channel is
  native messaging to one registered local host;
- reach Ethnos or screenshot the tab from injected code — both are forbidden in
  anything under `content/`, because the page it runs in is not trusted;
- read your account, cookies, or session tokens;
- run on any other site, start a separate browser profile, or change Firefox
  preferences.

It is not designed to conceal add-on use or to interfere with Hawkes
monitoring. Confirm that assistance tools are permitted for the work you are
doing.

## What it answers exactly

Every exact operation is selected by reading a verb out of the question's own
instruction. What is not on this list falls through to the vision-plus-model
path, which takes roughly a minute and produces an answer nothing can check —
so this table is also the list of what is *fast* and what is *verifiable*.

| Question says | Operation | Answered by |
| --- | --- | --- |
| factor | `factor` | SymPy, verified by re-expansion |
| greatest common factor, GCF | `gcf` | SymPy `factor_terms`, GCF only |
| expand, find the product, multiply | `expand` | SymPy, verified by re-factoring |
| simplify, simplified form | `simplify` | SymPy exact evaluation |
| rationalize | `rationalize` | SymPy `radsimp` |
| rational exponent | `rational_exponents` | SymPy, written with fractional powers |
| descending / ascending order | `descending_order`, `ascending_order` | SymPy term ordering |
| degree | `degree` | read from the polynomial's terms |
| leading coefficient | `leading_coefficient` | coefficient of the highest power |
| constant term | `constant_term` | the polynomial where the variable is zero |
| monomial / binomial / trinomial | `classify` | counting the terms |
| evaluate … for x = n | `evaluate` | exact substitution |

The orderings and both extractions were added after a live session where each
cost about a minute of model time for a result SymPy has in about one
millisecond. Two rules keep them honest: a rewriting verb alongside an ordering
wins, so "factor completely, then write in descending order" is a factoring
question; and anything with more than one variable declines rather than
guessing which one an ordering or a degree refers to.

A product verb beats "simplify", because these questions say "multiply the
following polynomials **and simplify your answer**" and mean multiply; and
"factor out the greatest common factor" is narrower than "factor", which would
otherwise return a complete factorization and answer a different question.

Coverage is swept offline, with no browser and no model:

```console
$ python3 -m ethnos.cli hawkes-coverage
17/20 answered exactly, 1 correctly declined (0 wrong, 3 unrecognized, ...)
```

It separates the two kinds of gap, which fall through to a model identically
and are fixed in completely different places: `no-verb` means no operation
matched the prompt, `solver-declined` means one did and SymPy would not answer.
A wrong exact answer fails the sweep; a gap does not, because gaps are the
backlog it exists to print. `--strict` fails on those too. Add phrasings to
`benchmarks/hawkes_lesson_coverage.json`.

## When it refuses

The add-on fails closed, and there are three reasons it will show an answer but
not let you insert it:

- **The two readers disagreed.** Ethnos transcribes the screenshot twice with
  different models and compares them. If they differ on a sign, exponent,
  radical, or fraction boundary, the answer is displayed with the disagreement
  and insertion stays disabled. An answer to the wrong question is worse than
  no answer.
- **The answer needs a template the question forbids.** Each question permits
  only some of fraction, radical and exponent, and publishes which. An answer
  needing one that is not offered is refused by name.
- **The answer is a choice, not a value.** Some questions are answered with a
  radio button. The answer is shown; selecting it stays your action.

There is also one case that is cautioned rather than refused. Every exact
operation is chosen by reading a verb out of the question's own instruction, so
when that instruction cannot be read the question reaches a model as a picture
with nothing stating what to do about it — the least reliable path the add-on
has. The answer is still offered, because it is often right and you review
every one before insertion; but the status line turns amber and says the
instruction was not read, instead of the ordinary green "Ready". `Details`
carries `instruction not read from the page`.

Supported structured answers—including fractions, radicals, exponents,
absolute value, and several tested nestings—are **built** with the editor's own
keypad templates rather than typed as punctuation. Nested fractions remain a
deliberate refusal.
`common/editor-plan.js` works out the sequence of presses and keystrokes, and
`common/page-actions.js` performs it. See
[`docs/HAWKES_EDITOR_FINDINGS.md`](../docs/HAWKES_EDITOR_FINDINGS.md) for how
the editor was reverse-engineered.

Plain-text insertion is presented one character at a time. It defaults to a
randomised Lo-fi cadence inside a 5–10 second window, leaving longer rests
after operators and separators so a demonstration voice-over can name each
part of the expression. Settings offers Classical, Jazz, Lo-fi, Electronic and
Custom arrangements, an independent 30–300 BPM tempo, and a configurable 2–12
second hard window. Cadence controls remain a draft until **Apply cadence**,
which writes them in one transaction. The in-Settings equation preview uses the
actual structured planner and shared cadence scheduler, draws the phrase as a
rhythm strip — spacing is the timing, height is the accent, a band is the
structural rest — and reports which end of the hard window decided the phrase's
length. It never touches a Hawkes page. Structured keypad plans use that same
cadence for their typed steps; template presses settle on the shared clock. The
timing is theatrical, not an attempt to imitate human input: synthetic events
and MAIN-world editor calls remain observable to the page. See the
authoritative [`Answer Cadence` design note](../docs/ANSWER_CADENCE.md).

## Site-footprint contract and hard limit

Opening and solving leave no persistent, site-visible artifact in the Hawkes
page. Inserting necessarily leaves the answer the user explicitly requested
and Hawkes' own resulting editor state; it leaves no extension marker around
that change. This is a correctness
property before it is a privacy one — a page that cannot see the add-on cannot
break because of it, and a page that can see it can also break it. Every bullet
below is enforced by `scripts/build_extension.py`, so it fails the build rather
than decaying into a comment.

This is deliberately **not** a claim of undetectability. Synthetic input events
carry `isTrusted === false`, and the structured-answer builder briefly calls
Hawkes' own editor methods in the MAIN world. Page code can observe either
while an insertion is happening. The add-on does not attempt to conceal those
actions or bypass monitoring.

**Nothing is exposed to fetch-probing.** The manifest declares no
`web_accessible_resources`, so there is no `moz-extension://` URL for a page to
request. This is a weaker attack in Firefox than in Chrome to begin with:
Chrome serves resources from a static `chrome-extension://<fixed-id>/` path,
which is what lets a tracking script test thousands of known extensions by
fetching their files, while Firefox mints a **random UUID per profile**, so the
URL cannot be guessed. The residual Firefox risk is an extension that hands its
own UUID to the page by injecting a resource URL — this one injects none.

**No UI is injected, so there is nothing to select or measure.** All interface
lives in the toolbar popup and the preferences page, which are extension pages.
The content scripts add no element, attribute, class, or stylesheet to the
page, and the manifest declares no `css`. Nothing is styled, so no layout shift
occurs for a `ResizeObserver` or timing probe to notice. This is why there is
no closed Shadow DOM here: a shadow *host* is still an element in the page's
tree, visible to `document.querySelectorAll("*")` and to any mutation observer.
Shadow DOM is the right answer when you must inject UI. Injecting none is
strictly better, and it is what this add-on does.

**Two scripts run in the page's own world, and they are the exception.**
Hawkes drives its editor through page-owned JavaScript — a `quant_wp_UI` model
holding each question's rules, and a `keyPadButtonClick` method that loads a
template. Neither is reachable from an isolated script, so reading the rules
and building an answer both require the page's world.
`content/hawkes-describe.js` reads and never writes; `common/page-actions.js`
is the single writer, and it may only type into answer boxes and press named
templates. The build fails if either strays: no `eval`, no clicking page
elements, no navigation, no requests, no markup, and no other file may touch
the model. While these run the page can observe them — that is the documented
cost of the MAIN world, and it is what buys the only access that works.

**The isolation boundary is otherwise never crossed.** Firefox content scripts already
run in a sandbox — "page scripts cannot see JavaScript properties added by
content scripts" — so nothing in `content/` is visible to Hawkes. Leaking
requires deliberately reaching across, and the three escapes that do it (the
unwrapped page object, and the clone and export helpers) are all on the
forbidden list, as is `.prototype.` assignment and `defineProperty`. No
built-in is patched, so prototype-tampering checks find nothing.

**Scope is per execution.** `content/hawkes-editor.js` is an IIFE that exposes
a single name, `ethnosHawkes`, into the frame's per-extension scope; every
other binding is local and rebuilt on each run, and the operation scripts add
nothing of their own. That one name is a `var` rather than a `const` because
the popup re-injects the file on every use, and Firefox gives an extension one
scope per frame — a top-level lexical declaration would throw a redeclaration
error the second time.

**No site-visible state survives a call.** The content scripts register no
listener and set no property on the page's `window` — not even an injection
marker. One helper name can remain in Firefox's extension-only isolated world
for the life of the document; Hawkes page script cannot access that world.
Each operation is idempotent and re-injects the helper before use.

**Messaging never touches the page.** The popup drives the content scripts
through `scripting.executeScript` return values, not a DOM message channel the
page could intercept.

**The background cannot observe the site.** A non-persistent Firefox MV3 event
page owns solve state so a toolbar popup may close mid-solve. It has no content
listener and neither observes nor rewrites traffic, so neither `webRequest` nor
`declarativeNetRequest` appears. There is no interception latency for a page to
time.

Plain insertion dispatches `beforeinput`/`input`; structured insertion changes
the editor through its own template API. Both are observable at the moment of
insertion and inherent to changing the answer field.

## Frames

Hawkes may render its editor inside an iframe, so `inspect-field.js` runs in
every frame of the active tab and each frame reports only for its own document.
At most one may claim the caret: a frame whose focus sits in a child says
`focus-in-subframe` instead. The insertion then targets that one frame by id —
`allFrames` and `frameIds` are mutually exclusive in an injection target, and
broadcasting an insert risks a sibling frame with a stale `activeElement`
taking it too.

If two frames claim the caret anyway, the add-on refuses rather than picking
one. Typing an answer into the wrong document is worse than not typing it.

`common/frames.js` holds that decision, free of DOM and `browser` API access so
it can be run directly. `tests/test_hawkes_frames.py` executes the shipped file
under QuickJS against the `InjectionResult` arrays Firefox would return —
top-frame, same-origin iframe, cross-origin, unreadable origin, nothing
focused, two claimants, and malformed input. Firefox itself still has to
confirm the injection behaviour; these tests pin the judgement about what comes
back.

### If the editor turns out to be cross-origin

The declared Hawkes host permission covers the top-level document and its
same-origin frames. A cross-origin editor frame is not covered, so it never
reports, and the parent's `focus-in-subframe` is the only signal. The parent can read that
child’s **origin**, so the popup names it: *"The answer field is inside
`https://…`, which this add-on has no permission to reach."* Only the origin is
taken, never the full URL, which can carry lesson query strings.

That layout remains unsupported until a real lesson proves another specific
origin is necessary. Any such origin must be reviewed and added explicitly;
the add-on will not request a broad pattern to make an unknown frame work.

What is *not* on the list is a broad pattern. `https://*/*` — or anything that
resolves to it — is every site, whatever the intent; and a declared
`<all_urls>` content script with `match_about_blank` and `all_frames` would
trade a click-scoped grant for standing access everywhere, which is both a
larger permission prompt and a larger fingerprint, since the add-on would then
run on every page. Decide with a real lesson URL in hand, and name one origin.

Content scripts also do not run in `about:blank`, `about:srcdoc`, `data:`, or
`blob:` frames without `matchOriginAsFallback`, which is not requested here.
Such a frame has no readable `src`, so the popup reports the unreachable case
without an origin.

It is not designed to conceal add-on use or to interfere with Hawkes monitoring.
Confirm that assistance tools are permitted for the work you are doing.

## Permissions

This add-on targets Firefox 142 or later. Desktop understands the
`data_collection_permissions` declaration below from 140, and on anything older
the disclosure is silently ignored — but Firefox for Android did not understand
it until 142, and `strict_min_version` covers both. Declaring 140 made the
floor contradict the manifest's own disclosure on Android, which is what
`web-ext lint --warnings-as-errors` refuses.

| Permission | Why it is needed |
|---|---|
| `activeTab` | Allows a screenshot fallback after a toolbar click. A sidebar opened directly may read exact markup but cannot capture. |
| `scripting` | Injects the scripts under `content/` into that tab so the answer field can be inspected and written. |
| `nativeMessaging` | Starts and speaks to the one registered `ethnos_hawkes` host. Not network access, and not a listening port. |
| `storage` | Holds preferences and the bounded redacted diagnostic log. Coursework answers are not stored. |

`host_permissions` is exactly `*://learn.hawkeslearning.com/*`. It is standing
access to the one site the add-on exists to serve; it does not inject or run
code by itself. Content scripts are still injected only on demand, and the
build rejects any broader host pattern. Firefox can withhold an MV3 host grant,
especially for a temporary install; in that state the sidebar offers **Grant
Hawkes access** and requests this exact pattern from the click.

Native messaging is preferred over a localhost HTTP server on purpose. Firefox
starts a fixed local command for a specifically identified extension; no port
is opened, so no other program on the machine and no web page can reach the
solver. The host's manifest names `ethnos-hawkes@local` and nothing else.

The manifest carries Firefox's current data-transmission disclosure. Mozilla
counts data sent through native messaging as leaving the add-on even when the
companion runs on the same computer. Because the question's text, MathML, or
screenshot is sent to that companion, the required category is
`websiteContent`:

```json
"data_collection_permissions": { "required": ["websiteContent"] }
```

The companion uses the material only to answer the requested question. Exact
MathML cases stay within the companion process. Screenshot/model fallbacks are
sent to the Ollama endpoint configured in Ethnos; keep that endpoint on
loopback for a fully local setup. Nothing is sold, shared for advertising, or
used for analytics. See [`PRIVACY.md`](PRIVACY.md) for the complete disclosure.
`scripts/build_extension.py` requires this exact manifest shape.

## Install the solver host

The add-on is inert until Ethnos is registered with Firefox. This writes two
small files — a launcher and a manifest — and nothing else. No service, no
port, no daemon:

```console
$ python3 deploy/firefox/install_native_host.py          # print the targets
$ python3 deploy/firefox/install_native_host.py --write
$ python3 deploy/firefox/install_native_host.py --check  # native health round trip
```

It prints every path before touching anything, and `--uninstall --write`
removes only the exact two files it created. **Restart Firefox afterwards** —
the manifest is read at startup.

To check the host without involving the browser, speak to the launcher the way
Firefox does:

```console
$ printf '' | deploy/firefox/ethnos-hawkes-host   # exits cleanly on a closed pipe
```

`pytest tests/test_hawkes_host.py` covers the framing, the operation allowlist,
and the refusal paths without loading a model.

## Install the add-on for development

1. Keep the Hawkes lesson open in your normal Firefox window.
2. Open `about:debugging#/runtime/this-firefox` in a separate tab.
3. Choose **Load Temporary Add-on**.
4. Select `extension/manifest.json`, or a built
   `dist/ethnos-hawkes-<version>-unsigned.xpi`.
5. Return to Hawkes and pin **Ethnos Hawkes Assistant** from the extensions menu
   if its toolbar button is not visible.

A temporary add-on does not create a Firefox profile or change any preference,
and Firefox removes it on restart.

## Use it

1. Open the question. If it has more than one visible answer box, click the
   box you mean so its caret is visible. A question with one visible box is
   found even when the open sidebar has moved focus back to the page body.
2. Click the **Ethnos Hawkes Assistant** toolbar button.
3. With the default automatic-solve setting, solving starts when the field is
   found. Otherwise click **Solve**. Exact MathML cases normally finish in
   under a second; screenshot fallback can take about a minute.
4. **Read the recognized problem against the screen.** If Ethnos transcribed
   the question wrongly, everything after it is wrong, and this is the only
   place you can catch it.
5. If the answer is insertable, click **Insert answer** once.
6. Check the answer box yourself. The add-on never submits; use the site's own
   controls only if and when you intend to.

If the panel reports multiple fields or cannot identify the field, close the
toolbar popup (if used), click the intended answer box, and reopen it. The
extension never guesses when more than one candidate is visible.

### What the panel shows after an insertion

The answer card keeps the answer it placed, marked **Placed**, with the source
that produced it beside it. Nothing there can be inserted again: the reviewed
answer is dropped from state at insertion and what remains is a display-only
copy, cleared by the next solve or the next question.

**Solve** stays available but stops being the primary action and is relabelled
**Solve again**, `Enter` is bound to nothing, and the status line says what
happens next — the docked sidebar keeps watching for the next question, while
the toolbar popup closes as soon as focus moves and so asks you to reopen it.

### Two browser windows

Each Firefox window has its own sidebar, and each acts on its own tab. One
question is worked on at a time: acting in a second window's panel rebuilds the
state for that window, which drops the first window's answer, so an answer
solved in one window can never be inserted into another. Until you act in it,
a second panel displays the first window's question.

### Keyboard

The panel is usable without the mouse. Focus starts on the primary action and
moves to **Insert** when a solve finishes. Where there is no primary action —
during an insertion, and after one — the panel takes no focus at all rather
than parking the caret on a control it does not want pressed.

| Key | Does |
| --- | --- |
| `Alt+Shift+E` | Open the panel. Rebindable in Settings. |
| `Enter` | The primary action: Solve, then Cancel, then Insert. Bound to nothing once an answer has been placed, so it cannot re-solve an answered question. |
| `Ctrl+Enter` | Solve, or cancel a solve, whatever is primary. |
| `Escape` | Close the panel. A solve under way carries on. |

## Settings

Open them from the gear in the panel, or from `about:addons`. Every preference
is declared once in `common/settings.js`; a stored value that is missing,
mistyped or out of range falls back to its default, so a corrupt preference
costs you the preference rather than the add-on.

| Setting | Default | What it changes |
| --- | --- | --- |
| Start solving as soon as the field is found | on | Saves a click per question. |
| Limit screenshots to the question region | on | Excludes header, account, answer and footer UI. If safe bounds cannot be found, nothing is sent. Turn off explicitly only for an unusual layout. |
| Give up on a solve after | 240s | 30–900. A larger vision model on a slower machine needs longer. |
| Panel width | 360px | 300–560. Firefox sizes a popup to its content, so this is the whole of the control there is over it. |
| Show the recognized problem expanded | off | Costs a little panel height. |
| Cadence genre | Lo-fi | Classical, Jazz, Lo-fi and Electronic supply distinct beat shapes, swing, variation and symbol rests. Custom exposes those controls directly. |
| Cadence tempo | 82 BPM | 30–300. Choosing a genre loads its suggested tempo into the draft; the slider can then override it. Cadence changes take effect together through **Apply cadence**. |
| Performance window | 5–10s | A hard 2–12 second range around the tempo-derived length, kept below the injected operation's 15-second deadline. |
| Keyboard shortcut | `Alt+Shift+E` | Rebound through Firefox's own `browser.commands`. |
| Record | Normal activity | What reaches the diagnostic log. |

There is deliberately **no automatic-insertion setting**. A second, separate
click is the add-on's safety contract, and a test asserts no such preference
appears.

**Test connection** asks the local host to identify itself. It loads no model,
so it answers at once — rather than a solve spending a minute finding out that
`ethnos_hawkes` was never registered.

## Diagnostics

Every context — the panel, the event page, the settings page — writes to one
bounded log, viewable, copyable and erasable at the bottom of Settings.

- **The log never contains your coursework.** Answers, recognized problems and
  screenshots are recorded only as shapes: `{answerLength: 4}`, never the
  answer. The rule lives in `common/log.js` and is enforced on every payload
  rather than trusted to each call site.
- It never leaves this machine. There is no transport in this add-on, and the
  log did not add the first one.
- 200 entries, oldest dropped, `storage.local` only, cleared with one button.
- The profile UUID is stripped from every stack, so a copied log is safe to
  paste into a report.

If the panel's own code ever throws, it shows a **fault banner** offering the
log and a reload, rather than freezing. That is what 0.22.0 did instead: it
threw on every render and said nothing.

## Verify it in a browser

Two layers, because the static checks cannot see a running browser.

**Automated.** `scripts/run_extension_harness.py` drives the add-on in a real
Firefox against local fixtures — installed temporarily over Marionette in a
throwaway profile, with `activeTab` granted by a real click on the toolbar
button, exactly as in normal use:

```console
$ xvfb-run -a python3 scripts/run_extension_harness.py
$ xvfb-run -a python3 scripts/run_extension_harness.py --scenario top
```

It covers the top frame, a same-origin editor frame, a page carrying an
unrelated cross-origin frame, a cross-origin editor, and nothing focused, and
reports what the popup actually displayed. It never touches your profile, your
running Firefox, or the real Hawkes site.

This layer exists because 0.7.0 shipped an add-on that could not inject at all:
`scripting.executeScript` resolves file paths against the calling document, so
`"content/hawkes-editor.js"` became `popup/content/hawkes-editor.js`. Every
probe written before this harness ran from a background script at the extension
root, where the broken path happened to resolve.

**Manual.** [`TESTING.md`](TESTING.md) is the protocol for a real lesson: each
check with its expected result and what a failure points at. The harness cannot
tell you whether the *Hawkes* editor accepts what the add-on builds — only that
editor can.

## Build and validate

```console
$ python3 scripts/build_extension.py --check   # validate only
$ python3 scripts/build_extension.py           # validate, then write dist/*.xpi
$ python3 scripts/build_extension.py --icons   # re-render PNGs from icons/icon.svg
```

The repository validator checks the permission set, fixed add-on ID and
minimum Firefox version, page CSP, every manifest-referenced file, localization
completeness, and the forbidden constructs listed above. It supplements—not
replaces—Mozilla's `web-ext lint` and AMO validation. It writes an explicitly
named unsigned, reproducible XPI with fixed timestamps and sorted entries, so
two builds of the same tree are byte-identical.
`pytest tests/test_hawkes_extension.py` runs the same local checks.

Icons are generated from `icons/icon.svg` with `rsvg-convert`; edit the SVG and
re-run with `--icons` rather than editing the PNGs.

## Release

The local artifact is deliberately named `*-unsigned.xpi`; normal Firefox will
not install it permanently. Follow [`RELEASE.md`](RELEASE.md) to run the
preflight, obtain an unlisted Mozilla signature, install the signed result in a
regular profile, verify the native companion, and roll back safely. Keep the
fixed ID `ethnos-hawkes@local`; do not disable Firefox signature enforcement.

## Remove it

- Temporary install: remove it on `about:debugging#/runtime/this-firefox`, or
  restart Firefox.
- Signed install: remove it from `about:addons`.

Removing the add-on ends its event page and clears its extension storage.
The separately installed native-messaging manifest remains until removed with
`python3 deploy/firefox/install_native_host.py --uninstall --write`. No host
process stays resident: Firefox starts it for a request and closes it with the
native port. Hawkes, Canvas, Firefox preferences, and saved logins are untouched.

## Layout

```text
extension/
├── manifest.json            MV3 manifest: fixed ID, four permissions, page CSP
├── _locales/en/messages.json every user-visible string
├── PRIVACY.md               complete data-use and retention disclosure
├── RELEASE.md               signing, permanent install, smoke test, rollback
├── common/config.js          shared origin and answer validation
├── common/frames.js          which frame may receive an answer (DOM-free)
├── common/i18n.js            data-i18n localisation for extension pages
├── common/log.js             the bounded, redacted diagnostic log
├── common/panel-view.js      what the panel shows, as data (DOM-free)
├── common/settings.js        every preference: type, default, bounds
├── common/theme.css          Firefox's Acorn tokens, one light-dark() pair each
├── content/hawkes-editor.js  shared sandbox helpers: find and write the field
├── content/inspect-field.js  per-frame report of the focused answer field
├── icons/                    icon.svg source and the rendered PNG set
├── options/                  preferences page
└── popup/                    toolbar panel
```
