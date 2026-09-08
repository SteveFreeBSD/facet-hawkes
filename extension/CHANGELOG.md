# Changelog

All notable changes to the Facet Hawkes Assistant add-on. Versions follow
`major.minor.patch` as required by the Firefox manifest. Entries below 0.44.0
name the add-on as it was called at the time.

## Unreleased

- **Nothing reaches the answer card unless it is an answer to the question on
  screen.** A quadrant question showed "all answers as they would ordinarily be
  written" -- Facet's own description of the line it asks a model to write,
  echoed back instead of answered. The two guards that should have stopped it
  had a hole exactly between them: a multi-part reply took its readable form as
  the reviewed answer without validating it, and the display guard beside it
  "fell back" to that same unvalidated string, so the fallback was a no-op and
  the sentence was published twice over. The previous fix checked the display
  and missed this, because on that branch the two fields were the same string.

  There is one gate now, at `update()` -- the single place every state change
  passes through on its way to the card, to the session store, to a restored
  question and to a failure record. It is asked of the state about to become
  current, against the shape the question published: a plan belongs to a graph
  question and carries no typed value; separate values must each be a valid
  answer and must match a count the page stated; a single value is not an
  answer to a question with several controls; several typed values are not an
  answer to one answered by choosing; and a readable form never stands alone --
  something validated has to be behind it. An answer that fails is withheld
  rather than shown, the card says so, and the diagnostic ring records the
  reason code and the length, never the text.

  The rule for readable text is about shape and not about any sentence: an
  answer is written in mathematics, and where it names itself -- "Not a Real
  Number" -- it does so in three words at most. Its first version let anything
  containing a digit through, which is most of a contract. Facet holds the same
  rule at its own end and no longer offers a line worth echoing.

- **A solve no longer leaves the computer and comes back.** The companion
  reached Facet with `ssh steve@192.168.0.247 facet-remote` -- this machine's
  own address -- so every question went out to the network, through sshd and a
  login shell, and arrived back where it started. It now runs `facet-remote` as
  a local subprocess. `facet-remote` is still the boundary, still its own
  isolated `uv tool` installation, and still speaks the same protocol on
  standard input; an exact solve returns byte-identical provenance either way,
  and a median of about 160 ms sooner (202 ms against 363 ms, measured over
  seven runs each). SSH is retained as an explicit transport for a Facet that
  genuinely runs on another machine, and is never fallen back to in either
  direction. The privacy notice is updated: in the default configuration a solve
  now involves no network at all. Nothing about solving, routing, insertion, or
  Answer Cadence changed.

- **The answer card shows the answer, not the spelling it travelled in.** The
  distance between `(7,0)` and `(-3,-1)` was solved exactly and reached the
  panel as `sqrt101`, beside "This question's answer box does not accept: s" --
  the `s` of `sqrt`, which in the panel's face reads as a 5. One defect, twice:
  the host's machine form is deliberately explicit so that nothing on a wire
  can misread it, and it was being shown to a person and handed to the entry
  planner unconverted. That question's editor publishes `0123456789-` and a
  Radical template, so the letters were refused one at a time against a
  question that needed no letters typed at all. The conversion is now made once
  and shared: the card reads `√101`, and Insert builds it by pressing the
  question's own Radical template and typing `101` into the radicand slot it
  opens. Nothing about solving, or about which characters an editor accepts,
  changed.
- **An insertion refusal now belongs to the answer that produced it.** The
  event page's state is merged rather than rebuilt, so a refusal and its
  arguments outlived the answer they were raised for and landed on the next
  one's card, naming a character that answer does not contain. A refusal is
  stamped with the answer it was about and shown only while that is still the
  answer; a new question drops it outright, and a fresh solve clears it. A
  fault that is not about a value -- a lost tab, a page that is not Hawkes --
  carries no stamp and is always shown, because clearing those early would hide
  a live one.
- **The prompt's own instructions can no longer be mistaken for an answer.**
  The host builds its model contract out of English sentences, and a model that
  echoes one back instead of answering hands it over as the answer -- which is
  how "all answers as they would ordinarily be written" reached the card. The
  machine form was checked against that all along; the readable form was
  published unchecked. It now has to be an answer too, and falls back to the
  checked form when it is not. The named escapes Hawkes really does ask for are
  short and are kept.

- **A cell already showing a fraction is selected through the half the page is
  actually in.** Reloaded onto the fix below, the live refusal named its own
  gate: `blank 1, written 0, why mirror, mirrorIndex 1, wantedIndex 0,
  routed []`. Two things that had been guessed at. The page publishes no
  element-valued property this add-on can enumerate, so the element half of the
  selection proof reads back empty and the editor's own mirror is the whole of
  the evidence -- and a cell already showing a fraction is being edited through
  its *denominator's* control, so requiring the cell's own control by name
  refused a table nobody had touched. Selection is now asked of one exact box,
  because every write is aimed at one: an expanded cell is emptied through its
  denominator first, which is where the page already is, and the value is then
  typed through the cell's own box, each proven separately. Accepting either
  half as "this cell" is not enough -- that types the numerator into the
  denominator -- and the crossing this proof exists to catch still fails it.

- **One fraction in a table no longer makes every cell of it unwritable.** With
  Insert finally reachable, the writer refused with nothing written at all --
  `table-cell-not-selected`, blank 1, three runs running -- on a table that
  already had one cell expanded into a numerator and a denominator by hand, and
  refused at blank 3 on a run where it had expanded blank 1 itself a moment
  earlier. The proof that Hawkes has selected a cell read the page's router as
  "every element-valued property the editor model publishes", and required all
  of them to name that one cell. That held only while a table had one box per
  blank. Hawkes keeps references to a drawn fraction's two halves for as long
  as it is on screen; they are furniture rather than a selection, and they do
  not move when the editor leaves that cell. So one fraction anywhere in the
  grid made every cell in it unselectable. Selection is now proven by the page
  naming *this* cell -- either of its halves -- alongside its own mirror naming
  this cell's control. The crossing this proof exists to catch still fails it,
  because there the page names the other cell and never this one, and every
  write is still read back against its own cell and every other cell of the
  table. A refusal now also says which half of the proof failed and what the
  router held, so the next one does not cost a look at the owner's screen.

- **Insert is offered for a table of fractions, not just written for one.** The
  writer had already learned that a Hawkes answer cell owns a numerator control
  and a denominator control, and that typing `/` opens the pair -- but the rule
  deciding whether to offer Insert at all had not. It judged `16/9` as one
  whole value against one box, saw the `/`, and named a keypad template the
  question does not publish and that this entry never needed. Live, that
  refused all four values of a four-blank table Facet had answered exactly:
  `cellFit` was `answer-needs-template` four times over four correct answers,
  and the button stayed grey. A cell that can open a second box is now judged
  as the pair it will hold the value in, each half against that box's own
  published bound -- so `100/9` fits two four-character boxes, as it does when
  a student types it. Whole-number entry is judged exactly as before, a half
  the question's character set rejects is still refused, and a fraction aimed
  at a cell with no second box to open is refused by name rather than
  attempted.

- **A table cell that holds a fraction is one blank, and its answer is entered
  into it.** Facet answered a four-blank table exactly -- `16/9`, `-8/3`,
  `1/3`, `34/9`, all four right by hand -- and could not enter any of them.
  Hawkes draws one box per blank; typing `/` turns that box into a numerator
  and a denominator, so the finished table shows four semantic blanks across
  eight physical inputs. The reader refused a cell showing two controls, which
  made the whole table unreadable the moment a fraction appeared in it, by hand
  or otherwise, and took Insert with it. A cell may now own either one ordinary
  box or one numerator/denominator pair, it is still named by its numerator --
  the id every earlier reading already used -- and its second half is counted
  as part of it rather than as a box somewhere else. The writer enters a
  fraction the way a student does: it types the numerator into the cell's own
  control, types the `/` that opens the pair, confirms through the page's own
  router that Hawkes has moved to the second box, types the denominator there,
  and verifies the cell's whole logical value settled without disturbing any
  other cell. A cell already showing a fraction is emptied from its second box
  back to its first. Plain integer entry is unchanged, and a pair that is not
  one cell's two halves is still refused.
- **One question stopped reading as a new question on every glance.** MathJax
  labels each expression it typesets with ids carrying a per-typeset counter
  and renumbers them whenever it re-renders, which it does whenever an answer
  control changes -- so the same question hashed differently on every read, and
  a correct answer was discarded each time. The identity digest normalizes
  those away; what crosses to Facet is still the page's own MathML.

- **A solved answer now survives the owner touching their own answer boxes.**
  Clicking into a completion cell threw away a correct four-part answer and
  solved the question again -- once through a reasoning model, for
  twenty-five seconds -- while the question on screen never moved. Question
  identity and editor insertability had been conflated: the signature carried
  the focused box's id and the answer table read *through* the answer controls,
  and clicking a cell makes Hawkes reveal that cell's second control, at which
  point the table reader refuses and the identity it fed changed with it. The
  sidebar watcher re-prepared the panel on every caret move for the same
  reason. Identity is now the question's own content; the table's givens are
  kept beside it and compared only when both readings state them, so a reading
  the controls prevented is not evidence the question changed. A mapping
  already validated for this same question is revalidated against the boxes the
  page is showing instead of being discarded, in prepare and again before a
  write, so Insert stays offered while the owner works in the grid -- and a
  renumbered grid still fails that check, and the next randomization of the
  table is still a new question.

- **A completion table's answers are now written through the editor the page
  owns, so each one settles in its own cell.** Five correct values, five
  distinct cells, and two live runs that reported success over a table holding
  one wrong answer: writing the fifth part into `MatrixTextBoxes6_num` also
  changed `MatrixTextBoxes3_num`, which is the second part's cell. A Hawkes
  completion cell is not a text box. The page keeps a control per cell with its
  own text buffer and a `focusedElementIndex` naming the one it believes is
  being edited, and its `input` handling is delegated: the event updates *that*
  control and rerenders the box it owns. `focus()` never moved it -- the panel
  held system focus the whole time -- so all five writes routed through
  whichever control the page had selected before the add-on was opened. The
  write now happens in the page's own world: every cell is resolved to exactly
  one page-owned control before anything is typed, Hawkes' own focus handling
  is made to select that control -- `focusedElementIndex` is only a mirror of
  its real selection, and a first attempt that assigned the mirror and read it
  back crossed two cells anyway, because a plain answer box is edited through
  the separate element reference beside it -- and each part is read back once
  the editor has settled. A cell that does not keep its part, a control that
  disagrees with its cell, or a write that moves any other cell of the table is
  a refusal that puts the table back, and success now means five page-owned
  states holding five parts rather than five write calls that returned.

- **A table of values is now answered by computing it, not by asking a model.**
  The grid crossed to Facet flattened into the instruction, which put it in
  front of a reasoning model and nowhere else: the only route that could read
  it was the one whose answers cannot be checked, and a live run came back with
  five values of the right shape and the wrong mathematics. The grid and the
  form an answer must take now cross as structure, so Facet completes lesson
  2.1's five blanks exactly -- `0, 8, 8, 5, 3` on the exact route, in
  milliseconds, with no model and no accelerator. Where a row has two roots the
  choice is a documented tie-break rather than a preference. And where a model
  does answer a question that carries a grid, its answer is put back into that
  grid and has to satisfy every row exactly before it is offered at all.

- **Two readings that refused a question now say which condition refused it.**
  A fresh install of the five-part build, one press of Solve, and lesson 2.1's
  five-blank table still answered `0`. The build was current -- the running
  marker folded from the working tree exactly -- and the isolated DOM sweep had
  found all five boxes by name. What decided the question was the page's own
  control collection, which described a single textbox; the answer shape is
  read from that description and nothing else, so Facet was asked for one
  value, returned one value correctly, and the panel rendered it. The five
  parts became one before the question left the browser.
  Which fault that was, the run could not say. A single described textbox comes
  back when the collection holds one usable control, when four of five are
  disabled, when `controlsCollectionData` covers only one index, and when the
  collection is not array-like and the candidate loop never runs -- four faults
  and one description. The probe now reports the collection beside the control
  it chose, in counts and a branch name, the way the DOM sweep has reported
  `multiFieldEvidence` since the labelled-pair fix. The completion table's
  refusal is named the same way: `candidates-0` stood for five conditions and
  is now a tally of which rule dropped which table. Neither changes a decision
  -- both probes were run against the previous build over every fixture and
  every collection shape, and decide identically.
- **A completion question now sends the table it is completed in.** Lesson
  2.1's table of values for `x = y²` states a value in one cell of each row and
  leaves an answer box in the other; the givens are the question, and none of
  them crossed. The existing data-table reader could not carry them -- it reads
  the table a question states its numbers in, and refuses any table holding an
  answer control, which is exactly what this one is. A second reader takes the
  mirror image: the grid, with each cell either a value the page states or a
  blank numbered in the order the page draws them, so a reply's part N and the
  page's Nth box mean the same cell. A cell MathJax rendered is carried as the
  MathML it left rather than as its glyphs, because a radical sign is drawn and
  not written and `2√2` reads as `22`; a cell it drew and left no MathML in is
  refused rather than guessed at, and so is a blank with anything beside it, a
  second candidate table, an answer box outside the table, a ragged row, and
  more blanks than one answer can have. Nothing is read out of an answer
  control: a blank is a position. The ordinary data table is untouched, and
  every existing fixture reads exactly as it did.
- **A question with five blank cells is no longer answered as one box.**
  Lesson 2.1 completes a table of values for `x = y²` and draws five blanks;
  the page publishes one enabled control for each of them. Every gate between
  the page and Facet bounded a multi-part answer at four -- a bound sized for
  `y = [] or []` and the roots behind it -- so the DOM sweep counted five boxes
  and reported no ids for them, the page's own editor model declined to call
  five controls a multi-control answer, and the question was sent as a single
  field. Facet answered the single field it was asked about, exactly, and one
  number came back for a five-part question. The bound is now five, in the one
  place the browser declares it and the two the host does, and the build's
  shared-constant check covers all three of the self-contained copies. A
  question with more parts than that is still refused whole rather than
  half-answered.
- **Facet is now told when every answer part must be a signed integer.** A
  recurring two-box question published two six-character textboxes accepting
  only digits and minus, but the solve request reduced that contract to the
  number `2`. The reasoning route could therefore return structured notation
  as one part; the browser correctly refused it because the question offered
  no templates. The browser now normalizes that one narrow textbox rule
  into an answer-form requirement, and the host includes it in the mathematical
  question sent to Facet. Raw character patterns, templates, slots and field
  identifiers still do not cross, and editor restrictions are unchanged.
- **Every diagnostic entry now says which operation it belongs to.** One user
  gesture mints a run id, and that id is also the native-host `request_id` as
  `<run>.<n>`, which Ethnos passes on to Facet unchanged -- so one gesture, one
  companion request and one Facet run share a name that can be grepped for.
  Reconstructing which `solved` belonged to which `solve-started` was done by
  reading timestamps and hoping, and with two windows open it was wrong.
- **Entries also carry the event page's generation.** The page is
  non-persistent, so `seq` restarts whenever Firefox unloads it and two
  lifetimes interleaved into one stream. An operation that outlived its own
  event page is now visible as exactly that.
- **The add-on records a digest of the code it is running.** A temporary
  add-on's version never moves between edits and Reload re-reads whichever
  directory was first selected, so a fix that had never been loaded was twice
  recorded as a fix that did not work. The marker is folded from the source
  text the browser parsed, computed once per generation, deferred, and never
  awaited by anything a user is waiting for.
- A run that ends now reports the stages it passed through, so "failed at
  solving" -- true of a capture that never happened and of a model that
  answered nothing alike -- is no longer the whole story. `solved` reports the
  runtime, model, backend and device that answered it, which the log previously
  held only for a graph plan.
- A lost insertion names the components that moved rather than reporting "the
  target changed" for a moved tab, an advanced question, a re-solved answer and
  a second window's claim alike. The pinned snapshot is logged when it is
  taken, so before and after both exist.
- **A failure no longer has to be watched to be diagnosed.** A run that fails,
  is refused, or produces an answer the editor will not take now leaves one
  bounded record in `storage.local`, assembled from the state the event page was
  already holding rather than read back out of the log -- so it does not depend
  on diagnostics having been turned up beforehand, which a live failure never
  is. Records are grouped by a fingerprint folded from the diagnostic fields two
  instances of one fault have in common, so a recurring problem is counted
  rather than reported four times as four questions.
- **The editor's own description of itself is kept by default.** `answer-needs-
  template` names one of fraction, radical, exponent and parentheses against a
  character set that was not recorded anywhere, and diagnosing that cost a
  screenshot of the owner's coursework to reach a guess. What the page says
  about its own control -- readable, enabled, maximum length, permitted
  characters, offered templates, keypad slots, and one of these per field on a
  multi-field question -- is now recorded at `info` and carried into the record.
  What the student typed into that control is specifically not read.
- The ledger is bounded by 40 records, 64 groups, 14 days and 96 KB, whichever
  binds first; it evicts the oldest automatically and keeps a count of what it
  dropped. Settings -> Diagnostics counts it and **Clear** erases it along with
  the ring, so it is not storage the user cannot see or remove.
- Writing a record starts no timer, opens no port, sends no message and is
  never awaited, so an unattended session behaves exactly as it would without
  it.
- None of the above records coursework: identifiers are locally generated, the
  marker is folded from code, and every record is shapes, counts and the page's
  own vocabulary, built by name and filtered against a fixed allowlist. See
  [PRIVACY.md](PRIVACY.md).

## 0.46.0 · RC5-Cadence

- The answer becomes a deterministic score shared by typing, the visual preview
  and local music. Structured entry consumes shared offsets instead of keeping
  another copy of the timing algorithm; plain multi-field entry shares one clock.
- Classical, Jazz, Lo-fi, Electronic and Custom are five arrangements of that
  one score, differing in mode, chord voicing, register, instrument, envelope,
  percussion and how the phrase resolves. The expression's own operators turn
  the harmony; a digit takes the degree of its value and a letter keeps one
  pitch throughout an answer. Genre changes never alter a timestamp: only the
  accompaniment carries a genre's feel, bounded at 30 ms, and the character's
  own voice is always exactly on its score offset.
- **A template is a fermata.** Building a fraction or an exponent takes the
  editor real time the score never allotted. The phrase is now held for exactly
  that overrun and resumes in tempo, instead of every remaining note falling due
  at once; the panel names the structure while it is built and the instrument
  sounds it. The writer reports the hold it took.
- **Late wake-ups are no longer audible.** A long `setTimeout` was measured
  waking 343 ms late on a four-second gap. Both transports now approach each
  deadline in two steps, and the instrument places each voice against an anchor
  derived from the same score, clamped to 8–60 ms after the write that caused
  it. Measured drift over a 2–12 second answer is 1–7 ms.
- **The second answer of a session is no longer silent.** The event page has no
  user activation, so a device it suspended could not be resumed; it now closes
  when idle and opens a fresh one per performance, which is the path Firefox
  admits. The event page also unlocks for itself, so a panel whose background
  reference has not resolved no longer costs the answer its music.
- Settings audibly previews its structured equation, sounds its templates, and
  reuses one output device across repeated previews instead of opening another
  each time. Volume, mute and the insertion-music switch are grouped and
  explained; music during insertion stays off unless turned on.
- Navigation, tab close, tab move, window close and cancellation each end a
  performance and close its device. Firefox's announcement that it is about to
  suspend the event page does the same, which is what the feature relies on
  rather than the idle timeout itself: measurement did not support the earlier
  claim that an open port cannot keep an event page alive. Sound failure never
  gates insertion. No new permissions, samples, models, runtime or network
  dependency; the feature adds 11.1 KB to the package and no measurable CPU over
  the same answer in silence.
- The transient, one-way presentation cue is documented as page-observable, and
  now carries an optional structure name that cannot advance the phrase. Hawkes
  safety, structured editor mechanics, graph actuation and never-submit
  behavior retain their existing boundaries.

## 0.45.1

### Fixed

- **A two-box question labelled "A:" and "B:" can now be answered.** Lesson
  3.3's "find two points on the parabola" step was solved correctly and then
  refused at insertion with "the answer editor could not be read", every time.
  The two readings of the page disagreed: its published editor model said two
  enabled controls, so Facet was asked for two parts, while the field sweep
  threw both boxes away. The sweep recognises several boxes as one answer only
  when the word **or** sits between them -- the shape `x = ___ or x = ___` --
  and this step writes "A:" and "B:" instead. With no field ids, no number of
  correct parts could ever be placed.
- The boxes are now carried to the event page as candidates, and adopted when
  the page's own editor model publishes exactly as many enabled editors as the
  DOM found visible, editable and uniquely identified. Agreement between two
  independent readings decides it, rather than a guess about Hawkes' wording --
  the same rule the data table already follows, where the plotted points must
  agree with the table before either is trusted. Where the two disagree the
  add-on falls back to the single focused box exactly as before, so a question
  with one answer beside another visible field is unaffected.

## 0.45.0

### Added

- **A question whose numbers are in a table is now read as a table.** Hawkes
  word problems state their data in a real table with a heading over each
  column, and the add-on now carries that across exactly — headings and cells,
  as the page wrote them — alongside the MathML and the plotted points it
  already read. Nothing is transcribed and nothing is measured off a picture.
- **Lesson 3.3's revenue question is answered exactly, with no model at all.**
  Three price/quantity/revenue rows, a quadratic regression, and "what number
  of photos sold and what price per photo will maximize her revenue?" now
  resolve to nine photos at thirty-six dollars in about forty milliseconds:
  Facet fits `y = -4x² + 72x` over exact rationals, turns it at x = 9, and
  reports 324/9 as the price. Both answers arrive as separate values and go to
  the two answer boxes through the existing safe insertion.
- Six checks stand between that answer and the boxes, and every one of them is
  the host's own: the table's rows multiply out (price × photos = revenue), the
  table agrees with the plotted points, Facet's coefficients satisfy the exact
  least-squares normal equations, the turning point is where that curve
  actually turns, the curve opens downwards, and the price times the count
  gives the revenue at the turning point. A reasoned answer to this question is
  refused outright: there would be no working to check.

### Fixed

- **A word problem's instruction is no longer truncated into a different
  question.** The prompt was cut at 400 characters with the table flattened
  into it, so on lesson 3.3 the cut landed mid-sentence and the words asking to
  fit a curve and maximize never arrived at all: the host was given a situation
  and no task. The table is now carried separately and the limit is 1200 —
  both were needed, because the prose alone still runs past 400.

## 0.44.0

### Changed

- **The add-on is now Facet Hawkes Assistant.** Facet has owned solver routing
  for some time — exact mathematics first, a reasoning model only for what
  those decline, and the parabola and quadratic-regression specialists for a
  graph — while every visible surface still said Ethnos. The name in the
  add-ons list, the toolbar tooltip, the sidebar, the panel heading, the
  Settings title, the solve button, the icon's accessible name, and every
  status and error message now say what actually answers.
- Provenance names the route Facet reports — **Facet Exact**, **Facet
  Reasoning · GPU**, **Facet Parabola Plan · GPU**, **Facet Quadratic
  Regression · GPU** — and the method, runtime, backend, device, and timing
  behind it are unchanged. A question read from a picture is answered by the
  companion and is labelled **Local exact** or **Local model**, because saying
  Facet answered it would not be true.
- A request that names no pipeline is now routed by Facet. It used to fall to
  the companion's own path, which is how questions were answered before the
  routing moved.

### Removed

- **The Solve engine setting.** "Ethnos only" and "Ethnos, then Facet"
  described a division of labour that no longer exists, and a browser that
  offers a choice it cannot honour is worse than one that offers none. Facet
  routes every question the page states as mathematics; a question the page
  draws as a picture is read by the companion, which is a capability fallback
  rather than an engine anyone picks. Settings now states what the pipeline is
  instead of asking which one to use.
- A `solveEngine` value left in an upgraded profile is removed on the next
  start. It is inert before that too: the schema no longer knows the key, so
  nothing reads it and it can select nothing.

### Fixed

- A question with no readable mathematics no longer sends its screenshot to
  Facet, which has no reader for one and would refuse it. The capture goes only
  to the path that can use it.

## 0.43.0

### Added

- **Answer Cadence is now a finished Settings instrument.** Cadence remains a
  presentation layer after answer validation and editor planning; it never
  changes correctness, target selection, safety, submission, or navigation.
  Its controls are edited as a draft and saved together only through the
  explicit **Apply cadence** action, with clear applied/unapplied state and an
  atomic storage update.
- The local Settings preview sends
  `(2ix^4√(2x)+3)/(5y^2)` through the real structured editor planner, then
  performs the resulting phrase without obtaining a Hawkes tab or touching a
  website. Its rhythm strip shows note spacing, accents, and structural rests;
  the transport reports elapsed and target time, beat/semantic-step position,
  the current character/operator/structure/rest/resolution action, effective
  tempo, planned counts, and the measured hard-window result.
- Classical, Jazz, Lo-fi, Electronic, and Custom remain the musical profiles.
  Tempo now spans 30–300 BPM, while Custom keeps beat shape, swing, timing
  variation, structural rests, and the 2–12 second hard performance window.
  Preview restart, Stop, Settings close, and live reduced-motion changes all
  cancel or redraw deterministically without duplicate timer runs.

### Changed

- Plain/contenteditable insertion and the Settings preview now share the
  normalization, weighted score, hard-window resolution, and scheduling
  transport in `common/cadence.js`. Structured insertion still carries a
  self-contained copy because Firefox serializes it into Hawkes' MAIN world;
  the package validator compares every tuning rule and bound so the two score
  builders cannot drift unnoticed.
- Exact symbolic handling is stricter and broader where live exercises proved
  the intended operation: parser prose can no longer become an expression,
  plain `sqrt(...)` is handled as a root, signed decimal substitutions are
  consumed completely, cosmetic rewrites are declined, named radical
  evaluation stays exact, and powers/products of `i` and numeric complex
  radicals simplify to Hawkes-compatible forms.

### Fixed

- Insertion claims its phase before yielding, uses the same reviewed machine
  form for its validated structured plan, and pins the originating window,
  tab, frame, field, question signature, and answer for the entire paced
  operation. Any ownership change stops the operation rather than retargeting
  it; a detached plain field is rejected on the next beat.
- A new prepare or solve cancels work already in flight instead of orphaning a
  solver that can overwrite newer state. Withheld capture permission now offers
  the existing Hawkes access recovery, invalid model answer text is reported as
  invalid rather than blaming the editor, and temporary-add-on/native-host
  inspection no longer reports false absence or false processes.
- Radical simplification now reads direct per-variable positivity assumptions
  and preserves half-integer powers correctly. The covered live form
  `√(-8x^9)` with `x > 0` resolves to `2ix^4√(2x)` rather than an uninsertable
  or value-changing display.

## 0.42.0

### Added

- Plain-text answers now arrive on a musical presentation cadence for
  number-and-symbol voice-over. Settings offers Classical, Jazz, Lo-fi,
  Electronic and Custom arrangements; tempo and a 2–12 second hard performance
  window remain independently adjustable, while Custom exposes beat shape,
  swing, timing variation and symbol rests. Contenteditable answers use the
  same character-at-a-time path instead of arriving in one burst. Beat weights
  are normalised to the chosen duration, keeping the performance inside the
  existing 15-second injected-operation deadline. The default remains a varied
  5–10 second performance.

- Structured answers built with the keypad templates perform on the same
  cadence. They previously arrived in one burst, because `enterPlan` is
  serialized into the page's own world and never received the cadence at all,
  and its `typeInto` wrote every character of a step in a single synchronous
  loop. One performance now covers every typed character of the whole plan;
  templates sit on the same clock, so a slow `settle` eats into the notes that
  follow rather than adding to the length.

### Fixed

- A one-character answer is struck on the downbeat instead of after the whole
  window. It used to hold the field empty for five to ten seconds and then fill
  it on the last beat, which reads as a hang -- and one-character answers are
  common in this course.

- A paced entry re-checks its target on every beat. Entry now spans seconds
  rather than one burst, so the field can be closed, replaced, or lose the
  caret part-way through. The contenteditable path is the one that mattered:
  `execCommand` writes wherever the selection happens to be, so losing focus
  mid-performance put the rest of the answer somewhere else on the page. It
  now stops with `editor-lost-focus`. The keypad path re-reads its box by id
  for the same reason.

## 0.41.4

### Changed

- The pause between characters is 40ms, up from 16ms. Still fixed rather than
  varied. `ENTRY_BUDGET_MS` is unchanged at 1500ms, so answers up to 37
  characters get the full 40ms and the longest permitted answer (40 characters)
  is compressed slightly to 37ms each — 1480ms either way, well inside the
  15-second deadline on an injected operation.

## 0.41.3

### Fixed

- The question's instruction is read again on steps that state it briefly.
  Two faults compounded. Hawkes prints "Step N of M" twice — once in the page
  header beside the question number, once at the head of the instruction — and
  the header comes first, so it was taken as the step and contributed no
  instruction. The instruction was then sought separately under a `> 20`
  character rule, and **"Identify the degree." is exactly twenty characters**,
  so it was skipped; the next line carrying an accepted verb was Hawkes' own
  note about radio buttons, which names no operation at all.

  The host was therefore asked to solve a question about radio buttons,
  declined, and fell through to a screenshot the sidebar has no permission to
  take — reported as "the question could not be captured from this tab", which
  was true and told nobody anything. A step line that carries an instruction is
  now preferred over the header, and the length rule admits a short sentence.

## 0.41.2

### Changed

- A markup fallback records why it fell back. The exact path declines for two
  reasons — markup that would not convert, and an instruction no exact
  operation matched — which fall back identically to a screenshot, a vision
  model, and most of a minute, and are fixed in completely different places.
  A 53-second solve seen in live use could be attributed to neither, because
  the log said only that a fallback had happened. The host now names which, and
  the panel's diagnostics carry it.

## 0.41.1

### Fixed

- "Find the product of the binomial factors using the appropriate special
  product (difference of two squares, square of a binomial sum, or square of a
  binomial difference)" is a multiplication. It was answered **`trinomial`** in
  live use: the classification rule counted mentions of
  monomial/binomial/trinomial, and that prompt says "binomial" three times.
  Classification now requires all three names or an explicit verb.
- The same prompt then resolved to factoring, because "factor" is matched as a
  substring and sits inside "binomial factors" — and declined, since
  `(x + 9)^2` has no further factorization. A named product is now read before
  the factoring checks: an explicit "find the product" beats an incidental
  noun. It answers `x^2 + 18x + 81`.
- Both prompts are now in the coverage corpus, which stands at 23 of 23 exact.

## 0.41.0

### Changed

- The answer is entered one character at a time rather than assigned in a
  single write. A field driven by a framework re-renders on each input event,
  and that work is asynchronous; the whole answer used to arrive as one
  assignment carrying one event with a whole string, which is not the shape
  such a field is built to receive. It is the likeliest reading of both the
  half-entered structured answers of 0.19 and an unexplained `errorNoBridge` at
  the write boundary seen during live use. Entry stops if the field closes
  part-way through, and a fixed budget keeps a long answer from holding the
  editor open.

  The pace is fixed at what the editor absorbs. It is deliberately not varied,
  randomised, or shaped to resemble anything: as `README.md` has always said,
  the add-on does not conceal that it is the one typing.

## 0.40.3

### Fixed

- A trinomial that cannot be factored is now answered, not abandoned.
  Factoring is the one rewriting whose input can legitimately be its answer,
  and these questions say so themselves — "if it cannot be factored, indicate
  Not Factorable". Read as a failure, `y^2 + y + 17` cost seventy-six seconds
  of vision and model for a fact SymPy had in thirty-six milliseconds. Only
  claimed when the question actually offers that escape; a bare "factor
  completely" is still handed back. The panel routes the result to Hawkes'
  radio button as a manual choice, as it already does for "Not a Real Number".

## 0.40.2

### Fixed

- A panel takes focus only in the window being used. Every window has its own
  sidebar, and loading or reloading the add-on reloads all of them at once —
  each then put the caret on its primary button, including panels in windows
  nobody was in. Reported as the add-on jumping to another window the instant
  it was loaded. The add-on has never been able to move a tab or a window
  (`tabs.update`, `tabs.create`, `windows.update` and `windows.create` are all
  build failures); taking focus inside an unattended panel was the only thing
  it could do that looked like it.

## 0.40.1

### Fixed

- Moving between tabs re-checks what is in front. A sidebar belongs to a
  window, not to a tab — it stays open as the window moves between tabs, just
  as Firefox's own sidebars do — and nothing watched for that, so the panel
  went on showing a question and an answer belonging to a tab no longer on
  screen. Reported as the add-on being attached to every tab at once.
- The diagnostic log records which version is running. A temporary add-on
  reports nothing about itself, and `about:debugging`'s **Reload** re-reads
  whichever file was first selected — so a freshly built version can silently
  not be the one under test, and a bug can be diagnosed at length in a build
  that never contained its fix.

## 0.40.0

### Added

- **The answer is drawn as mathematics.** The card showed the string the answer
  travelled in — `\frac{z^4|y^5|}{3}`, `-x^13 + 2x^12`, `y^(3/2)` — which is
  neither what Hawkes renders nor what anyone types, and reads as an encoding
  rather than an answer. It now has real superscripts, a fraction bar between
  numerator and denominator, a radical sign with a rule over exactly its
  radicand, and bars for absolute value. `common/answer-math.js` decides the
  layout and has no DOM, so the suite runs it against the forms the solver
  actually produces; the panel only builds elements from that.
- Three more exact operations: the **constant term**, **classifying** a
  polynomial as monomial/binomial/trinomial, and **evaluating** one at a given
  value. Each was a question type that fell through to roughly a minute of
  vision-plus-model and now answers in about a millisecond. The shipped
  coverage corpus is at 20 of 20 exact, none wrong.

### Fixed

- **Copy** takes the answer from the panel's state rather than reading the
  card. Once the card holds elements its text is the rendered form — `x13` for
  `x^13` — so drawing the answer properly would otherwise have quietly begun
  copying something different from what is displayed, in precisely the cases
  (option questions, refused notation) where copying is the only way in.
- "Factor the following **trinomial** completely" is a factoring question.
  Matching a classification on the word alone answered `trinomial` to a request
  to factor: fast, confident, and wrong. Caught by the coverage sweep before it
  shipped, which is what the sweep is for.

## 0.39.5

### Fixed

- The question watcher rebuilds what it watches instead of giving up in
  silence. It is the only guard against a previous question's answer staying on
  screen, and a frame that has gone — Hawkes reloading its editor, the tab
  moving on — made every read throw. Logged at debug and swallowed, that
  retired the guard: it failed every tick, forever, and nothing said so. Three
  consecutive failures now re-prepare, and say why.
- Closing the window the add-on was working in hands the work to a surviving
  panel. Panels in a closing window disconnect by themselves, but the state
  went on naming a window that no longer existed — so every other panel was
  shown a blank of its own and nothing ever re-prepared, which looks exactly
  like a panel that has stopped working.

## 0.39.4

### Fixed

- A panel beside a non-Hawkes tab said "No active Firefox tab was found" of a
  window plainly showing one. The add-on may read a single host; if that grant
  is held and the active tab's URL is still unreadable, the tab cannot be
  Hawkes, because a Hawkes URL is precisely what the grant makes readable. It
  now says so — open the panel from a Hawkes lesson tab — instead of sending
  the reader to look for a tab that was never missing.

## 0.39.3

### Fixed

- A panel no longer shows another window's question. One state exists at a time
  and names the window it describes, but it was posted to every connected
  panel — so a sidebar open in an unrelated window displayed the Hawkes
  question, its answer, its source, and an enabled **Insert answer**. Seen live
  across two monitors: lesson 1.3's answer sitting in the sidebar of a Discord
  window, offering to insert itself. Insertion was already guarded and would
  have refused, but an offer that only a guard prevents is not one to leave
  standing. Each panel is now shown its own window's state, or a blank of its
  own — which is exactly true for a window where nothing has been solved.

- A panel no longer acts before it knows which window it is in. The tab lookup
  falls back to `currentWindow` when given no window, and in a background page
  that is whichever window was focused last. A panel learns its own window
  asynchronously from `windows.getCurrent()`, while its automatic prepare fires
  on the first state — and routinely won that race. Dragging a tab into a new
  window focuses that window, so the panel left behind pointed itself at the
  tab that had just left it. Requests are now held until the window is known.
- After its tab changes window, a panel re-prepares in the window it belongs to
  instead of sitting at "Checking the focused answer field" with nothing to act
  on. Forgetting the moved tab was correct but left the panel unusable.

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
