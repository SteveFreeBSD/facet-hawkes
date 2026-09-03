# Changelog

All notable changes to the Ethnos Hawkes Assistant add-on. Versions follow
`major.minor.patch` as required by the Firefox manifest.

## 0.39.2

### Fixed

- A tab dragged out into a window of its own is no longer read from or written
  to by the panel left behind. `state` pairs one window with one tab, both
  captured when the answer field is found; detaching that tab changes which
  window it is in while its id stays the same, so the pair silently stopped
  describing anything real. Scoping the tab lookup by window did not cover
  this, because the lookup had already happened. The event page now forgets a
  tab on `onAttached`, `onDetached` and `onRemoved`, and insertion re-checks
  that the tab is still in the expected window immediately before writing —
  an event can be missed, a check at the write cannot.

## 0.39.1

### Fixed

- `strict_min_version` is 142.0. Mozilla's own `web-ext lint`, run with
  `--warnings-as-errors` as the release runbook requires, refused the 0.39.0
  candidate: Firefox for Android did not understand
  `browser_specific_settings.gecko.data_collection_permissions` until 142, so a
  declared floor of 140 contradicted the manifest's own data-collection
  disclosure on that platform. Desktop understood the key from 140 and is
  unaffected in practice.

## 0.39.0

### Changed

- The panel now works out one named **stance** — offline, solve, working,
  review, inserting, placed — and derives the primary button, the Enter key and
  the footer hint from it in a single place. Those three were previously
  re-decided at each site that needed them, and a finished insertion was the
  state none of them had a name for, so every one fell through to its "nothing
  has happened yet" default.
- The source badge has left the header, where it competed with the add-on name
  and three icon buttons for one 360px row and could be clipped to a mystery
  `mod.`. It now sits inside the answer card, which is what it describes, with
  room to spell `polynomial` in full and an ellipsis if it ever cannot.

### Fixed

- The answer card keeps showing the answer after insertion, marked **Placed**,
  instead of emptying to an em dash at the moment the add-on had succeeded. The
  reviewed answer is still dropped from state — nothing can insert it twice or
  offer it to a later question — and what the card shows is a display-only
  copy, cleared by a new solve or a new question like everything else. The
  recognized problem and source survive alongside it, so the sidebar watcher no
  longer blanks the card 1.5 seconds after a successful insertion.
- "Inserted. Submit it, then reopen for the next question" was written before
  the sidebar watcher existed. The docked sidebar now says it is watching for
  the next question, because it is; the toolbar popup still says to reopen,
  because it closes as soon as focus moves and stops watching.
- The footer no longer offers "Enter to solve" after an insertion, and Enter is
  bound to nothing there. Enter took its action from whichever button was not
  disabled, and Solve stays enabled so a doubted answer can be re-solved — so
  the key quietly re-solved the question that had just been answered.
- A second browser window no longer kills the first window's panel. Firefox
  gives every window its own sidebar, and the event page held one `panel`
  variable that each new connection overwrote: the earlier panel received its
  first state and then nothing further, which from the outside is a panel that
  will not open. Panels are now tracked as a set and all of them are kept
  current.
- An operation now targets the window whose panel asked for it. Tab lookup used
  `currentWindow`, which in a background event page means the most recently
  focused window — so with two windows open a solve could read, and an
  insertion could write to, the other one's tab. The panel reports its own
  window (a sidebar's port carries no sender tab) and every lookup is scoped to
  it. A request from a window other than the one the current state describes
  rebuilds that state first, dropping the previous window's answer, so an
  answer solved in one window can no longer be inserted into another.
- Two consecutive steps of a multi-step question were the same question. The
  page probe reported an instruction only when it matched a fixed verb list,
  and "Identify the leading coefficient" matched nothing — so with Hawkes
  keeping one prompt and one expression across every step, the signature
  reduced to the field and the shared polynomial and was identical for both.
  The previous step's answer stayed on the card, and because that signature is
  what `insert()` re-checks, an un-inserted answer could have entered the next
  step's box. The probe now reads the `Step N of M` marker, which distinguishes
  steps whatever their wording, and the verb list is wider.
- An answer reached without the question's instruction is no longer presented
  as though it were derived exactly. Without a prompt no exact operation can be
  selected, so the question reaches a model as a picture with nothing saying
  what to do about it — and the result was reported identically to an exact
  one. The host now reports `prompt_seen`, and the panel shows an amber note
  instead of the green "Ready". The answer is still offered for review; it just
  no longer looks like something it is not.
- Solve gives up the accent and the caret after a successful insertion, and is
  relabelled **Solve again**. Left prominent, focused, and reading "Solve with
  Ethnos", it presented itself as the next step and invited the needless retry
  this release was opened to fix. It stays available, and Ctrl+Enter still
  reaches it from the keyboard.

## 0.38.1

### Fixed

- Pressing Solve again now clears the previous answer, recognized problem, and
  source immediately in both the panel and event page. A slow or failed retry
  can no longer display an old result as though it belongs to work still in
  progress. The panel view also suppresses answer text while solving as a
  defense against delayed state updates.

## 0.38.0

### Changed

- Display notation and editor-entry notation now have separate state. The
  panel keeps readable math for review, while structured planning consumes the
  host's explicit keyboard form and normalizes `sqrt(...)`/`cbrt(...)` itself.
  This removes compact-display ambiguity from the insertion boundary.
- When sidebar focus sits on the page body, discovery may use the sole visible,
  editable Hawkes input. Multiple candidates still fail closed.
- The Firefox data-transmission declaration is now accurately
  `websiteContent`: Mozilla treats question material sent to a native companion
  as transmitted even when processing stays local. A complete privacy notice
  documents the companion and configured Ollama boundary.
- Screenshot fallback now crops from the question instruction to the answer
  area, excluding header/account UI as well as the keypad and footer. The
  privacy default fails closed if safe bounds cannot be established; sending a
  full viewport requires an explicit settings change. Same-origin frame offsets
  are translated into top-level screenshot coordinates; opaque frame boundaries
  are refused rather than cropped at a misleading position.
- Local packages are named `*-unsigned.xpi`, and the release runbook separates
  reproducible local validation from Mozilla signing and permanent install.

### Fixed

- Question 16's rational-exponent product now works from an open sidebar even
  after page focus is lost. Live result: `a^(11/12)`, rendered by Hawkes with
  `a` as the base and `11/12` as its exponent.

## 0.37.0

### Fixed

- An already-open sidebar no longer pretends to solve after its background
  port has been invalidated by an add-on reload. It immediately disables the
  stale view and reloads into a fresh extension context. A failed send cannot
  paint an optimistic running, inserting, or resetting state.
- Hawkes' wording "Express your answer in simplified form" now selects the
  exact simplifier. The live `-sqrt(144)` case returns `-12` in milliseconds
  instead of declining markup or falling through to vision.
- Hawkes' alternate non-real wording ("does not represent a real number") now
  returns `Not a Real Number`. The live `sqrt(-36)` case had escaped as the
  complex notation `6I`, which Hawkes correctly refuses. A numeric answer box
  now presents that prose result as a manual-choice handoff instead of the
  misleading refusal "does not accept: N".
- Readable markup that the exact solvers cannot handle now triggers the
  screenshot path deliberately. The browser previously omitted the screenshot
  whenever any MathML existed while the host described vision as its fallback,
  making that fallback unreachable.
- Plain insertion receives the reviewed answer directly as a one-shot function
  argument. The removed storage handoff had a fail-open placeholder that could
  type an unrelated answer before the background detected the mismatch.
- The browser host never writes screenshot transcriptions to the CLI's cache,
  and the native boundary rejects solve requests naming any other origin.
- A sidebar opened without a granted MV3 host permission now offers a
  user-gesture recovery for exactly the declared Hawkes pattern. Firefox 154
  exposes that permission as requestable in temporary installs; the old panel
  assumed declaration meant grant and could not recover after navigation.
- A successful insertion now keeps the current question's signature as a
  handled marker in event-page memory, rebased after Hawkes finishes rendering
  the inserted structure. The sidebar watcher and a later reopen no longer
  mistake answer-rendering changes for a new question and solve it a second
  time; a changed prompt/MathML still starts the next solve automatically.
- A radical followed by a factor now keeps an explicit boundary in the
  displayed plan. The exact live result `y*sqrt(30)/30` was rendered as
  `√30y/30`, which the structured editor correctly but wrongly grouped as
  `sqrt(30y)/30`. The formatter now keeps the canonical factor first as
  `y√30/30`, avoiding both the ambiguity and Hawkes' fragile post-radical
  continuation slot.
- A docked sidebar no longer fails question discovery merely because Firefox
  leaves the page focused on `BODY`. It falls back only when exactly one
  visible, editable Hawkes answer input exists; multiple candidates still
  refuse rather than guessing.

### Clarified

- The README now defines zero website footprint precisely: no persistent DOM,
  CSS, page-global, listener, resource, or request-interception artifact. It
  also documents the unavoidable observable moment of synthetic input and
  MAIN-world editor calls instead of claiming undetectability.

## 0.29.0

### Fixed

- The panel no longer offers one question's answer for another. Hawkes swaps
  questions in place without navigating, so the panel decided whether the
  question had changed by comparing the answer control's id and its character
  rules -- but those describe the *editor*, and every question of the same kind
  publishes the same ones. `cbrt(y^4)` and `7th-root(y^8)` were indistinguishable,
  so `y^4` was built into the box for a question whose answer was `y^(8/7)`,
  and reported as solved and exact. The question is now identified by its own
  prompt and markup.
- An answer is checked against the question on screen immediately before it is
  inserted, and refused if the question has changed in the meantime.
- A question that cannot be read is never treated as the previous one, so an
  unreadable page re-solves rather than reusing an answer.

## 0.31.0

### Added

- Absolute-value answers are built, not refused. The editor calls the template
  `Mod` and groups it with its parentheses -- `addElement` guards it with
  `qualifyLoadParenthesis` and loads it with `loadParenthesis`, unlike every
  other template the planner drives -- so both the guard and the loader now
  take the type as an argument. Verified live on lesson 1.2 question 7: the
  fourth root of `y^20*z^16/81` built as `z^4|y^5|/3` and was marked correct.
- The editor description reports whether a question permits bars. There is no
  `qdyAbsoluteValueAllowed` flag; a question instead names the templates each
  slot accepts, and question 7 listed `Mod` for its base and for both halves
  of a fraction -- the question stating that its answer is built from bars.

### Changed

- The solver prints the bars around the power, `|y^5|` rather than `|y|^5`.
  They are the same number for every real y, but the editor raises an exponent
  on the box the cursor is in, so bars-around-the-power keeps the exponent
  inside the bars, on a box the planner can reach.

## 0.33.0

### Added

- "Determine if this radical expression is a real number" is answered. The
  panel names the option that is right -- "Not a Real Number", or the value
  when it is real -- while selecting it stays the reader's action, as it has
  always been. The host used to report these unsupported: the symbolic solver
  produced `10*I` for the square root of -100, which is not an answer to the
  question asked.
- The test is the index's parity, not SymPy's principal branch. `(-27)**(1/3)`
  evaluates to a complex number, but the real cube root of -27 is -3 and that
  is what the question means. Only an even root of a negative is not real.

## 0.35.0

### Fixed

- The add-on reads the question from the page again. `QUESTION_SCRIPT` was used
  in `background.js` and declared nowhere, so every read threw a
  `ReferenceError` that `readQuestion` caught and logged as a warning -- and
  the solve fell back to a screenshot and its two vision readers on every
  single question, silently. That is where the reported reader disagreements
  came from, and it is how a misread index produced `x^(5/7)` for the square
  root of x^5, whose answer is `x^(5/2)`.
- Nothing caught it: the tests read `background.js` as text, and the live
  harness loads the reader file itself, so both the suite and every live probe
  looked fine while the add-on never once used the exact reader.

### Added

- The packaging check rejects any SHOUTING_CASE name a script uses but does not
  declare or import, verified by removing the declaration and watching it fail.
  This is the second bug of the shape "a name `background.js` reads is not
  there" -- the first was a const read above its declaration.
## 0.36.0

### Fixed

- An open panel notices the question changing. Hawkes swaps questions in place
  -- no navigation, no `tabs.onUpdated`, no event of any kind -- and the
  question was only re-checked when the panel opened. That is enough for the
  popup, which closes whenever focus moves, but the sidebar stays open, so a
  solved answer sat there across question changes. A worded answer is the worst
  case: "Not a Real Number" stays readable and looks deliberate while belonging
  to the question before, and it is read and acted on by hand, so no check made
  at insertion time can catch it. An open panel now re-reads the question every
  1.5 seconds and re-prepares when it differs, standing aside while a check,
  solve, or insertion is in flight.

## 0.34.0

### Fixed

- The question read waits for MathJax instead of falling through to the
  screenshot. An empty expression list counted as a successful read -- an empty
  array is still an array -- so a read that landed before MathJax had left its
  markup behind sent the solve to the screenshot and its two transcription
  readers. That is where "the two readers disagreed" came from, on questions
  that could be read exactly.
- Each slot is checked against its own character set. A question publishes one
  set per slot and they differ: seen live with a base taking `0123456789y`
  while both halves of a fraction took digits only. Every run was checked
  against the base's set, so `1/(7y^2z^3)` was typed into a digits-only
  denominator -- the 7 landed, the y was refused, and half an answer was left
  behind. Such an answer is now refused before anything is typed.
- A failed insertion checks that it cleared. `addElement` reads the caret
  before dispatching, but only for a call that says it came from the keypad,
  and with no `CurrentBase` -- where a rejected character leaves it -- that
  read throws and `Clear` never runs. The clear now goes in without the
  keypad's caret read, falls back to the editor's own backspace, and reports
  `leftBehind` rather than letting a half-built answer look like a clean
  refusal.

## 0.32.0

### Added

- Indexed radicals are built rather than declined. `IndexedRadical` is the same
  loader as `Radical` with its index box asked for by a second argument --
  `loadRadical(fromKeypad, IsIndexed)` -- and it focuses the index first,
  offering the radicand as its next slot. The planner reads the index out of
  the sign the solver writes: two for the plain sign, three and four for the
  cube and fourth-root signs, and a superscript digit for anything higher.
  Verified live on lesson 1.2 question 9, the cube root of 320, entered as
  4 times the cube root of 5.

### Removed

- The refusal list that declined the cube- and fourth-root signs by name. It
  dated from before the planner could fill an index box, and it reported
  "needs a keypad template: radical" for answers the editor was ready to take.

## 0.30.0

### Fixed

- Even-index radicals keep their absolute value. The fourth root of
  `y^20*z^16/81` was answered `y^5z^4/3`, which Hawkes marked incorrect --
  rightly, because at `y = -2, z = 3` the radical is 864 and `y^5z^4/3` is
  -864. A fourth root cannot be negative. The solver forced the variables
  positive for every radical, a convention borrowed from a *fifth*-root
  question where it is harmless, and it silently dropped the bars. The
  assumption now depends on the index's parity, and on whether the question
  states it.
- Variables are declared real rather than unrestricted when positivity is not
  assumed, so SymPy still extracts the root instead of handing the question
  back unsimplified.

### Changed

- An answer needing absolute-value bars is refused by name, pointing at the
  keypad's own `|a|` button, instead of reporting the bar as a character the
  editor rejects. The editor does accept bars; this add-on cannot build them
  yet.

## 0.28.2

### Fixed

- The panel no longer reports "the answer editor could not be read" when the
  editor is merely mid-rebuild. Hawkes discards its editor model while it swaps
  in the next question, and a probe that landed in that gap saw nothing at all.
  The description is now retried for up to a second and a quarter, so a question
  change no longer looks like a missing editor.

## 0.28.1

### Fixed

- **"This question's answer box does not accept: y"** on a question whose
  answer box plainly accepts `y`. The editor publishes its accepted characters
  per question, and the panel's copy is taken when the answer field is found —
  so if the question changed in between, which it does in place without ever
  navigating, the new answer was checked against the previous question's
  character set. The rules are now re-read immediately before inserting.

  Verified on the seventh root of `y^8`: the answer `y^(8/7)` builds correctly,
  base `y` with numerator `8` over denominator `7`.

## 0.28.0

### Changed — the add-on declares the one site it works on

`activeTab` was an elegant choice and the wrong one. It is granted only by a
click on the **toolbar button**, which meant:

- the sidebar had no access to the lesson at all — it could not even read the
  tab's URL, and reported that it could not find the tab;
- `tabs.captureVisibleTab` was impossible there, because it needs `activeTab`
  or all-sites access and a single-host permission does not satisfy it;
- and the panel ended up asking the user to grant a permission the add-on
  cannot do anything without — which is not a choice, it is a nag.

`host_permissions` is now `*://learn.hawkeslearning.com/*`: one origin, one
prompt at install, nothing afterwards. The grant button and the optional
permission are gone. The build still fails on anything wider than this single
origin, and `<all_urls>` remains impossible.

This is a real widening of the footprint, and it is deliberate. The add-on
exists to work on one site; pretending otherwise cost more in broken behaviour
than it bought in minimalism.

## 0.27.0

The question is read from the page, not photographed.

### Changed — a solve takes under a second

Hawkes renders with MathJax, which leaves every expression in the document as
presentation MathML. Reading that instead of screenshotting the page:

- **is instant.** Measured on the live lesson: **0.54s**, against roughly a
  minute. Almost all of that minute was the two independent image
  transcriptions, and there is now nothing to transcribe.
- **is exact.** Nothing can misread an exponent that was never rendered to
  pixels, so the two-reader disagreement cannot arise and there is no reading
  to dispute. The answer is reported as `source: markup`,
  `transcription: exact`.
- **needs no screenshot permission.** `tabs.captureVisibleTab` requires
  `activeTab` or all-sites access, and the sidebar has neither — which is what
  produced "the question could not be captured from this tab". Reading the DOM
  needs only the access already used to reach the tab.

A screenshot is still the fallback: a question drawn as an image, or MathML
this converter cannot read exactly, goes through vision as before, with the
two-reader check that applies there.

Only the **exact** solvers run on markup. Without a transcription there is no
independent check on a reading, so handing markup to the model would produce an
answer with nothing behind it; that case falls back to a screenshot instead.

### Fixed

- A power's base keeps its parentheses. `(-2)^6` is 64 and `-2^6` is -64, and
  the grouping the MathML carries is the whole difference; an early version of
  the converter dropped it.
- Only mathematics *above* the answer controls is read. The answer area has
  MathML of its own — whatever has been entered so far — and including it would
  feed the add-on's own output back in as part of the question.

## 0.26.0

### Fixed

- **`y^(3/4) · y^(3/5)` produced no answer at all.** The exponent guard
  admitted only *unit* fractions, so `1/4` passed and `3/4` was rejected — which
  made "express your answer using rational exponents" unanswerable for most of
  its own questions. Small rationals are now accepted; the bounds are what keep
  the evaluation cheap, and a numerator of 1 never had anything to do with it.
  Absurd powers are still refused, and tested.
- **"Grant access to this lesson" appeared to do nothing.** Once the permission
  has been given, requesting it again resolves instantly with no prompt, so the
  button looked inert while the stale error stayed on screen. It now checks
  first and, either way, ends by re-checking the tab — which is what pressing
  it is for.

## 0.25.0

### Fixed — a template could land in the wrong slot

`\sqrt{y^5/(144x^6y^7)}` is `1/(12x^3y)`. The `12x` went into the denominator
correctly and the `^3` that followed it went into the **numerator**, because
setting DOM focus on an input does not move the editor's cursor — it keeps its
own `CurrentBase`, and a template loads onto that.

The editor's object tree is now walked to find the base that owns the box the
plan is working in, and the template is aimed there. Confirmed against the live
tree, which showed the exponent parented to `Numerator` while the denominator
sat untouched beside it.

### Fixed — a disabled control silently swallowed every template

`addElement` skips its entire body when the control is disabled and the call
came from the keypad. Typing still works, because that goes through the DOM.
So on a question whose editor was disabled — after a submit, for instance —
characters landed and structure did not, and nothing reported it. That is a
plain explanation for half-built answers, and it is now refused before
anything is touched, and re-checked before every template in case a submit
lands mid-plan.

### Fixed — the sidebar could not see the tab

`activeTab` is granted by a click on the toolbar button and by nothing else, so
the sidebar had no access to the lesson at all and reported that it could not
find the tab. It now says so plainly and offers the one permission that fixes
it: `*://learn.hawkeslearning.com/*`, declared **optional**, requested from a
click, listed in the add-on's Permissions tab and revocable there.

## 0.24.0

Two things the live run exposed: answers were built only partly, and the panel
kept vanishing with the answer still on it.

### Fixed — a half-built answer was left in the box

`⁷√(y⁴⁹z²⁸x⁴²)` is `x⁶y⁷z⁴`. The solver and the plan were both right; the
executor stopped at the *second* exponent and left `x⁶y` in the box, which was
then submitted and marked wrong.

The cause was typing and pressing in the same turn. The editor updates its
notion of the current box from its own focus handling and had not caught up, so
its guard refused the template. A template is now pressed only once that guard
— `qualifyLoadExponent`, `qualifyLoadFraction`, `qualifyLoadRadical`, the same
ones the editor itself consults — says yes, waiting up to the settle deadline.

**And every failure now clears what it had entered.** Partial content that
looks complete enough to submit is worse than an empty box; that is what turned
a caught, reported failure into a wrong answer.

### Added — the panel can be docked

A toolbar popup is torn down whenever anything else takes focus, which loses
the answer mid-read and makes a minute-long solve impossible to watch. The same
panel is now available as a **sidebar**, which stays put:

- a dock button in the popup header hands over to it, and the solve carries on
  because the work lives in the background page either way;
- `Alt+Shift+S` opens it;
- the sidebar is resizable, so it fills whatever width you give it, while the
  popup keeps the configured width.

## 0.23.0

The panel was broken, and nothing said so. This release fixes that, and then
makes the same class of failure impossible to ship again.

### Fixed — the panel did not work at all

`render()` in `popup/popup.js` read a `const` it declared thirty-eight lines
below itself. A `const` is hoisted but uninitialized until its declaration
runs, so reading it first throws `ReferenceError` — every time, on every state.
The panel therefore opened, printed "Checking…", and never updated again;
Solve, Insert and Reset all threw before sending anything. The whole test suite
passed throughout, because every test read the panel's JavaScript as text and
none of them ran it.

### Added — the panel says when it has failed

- `common/log.js`: one bounded, redacted diagnostic log shared by the panel,
  the event page and the settings page, replacing about thirty bare
  `catch {}` blocks. 200 entries, `storage.local` only, cleared with one
  button.
- **Answers, recognized problems and screenshots are never recorded** — only
  their shapes, e.g. `{answerLength: 4}`. The redaction is enforced centrally
  rather than left to each call site, and the profile UUID is stripped from
  every stack, because the log is meant to be pasteable.
- Uncaught exceptions and unhandled rejections are caught in every context. In
  the panel they raise a **fault banner** offering the log and a reload,
  instead of leaving a frozen panel. `render` can no longer throw silently.

### Added — checks that would have caught it

- The build now rejects a `const` or `let` read above its own declaration in
  the same block. Verified against the 0.22.0 bug itself.
- The build now rejects `querySelector("#id")` for an element the page does not
  contain — the same total failure, reached by renaming an element.
- `common/panel-view.js` is new: every decision the panel makes, as plain data,
  with no DOM and no `browser`. `tests/test_hawkes_panel.py` runs it under
  QuickJS against all eight phases. The panel itself is now only assignments.

### Changed — Firefox's own design language

`common/theme.css` is rebuilt on Acorn, the design system Firefox is built in:
its panel surfaces, its in-content text, its `#0060df` / `#00ddff` accent, its
4px control radius and its 2px focus ring at 2px offset. One `light-dark()`
definition per colour instead of a light block and a dark override that could
drift apart. The toolbar icon moved to the same blue.

- **High contrast**: every colour is replaced under `forced-colors`.
- **Reduced motion**: no transition runs outside a `prefers-reduced-motion`
  query. Asserted for all three stylesheets.
- **No white flash**: both pages declare `color-scheme` before their stylesheet,
  so a dark-theme popup no longer opens as a white rectangle.

### Changed — the panel

- Focus starts on the primary action, and moves to **Insert** when a solve
  finishes — but only if it is still where the panel put it. Previously the
  footer said "Enter to insert" while the caret sat on Solve.
- The answer can be **copied**, which matters exactly where insertion is
  refused: an option question, or notation the editor forbids.
- Repaints are coalesced into one animation frame, so a burst of stage updates
  cannot outpace the display.
- A failure relabels the primary button **Try again**, rather than repeating
  "Solve".
- Ctrl+Enter reaches Solve even when Insert is primary.
- If the event page is unloaded, the panel says so instead of sitting on a
  state that can no longer change.
- The source badge no longer draws an empty chip before anything has answered.

### Changed — settings that do something

The page offered a text box for a fixed answer, left from before there was a
solver, beside one working checkbox. Everything that actually governed a solve
was a constant. `common/settings.js` now declares each preference once — type,
default, bounds — and both the page and the event page read that declaration.

- **Automatic solving** (kept). Automatic *insertion* is deliberately not a
  preference, and there is a test asserting it never becomes one.
- **Solve timeout**, 30–900s. Was a hardcoded four minutes.
- **Crop the capture to the question**. Was always on; off gets the whole
  viewport read when a question is laid out unusually.
- **Panel width**, 300–560px. Firefox sizes a popup to its content, so this is
  the only control there is over it.
- **Show the recognized problem expanded.**
- **Keyboard shortcut**, rebound through `browser.commands` — Firefox's own
  mechanism, needing no permission.
- **Test connection**: asks the native host to identify itself. It loads no
  model, so it answers at once, rather than a solve spending a minute finding
  out.
- **Diagnostics**: log level, a live view, copy, and clear.
- **Restore every default.**

A stored value that is missing, mistyped or out of range falls back to the
declared default: a corrupt preference costs you the preference, not the
add-on. A number *typed* out of range is instead pulled to the nearest end of
it, because someone entering 9999 into a field labelled "30 to 900" means the
maximum, not the default.

### Fixed — the browser harness had been failing every scenario

`scripts/run_extension_harness.py` repointed the content scripts at the fixture
origin but not `background.js`, where the tab gate has lived since the event
page was introduced, so every scenario failed on `errorWrongSite`. Its
`url.protocol` rewrite was still aimed at `popup.js`, which stopped containing
that check at the same time. Three scenarios also still expected the
pre-solver panel, which offered a fixed answer for insertion the moment a field
was found. All five pass again.

### Fixed — a copied diagnostic could miss its last lines

`flushLog()` resolved immediately whenever a write was already in progress, so
`await flushLog()` followed by a read returned stale entries — precisely when
copying the log after a failure.

### Permissions

Unchanged: `activeTab`, `nativeMessaging`, `scripting`, `storage`. No network
transport was added, and the log does not become the first one.

## 0.22.0

Presentation and documentation brought up to date.

### Changed — the panel keeps one shape

Every region is now always present and holds its height, so moving between
idle, solving and solved no longer reflows anything. Previously a stage
checklist, a detail block and a third and fourth button appeared and vanished,
and the answer box changed font size when empty — so the layout jumped on
almost every state change.

- Four buttons that wrapped unpredictably are now **two in a fixed grid**.
  Solve becomes Cancel while a solve runs, in the same slot, so the row never
  reflows. Reset and Details moved to the footer as links.
- The four-line stage checklist is now **one progress bar and one line of
  text**.
- The answer area has a fixed height, so a single character and a stacked
  fraction occupy the same space.
- The status line reserves two lines, so a message that wraps does not move the
  buttons.
- The header carries the add-on name once, rather than an eyebrow and a
  heading saying much the same thing.

### Documentation

- `TESTING.md` rewritten. It described a build with no background page, a fixed
  test answer, and none of structured building, option questions, automatic
  solving, cancelling or the question-change reset.
- The superseded pre-implementation plan is now a short signpost to the current
  documents. It described a protocol, permission set and insertion strategy the
  built add-on does not follow, and several of its assumptions turned out to be
  wrong once the editor was observed.
- `homepage_url` pointed at that superseded plan; it now points at the add-on's
  own README. The repository doc index did too.

## 0.21.2

### Fixed

- **Clicking the toolbar button again would not close the panel.** Not an
  add-on bug: the development harness had set Firefox's
  `ui.popup.disable_autohide`, which keeps a panel open for inspection and in
  doing so disables the normal toggle and click-away dismissal. The harness no
  longer sets it.

### Added

- A close button in the panel header, next to the source badge. Escape already
  worked but was not discoverable.

## 0.21.1

### Fixed

- **An option question still needed a radio focused, which is circular.** On a
  typed question the caret says where the answer goes; on an option question
  clicking a radio *is* answering, so requiring focus first meant choosing
  before being told what to choose. The question's own option group is the
  signal now, and nothing needs clicking before the panel finds it.

## 0.21.0

### Fixed

- **A radio-button question would not solve at all.** `inspectField` only
  looked for text fields, so a focused option read as "no answer field" and the
  whole flow stopped before it ever reached the solver — even though the
  page-world probe correctly identified it as an option control. Observed on
  `√(-121)`, answered by choosing "Not a Real Number".

  An option question is now found like any other: it is solved, the answer is
  shown, and only the selecting stays the user's.
- The planner refuses an option question outright, rather than producing a plan
  to type into a radio button. It also refuses to type when the editor
  publishes no character set at all — typing blind is how the editor's
  refusal dialog appears.

## 0.20.0

Fewer steps per question.

### Changed

- **The panel resets itself after inserting.** The answer is in the box, so
  holding on to it only meant showing stale information next time. Everything
  about the finished question is dropped — including the signature, so the next
  check treats whatever is on screen as new and finds its answer field afresh.
- **Solving starts as soon as the answer field is found**, removing a click per
  question. It can be turned off in Settings; Cancel is always available. On by
  default, since the field is only found after you have deliberately opened the
  panel on a question.
- The inserted message now says what to do next rather than only what happened.

## 0.19.2

### Fixed

- **Structured answers were entered only partly.** The executor waited for the
  box list to *change* after loading a template and then read it. But
  `Fraction` adds three boxes — numerator, denominator, and the continuation
  after it — and they do not all appear in the same tick. Reading at the first
  change captured only some of them, so the slots recorded for that template
  were wrong and every later move went to the wrong box.

  Observed live on `⁴√(x¹²y⁸/16)` = `x³y²/2`: the box ended up with `x³y` over
  an empty denominator, missing the exponent on `y` and the denominator
  entirely. The same plan, run with a pause after each press, entered all ten
  steps correctly — which is what identified this as a race rather than a
  logic error.

  The wait now requires the list to *settle*: changed, then unchanged for three
  consecutive polls, with a longer deadline.

## 0.19.1

### Fixed

- **The ready message read as an instruction to the user.** "Insert to build it
  with the keypad" parses as "you build it with the keypad", so a working
  build looked like a refusal and the panel appeared stuck. It now says the
  add-on does it: "press Insert — it builds this with the keypad for you."
- **Insert becomes the primary button** once there is something to insert, so
  the next step is visible rather than described. Solve steps back to
  secondary.

## 0.19.0

### Fixed

- **"The two readers disagreed" on questions where they plainly agreed.** Both
  readings of `1/(6n^-5)` were identical, but one reader wrote the escape `\n`
  as two literal characters before the expression, which defeated the
  line-based check that exists to rescue exactly this case — and the other
  decomposed the expression into `["1","6","n","5"]`, single characters that
  are not a list of expressions. The comparison now normalises the escape and
  ignores fragments with no structure, so it compares the mathematics rather
  than the bookkeeping.

  The safety property is unchanged and tested in both directions: a genuine
  difference — `6n^-4` against `6n^-5` — is still caught and still blocks
  insertion. A reading nobody can confirm is worse than no answer.

## 0.18.0

### Fixed

- **The panel stayed on the previous answer.** Hawkes swaps the answer
  controls in place when it moves to the next question — nothing navigates —
  so the reset that hung off `tabs.onUpdated` never fired. The control's
  identity and published rules now stand in for "which question", the panel
  re-checks on every open rather than only the first, and an answer is carried
  over only while the question is genuinely unchanged.
- **Cancel did not stop anything.** It set an abort flag, but the native port
  stayed open, so the host kept working and holding the model for the rest of
  the minute while the panel claimed it had stopped. Cancelling now rejects the
  request, which disconnects the port, closes the pipe and ends the host. The
  panel also looks stopped the instant it is clicked.
- **The planner read a plain answer box's rule as a literal character set.**
  A textbox publishes `[0-9-]`; read literally that string holds `[`, `0`, `-`,
  `9`, `]` — not `6` — so the planner rejected `64` for a box that plainly
  accepts it. It shared the correct check with `editor-rules` instead. This
  never bit, because the typeable path answered first, but it would have
  reported the wrong reason on any question where neither path worked.

### Added

- A **Reset** button, to clear the panel and re-check the current question.
- The recognized problem is now a fold, closed by default — it is there to
  check against the screen when you want it, not to fill the panel.

## 0.17.0

Responsiveness, and the bug that made 0.16.0's builder unreachable.

### Fixed

- **The Insert button was disabled for exactly the answers the builder exists
  to handle.** 0.16.0 wired structured building into the background but left
  the panel disabling Insert whenever an answer was not *directly typeable*,
  so it could never be triggered — the panel just said "build it with the
  keypad". The button is now enabled when the answer is typeable **or**
  buildable, and says which is about to happen.

### Added

- **Stage-by-stage progress.** The host reports each stage as it begins —
  capturing, reading, checking the reading, solving — and names the model or
  solver doing it. The panel shows a checklist with the current stage marked,
  instead of one static line for the whole minute. This needed a native
  **port** rather than a one-shot message, since a single reply cannot carry
  progress.
- **The screenshot is cropped to the question.** The answer panel, keypad and
  footer are most of the viewport and none of the question; the cut is taken at
  the top of the answer controls, so it needs no fragile selector. The two
  image readings are almost the whole of a solve, so sending less is the
  cheapest speed-up available. An uncropped question still solves if measuring
  fails.
- A distinct message for an answer needing a template the question does not
  offer, separate from one that merely cannot be typed.

## 0.16.0

Structured answers are entered, not just displayed. End to end.

### Added

- **`common/page-actions.js` — the executor.** It runs in the page's own world
  and performs a plan: typing into answer boxes and pressing the editor's own
  keypad templates. Passed to `executeScript` as a function rather than a file,
  which is what lets the plan be an argument.
- It keeps a **stack of template frames**, so "go to the denominator" returns
  to the fraction rather than to a radical opened inside it — and it predicts
  no box ids, taking the newly focused box after each press.
- **Radicals are planned.** `√(6y/(5z))` → `√(30yz)/(5z)` is now built
  automatically: fraction, radical in the numerator, then the denominator.
  Verified on the live lesson.

### Changed — footprint

This is a deliberate widening, and it is the first time the add-on **writes**
through the page's world. Until now the only page-world script was a read-only
probe, and the build enforced that.

The reason it is necessary: structure cannot be typed. Hawkes builds it by
calling `keyPadButtonClick`, a page-owned method, and refuses characters like
`/` and `(` outright with a blocking dialog. There is no synthesized-event
route — a trusted click does not work either.

The writer is bounded, and the build enforces every bound: it may type into
answer boxes and press named templates, and it may not `eval`, click page
elements, navigate, make requests, write markup, or submit. No third file may
reach the editor model.

## 0.15.0

### Fixed

- **The panel showed unreadable ASCII.** For `√(6y/(5z))` it displayed
  `sqrt(30)*sqrt(y)*sqrt(z)/(5*z)` while `√(30yz)/(5z)` was sitting right
  there. The cause was conflating two different questions: what can be *shown*
  and what can be *typed*. The answer is now always displayed in its readable
  form, and insertability is decided separately — so an answer you have to
  enter by hand is still legible.
- **Split radicals are written as one.** SymPy splits a root over a product and
  keeps it split, so `√(6y/(5z))` came out as `√30·√y·√z/(5z)` instead of
  `√(30yz)/(5z)`. Merged per part of the fraction, and built unevaluated —
  `sqrt(5*x)` splits straight back the moment SymPy evaluates it for a positive
  variable. `9/√(5x)` improves from `9√5√x/(5x)` to `9√(5x)/(5x)` as well.
- A compound denominator keeps its parentheses in the panel: `1/(12x^7y)`, not
  `1/12x^7y`, which reads as `(1/12)x^7y`.

## 0.14.0

### Added

- The planner handles **rational exponents** — `y^(3/2)` becomes an exponent
  template with a fraction nested inside it. This was the third question in a
  row needing that shape, and the first two had to be entered by hand.

### Fixed

- "Convert the given radical expression to rational exponent notation" produced
  `(y^3)^(1/2)`: equivalent, but not the single rational exponent asked for.
  SymPy only collapses a nested power when the variable is known non-negative,
  and that assumption had been limited to simplification and rationalisation.
  Now `sqrt(y^3)` gives `y^(3/2)` and `cbrt(x^5)` gives `x^(5/3)`.

### Verified

- A plan produced by `editor-plan.js` was executed against the live editor by a
  generic runner that predicts no box ids — it diffs the visible boxes across
  each template press and takes the newly focused one. Two levels of nesting,
  no dialog. The algorithm is written up in `docs/HAWKES_EDITOR_FINDINGS.md`.

## 0.13.0

Robustness from the failures found by exercising the paths that had never run.

### Fixed

- **Prose answers were mangled.** The first successful model-path solve —
  `√(-324)` → "Not a Real Number" — came back as
  `N*o*t*a*R*e*a*l*N*u*m*b*e*r`, because the maths keyboard conversion treats
  adjacent letters as factors. Prose answers now skip that conversion.
- **Option questions are recognised.** Some questions are answered by choosing
  a radio button rather than typing, and the editor reports those as `opt`
  controls with no value. The panel now says so and shows the answer for you
  to select, instead of reporting that no answer field was found.
- **An answer that only needs manual entry no longer reads as an error.**
  Choosing an option, or building a fraction with the keypad, leaves the
  answer perfectly good — the panel now presents those as instructions rather
  than in red.
- The page-world write check matched `boxValue === undefined`, a comparison,
  and flagged the read-only probe as writing. It now matches assignment.

### Verified

- The model fallback path, which had never once succeeded — it crashed on a
  settings attribute that does not exist, and the fix was untested. It now
  answers correctly, and reports `source: model` so the panel can say the
  answer did not come from the exact solver.

## 0.12.2

### Fixed

- The panel and the background now talk over a **port** instead of one-off
  messages. Two separate console errors came from the old arrangement, both
  seen live: a request the panel was awaiting when it closed, and state pushed
  to a popup that had already gone. A port needs no reply, and disconnects
  cleanly, so neither can happen.
- An operation started from the panel can no longer leak an unhandled
  rejection; failures are reported as state like any other.

### Changed

- The `postMessage` prohibition is now scoped to what it was protecting
  against — a DOM message channel with the page — rather than banning
  extension port messaging along with it. Content scripts still may not use
  any form of it.

## 0.12.1

### Fixed

- Closing the panel mid-operation logged an uncaught rejection —
  *"Promise rejected after context unloaded: Actor 'Conduits' destroyed"* —
  because the panel awaited replies to operations that outlive it. Observed in
  Firefox's console on 0.12.0. The panel now awaits only the fast state read
  and receives progress as pushed state, and the background replies before
  starting work rather than after finishing it.

## 0.12.0

Hardening, from the failures this project actually hit.

### Fixed

- **The background page now uses static imports in a module event page.**
  0.11.0 shipped dynamic `import()` inside a classic background script, which
  is not a documented capability — if Firefox had refused it, nothing would
  have worked and the panel would only have said "could not be inspected".
- **An open Hawkes message box is reported as itself.** While one is up it
  holds focus, the editor reports no focused control, and every `focus()` fails
  silently — so any attempt in that state looks like an unrelated bug. This
  cost hours of live debugging; now the panel says to close the box. It
  outranks every other frame report, because they are all consequences of it.
- **A lapsed tab grant is named.** `activeTab` lasts until the tab navigates;
  when it expires Firefox reports a missing host permission, which reads as a
  defect rather than "click the toolbar button again".
- **A solved answer can no longer leak into the next question.** The insertion
  script reads the answer from storage, so navigating away now clears it —
  otherwise the previous question's answer stayed insertable, and Hawkes
  randomises the question every time.

### Added

- A deadline on every page operation, so an unresponsive lesson fails with a
  clear message instead of hanging the panel.

## 0.11.0

A usable panel. The solve no longer dies when the popup closes.

### Added

- **A background event page owns the work.** A popup closes the moment
  anything else takes focus, and a solve takes the better part of a minute, so
  it used to be lost to a stray click along with its whole JavaScript context.
  The solve now runs in `background.js` and the panel is a view onto its state:
  close it, reopen it, click elsewhere — the solve carries on and the panel
  shows wherever it got to. This is the add-on's one resident context, it is a
  non-persistent event page, and the build keeps it that way.
- **`health` is checked before a capture is spent.** It needs no model, so an
  unregistered native host is reported in a moment instead of after a minute
  of transcription.
- **Cancel.** An in-progress solve can be abandoned rather than only waited
  out, via an `AbortController` the background holds.
- **Elapsed seconds and a pulse on the status line**, so a long solve looks
  alive rather than stuck.
- **Keyboard**: Escape dismisses the panel, Enter inserts when insertion is
  available. `Alt+Shift+E` opens the panel.
- A badge naming which stage answered (`symbolic`, `polynomial`, `model`), and
  the technical detail line folded behind a **Details** toggle rather than
  always occupying the panel.
- A distinct message when the screenshot itself fails, instead of the generic
  "could not be inspected".

### Changed

- Navigating the solved tab clears the state, since the answer field it found
  no longer exists.
- `common/bridge.js` is gone; the background page talks to the host directly,
  and nothing else may.

### Removed

- The `guard()` backstop in the popup. The panel no longer runs async work, so
  there is nothing left there to leak an unhandled rejection.

## 0.10.0

Structured answers are now planned, and the editor mechanism that builds them
is understood and documented.

### Added

- `common/editor-plan.js`: `planEntry()` turns an answer into the ordered plan
  of typing and template presses the Hawkes editor needs — exponents and one
  top-level fraction, including an exponent nested in a denominator. It refuses
  what it cannot build rather than entering it partially.
- `tests/test_hawkes_plan.py` runs it under QuickJS against the two plans that
  were verified by live entry: `x^6yz^5` and `1/(12x^7y)`.
- The full mechanism is written up in `docs/HAWKES_EDITOR_FINDINGS.md`,
  including why a template needs a base, why the refusal dialog was mistaken
  for a character rejection, and how slot boxes are found by diffing the
  visible box list across a template press rather than by predicting ids.

### Fixed

- Questions asking to "express your answer using rational exponents" were
  answered with a radical, which is marked wrong. SymPy prints
  `a**Rational(1,2)` as `sqrt(a)` and will not rewrite it, so that display is
  now inverted for those questions: `a^(1/6)·a^(1/3)` returns `a^(1/2)`.
- The expression parser rejected any braced exponent that was not a plain
  integer, so `a^{\frac{1}{6}}` failed outright as "unsupported characters".

### Still to come

The plan is not executed yet. Pressing a template is a *write* into the page's
world, and the shipped page-world probe is deliberately read-only with the
build enforcing it. Wiring the executor is a footprint decision as much as a
coding one; see "Footprint consequence" in the findings document.

## 0.9.2

### Fixed

- Radical simplification returned the question as its own answer. SymPy will
  not extract a root without knowing the variables' signs, and lesson 1.2's
  question 9 -- unlike question 8 -- does not say they are positive, so the
  fifth root of `y^5 x^30 z^25` came back unchanged. Radical-simplification and
  rationalisation now assume the exercise convention Hawkes itself marks
  correct; factoring and plain algebraic simplification still assume nothing.

### Added

- `scripts/live_browser.py solve`: the whole loop in one command — screenshot
  the live question, read the editor's rules, solve with the native host,
  choose the form the editor accepts, insert, and read back. It uses the
  shipped host and the shipped content scripts rather than copies.

## 0.9.1

### Fixed

- The popup inserted Ethnos's explicit ASCII form, so the verified answer `3y`
  was offered as `3*y` — and `*` is not in that question's accepted set, so the
  correct answer would have been refused. It now tries the displayed form
  first and falls back to the explicit one, choosing whichever the editor
  accepts.

## 0.9.0

Insertability now comes from the Hawkes editor itself instead of a guess.

### Added

- `content/hawkes-describe.js`, the one script that runs in the page's own
  world. Hawkes drives its editor through a page-owned `quant_wp_UI` model that
  an isolated content script cannot see, and that model publishes, per
  question, the exact character set the answer box accepts, its maximum length,
  and which keypad templates the question permits.
- `common/editor-rules.js` decides insertability from that description, with
  `tests/test_hawkes_rules.py` running it under QuickJS against the real
  descriptions observed on a live lesson.
- Refusals now name the cause: which characters the box rejected, or which
  template the answer needs.

### Fixed

- The old rule refused any answer containing `(`, `)`, `/`, or `.`. That was
  wrong in both directions: it is per question. One question in lesson 1.2
  accepts `0123456789y`, and the next accepts `[0-9.-]` — where a decimal point
  is required, not forbidden.
- The host read `settings.ollama_num_predict`, which does not exist, so every
  question the exact solver could not answer failed after the transcription had
  already run. It is `ollama_answer_num_predict`.

### Note on the MAIN world

Running in the page's world is a real trade. While that probe runs, the page
can observe it — so the add-on is no longer strictly undetectable, and the
"Page footprint" section in `README.md` is qualified accordingly. It buys the
only access that works: the rules are not exposed anywhere else, and without
them the add-on either guesses or triggers Hawkes's blocking
"character not required" dialog. The probe is read-only, takes no arguments,
declares nothing on the page, and the build fails if it ever writes.

## 0.8.0

Ethnos is connected. The add-on no longer carries a fixed answer.

### Added

- **Native messaging bridge.** `common/bridge.js` speaks a versioned protocol
  to `ethnos_hawkes`, a local host Firefox starts itself for this extension
  only. Nothing listens on a port, so no other program or page can reach it.
- **Solve with Ethnos.** The popup captures the visible tab, sends it to the
  host, and shows the recognized problem beside the answer for review. The
  screenshot goes to a local process and is not retained.
- The host runs the existing pipeline: two-reader image transcription, then the
  exact sympy solver, the polynomial solver, and only then the language model.
  The panel reports which one answered.
- An answer is insertable only when both readers agreed about the question, and
  only when it contains no parentheses, slash, or decimal point -- the Hawkes
  field silently discards those, so structured answers are shown to be entered
  by hand rather than half-inserted.

### Changed

- `nativeMessaging` is the one new permission. It is forbidden in anything
  injected into the page, along with `captureVisibleTab`, and the build
  enforces that: the page an injected script runs in is not trusted.
- The stored answer is now whatever Ethnos last solved. The preferences page
  remains a manual override for testing insertion.
- The panel's standing note no longer claims the add-on cannot contact Ethnos.

## 0.7.2

### Fixed

- A third-party subframe reporting `wrong-site` outranked everything else, so a
  page carrying any unrelated frame told the user to "open this panel from a
  Hawkes lesson tab" while they were already on one. Only the top frame can
  decide the tab is the wrong site. Found by the browser harness.

## 0.7.1

### Fixed

- **Injection never worked from the popup.** `scripting.executeScript` resolves
  `files` paths against the *calling document*, not the extension root, so
  `"content/hawkes-editor.js"` became `popup/content/hawkes-editor.js` and threw
  "Unable to load script" inside every frame. The popup reported this only as a
  generic failure. Paths are now root-absolute (`/content/...`).
- `scripts/build_extension.py` now rejects any injected path that is not
  root-absolute or does not exist, so this cannot recur.

### Added

- `scripts/run_extension_harness.py` and `scripts/harness/marionette.py`: the
  add-on is driven in a real Firefox against local fixtures, installed
  temporarily over Marionette in a throwaway profile, with `activeTab` granted
  by a real click on the toolbar button. This is what found the path bug —
  every earlier probe ran from a background script at the extension root, where
  the broken path happened to resolve.

## 0.7.0

Diagnostics, after 0.6.1 failed its first live run with a message that said
nothing useful.

### Added

- The popup shows a technical detail line under the status when something
  fails: per-frame reason codes, thrown messages, and which operation was
  running. Reason codes and frame ids only — never page content.
- `describeResults()` in `common/frames.js` builds that line.
- The operation scripts check for the shared prelude with `typeof` and return
  `prelude-missing` rather than throwing a bare `ReferenceError`, which
  `InjectionResult.error` would have reduced to a generic failure.

## 0.6.1

### Added

- `TESTING.md`: the live verification protocol — eight checks against a real
  lesson, each with its expected result and what a failure points at, including
  the event-dispatch ladder to try if the editor ignores an insertion and the
  stickiness to watch for in the ambiguous-frame case.

### Fixed

- Every async entry point now runs through a `guard()` backstop, so a fault in
  a handler's own error reporting cannot surface as an uncaught promise
  rejection in the add-on console. This covers `initialize()`, the insert
  handler, and `openOptionsPage()`.

## 0.6.0

The frame-selection logic is now exercised rather than assumed.

### Added

- `common/frames.js`: `selectAnswerFrame()`, the decision about which frame may
  receive an answer, extracted free of DOM and `browser` API access so it can
  be run directly.
- `tests/test_hawkes_frames.py` runs that shipped source under QuickJS against
  the `InjectionResult` arrays Firefox would return, covering top-frame,
  same-origin iframe, cross-origin, unreadable-origin, no-focus, ambiguous, and
  malformed results. `quickjs` is a new dev dependency; the suite skips the
  file if it is absent.
- A frame whose focus sits in a child now reports that child's **origin**, and
  the popup names it: the message says which single host would have to be
  granted rather than only that something is out of reach. Only the origin is
  read, never the full URL.

### Changed

- Two frames claiming the caret at once is now refused as `ambiguous-frame`
  instead of silently taking the first. A sibling frame can hold a stale
  `activeElement`, and guessing would type the answer into the wrong document.
- A claim carrying no `frameId` is no longer treated as success, since the
  insertion targets a frame by id.
- `message()` and the popup's `setStatus()` accept substitutions.

## 0.5.0

Correctness pass on the signing metadata, and a tighter content-script scope.

### Changed

- `strict_min_version` is now `140.0`, the first Firefox that understands the
  data consent declaration. Below it the disclosure is silently ignored, so
  pinning there means users actually see it.
- `content/hawkes-editor.js` is an IIFE that exposes one name,
  `ethnosHawkes`. Everything else is local to a single execution rather than
  sitting in the frame's shared extension scope. The one exported name stays a
  `var`, since re-injection would trip over a lexical redeclaration.
- The operation scripts call through that namespace, so neither leaves a
  declaration of its own behind.

### Added

- The drift check now also ties the content script's allowed origin to
  `ALLOWED_HOSTNAME`, and compares the answer pattern by name rather than by a
  hand-maintained alias table.
- A test asserting `data_collection_permissions` is an object whose `required`
  array is exactly `["none"]` -- the shape AMO validates, which is neither a
  bare array nor the value `none_required`.

## 0.4.0

Hardening pass against extension-fingerprinting techniques, and the frame
handling a real Hawkes lesson needs. Still not connected to Ethnos.

### Changed

- Replaced the message-listener bridge with three injected files whose results
  come back as `scripting.executeScript` completion values:
  `content/hawkes-editor.js` (shared sandbox helpers),
  `content/inspect-field.js`, and `content/insert-answer.js`. Nothing is
  registered on the page, so no state survives a call and repeat use is
  idempotent without an injection marker.
- The shared prelude declares only `var`s and functions. Firefox gives an
  extension one scope per frame, so a top-level `const` would throw a
  redeclaration error when the file is injected a second time.
- The popup inspects every frame in the tab and inserts into the single frame
  that claimed the caret, so an editor inside an iframe now works. A frame
  whose focus is in a child reports `focus-in-subframe`, which lets the popup
  distinguish a cross-origin editor frame from nothing being focused.
- `insert-answer.js` reads the answer from storage and returns what it
  inserted; the popup rejects a value that differs from the one on screen.

### Added

- Build and test rules forbidding the content-script isolation escapes (the
  unwrapped page object, and the clone and export helpers), `.prototype.`
  assignment, `defineProperty`, `insertCSS`, `chrome.*`, a `background` key,
  and any request-interception key.
- A drift check tying the content scripts' copies of the answer pattern,
  length limit, storage key, and default to `common/config.js`.
- README sections on the page footprint and on frame handling, recording why
  there is no Shadow DOM here and how Firefox's per-profile `moz-extension`
  UUID changes the fetch-probing picture.

## 0.3.0

First build intended to look and behave like a real add-on rather than a
scratch proof of concept. Still not connected to Ethnos.

### Added

- Icon set rendered from `icons/icon.svg` at 16, 32, 48, 96, and 128 px.
- Full localisation through `_locales/en/messages.json`; no user-visible string
  is hard-coded in markup or script.
- Preferences page for the inserted answer, with shared validation and a
  restore-default action.
- `content/hawkes-field.js`, a reviewable isolated-world content script that
  answers two named messages, replacing serialized injected functions.
- `scripts/build_extension.py`: validation plus a reproducible XPI build. It
  also enforces the page-footprint rules: no `web_accessible_resources`, and no
  DOM, stylesheet, `window`, or page-message writes from the content script.
- This changelog, an expanded README covering permissions and removal, and a
  shared light/dark stylesheet.

### Changed

- Renamed from "Ethnos Hawkes Answer POC" to "Ethnos Hawkes Assistant"; the
  add-on ID is now the permanent `ethnos-hawkes@local`.
- The manifest declares an author, homepage, `strict_min_version`, an explicit
  extension-pages CSP, and `data_collection_permissions: none`.
- The inserted answer is configurable and validated instead of the hard-coded
  literal `11y`, which is now only the default.
- Errors are reported as reason codes mapped to catalogue messages, rather than
  as thrown English strings.
- The popup probes for an existing bridge before injecting one, so the content
  script no longer needs an injection marker on the page's `window` and the
  add-on leaves nothing on the page for a site script to fingerprint.

### Removed

- The committed `.xpi` artifact; builds now go to the ignored `dist/`.

## 0.2.0

- Added a preview step and an explicit **Insert 11y** button.

## 0.1.0

- Verified that a user-triggered add-on can insert a fixed value into the live
  Hawkes math editor.
